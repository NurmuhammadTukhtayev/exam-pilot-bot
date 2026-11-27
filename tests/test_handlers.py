"""Drive the handlers end-to-end with fake Telegram objects (no network)."""

from types import SimpleNamespace

from sqlalchemy import select

from bot import handlers
from bot.config import Settings


class FakeChat:
    def __init__(self):
        self.sent = []  # (text, markup)
        self.type = "private"

    async def send_message(self, text, reply_markup=None, parse_mode=None):
        self.sent.append((text, reply_markup))
        return SimpleNamespace(text=text)


class FakeQuery:
    def __init__(self, chat, data):
        self.chat, self.data, self.message = chat, data, SimpleNamespace()
        self.toasts, self.edits = [], []

    async def answer(self, text=None, **_):
        self.toasts.append(text)

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.edits.append((text, reply_markup))
        self.chat.sent.append((text, reply_markup))

    async def edit_message_reply_markup(self, reply_markup=None):
        pass


class Harness:
    def __init__(self, sessionmaker):
        self.chat = FakeChat()
        self.user = SimpleNamespace(id=42, username="tester", first_name="Test", language_code="ru")
        self.context = SimpleNamespace(
            user_data={},
            args=None,
            application=SimpleNamespace(bot_data={
                "sessionmaker": sessionmaker,
                "settings": Settings(bot_token="x", database_url="", exam_question_count=25),
            }),
        )

    def _update(self, query=None, text=None, contact=None):
        message = None
        if text is not None or contact is not None:
            message = SimpleNamespace(text=text, contact=contact, reply_text=self.chat.send_message)
        return SimpleNamespace(effective_user=self.user, effective_chat=self.chat, callback_query=query,
                               message=message)

    async def contact(self, user_id=None, phone="998 90 123-45-67"):
        contact = SimpleNamespace(user_id=user_id or self.user.id, phone_number=phone)
        await handlers.on_contact(self._update(contact=contact), self.context)

    async def register(self, lang="en", name="Ali Valiyev", group="5-kurs IX"):
        await self.command(handlers.cmd_start)
        await self.press(f"lang:{lang}")
        await self.text(name)
        await self.contact()
        await self.text(group)

    async def command(self, fn):
        await fn(self._update(), self.context)

    async def text(self, value):
        await handlers.on_text(self._update(text=value), self.context)

    async def press(self, data):
        query = FakeQuery(self.chat, data)
        await handlers.on_callback(self._update(query=query), self.context)
        return query

    @property
    def last(self):
        return self.chat.sent[-1]

    def buttons(self, markup=None):
        markup = markup or self.last[1]
        return [b.callback_data for row in markup.inline_keyboard for b in row]


async def test_full_practice_and_exam_flow(seeded):
    h = Harness(seeded)

    await h.command(handlers.cmd_start)
    assert "Выберите язык" in h.last[0]
    assert h.buttons() == ["lang:uz", "lang:ru", "lang:en"]

    await h.press("lang:en")
    assert "Please register" in h.chat.sent[-2][0]
    assert "full name" in h.last[0]

    # registration is required before anything else works
    await h.command(handlers.cmd_results)
    assert "full name" in h.last[0]
    await h.text("x")
    assert "3–100 characters" in h.last[0]
    await h.text("Ali   Valiyev")
    assert "share your phone" in h.last[0]
    await h.text("+998901234567")  # typed numbers aren't accepted
    assert "share your phone" in h.last[0]
    await h.contact(user_id=999)  # someone else's contact
    assert "your own number" in h.last[0]
    await h.contact()
    assert "Enter your group" in h.last[0]
    await h.text("5-kurs IX")
    assert "You're registered" in h.chat.sent[-2][0]
    assert "Choose a theme" in h.last[0]
    theme_button = next(b for b in h.buttons() if b.startswith("theme:"))
    theme_id = int(theme_button.split(":")[1])

    await h.press(theme_button)
    assert "Choose a mode" in h.last[0]
    await h.press(f"mode:{theme_id}:practice")
    assert "In which order" in h.last[0]
    assert h.buttons() == [f"order:{theme_id}:random", f"order:{theme_id}:seq", f"theme:{theme_id}"]
    await h.press(f"order:{theme_id}:random")
    assert "How many questions" in h.last[0]

    await h.text("abc")
    assert "Please send a number" in h.last[0]
    await h.text("3")
    assert "Question 1/3" in h.last[0]

    for i in range(3):
        ans = next(b for b in h.buttons() if b.startswith("ans:") and b.endswith(":0"))
        q = await h.press(ans)
        assert "Correct!" in q.edits[-1][0] or "Wrong. Correct answer" in q.edits[-1][0]
        # pressing the same button again is rejected
        q2 = await h.press(ans)
        assert q2.toasts == ["This question is already closed."]
        if i < 2:
            assert f"Question {i + 2}/3" in h.last[0]
    assert "Result" in h.last[0] and "/3" in h.last[0]

    # exam: 25 questions, answers revealed only at the end
    await h.press(f"mode:{theme_id}:exam")
    assert "Exam" in h.last[0] and "Question 1/25" in h.last[0]
    for _ in range(25):
        ans = next(b for b in h.buttons() if b.startswith("ans:") and b.endswith(":1"))
        q = await h.press(ans)
        assert "Your answer: B" in q.edits[-1][0]
        assert "Correct" not in q.edits[-1][0]
    texts = [t for t, _ in h.chat.sent[-6:]]
    assert any("/25" in t for t in texts)
    assert any("Mistakes review" in t for t in texts)
    assert all(len(t) <= 4096 for t, _ in h.chat.sent)

    await h.command(handlers.cmd_results)
    assert "Recent results" in h.last[0]
    assert h.last[0].count("\n") >= 3  # title, blank, 2 results


async def test_stop_and_resume(seeded):
    h = Harness(seeded)
    await h.register(lang="uz")
    theme_id = int(next(b for b in h.buttons() if b.startswith("theme:")).split(":")[1])
    await h.press(f"count:{theme_id}:5")
    first_answer = next(b for b in h.buttons() if b.startswith("ans:"))
    await h.press(first_answer)

    await h.command(handlers.show_main_menu)
    assert h.buttons()[0] == "resume"
    await h.press("resume")
    assert "Savol 2/5" in h.last[0]

    await h.press("stop")
    assert "to'xtatildi" in h.chat.sent[-1][0]
    assert "Javob berilgan: 1/5" in h.chat.sent[-1][0]
    await h.press(first_answer)  # old button after stop
    await h.command(handlers.show_main_menu)
    assert "resume" not in h.buttons()


async def test_profile_logout_login(seeded):
    h = Harness(seeded)
    await h.register()
    await h.press("profile")
    assert "Ali Valiyev" in h.last[0] and "+998901234567" in h.last[0] and "5-kurs IX" in h.last[0]

    await h.press("logout")
    assert "logged out" in h.last[0]
    await h.command(handlers.cmd_menu)
    assert "You're logged out" in h.last[0] and h.buttons() == ["login"]
    await h.press("login")
    assert "Choose a theme" in h.last[0]

    await h.press("edit_profile")
    assert "full name" in h.last[0]
    await h.text("Vali Aliyev")
    assert "Enter your group" in h.last[0]  # phone is kept
    await h.text("5-kurs X")
    await h.press("profile")
    assert "Vali Aliyev" in h.last[0] and "5-kurs X" in h.last[0]


async def test_leaderboard(seeded):
    alice, bob = Harness(seeded), Harness(seeded)
    bob.user = SimpleNamespace(id=43, username="bob", first_name="Bob", language_code="en")
    await alice.register(name="Alice Smith", group="G1")
    await bob.register(name="Bob Jones", group="G2")
    theme_id = int(next(b for b in alice.buttons() if b.startswith("theme:")).split(":")[1])

    await alice.press("top")
    await alice.press(f"top:{theme_id}")
    assert "No exam results" in alice.last[0] and "haven't taken" in alice.last[0]

    for h, idx in ((alice, 0), (bob, 1), (bob, 2)):
        await h.press(f"mode:{theme_id}:exam")
        for _ in range(25):
            ans = next(b for b in h.buttons() if b.startswith("ans:") and b.endswith(f":{idx}"))
            await h.press(ans)

    await bob.press(f"top:{theme_id}")
    board = bob.last[0]
    assert board.count("Bob Jones") == 1  # best attempt only
    assert "Alice Smith (G1)" in board and "Bob Jones (G2)" in board
    assert "Your rank: <b>" in board and "👈" in board


async def test_error_handler_log_levels(caplog):
    import logging

    from telegram.error import BadRequest, NetworkError, TimedOut

    caplog.set_level(logging.WARNING, logger="bot.handlers")
    for err in (NetworkError("httpx.ReadError: "), TimedOut()):
        caplog.clear()
        await handlers.on_error(None, SimpleNamespace(error=err))
        assert [r.levelname for r in caplog.records] == ["WARNING"] and caplog.records[0].exc_info is None

    for err in (BadRequest("Message is too long"), ValueError("boom")):
        caplog.clear()
        await handlers.on_error(None, SimpleNamespace(error=err))
        assert [r.levelname for r in caplog.records] == ["ERROR"] and caplog.records[0].exc_info


async def test_error_handler_job_errors_are_not_called_retried(caplog):
    import logging

    from telegram.error import TimedOut

    caplog.set_level(logging.WARNING, logger="bot.handlers")
    job = SimpleNamespace(name="battle:1:next")
    await handlers.on_error(None, SimpleNamespace(error=TimedOut(), job=job))
    assert "battle:1:next" in caplog.text and "watchdog will retry" in caplog.text
    caplog.clear()
    await handlers.on_error(None, SimpleNamespace(error=KeyError("x"), job=job))
    assert caplog.records[0].levelname == "ERROR" and caplog.records[0].exc_info


async def test_practice_in_order(seeded):
    """Practice "in order": pick a start number, questions come in document order, next chunk button."""
    from bot import services as svc
    from bot.models import Question

    h = Harness(seeded)
    await h.register()
    theme_id = int(next(b for b in h.buttons() if b.startswith("theme:")).split(":")[1])
    async with seeded() as db:
        ordered = await svc.theme_question_ids(db, theme_id)
        texts = {q.id: q.text for q in await db.scalars(select(Question).where(Question.id.in_(ordered)))}
    total = len(ordered)

    await h.press(f"mode:{theme_id}:practice")
    await h.press(f"order:{theme_id}:seq")
    assert "Start from which question" in h.last[0]
    assert h.buttons()[:3] == [f"from:{theme_id}:1", f"from:{theme_id}:26", f"from:{theme_id}:51"]

    # typed start number, then validation of the count against what's left from there
    await h.text(str(total + 1))
    assert f"from 1 to {total}" in h.last[0]
    await h.text("41")
    assert "How many questions from #41" in h.last[0]
    assert f"seq:{theme_id}:41:{total - 40}" in h.buttons()          # "All remaining"
    await h.text(str(total))                                          # more than what's left from #41
    assert f"from 1 to {total - 40}" in h.last[0]
    await h.text("3")

    for i in range(3):
        assert f"Question {i + 1}/3 · #{41 + i}" in h.last[0]
        assert texts[ordered[40 + i]].split()[0] in h.last[0]       # document order: #41, #42, #43
        await h.press(next(b for b in h.buttons() if b.startswith("ans:")))
        if i < 2:
            assert f"Question {i + 1}/3 · #{41 + i}" in h.chat.sent[-2][0]  # answered view keeps the number
    assert "#41–43" in h.last[0]
    assert h.buttons()[0] == f"again:{theme_id}:practice:3:44"        # ➡️ Next 3
    assert f"again:{theme_id}:practice:3:41" in h.buttons()           # 🔁 Again (same chunk)

    await h.press(f"again:{theme_id}:practice:3:44")
    assert "Question 1/3 · #44" in h.last[0]

    # the last chunk is capped at the end of the theme and offers no "next"
    await h.press("stop")
    await h.press(f"seq:{theme_id}:{total - 1}:5")
    assert f"Question 1/2 · #{total - 1}" in h.last[0]
    for _ in range(2):
        await h.press(next(b for b in h.buttons() if b.startswith("ans:")))
    assert not any(b.endswith(f":{total + 1}") for b in h.buttons())   # no next chunk after the last question

    await h.command(handlers.cmd_results)
    assert f"#{total - 1}–{total}" in h.last[0] and "#41–43" in h.last[0]
