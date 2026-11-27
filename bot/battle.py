"""Group battle rules: lobby, live questions, speed scoring, reveal, standings. No Telegram code.

Time is always passed in (`now`) so the rules can be tested without waiting.
"""

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import (
    Battle,
    BattleAnswer,
    BattlePlayer,
    BattleQuestion,
    GroupChat,
    Option,
    Question,
    Theme,
    User,
)

LOBBY, RUNNING, FINISHED, CANCELLED = "lobby", "running", "finished", "cancelled"
ACTIVE = (LOBBY, RUNNING)

QUESTION_COUNT = 25
SECONDS_PER_QUESTION = 30
LOBBY_SECONDS = 120
MIN_PLAYERS = 2
REVEAL_PAUSE_SECONDS = 5
ANSWER_GRACE_MS = 1500  # taps that left the phone before the deadline may arrive slightly late


class BattleError(Exception):
    """A rule was violated; `code` is shown to the user as a translated message."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Standing:
    rank: int
    user_id: int
    name: str
    points: int
    correct: int
    total_ms: int


@dataclass
class AnswerOutcome:
    option_index: int
    answered: int
    players: int

    @property
    def everyone_answered(self) -> bool:
        return self.answered >= self.players


@dataclass
class RevealResult:
    battle: Battle
    item: BattleQuestion
    correct_index: int
    answered: int
    correct: int
    players: int
    top: list[Standing]


@dataclass
class ReviewItem:
    position: int
    question: str
    chosen_letter: str | None  # None = not answered in time
    chosen_text: str | None
    correct_letter: str
    correct_text: str


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes (stored as UTC); PostgreSQL returns aware ones."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)


def speed_points(elapsed_ms: int, seconds: int) -> int:
    """Kahoot-style: 1000 for an instant correct answer, down to 500 at the deadline."""
    limit = seconds * 1000
    elapsed = min(max(elapsed_ms, 0), limit)
    return round(1000 * (1 - elapsed / (2 * limit)))


def letter(index: int) -> str:
    return chr(ord("A") + index)


def ordered_options(item: BattleQuestion) -> list[Option]:
    by_id = {o.id: o for o in item.question.options}
    return [by_id[i] for i in item.option_order if i in by_id]


# ---------------------------------------------------------------- loading

def _battle_query():
    return select(Battle).options(
        selectinload(Battle.theme),
        selectinload(Battle.players).selectinload(BattlePlayer.user),
    )


async def get_battle(db: AsyncSession, battle_id: int) -> Battle | None:
    return await db.scalar(_battle_query().where(Battle.id == battle_id).execution_options(populate_existing=True))


async def active_battle(db: AsyncSession, chat_id: int) -> Battle | None:
    return await db.scalar(
        _battle_query().where(Battle.chat_id == chat_id, Battle.status.in_(ACTIVE)).order_by(Battle.id.desc()).limit(1)
    )


async def battles_to_recover(db: AsyncSession) -> list[Battle]:
    return list(await db.scalars(_battle_query().where(Battle.status.in_(ACTIVE))))


async def get_question(db: AsyncSession, battle_id: int, position: int) -> BattleQuestion | None:
    return await db.scalar(
        select(BattleQuestion)
        .where(BattleQuestion.battle_id == battle_id, BattleQuestion.position == position)
        .options(selectinload(BattleQuestion.question).selectinload(Question.options))
        .execution_options(populate_existing=True)
    )


# ---------------------------------------------------------------- groups

async def get_or_create_group(db: AsyncSession, chat_id: int, title: str | None) -> GroupChat:
    group = await db.get(GroupChat, chat_id)
    if group is None:
        group = GroupChat(id=chat_id, title=title, language="uz")
        db.add(group)
    elif title and group.title != title:
        group.title = title
    await db.commit()
    return group


async def set_group_language(db: AsyncSession, chat_id: int, language: str) -> None:
    await db.execute(update(GroupChat).where(GroupChat.id == chat_id).values(language=language))
    await db.commit()


# ---------------------------------------------------------------- lobby

async def create_battle(db: AsyncSession, chat_id: int, theme_id: int, user: User, now: datetime) -> Battle:
    if not user.is_registered:
        raise BattleError("not_registered")
    if await active_battle(db, chat_id):
        raise BattleError("battle_active")
    available = await db.scalar(
        select(func.count(Question.id))
        .join(Theme, Theme.id == Question.theme_id)
        .where(Question.theme_id == theme_id, Question.is_active, Theme.is_active)
    )
    if not available:
        raise BattleError("no_questions")
    battle = Battle(
        chat_id=chat_id, theme_id=theme_id, created_by=user.id, status=LOBBY,
        question_count=min(QUESTION_COUNT, available), seconds_per_question=SECONDS_PER_QUESTION,
        current_index=-1, lobby_deadline=now + timedelta(seconds=LOBBY_SECONDS),
        players=[BattlePlayer(user_id=user.id, joined_at=now)],
    )
    db.add(battle)
    await db.commit()
    return await get_battle(db, battle.id)


async def set_lobby_message(db: AsyncSession, battle_id: int, message_id: int) -> None:
    await db.execute(update(Battle).where(Battle.id == battle_id).values(lobby_message_id=message_id))
    await db.commit()


async def join(db: AsyncSession, battle_id: int, user: User, now: datetime) -> Battle:
    battle = await get_battle(db, battle_id)
    if battle is None or battle.status != LOBBY:
        raise BattleError("not_lobby")
    if not user.is_registered:
        raise BattleError("not_registered")
    if any(p.user_id == user.id for p in battle.players):
        raise BattleError("already_joined")
    db.add(BattlePlayer(battle_id=battle.id, user_id=user.id, joined_at=now))
    try:
        await db.commit()
    except IntegrityError as e:  # double tap
        await db.rollback()
        raise BattleError("already_joined") from e
    return await get_battle(db, battle_id)


async def start(db: AsyncSession, battle_id: int, now: datetime, rng: random.Random | None = None) -> Battle:
    """Lobby -> running. Picks the questions; the first one is timed once it's posted (mark_posted)."""
    rng = rng or random.SystemRandom()
    battle = await get_battle(db, battle_id)
    if battle is None or battle.status != LOBBY:
        raise BattleError("not_lobby")
    if len(battle.players) < MIN_PLAYERS:
        raise BattleError("not_enough_players")

    ids = list(await db.scalars(
        select(Question.id).where(Question.theme_id == battle.theme_id, Question.is_active)
    ))
    picked = rng.sample(ids, min(battle.question_count, len(ids)))
    options: dict[int, list[int]] = {}
    for qid, oid in await db.execute(select(Option.question_id, Option.id).where(Option.question_id.in_(picked))):
        options.setdefault(qid, []).append(oid)

    for position, qid in enumerate(picked):
        order = options[qid]
        rng.shuffle(order)
        db.add(BattleQuestion(battle_id=battle.id, question_id=qid, position=position, option_order=order))
    # Only move on if still in the lobby (the starter's button and the auto-start timer may race).
    moved = await db.execute(
        update(Battle).where(Battle.id == battle.id, Battle.status == LOBBY)
        .values(status=RUNNING, current_index=0, question_count=len(picked), started_at=now)
    )
    if moved.rowcount != 1:
        await db.rollback()
        raise BattleError("not_lobby")
    await db.commit()
    return await get_battle(db, battle_id)


async def cancel(db: AsyncSession, battle_id: int, now: datetime) -> bool:
    result = await db.execute(
        update(Battle).where(Battle.id == battle_id, Battle.status.in_(ACTIVE))
        .values(status=CANCELLED, finished_at=now)
    )
    await db.commit()
    return result.rowcount == 1


# ---------------------------------------------------------------- questions

async def mark_posted(db: AsyncSession, battle_id: int, position: int, message_id: int, now: datetime) -> datetime:
    """The question is visible: start its clock. Returns the deadline."""
    battle = await db.get(Battle, battle_id)
    deadline = now + timedelta(seconds=battle.seconds_per_question)
    await db.execute(
        update(BattleQuestion).where(BattleQuestion.battle_id == battle_id, BattleQuestion.position == position)
        .values(message_id=message_id)
    )
    await db.execute(
        update(Battle).where(Battle.id == battle_id, Battle.current_index == position)
        .values(question_started_at=now, question_deadline=deadline)
    )
    await db.commit()
    return deadline


async def answer(
    db: AsyncSession, battle_id: int, position: int, user_id: int, option_index: int, now: datetime
) -> AnswerOutcome:
    battle = await db.get(Battle, battle_id, populate_existing=True)
    if battle is None or battle.status != RUNNING or battle.current_index != position:
        raise BattleError("too_late")
    item = await get_question(db, battle_id, position)
    started, deadline = as_utc(battle.question_started_at), as_utc(battle.question_deadline)
    if item is None or item.revealed or started is None:
        raise BattleError("too_late")
    if now > deadline + timedelta(milliseconds=ANSWER_GRACE_MS):
        raise BattleError("too_late")

    player = await db.scalar(
        select(BattlePlayer).where(BattlePlayer.battle_id == battle_id, BattlePlayer.user_id == user_id)
    )
    if player is None:
        raise BattleError("not_player")
    already = await db.scalar(
        select(BattleAnswer.id).where(BattleAnswer.battle_id == battle_id, BattleAnswer.position == position,
                                      BattleAnswer.user_id == user_id)
    )
    if already is not None:
        raise BattleError("already_answered")
    options = ordered_options(item)
    if not 0 <= option_index < len(options):
        raise BattleError("too_late")

    chosen = options[option_index]
    elapsed_ms = int((now - started).total_seconds() * 1000)
    elapsed_ms = min(max(elapsed_ms, 0), battle.seconds_per_question * 1000)
    points = speed_points(elapsed_ms, battle.seconds_per_question) if chosen.is_correct else 0
    db.add(BattleAnswer(
        battle_id=battle_id, position=position, user_id=user_id, option_id=chosen.id, option_index=option_index,
        is_correct=chosen.is_correct, points=points, answer_ms=elapsed_ms, answered_at=now,
    ))
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise BattleError("already_answered") from e
    if chosen.is_correct:
        await db.execute(
            update(BattlePlayer).where(BattlePlayer.id == player.id).values(
                points=BattlePlayer.points + points,
                correct_count=BattlePlayer.correct_count + 1,
                total_ms=BattlePlayer.total_ms + elapsed_ms,
            )
        )
    await db.commit()
    answered, players = await answered_count(db, battle_id, position)
    return AnswerOutcome(option_index=option_index, answered=answered, players=players)


async def answered_count(db: AsyncSession, battle_id: int, position: int) -> tuple[int, int]:
    """(answers given to this question, players in the battle)"""
    answered = await db.scalar(
        select(func.count(BattleAnswer.id))
        .where(BattleAnswer.battle_id == battle_id, BattleAnswer.position == position)
    )
    players = await db.scalar(select(func.count(BattlePlayer.id)).where(BattlePlayer.battle_id == battle_id))
    return answered, players


async def reveal(db: AsyncSession, battle_id: int, position: int) -> RevealResult | None:
    """Close the question. Returns None if it was already revealed or the battle isn't running."""
    battle = await get_battle(db, battle_id)
    if battle is None or battle.status != RUNNING or battle.current_index != position:
        return None
    closed = await db.execute(
        update(BattleQuestion)
        .where(BattleQuestion.battle_id == battle_id, BattleQuestion.position == position,
               BattleQuestion.revealed.is_(False))
        .values(revealed=True)
    )
    await db.commit()
    if closed.rowcount != 1:
        return None
    item = await get_question(db, battle_id, position)
    options = ordered_options(item)
    correct_index = next(i for i, o in enumerate(options) if o.is_correct)
    answers = list(await db.scalars(
        select(BattleAnswer).where(BattleAnswer.battle_id == battle_id, BattleAnswer.position == position)
    ))
    return RevealResult(
        battle=battle, item=item, correct_index=correct_index, answered=len(answers),
        correct=sum(a.is_correct for a in answers), players=len(battle.players),
        top=(await standings(db, battle_id))[:3],
    )


async def advance(db: AsyncSession, battle_id: int, from_position: int, now: datetime) -> Battle | None:
    """Move past a revealed question. Returns the battle (running or finished), or None if already moved."""
    battle = await db.get(Battle, battle_id, populate_existing=True)
    if battle is None or battle.status != RUNNING or battle.current_index != from_position:
        return None
    last = from_position + 1 >= battle.question_count
    values = (
        {"status": FINISHED, "finished_at": now}
        if last else
        {"current_index": from_position + 1, "question_started_at": None, "question_deadline": None}
    )
    moved = await db.execute(
        update(Battle).where(Battle.id == battle_id, Battle.status == RUNNING, Battle.current_index == from_position)
        .values(**values)
    )
    await db.commit()
    if moved.rowcount != 1:
        return None
    return await get_battle(db, battle_id)


# ---------------------------------------------------------------- results

async def standings(db: AsyncSession, battle_id: int) -> list[Standing]:
    players = list(await db.scalars(
        select(BattlePlayer).where(BattlePlayer.battle_id == battle_id).options(selectinload(BattlePlayer.user))
        .execution_options(populate_existing=True)
    ))
    players.sort(key=lambda p: (-p.points, -p.correct_count, p.total_ms, as_utc(p.joined_at)))
    return [
        Standing(rank=n, user_id=p.user_id, name=p.user.display_name, points=p.points,
                 correct=p.correct_count, total_ms=p.total_ms)
        for n, p in enumerate(players, start=1)
    ]


async def player_review(db: AsyncSession, battle_id: int, user_id: int) -> list[ReviewItem]:
    """Questions the player got wrong or didn't answer in time."""
    items = list(await db.scalars(
        select(BattleQuestion).where(BattleQuestion.battle_id == battle_id)
        .options(selectinload(BattleQuestion.question).selectinload(Question.options))
        .order_by(BattleQuestion.position)
    ))
    answers = {
        a.position: a for a in await db.scalars(
            select(BattleAnswer).where(BattleAnswer.battle_id == battle_id, BattleAnswer.user_id == user_id)
        )
    }
    review = []
    for item in items:
        if not item.revealed:
            continue  # never shown (battle cancelled before it)
        answer_row = answers.get(item.position)
        if answer_row and answer_row.is_correct:
            continue
        options = ordered_options(item)
        correct_index = next(i for i, o in enumerate(options) if o.is_correct)
        chosen = options[answer_row.option_index] if answer_row else None
        review.append(ReviewItem(
            position=item.position, question=item.question.text,
            chosen_letter=letter(answer_row.option_index) if answer_row else None,
            chosen_text=chosen.text if chosen else None,
            correct_letter=letter(correct_index), correct_text=options[correct_index].text,
        ))
    return review

