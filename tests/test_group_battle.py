"""End-to-end group battle flow with a fake Telegram bot and a manually fired job queue."""

from types import SimpleNamespace

import pytest
from telegram.error import NetworkError

from bot import battle as bt
from bot import group_handlers as gh
from bot import handlers
from bot import services as svc
from bot.config import Settings

CHAT_ID = -1001234


class FakeBot:
    username = "examtestbot"

    def __init__(self, admins=()):
        self.messages = {}      # (chat_id, message_id) -> {"text", "markup"}
        self.log = []           # (chat_id, message_id) in send order
        self.admins = set(admins)
        self.deleted = set()
        self.fail_next_send = False
        self.deliver_then_fail_next_send = False   # Telegram posts it, but the bot gets a network error
        self._next_id = 100

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        if self.fail_next_send:
            self.fail_next_send = False
            from telegram.error import TimedOut
            raise TimedOut()
        self._next_id += 1
        self.messages[(chat_id, self._next_id)] = {"text": text, "markup": reply_markup}
        self.log.append((chat_id, self._next_id))
        if self.deliver_then_fail_next_send:
            self.deliver_then_fail_next_send = False
            from telegram.error import NetworkError
            raise NetworkError("httpx.ReadError: ")
        return SimpleNamespace(message_id=self._next_id)

    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None, parse_mode=None):
        self.messages[(chat_id, message_id)] = {"text": text, "markup": reply_markup}

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
        self.messages[(chat_id, message_id)]["markup"] = reply_markup

    async def delete_message(self, chat_id, message_id):
        self.deleted.add((chat_id, message_id))
        return True

    def visible(self, chat_id=CHAT_ID):
        """Texts of messages still in the chat (not deleted), in send order."""
        return [self.messages[k]["text"] for k in self.log if k[0] == chat_id and k not in self.deleted]

    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status="administrator" if user_id in self.admins else "member")

    # helpers
    def last(self, chat_id=CHAT_ID):
        key = [k for k in self.log if k[0] == chat_id][-1]
        return key[1], self.messages[key]

    def sent_to(self, chat_id):
        return [self.messages[k]["text"] for k in self.log if k[0] == chat_id]


class FakeJob:
    def __init__(self, callback, when, data, name):
        self.callback, self.when, self.data, self.name, self.removed = callback, when, data, name, False

    def schedule_removal(self):
        self.removed = True


class FakeJobQueue:
    def __init__(self):
        self._jobs = []

    def run_once(self, callback, when, data=None, name=None):
        self._jobs.append(FakeJob(callback, when, data, name))

    def jobs(self):
        return [j for j in self._jobs if not j.removed]

    def names(self):
        return [j.name for j in self.jobs()]


class Group:
    def __init__(self, sessionmaker, admins=()):
        self.bot = FakeBot(admins)
        self.jq = FakeJobQueue()
        self.app = SimpleNamespace(bot_data={
            "sessionmaker": sessionmaker,
            "settings": Settings(bot_token="x", database_url="", exam_question_count=25),
        }, job_queue=self.jq, bot=self.bot)
        self.chat = SimpleNamespace(id=CHAT_ID, type="supergroup", title="IX group", send_message=self._chat_send)

    async def _chat_send(self, text, reply_markup=None, parse_mode=None):
        return await self.bot.send_message(CHAT_ID, text, reply_markup=reply_markup, parse_mode=parse_mode)

    def context(self, job=None):
        return SimpleNamespace(application=self.app, bot=self.bot, bot_data=self.app.bot_data,
                               job_queue=self.jq, job=job, user_data={}, args=None)

    def update(self, user, query=None):
        return SimpleNamespace(effective_user=user, effective_chat=self.chat, callback_query=query, message=None)

    async def command(self, fn, user):
        await fn(self.update(user), self.context())

    async def press(self, user, data, message_id=None):
        query = SimpleNamespace(data=data, from_user=user, message=SimpleNamespace(message_id=message_id),
                                toasts=[], urls=[])

        async def answer(text=None, url=None, show_alert=False):
            query.toasts.append(text)
            query.urls.append(url)
        query.answer = answer
        await gh.on_group_callback(self.update(user, query), self.context())
        return query

    async def fire(self, prefix):
        """Run (and remove) the pending job whose name starts with `prefix`."""
        job = next(j for j in self.jq.jobs() if j.name.startswith(prefix))
        job.removed = True
        await job.callback(self.context(job))
        return job


def tg_user(uid, name, lang="en"):
    return SimpleNamespace(id=uid, first_name=name, username=None, language_code=lang)


async def register(sessionmaker, uid, name, lang="en"):
    async with sessionmaker() as db:
        user = await svc.upsert_user(db, uid, None, name)
        await svc.set_language(db, uid, lang)
        await svc.update_registration(db, user, full_name=name, phone="+1", group_name="G")


def buttons(markup):
    return [b.callback_data or b.url for row in markup.inline_keyboard for b in row] if markup else []


async def correct_index(sessionmaker, battle_id, position):
    async with sessionmaker() as db:
        item = await bt.get_question(db, battle_id, position)
    return next(i for i, o in enumerate(bt.ordered_options(item)) if o.is_correct)


@pytest.fixture
async def players(seeded):
    await register(seeded, 1, "Ali Valiyev", "ru")
    await register(seeded, 2, "Bob Jones", "en")
    await register(seeded, 4, "Admin Person", "en")
    return {"ali": tg_user(1, "Ali", "ru"), "bob": tg_user(2, "Bob"), "carl": tg_user(3, "Carl"),
            "admin": tg_user(4, "Admin")}


async def set_english(g, admin):
    await g.command(gh.cmd_group_language, admin)
    msg_id, msg = g.bot.last()
    assert "gl:en" in buttons(msg["markup"])
    await g.press(admin, "gl:en", msg_id)


async def test_full_battle(seeded, players):
    ali, bob, carl, admin = players["ali"], players["bob"], players["carl"], players["admin"]
    g = Group(seeded, admins={4})

    # bot added to the group -> intro in Uzbek (default group language) with a start button
    change = SimpleNamespace(chat=g.chat, old_chat_member=SimpleNamespace(status="left"),
                             new_chat_member=SimpleNamespace(status="member"))
    await gh.on_my_chat_member(SimpleNamespace(my_chat_member=change), g.context())
    _, intro = g.bot.last()
    assert "bellashuv" in intro["text"] and buttons(intro["markup"]) == ["bt:new"]

    # language: members can't change it, admins can
    await g.command(gh.cmd_group_language, bob)
    assert "Faqat" in g.bot.last()[1]["text"] or "faqat" in g.bot.last()[1]["text"]
    await set_english(g, admin)

    # unregistered member can't start; gets a register link
    await g.command(gh.cmd_battle, carl)
    _, msg = g.bot.last()
    assert "register" in msg["text"] and buttons(msg["markup"]) == ["https://t.me/examtestbot?start=battle"]

    # Ali starts -> theme picker that only Ali may use
    await g.command(gh.cmd_battle, ali)
    picker_id, picker = g.bot.last()
    theme_cb = buttons(picker["markup"])[0]
    q = await g.press(bob, theme_cb, picker_id)
    assert q.toasts == ["Only the person who started the battle can do this."]
    await g.press(ali, theme_cb, picker_id)
    lobby = g.bot.messages[(CHAT_ID, picker_id)]
    assert "Players (1)" in lobby["text"] and "Ali Valiyev" in lobby["text"]
    battle_id = int(buttons(lobby["markup"])[0].split(":")[2])
    assert g.jq.names() == [f"battle:{battle_id}:lobby"]

    # a second battle can't be opened meanwhile
    await g.command(gh.cmd_battle, bob)
    assert "already running" in g.bot.last()[1]["text"]

    # joining: unregistered -> deep link; Bob joins once; start rules
    q = await g.press(carl, f"bt:join:{battle_id}", picker_id)
    assert q.urls == ["https://t.me/examtestbot?start=battle"]
    q = await g.press(ali, f"bt:start:{battle_id}", picker_id)
    assert q.toasts == ["Нужно минимум 2 участника."]                       # Ali's popups are in Russian
    q = await g.press(bob, f"bt:join:{battle_id}", picker_id)
    assert q.toasts == ["You're in! ✅"]
    assert "Players (2)" in g.bot.messages[(CHAT_ID, picker_id)]["text"]
    q = await g.press(bob, f"bt:join:{battle_id}", picker_id)
    assert q.toasts == ["You've already joined."]
    q = await g.press(bob, f"bt:start:{battle_id}", picker_id)
    assert q.toasts == ["Only the person who started the battle can do this."]
    await g.press(ali, f"bt:start:{battle_id}", picker_id)
    assert "Battle started" in g.bot.messages[(CHAT_ID, picker_id)]["text"]
    assert g.jq.names() == [f"battle:{battle_id}:q0"]                     # lobby timer removed

    for pos in range(25):
        qmsg_id, qmsg = g.bot.last()
        assert f"question {pos + 1}/25" in qmsg["text"] and "Answered: 0/2" in qmsg["text"]
        right = await correct_index(seeded, battle_id, pos)
        wrong = (right + 1) % 4

        q = await g.press(carl, f"ba:{battle_id}:{pos}:{right}", qmsg_id)
        assert q.toasts == ["You're not in this battle. Join the next one!"]
        q = await g.press(ali, f"ba:{battle_id}:{pos}:{right}", qmsg_id)
        assert q.toasts == [f"Ответ принят: {bt.letter(right)}"]            # no hint whether it's right
        q = await g.press(ali, f"ba:{battle_id}:{pos}:{wrong}", qmsg_id)
        assert q.toasts == ["Вы уже ответили."]

        if pos == 3:
            # Bob doesn't answer -> the 30 s timer reveals the question
            assert "Answered: 1/2" in g.bot.messages[(CHAT_ID, qmsg_id)]["text"]   # live counter
            await g.fire(f"battle:{battle_id}:q{pos}")
        else:
            await g.press(bob, f"ba:{battle_id}:{pos}:{wrong}", qmsg_id)    # everyone answered -> early reveal
            assert f"battle:{battle_id}:q{pos}" not in g.jq.names()

        revealed = g.bot.messages[(CHAT_ID, qmsg_id)]
        assert f"✅ <b>{bt.letter(right)})</b>" in revealed["text"] and "Correct: 1/2" in revealed["text"]
        assert "🥇 Ali Valiyev" in revealed["text"] and revealed["markup"] is None
        q = await g.press(bob, f"ba:{battle_id}:{pos}:{right}", qmsg_id)
        assert q.toasts == ["Time's up for this question."]
        await g.fire(f"battle:{battle_id}:next")
        if pos < 24:
            assert (CHAT_ID, qmsg_id) in g.bot.deleted                     # old question cleaned up

    results = g.bot.sent_to(CHAT_ID)[-1]
    assert "Battle results" in results and "🥇 Ali Valiyev" in results and "✅ 25/25" in results
    assert "🥈 Bob Jones" in results and "✅ 0/25" in results
    visible = g.bot.visible()
    assert not any("question" in v and "/25" in v for v in visible)           # no question messages left
    assert not any("Battle started" in v for v in visible)                     # lobby message removed
    assert visible[-1] == results
    ali_dm = "\n".join(g.bot.sent_to(1))
    assert "Разбор батла" in ali_dm and "Место: <b>1/2</b>" in ali_dm and "Все ответы верные" in ali_dm
    bob_dm = "\n".join(g.bot.sent_to(2))
    assert "Rank: <b>2/2</b>" in bob_dm and bob_dm.count("❌ Your answer") == 25
    assert "not answered" in bob_dm                                          # question 4 timed out
    assert g.jq.names() == []


async def test_cancel_rules_and_lobby_timeout(seeded, players):
    ali, bob, admin = players["ali"], players["bob"], players["admin"]
    g = Group(seeded, admins={4})
    await set_english(g, admin)

    await g.command(gh.cmd_battle, ali)
    picker_id, picker = g.bot.last()
    await g.press(ali, buttons(picker["markup"])[0], picker_id)
    battle_id = int(buttons(g.bot.messages[(CHAT_ID, picker_id)]["markup"])[0].split(":")[2])

    q = await g.press(bob, f"bt:cancel:{battle_id}", picker_id)
    assert q.toasts == ["Only the starter or a group admin can do this."]
    # nobody else joined -> the 2-minute timer cancels it
    await g.fire(f"battle:{battle_id}:lobby")
    assert "not enough players" in g.bot.messages[(CHAT_ID, picker_id)]["text"]

    # a running battle cancelled by an admin
    await g.command(gh.cmd_battle, ali)
    picker_id, picker = g.bot.last()
    await g.press(ali, buttons(picker["markup"])[0], picker_id)
    battle_id = int(buttons(g.bot.messages[(CHAT_ID, picker_id)]["markup"])[0].split(":")[2])
    await g.press(bob, f"bt:join:{battle_id}", picker_id)
    await g.fire(f"battle:{battle_id}:lobby")                                # auto-start with 2 players
    qmsg_id, qmsg = g.bot.last()
    assert "question 1/25" in qmsg["text"]

    await g.command(gh.cmd_battle_stop, bob)
    assert "Only the starter or a group admin" in g.bot.last()[1]["text"]
    await g.command(gh.cmd_battle_stop, admin)
    assert "Battle cancelled" in g.bot.last()[1]["text"]
    assert (CHAT_ID, qmsg_id) in g.bot.deleted and g.jq.names() == []        # question removed from chat
    await g.command(gh.cmd_battle_stop, admin)
    assert "no active battle" in g.bot.last()[1]["text"]


async def start_two_player_battle(g, ali, bob):
    await g.command(gh.cmd_battle, ali)
    picker_id, picker = g.bot.last()
    await g.press(ali, buttons(picker["markup"])[0], picker_id)
    battle_id = int(buttons(g.bot.messages[(CHAT_ID, picker_id)]["markup"])[0].split(":")[2])
    await g.press(bob, f"bt:join:{battle_id}", picker_id)
    return battle_id, picker_id


async def overdue(sessionmaker, battle_id, seconds=60):
    """Move the current question's clock into the past (as if the timer job was lost)."""
    from datetime import timedelta

    from sqlalchemy import update

    from bot.models import Battle
    async with sessionmaker() as db:
        b = await db.get(Battle, battle_id)
        await db.execute(update(Battle).where(Battle.id == battle_id).values(
            question_started_at=bt.as_utc(b.question_started_at) - timedelta(seconds=seconds),
            question_deadline=bt.as_utc(b.question_deadline) - timedelta(seconds=seconds)))
        await db.commit()


async def test_watchdog_heals_failed_steps_and_restarts(seeded, players):
    ali, bob, admin = players["ali"], players["bob"], players["admin"]
    g = Group(seeded, admins={4})
    await set_english(g, admin)
    battle_id, picker_id = await start_two_player_battle(g, ali, bob)

    # Posting question 1 times out -> nothing is shown, the battle would be stuck...
    g.bot.fail_next_send = True
    with pytest.raises(NetworkError):  # TimedOut is a NetworkError
        await g.press(ali, f"bt:start:{battle_id}", picker_id)
    assert not any("question 1/25" in v for v in g.bot.visible())
    # ...until the watchdog posts it.
    assert await gh.heal_battle(g.context(), battle_id) == "post q0"
    assert "question 1/25" in g.bot.last()[1]["text"]
    assert await gh.heal_battle(g.context(), battle_id) is None                # healthy: nothing to do

    # Restart: timers are gone. The watchdog re-arms the open question's timer...
    g.jq._jobs.clear()
    assert await gh.heal_battle(g.context(), battle_id) == "rearm q0"
    assert g.jq.names() == [f"battle:{battle_id}:q0"]
    # ...or reveals it if it's already overdue,
    g.jq._jobs.clear()
    await overdue(seeded, battle_id)
    assert await gh.heal_battle(g.context(), battle_id) == "reveal q0"
    assert "Correct: 0/2" in g.bot.last()[1]["text"]
    # ...and moves on if the "next" step was lost.
    g.jq._jobs.clear()
    assert await gh.heal_battle(g.context(), battle_id) == "next after q0"
    assert "question 2/25" in g.bot.last()[1]["text"]

    # The watchdog itself is a repeating job started at boot.
    calls = []
    g.app.job_queue.run_repeating = lambda cb, interval, first, name: calls.append((cb, interval, name))
    await gh.recover_battles(g.app)
    assert calls == [(gh.job_watchdog, gh.WATCHDOG_INTERVAL, "battle-watchdog")]


async def test_duplicate_question_copy_is_removed_when_tapped(seeded, players):
    ali, bob, admin = players["ali"], players["bob"], players["admin"]
    g = Group(seeded, admins={4})
    await set_english(g, admin)
    battle_id, picker_id = await start_two_player_battle(g, ali, bob)

    # Question 1 reaches the group, but the bot only sees a network error -> it can't know the id.
    g.bot.deliver_then_fail_next_send = True
    with pytest.raises(NetworkError):  # TimedOut is a NetworkError
        await g.press(ali, f"bt:start:{battle_id}", picker_id)
    stray_id, stray = g.bot.last()
    assert "question 1/25" in stray["text"]
    # The watchdog posts it again: now the group sees question 1 twice.
    assert await gh.heal_battle(g.context(), battle_id) == "post q0"
    real_id, _ = g.bot.last()
    assert sum("question 1/25" in v for v in g.bot.visible()) == 2

    # Tapping the stray copy still counts as an answer (same option order) and removes the copy.
    right = await correct_index(seeded, battle_id, 0)
    q = await g.press(ali, f"ba:{battle_id}:0:{right}", stray_id)
    assert q.toasts == [f"Ответ принят: {bt.letter(right)}"]
    assert (CHAT_ID, stray_id) in g.bot.deleted and (CHAT_ID, real_id) not in g.bot.deleted
    assert sum("question 1/25" in v for v in g.bot.visible()) == 1
    # Taps on the real message never delete it.
    await g.press(bob, f"ba:{battle_id}:0:{right}", real_id)
    assert (CHAT_ID, real_id) not in g.bot.deleted
    assert "Correct: 2/2" in g.bot.messages[(CHAT_ID, real_id)]["text"]   # both answers counted


async def test_lobby_watchdog_after_restart(seeded, players):
    ali, admin = players["ali"], players["admin"]
    g = Group(seeded, admins={4})
    await set_english(g, admin)
    await g.command(gh.cmd_battle, ali)
    picker_id, picker = g.bot.last()
    await g.press(ali, buttons(picker["markup"])[0], picker_id)
    battle_id = int(buttons(g.bot.messages[(CHAT_ID, picker_id)]["markup"])[0].split(":")[2])
    g.jq._jobs.clear()                                                          # restart lost the lobby timer
    assert await gh.heal_battle(g.context(), battle_id) is None                 # not due yet
    from datetime import timedelta

    from sqlalchemy import update

    from bot.models import Battle, utcnow
    async with seeded() as db:
        await db.execute(update(Battle).where(Battle.id == battle_id)
                         .values(lobby_deadline=utcnow() - timedelta(minutes=1)))
        await db.commit()
    assert await gh.heal_battle(g.context(), battle_id) == "lobby_timeout"
    assert "not enough players" in g.bot.messages[(CHAT_ID, picker_id)]["text"]


async def test_private_router_ignores_group_buttons(seeded):
    chat = SimpleNamespace(id=CHAT_ID, type="supergroup")
    toasts = []

    async def answer(text=None, **_):
        toasts.append(text)
    query = SimpleNamespace(data="menu", answer=answer)
    update = SimpleNamespace(effective_chat=chat, effective_user=tg_user(1, "A"), callback_query=query)
    await handlers.on_callback(update, SimpleNamespace(user_data={}))
    assert toasts == [None]
