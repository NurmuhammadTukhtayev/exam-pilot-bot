"""Quiz, registration and leaderboard logic, shared by the bot and the Mini App API."""

import random
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import Option, Question, QuizSession, SessionQuestion, Theme, User, utcnow

PRACTICE = "practice"
EXAM = "exam"
MODES = (PRACTICE, EXAM)

ACTIVE, FINISHED, STOPPED = "active", "finished", "stopped"


@dataclass
class ThemeInfo:
    id: int
    name: str
    question_count: int


@dataclass
class AnswerResult:
    item: SessionQuestion
    session: QuizSession
    chosen: Option
    correct: Option
    is_correct: bool
    finished: bool


def letter(index: int) -> str:
    return chr(ord("A") + index)


def ordered_options(item: SessionQuestion) -> list[Option]:
    """The question's options in the shuffled order the user sees."""
    by_id = {o.id: o for o in item.question.options}
    return [by_id[i] for i in item.option_order if i in by_id]


async def upsert_user(db: AsyncSession, user_id: int, username: str | None, first_name: str | None) -> User:
    user = await db.get(User, user_id)
    if user is None:
        user = User(id=user_id, username=username, first_name=first_name)
        db.add(user)
    else:
        user.username, user.first_name = username, first_name
    await db.commit()
    return user


async def set_language(db: AsyncSession, user_id: int, language: str) -> None:
    await db.execute(update(User).where(User.id == user_id).values(language=language))
    await db.commit()


# ---------------------------------------------------------------- registration / login

NAME_MIN, NAME_MAX = 3, 100
GROUP_MAX = 50

STEP_NAME, STEP_PHONE, STEP_GROUP = "name", "phone", "group"


def registration_step(user: User) -> str | None:
    """The next missing registration field, or None when everything is filled in."""
    if not user.full_name:
        return STEP_NAME
    if not user.phone:
        return STEP_PHONE
    if not user.group_name:
        return STEP_GROUP
    return None


def clean_full_name(raw: str | None) -> str | None:
    value = " ".join((raw or "").split())
    if not NAME_MIN <= len(value) <= NAME_MAX or value.startswith("/"):
        return None
    if not any(ch.isalpha() for ch in value):
        return None
    return value


def clean_group(raw: str | None) -> str | None:
    value = " ".join((raw or "").split())
    if not 1 <= len(value) <= GROUP_MAX or value.startswith("/"):
        return None
    return value


def normalize_phone(raw: str) -> str:
    return "+" + re.sub(r"\D", "", raw)


async def _maybe_complete_registration(db: AsyncSession, user: User) -> None:
    if user.registered_at is None and registration_step(user) is None:
        user.registered_at = utcnow()
        user.is_logged_in = True
    await db.commit()


async def update_registration(
    db: AsyncSession, user: User, *, full_name: str | None = None, phone: str | None = None,
    group_name: str | None = None,
) -> User:
    """Save any provided (already validated) fields and complete registration once all are present."""
    if full_name is not None:
        user.full_name = full_name
    if phone is not None:
        user.phone = phone
    if group_name is not None:
        user.group_name = group_name
    await _maybe_complete_registration(db, user)
    return user


async def restart_registration(db: AsyncSession, user: User) -> User:
    """Edit profile: ask for name and group again (the Telegram-verified phone is kept)."""
    user.full_name = None
    user.group_name = None
    user.registered_at = None
    await db.commit()
    return user


async def set_logged_in(db: AsyncSession, user: User, logged_in: bool) -> User:
    user.is_logged_in = logged_in
    if not logged_in:
        await db.execute(
            update(QuizSession)
            .where(QuizSession.user_id == user.id, QuizSession.status == ACTIVE)
            .values(status=STOPPED, finished_at=utcnow())
        )
    await db.commit()
    return user


async def list_themes(db: AsyncSession) -> list[ThemeInfo]:
    rows = await db.execute(
        select(Theme.id, Theme.name, func.count(Question.id))
        .join(Question, (Question.theme_id == Theme.id) & Question.is_active)
        .where(Theme.is_active)
        .group_by(Theme.id, Theme.name)
        .order_by(Theme.name)
    )
    return [ThemeInfo(id=r[0], name=r[1], question_count=r[2]) for r in rows]


async def get_theme(db: AsyncSession, theme_id: int) -> ThemeInfo | None:
    for theme in await list_themes(db):
        if theme.id == theme_id:
            return theme
    return None


async def theme_question_ids(db: AsyncSession, theme_id: int) -> list[int]:
    """Active question ids of a theme in document order: index 0 is question #1."""
    return list(await db.scalars(
        select(Question.id)
        .where(Question.theme_id == theme_id, Question.is_active)
        .order_by(Question.source_row, Question.id)
    ))


async def start_quiz(
    db: AsyncSession, user_id: int, theme_id: int, mode: str, count: int, rng: random.Random | None = None,
    start: int | None = None,
) -> QuizSession | None:
    """Create a session; answer options are always shuffled.

    start=None: `count` random questions (capped at what's available).
    start=N (practice only): questions #N, #N+1, ... in document order (capped at the end of the theme).
    Returns None if there's nothing to ask (no questions, count < 1, start out of range).
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    if start is not None and mode != PRACTICE:
        raise ValueError("'in order' is only available in practice mode")
    rng = rng or random.SystemRandom()

    question_ids = await theme_question_ids(db, theme_id)
    if not question_ids or count < 1:
        return None
    if start is None:
        picked = rng.sample(question_ids, min(count, len(question_ids)))
    else:
        if not 1 <= start <= len(question_ids):
            return None
        picked = question_ids[start - 1:start - 1 + count]

    options = await db.execute(select(Option.question_id, Option.id).where(Option.question_id.in_(picked)))
    options_by_question: dict[int, list[int]] = {}
    for question_id, option_id in options:
        options_by_question.setdefault(question_id, []).append(option_id)

    await db.execute(
        update(QuizSession)
        .where(QuizSession.user_id == user_id, QuizSession.status == ACTIVE)
        .values(status=STOPPED, finished_at=utcnow())
    )

    session = QuizSession(user_id=user_id, theme_id=theme_id, mode=mode, total=len(picked), items=[],
                          start_number=start)
    for position, question_id in enumerate(picked):
        order = options_by_question[question_id]
        rng.shuffle(order)
        session.items.append(SessionQuestion(question_id=question_id, position=position, option_order=order))
    db.add(session)
    await db.commit()
    return session


async def get_active_session(db: AsyncSession, user_id: int) -> QuizSession | None:
    return await db.scalar(
        select(QuizSession)
        .where(QuizSession.user_id == user_id, QuizSession.status == ACTIVE)
        .options(selectinload(QuizSession.theme))
        .order_by(QuizSession.id.desc())
        .limit(1)
    )


async def get_item(db: AsyncSession, session_id: int, position: int) -> SessionQuestion | None:
    return await db.scalar(
        select(SessionQuestion)
        .where(SessionQuestion.session_id == session_id, SessionQuestion.position == position)
        .options(
            selectinload(SessionQuestion.question).selectinload(Question.options),
            selectinload(SessionQuestion.session).selectinload(QuizSession.theme),
        )
    )


async def answer(
    db: AsyncSession, user_id: int, session_id: int, position: int, option_index: int
) -> AnswerResult | None:
    """Record an answer. Returns None for stale/duplicate/foreign button presses."""
    item = await get_item(db, session_id, position)
    if item is None:
        return None
    session = item.session
    if (
        session.user_id != user_id
        or session.status != ACTIVE
        or session.current_index != position
        or item.selected_option_id is not None
    ):
        return None
    options = ordered_options(item)
    if not 0 <= option_index < len(options):
        return None

    chosen = options[option_index]
    correct = next(o for o in options if o.is_correct)
    item.selected_option_id = chosen.id
    item.is_correct = chosen.is_correct
    item.answered_at = utcnow()
    session.current_index += 1
    if chosen.is_correct:
        session.correct_count += 1
    finished = session.current_index >= session.total
    if finished:
        session.status = FINISHED
        session.finished_at = utcnow()
    await db.commit()
    return AnswerResult(item, session, chosen, correct, chosen.is_correct, finished)


async def stop_active(db: AsyncSession, user_id: int) -> QuizSession | None:
    session = await get_active_session(db, user_id)
    if session is None:
        return None
    session.status = STOPPED
    session.finished_at = utcnow()
    await db.commit()
    return session


async def session_items(db: AsyncSession, session_id: int) -> list[SessionQuestion]:
    return list(
        await db.scalars(
            select(SessionQuestion)
            .where(SessionQuestion.session_id == session_id)
            .options(selectinload(SessionQuestion.question).selectinload(Question.options))
            .order_by(SessionQuestion.position)
        )
    )


async def recent_results(db: AsyncSession, user_id: int, limit: int = 10) -> list[QuizSession]:
    return list(
        await db.scalars(
            select(QuizSession)
            .where(QuizSession.user_id == user_id, QuizSession.status == FINISHED)
            .options(selectinload(QuizSession.theme))
            .order_by(QuizSession.id.desc())
            .limit(limit)
        )
    )


# ---------------------------------------------------------------- summaries

@dataclass
class Mistake:
    position: int
    question: str
    chosen_letter: str
    chosen_text: str
    correct_letter: str
    correct_text: str


@dataclass
class SessionSummary:
    session: QuizSession
    answered: int
    base: int  # denominator for the score: total if finished, answered if stopped early
    percent: int
    mistakes: list[Mistake]


def _percent(part: int, whole: int) -> int:
    return round(part * 100 / whole) if whole else 0


async def session_summary(db: AsyncSession, session_id: int) -> SessionSummary | None:
    session = await db.scalar(
        select(QuizSession).where(QuizSession.id == session_id).options(selectinload(QuizSession.theme))
    )
    if session is None:
        return None
    items = await session_items(db, session_id)
    answered = [i for i in items if i.selected_option_id is not None]
    mistakes = []
    for item in answered:
        if item.is_correct:
            continue
        options = ordered_options(item)
        chosen = next(o for o in options if o.id == item.selected_option_id)
        correct = next(o for o in options if o.is_correct)
        mistakes.append(Mistake(
            position=item.position, question=item.question.text,
            chosen_letter=letter(options.index(chosen)), chosen_text=chosen.text,
            correct_letter=letter(options.index(correct)), correct_text=correct.text,
        ))
    base = session.total if session.status == FINISHED else len(answered)
    return SessionSummary(session, len(answered), base, _percent(session.correct_count, base), mistakes)


# ---------------------------------------------------------------- leaderboard

@dataclass
class LeaderboardEntry:
    rank: int
    user_id: int
    name: str
    group: str | None
    correct: int
    total: int
    percent: int
    seconds: int
    finished_at: datetime


def _seconds(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds()))


async def leaderboard(
    db: AsyncSession, theme_id: int, user_id: int | None = None, limit: int = 10
) -> tuple[list[LeaderboardEntry], LeaderboardEntry | None]:
    """Best finished exam per registered user: higher score first, then faster, then earlier."""
    rows = await db.execute(
        select(QuizSession, User)
        .join(User, User.id == QuizSession.user_id)
        .where(
            QuizSession.theme_id == theme_id,
            QuizSession.mode == EXAM,
            QuizSession.status == FINISHED,
            User.registered_at.is_not(None),
        )
    )

    def sort_key(s: QuizSession):
        return (-s.correct_count / s.total, _seconds(s.started_at, s.finished_at), s.finished_at)

    best: dict[int, tuple[QuizSession, User]] = {}
    for session, user in rows:
        current = best.get(user.id)
        if current is None or sort_key(session) < sort_key(current[0]):
            best[user.id] = (session, user)

    ranked = sorted(best.values(), key=lambda pair: sort_key(pair[0]))
    entries = [
        LeaderboardEntry(
            rank=n, user_id=u.id, name=u.display_name, group=u.group_name,
            correct=s.correct_count, total=s.total, percent=_percent(s.correct_count, s.total),
            seconds=_seconds(s.started_at, s.finished_at), finished_at=s.finished_at,
        )
        for n, (s, u) in enumerate(ranked, start=1)
    ]
    mine = next((e for e in entries if e.user_id == user_id), None)
    return entries[:limit], mine


def format_duration(seconds: int) -> str:
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"
