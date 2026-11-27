import random

from bot import services as svc


async def _user_and_theme(db, name_part="Bulutli"):
    await svc.upsert_user(db, 1, "u", "User")
    themes = await svc.list_themes(db)
    return next(t for t in themes if name_part in t.name)


async def test_list_themes(seeded):
    async with seeded() as db:
        themes = await svc.list_themes(db)
    assert sorted(t.question_count for t in themes) == [159, 194, 194]


async def test_exam_has_25_unique_questions_with_shuffled_options(seeded):
    async with seeded() as db:
        theme = await _user_and_theme(db)
        session = await svc.start_quiz(db, 1, theme.id, svc.EXAM, 25, rng=random.Random(1))
        items = await svc.session_items(db, session.id)
    assert session.total == 25 and len(items) == 25
    assert len({i.question_id for i in items}) == 25
    for item in items:
        assert sorted(item.option_order) == sorted(o.id for o in item.question.options)
    # with 25 questions, options can't all be in doc order (correct answer first)
    assert any(svc.ordered_options(i)[0].is_correct is False for i in items)


async def test_practice_count_is_capped(seeded):
    async with seeded() as db:
        theme = await _user_and_theme(db)
        session = await svc.start_quiz(db, 1, theme.id, svc.PRACTICE, 10_000)
    assert session.total == theme.question_count


async def test_answer_flow_and_stale_presses(seeded):
    async with seeded() as db:
        theme = await _user_and_theme(db)
        session = await svc.start_quiz(db, 1, theme.id, svc.PRACTICE, 3, rng=random.Random(2))

    correct_answers = 0
    for position in range(3):
        async with seeded() as db:
            item = await svc.get_item(db, session.id, position)
            options = svc.ordered_options(item)
            # answer first question correctly, the rest wrong
            want_correct = position == 0
            idx = next(i for i, o in enumerate(options) if o.is_correct == want_correct)
            assert await svc.answer(db, 2, session.id, position, idx) is None  # someone else's session
            assert await svc.answer(db, 1, session.id, position + 1, idx) is None  # not current yet
            result = await svc.answer(db, 1, session.id, position, idx)
            assert result.is_correct == want_correct
            correct_answers += want_correct
            assert await svc.answer(db, 1, session.id, position, idx) is None  # double tap
            assert result.finished == (position == 2)

    async with seeded() as db:
        assert await svc.get_active_session(db, 1) is None
        results = await svc.recent_results(db, 1)
    assert results[0].correct_count == correct_answers == 1


async def test_new_quiz_stops_previous_and_stop(seeded):
    async with seeded() as db:
        theme = await _user_and_theme(db)
        first = await svc.start_quiz(db, 1, theme.id, svc.PRACTICE, 5)
        second = await svc.start_quiz(db, 1, theme.id, svc.EXAM, 25)
        active = await svc.get_active_session(db, 1)
        assert active.id == second.id
        await db.refresh(first)
        assert first.status == svc.STOPPED
        stopped = await svc.stop_active(db, 1)
        assert stopped.id == second.id
        assert await svc.get_active_session(db, 1) is None
        assert await svc.recent_results(db, 1) == []


async def test_leaderboard_ranking_rules(seeded):
    """Best attempt per user; higher score wins; equal scores -> faster wins; unregistered users hidden."""
    from datetime import timedelta

    from bot.models import QuizSession

    async with seeded() as db:
        theme = await _user_and_theme(db)
        now = svc.utcnow()
        users = {1: "Slow", 2: "Fast", 3: "Better", 4: "Unregistered"}
        for uid, name in users.items():
            user = await svc.upsert_user(db, uid, None, name)
            if name != "Unregistered":
                await svc.update_registration(db, user, full_name=name, phone="+1", group_name="G")

        def exam(uid, correct, minutes):
            return QuizSession(user_id=uid, theme_id=theme.id, mode=svc.EXAM, status=svc.FINISHED, total=25,
                               current_index=25, correct_count=correct,
                               started_at=now - timedelta(minutes=minutes), finished_at=now)

        db.add_all([
            exam(1, 20, 10), exam(1, 5, 1),     # Slow: best is 20/25 in 10 min
            exam(2, 20, 4),                      # Fast: 20/25 in 4 min
            exam(3, 22, 30),                     # Better: higher score beats speed
            exam(4, 25, 1),                      # not registered -> not listed
        ])
        practice = exam(3, 25, 1)
        practice.mode = svc.PRACTICE             # practice never counts
        db.add(practice)
        await db.commit()

        top, mine = await svc.leaderboard(db, theme.id, user_id=1)
    assert [(e.rank, e.name, e.correct) for e in top] == [(1, "Better", 22), (2, "Fast", 20), (3, "Slow", 20)]
    assert mine.rank == 3 and mine.seconds == 600
    assert svc.format_duration(600) == "10:00" and svc.format_duration(3725) == "1:02:05"
