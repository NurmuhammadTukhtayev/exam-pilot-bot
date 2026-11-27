import random
from datetime import UTC, datetime, timedelta

import pytest

from bot import battle as bt
from bot import services as svc

T0 = datetime(2026, 11, 27, 12, 0, 0, tzinfo=UTC)
CHAT = -100123


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


async def make_user(db, uid, name=None, registered=True):
    user = await svc.upsert_user(db, uid, None, name or f"U{uid}")
    if registered:
        await svc.update_registration(db, user, full_name=name or f"User {uid}", phone="+1", group_name="G")
    return user


async def lobby_with(db, *uids):
    await bt.get_or_create_group(db, CHAT, "Group")
    theme = (await svc.list_themes(db))[0]
    users = [await make_user(db, uid) for uid in uids]
    battle = await bt.create_battle(db, CHAT, theme.id, users[0], now=T0)
    for u in users[1:]:
        battle = await bt.join(db, battle.id, u, now=T0)
    return battle, users


async def post(db, battle, position, now):
    return await bt.mark_posted(db, battle.id, position, message_id=1000 + position, now=now)


async def answer_correct(db, battle_id, position, uid, now, correct=True):
    item = await bt.get_question(db, battle_id, position)
    idx = next(i for i, o in enumerate(bt.ordered_options(item)) if o.is_correct == correct)
    return await bt.answer(db, battle_id, position, uid, idx, now)


def test_speed_points():
    assert bt.speed_points(0, 30) == 1000
    assert bt.speed_points(3_000, 30) == 950
    assert bt.speed_points(15_000, 30) == 750
    assert bt.speed_points(30_000, 30) == 500
    assert bt.speed_points(99_000, 30) == 500


async def test_lobby_rules(seeded):
    async with seeded() as db:
        await bt.get_or_create_group(db, CHAT, "Group")
        theme = (await svc.list_themes(db))[0]
        stranger = await make_user(db, 9, registered=False)
        with pytest.raises(bt.BattleError, match="not_registered"):
            await bt.create_battle(db, CHAT, theme.id, stranger, now=T0)

        battle, (ali, bob) = await lobby_with(db, 1, 2)
        assert [p.user_id for p in battle.players] == [1, 2]  # starter joined automatically
        assert battle.question_count == 25 and battle.seconds_per_question == 30
        assert bt.as_utc(battle.lobby_deadline) == at(120)

        with pytest.raises(bt.BattleError, match="battle_active"):
            await bt.create_battle(db, CHAT, theme.id, ali, now=T0)
        with pytest.raises(bt.BattleError, match="already_joined"):
            await bt.join(db, battle.id, bob, now=T0)
        with pytest.raises(bt.BattleError, match="not_registered"):
            await bt.join(db, battle.id, stranger, now=T0)


async def test_start_needs_two_players_and_only_once(seeded):
    async with seeded() as db:
        battle, _ = await lobby_with(db, 1)
        with pytest.raises(bt.BattleError, match="not_enough_players"):
            await bt.start(db, battle.id, now=at(5))
        carol = await make_user(db, 3)
        await bt.join(db, battle.id, carol, now=at(6))
        started = await bt.start(db, battle.id, now=at(7), rng=random.Random(1))
        assert started.status == bt.RUNNING and started.current_index == 0
        with pytest.raises(bt.BattleError, match="not_lobby"):
            await bt.start(db, battle.id, now=at(8))
        with pytest.raises(bt.BattleError, match="not_lobby"):
            await bt.join(db, battle.id, await make_user(db, 4), now=at(8))
        items = [await bt.get_question(db, battle.id, i) for i in range(25)]
        assert len({i.question_id for i in items}) == 25


async def test_answer_scoring_and_guards(seeded):
    async with seeded() as db:
        battle, _ = await lobby_with(db, 1, 2, 3)
        await bt.start(db, battle.id, now=at(1))
        # not posted yet -> no clock -> rejected
        with pytest.raises(bt.BattleError, match="too_late"):
            await answer_correct(db, battle.id, 0, 1, at(1))

        deadline = await post(db, battle, 0, at(10))
        assert deadline == at(40)
        out = await answer_correct(db, battle.id, 0, 1, at(13))            # 3 s, correct -> 950
        assert (out.answered, out.players, out.everyone_answered) == (1, 3, False)
        with pytest.raises(bt.BattleError, match="already_answered"):
            await answer_correct(db, battle.id, 0, 1, at(14))
        with pytest.raises(bt.BattleError, match="not_player"):
            await answer_correct(db, battle.id, 0, 99, at(14))
        with pytest.raises(bt.BattleError, match="too_late"):
            await answer_correct(db, battle.id, 0, 2, at(42))               # past deadline + grace
        out = await answer_correct(db, battle.id, 0, 2, at(41), correct=False)  # within grace, wrong -> 0
        out = await answer_correct(db, battle.id, 0, 3, at(25))            # 15 s -> 750
        assert out.everyone_answered
        with pytest.raises(bt.BattleError, match="too_late"):
            await answer_correct(db, battle.id, 1, 1, at(26))               # not the current question

        result = await bt.reveal(db, battle.id, 0)
        assert (result.answered, result.correct, result.players) == (3, 2, 3)
        assert [(s.user_id, s.points) for s in result.top] == [(1, 950), (3, 750), (2, 0)]
        assert await bt.reveal(db, battle.id, 0) is None                    # idempotent
        with pytest.raises(bt.BattleError, match="too_late"):
            await answer_correct(db, battle.id, 0, 2, at(30))               # closed


async def test_full_battle_finishes_and_reviews(seeded):
    async with seeded() as db:
        battle, _ = await lobby_with(db, 1, 2)
        await bt.start(db, battle.id, now=at(0))
        t = 0
        for pos in range(25):
            t += 10
            await post(db, battle, pos, at(t))
            await answer_correct(db, battle.id, pos, 1, at(t + 2))                       # always right, fast
            if pos % 2 == 0:
                await answer_correct(db, battle.id, pos, 2, at(t + 5), correct=False)    # wrong half the time
            assert await bt.reveal(db, battle.id, pos)
            assert await bt.advance(db, battle.id, pos + 1, at(t + 6)) is None           # wrong position
            moved = await bt.advance(db, battle.id, pos, at(t + 6))
            assert moved.status == (bt.FINISHED if pos == 24 else bt.RUNNING)
            assert await bt.advance(db, battle.id, pos, at(t + 6)) is None               # only once

        table = await bt.standings(db, battle.id)
        assert [(s.rank, s.user_id, s.correct) for s in table] == [(1, 1, 25), (2, 2, 0)]
        assert table[0].points == 25 * bt.speed_points(2000, 30)
        assert await bt.player_review(db, battle.id, 1) == []
        review = await bt.player_review(db, battle.id, 2)
        assert len(review) == 25                                     # 13 wrong + 12 unanswered
        assert sum(r.chosen_letter is None for r in review) == 12
        assert await bt.active_battle(db, CHAT) is None


async def test_ties_and_cancel(seeded):
    async with seeded() as db:
        battle, _ = await lobby_with(db, 1, 2, 3)
        await bt.start(db, battle.id, now=at(0))
        await post(db, battle, 0, at(0))
        # 2 and 3 tie on points (same time); 3 joined later, so 2 ranks higher
        await answer_correct(db, battle.id, 0, 3, at(4))
        await answer_correct(db, battle.id, 0, 2, at(4))
        table = await bt.standings(db, battle.id)
        assert [s.user_id for s in table] == [2, 3, 1]

        assert await bt.cancel(db, battle.id, at(5)) is True
        assert await bt.cancel(db, battle.id, at(6)) is False
        assert await bt.reveal(db, battle.id, 0) is None
        with pytest.raises(bt.BattleError):
            await answer_correct(db, battle.id, 0, 1, at(6))
        assert await bt.active_battle(db, CHAT) is None
