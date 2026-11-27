"""Telegram handlers for group battles (rules live in bot/battle.py).

Flow: /battle -> theme picker -> lobby (Join/Start/Cancel, auto-start timer) -> 25 questions
(answer buttons, 30 s timer, early advance) -> reveal + top 3 -> ... -> results + private reviews.

Reliability: every battle step runs under a per-battle lock, and a watchdog job checks running
battles every few seconds and redoes any step that failed (e.g. a network timeout while posting a
question). All state is in the database, so the watchdog also resumes battles after a restart.
Old question messages are deleted as the battle moves on, leaving only the results in the chat.
"""

import asyncio
import html
import logging
import time
from datetime import timedelta

from telegram import ChatMember, InlineKeyboardMarkup, Update
from telegram import InlineKeyboardButton as Btn
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError
from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, ContextTypes, filters

from bot import battle as bt
from bot import services as svc
from bot.i18n import LANGUAGES, normalize_language, t
from bot.models import GroupChat, User, utcnow

log = logging.getLogger(__name__)

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
COUNTER_EDIT_INTERVAL = 5.0  # seconds between "Answered: x/y" edits (Telegram flood limits)
MAX_MESSAGE = 3800
GROUP_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)
WATCHDOG_INTERVAL = 3.0      # seconds between health checks of running battles
WATCHDOG_GRACE = 3.0         # how overdue a step must be before the watchdog redoes it
RETRIES = 3                  # attempts for edits/deletes on network errors


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _db(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["sessionmaker"]()


def _fmt_points(points: int) -> str:
    return f"{points:,}".replace(",", " ")


async def _group_lang(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str:
    async with _db(context) as db:
        group = await db.get(GroupChat, chat_id)
    return group.language if group else "uz"


async def _ensure_group(context: ContextTypes.DEFAULT_TYPE, chat) -> str:
    async with _db(context) as db:
        group = await bt.get_or_create_group(db, chat.id, chat.title)
    return group.language


async def _user_lang(context: ContextTypes.DEFAULT_TYPE, tg_user) -> str:
    async with _db(context) as db:
        user = await db.get(User, tg_user.id)
    if user and user.language:
        return user.language
    return normalize_language(tg_user.language_code)


async def _is_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
    except TelegramError:
        return False
    return member.status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER)


def _deep_link(context: ContextTypes.DEFAULT_TYPE) -> str:
    return f"https://t.me/{context.bot.username}?start=battle"


def _register_markup(context: ContextTypes.DEFAULT_TYPE, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[Btn(t(lang, "btn_register"), url=_deep_link(context))]])


async def _retrying(action, what: str) -> bool:
    """Run a Telegram call, retrying network errors a few times. Returns False if it finally failed."""
    for attempt in range(1, RETRIES + 1):
        try:
            await action()
            return True
        except BadRequest as e:
            if "not modified" not in str(e).lower() and "not found" not in str(e).lower():
                log.warning("%s failed: %s", what, e)
            return False
        except NetworkError as e:  # includes TimedOut; BadRequest is handled above
            if attempt == RETRIES:
                log.warning("%s failed after %d attempts: %s", what, RETRIES, e)
                return False
            await asyncio.sleep(attempt)
        except TelegramError as e:
            log.warning("%s failed: %s", what, e)
            return False
    return False


async def _edit(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int | None, text: str,
                markup: InlineKeyboardMarkup | None = None) -> None:
    if message_id is None:
        return
    await _retrying(
        lambda: context.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id,
                                              reply_markup=markup, parse_mode="HTML"),
        f"edit {chat_id}/{message_id}",
    )


async def _delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int | None) -> None:
    """Best effort: bots may delete their own messages in groups (younger than 48 h)."""
    if message_id is None:
        return
    await _retrying(lambda: context.bot.delete_message(chat_id, message_id), f"delete {chat_id}/{message_id}")


# ---------------------------------------------------------------- jobs & locks

def _job_name(battle_id: int, kind: str) -> str:
    return f"battle:{battle_id}:{kind}"


def _schedule(job_queue, callback, seconds: float, battle_id: int, kind: str, **data) -> None:
    job_queue.run_once(callback, when=max(seconds, 0.05), data={"battle_id": battle_id, **data},
                       name=_job_name(battle_id, kind))


def _has_job(job_queue, battle_id: int, kind: str) -> bool:
    name = _job_name(battle_id, kind)
    return any(job.name == name for job in job_queue.jobs())


def _cancel_jobs(job_queue, battle_id: int, kind: str | None = None) -> None:
    prefix = _job_name(battle_id, kind) if kind else f"battle:{battle_id}:"
    for job in job_queue.jobs():
        if job.name and job.name.startswith(prefix):
            job.schedule_removal()


def _lock(context: ContextTypes.DEFAULT_TYPE, battle_id: int) -> asyncio.Lock:
    """One battle step at a time (timer, early advance, buttons and watchdog never interleave)."""
    locks = context.application.bot_data.setdefault("battle_locks", {})
    return locks.setdefault(battle_id, asyncio.Lock())


# ---------------------------------------------------------------- views

def _starter_name(battle) -> str:
    starter = next((p for p in battle.players if p.user_id == battle.created_by), None)
    return starter.user.display_name if starter else "?"


def lobby_view(battle, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    players = "\n".join(f"• {esc(p.user.display_name)}" for p in battle.players)
    text = t(lang, "battle_lobby", theme=esc(battle.theme.name), n=battle.question_count,
             s=battle.seconds_per_question, name=esc(_starter_name(battle)), k=len(battle.players),
             players=players, min=bt.MIN_PLAYERS)
    markup = InlineKeyboardMarkup([
        [Btn(t(lang, "btn_join"), callback_data=f"bt:join:{battle.id}"),
         Btn(t(lang, "btn_start"), callback_data=f"bt:start:{battle.id}")],
        [Btn(t(lang, "btn_cancel"), callback_data=f"bt:cancel:{battle.id}")],
    ])
    return text, markup


def _question_lines(battle, item, lang: str) -> list[str]:
    header = t(lang, "battle_question_header", theme=esc(battle.theme.name), i=item.position + 1,
               n=battle.question_count, s=battle.seconds_per_question)
    return [f"<i>{header}</i>", "", f"<b>{esc(item.question.text)}</b>", ""]


def question_view(battle, item, lang: str, answered: int, players: int) -> tuple[str, InlineKeyboardMarkup]:
    options = bt.ordered_options(item)
    lines = _question_lines(battle, item, lang)
    lines += [f"<b>{bt.letter(i)})</b> {esc(o.text)}" for i, o in enumerate(options)]
    lines += ["", t(lang, "battle_answered", a=answered, p=players)]
    buttons = [Btn(bt.letter(i), callback_data=f"ba:{battle.id}:{item.position}:{i}") for i in range(len(options))]
    return "\n".join(lines), InlineKeyboardMarkup([buttons])


def _standing_line(s: bt.Standing, lang: str, with_correct: int | None = None) -> str:
    place = MEDALS.get(s.rank, f"{s.rank}.")
    line = f"{place} {esc(s.name)} — <b>{_fmt_points(s.points)}</b> {t(lang, 'battle_points')}"
    if with_correct is not None:
        line += f" · ✅ {s.correct}/{with_correct}"
    return line


def reveal_text(result: bt.RevealResult, lang: str) -> str:
    options = bt.ordered_options(result.item)
    lines = _question_lines(result.battle, result.item, lang)
    for i, o in enumerate(options):
        mark = "✅" if i == result.correct_index else "▫️"
        lines.append(f"{mark} <b>{bt.letter(i)})</b> {esc(o.text)}")
    lines += ["", t(lang, "battle_correct_count", c=result.correct, p=result.players), "", t(lang, "battle_top")]
    lines += [_standing_line(s, lang) for s in result.top]
    return "\n".join(lines)


def results_text(battle, table: list[bt.Standing], lang: str) -> str:
    lines = [t(lang, "battle_results_title", theme=esc(battle.theme.name)), ""]
    lines += [_standing_line(s, lang, with_correct=battle.question_count) for s in table]
    lines += ["", t(lang, "battle_results_footer")]
    return "\n".join(lines)


# ---------------------------------------------------------------- lobby

async def show_theme_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, tg_user = update.effective_chat, update.effective_user
    lang = await _ensure_group(context, chat)
    async with _db(context) as db:
        user = await db.get(User, tg_user.id)
        active = await bt.active_battle(db, chat.id)
        themes = await svc.list_themes(db)
    name = esc(user.display_name if user else tg_user.first_name)
    if user is None or not user.is_registered:
        await chat.send_message(t(lang, "battle_need_register", name=name),
                                reply_markup=_register_markup(context, lang), parse_mode="HTML")
        return
    if active:
        await chat.send_message(t(lang, "battle_already_active"))
        return
    rows = [[Btn(f"📚 {th.name}", callback_data=f"bt:theme:{th.id}:{tg_user.id}")] for th in themes]
    await chat.send_message(t(lang, "battle_choose_theme", name=name), reply_markup=InlineKeyboardMarkup(rows),
                            parse_mode="HTML")


async def on_theme_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE, theme_id: int, starter_id: int) -> None:
    query, chat, tg_user = update.callback_query, update.effective_chat, update.effective_user
    ulang = await _user_lang(context, tg_user)
    if tg_user.id != starter_id:
        await query.answer(t(ulang, "toast_only_starter"), show_alert=False)
        return
    lang = await _group_lang(context, chat.id)
    async with _db(context) as db:
        user = await db.get(User, tg_user.id)
        try:
            battle = await bt.create_battle(db, chat.id, theme_id, user, now=utcnow())
        except bt.BattleError as e:
            if e.code == "not_registered":
                await query.answer(url=_deep_link(context))
            else:
                await query.answer(t(ulang, "toast_battle_active" if e.code == "battle_active" else "toast_not_lobby"))
            return
        await bt.set_lobby_message(db, battle.id, query.message.message_id)
    await query.answer()
    text, markup = lobby_view(battle, lang)
    await _edit(context, chat.id, query.message.message_id, text, markup)
    _schedule(context.job_queue, job_lobby_timeout, bt.LOBBY_SECONDS, battle.id, "lobby")


async def on_join(update: Update, context: ContextTypes.DEFAULT_TYPE, battle_id: int) -> None:
    query, tg_user = update.callback_query, update.effective_user
    ulang = await _user_lang(context, tg_user)
    async with _db(context) as db:
        user = await db.get(User, tg_user.id)
        if user is None:
            user = await svc.upsert_user(db, tg_user.id, tg_user.username, tg_user.first_name)
        try:
            battle = await bt.join(db, battle_id, user, now=utcnow())
        except bt.BattleError as e:
            if e.code == "not_registered":
                await query.answer(url=_deep_link(context))  # opens the private chat to register
            else:
                await query.answer(t(ulang, f"toast_{e.code}"))
            return
    await query.answer(t(ulang, "toast_joined"))
    text, markup = lobby_view(battle, await _group_lang(context, battle.chat_id))
    await _edit(context, battle.chat_id, battle.lobby_message_id, text, markup)


async def on_start_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE, battle_id: int) -> None:
    query, tg_user = update.callback_query, update.effective_user
    ulang = await _user_lang(context, tg_user)
    async with _lock(context, battle_id):
        async with _db(context) as db:
            battle = await bt.get_battle(db, battle_id)
            if battle is None or battle.status != bt.LOBBY:
                await query.answer(t(ulang, "toast_not_lobby"))
                return
            if battle.created_by != tg_user.id:
                await query.answer(t(ulang, "toast_only_starter"))
                return
            try:
                battle = await bt.start(db, battle_id, now=utcnow())
            except bt.BattleError as e:
                key = "toast_need_players" if e.code == "not_enough_players" else "toast_not_lobby"
                await query.answer(t(ulang, key, min=bt.MIN_PLAYERS))
                return
        await query.answer()
        await _begin(context, battle)


async def job_lobby_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    battle_id = context.job.data["battle_id"]
    async with _lock(context, battle_id):
        await _lobby_timeout(context, battle_id)


async def _lobby_timeout(context: ContextTypes.DEFAULT_TYPE, battle_id: int) -> None:
    async with _db(context) as db:
        try:
            battle = await bt.start(db, battle_id, now=utcnow())
        except bt.BattleError as e:
            if e.code != "not_enough_players":
                return  # already started or cancelled
            battle = await bt.get_battle(db, battle_id)
            await bt.cancel(db, battle_id, now=utcnow())
            lang = await _group_lang(context, battle.chat_id)
            await _edit(context, battle.chat_id, battle.lobby_message_id,
                        t(lang, "battle_cancelled_players", min=bt.MIN_PLAYERS))
            return
    await _begin(context, battle)


async def _begin(context: ContextTypes.DEFAULT_TYPE, battle) -> None:
    _cancel_jobs(context.job_queue, battle.id, "lobby")
    lang = await _group_lang(context, battle.chat_id)
    players = ", ".join(esc(p.user.display_name) for p in battle.players)
    await _edit(context, battle.chat_id, battle.lobby_message_id,
                t(lang, "battle_started", theme=esc(battle.theme.name), players=players))
    await _post_question(context, battle.id)


# ---------------------------------------------------------------- questions (call with the battle lock held)

async def _post_question(context: ContextTypes.DEFAULT_TYPE, battle_id: int) -> None:
    async with _db(context) as db:
        battle = await bt.get_battle(db, battle_id)
        if battle is None or battle.status != bt.RUNNING:
            return
        item = await bt.get_question(db, battle_id, battle.current_index)
        previous = await bt.get_question(db, battle_id, item.position - 1) if item.position else None
    lang = await _group_lang(context, battle.chat_id)
    text, markup = question_view(battle, item, lang, answered=0, players=len(battle.players))
    # If this fails (e.g. network timeout) the watchdog posts it again a few seconds later.
    message = await context.bot.send_message(battle.chat_id, text, reply_markup=markup, parse_mode="HTML")
    async with _db(context) as db:
        await bt.mark_posted(db, battle_id, item.position, message.message_id, now=utcnow())
    _schedule(context.job_queue, job_question_timeout, battle.seconds_per_question, battle_id,
              f"q{item.position}", position=item.position)
    if previous is not None:
        await _delete(context, battle.chat_id, previous.message_id)  # keep the chat tidy


async def _reveal(context: ContextTypes.DEFAULT_TYPE, battle_id: int, position: int) -> None:
    async with _db(context) as db:
        result = await bt.reveal(db, battle_id, position)
    if result is None:
        return  # already revealed (timer vs. early advance) or battle cancelled
    _cancel_jobs(context.job_queue, battle_id, f"q{position}")
    context.application.bot_data.get("battle_counter", {}).pop((battle_id, position), None)
    # Schedule the next step first, so a failing edit can't stall the battle.
    _schedule(context.job_queue, job_next, bt.REVEAL_PAUSE_SECONDS, battle_id, "next", position=position)
    lang = await _group_lang(context, result.battle.chat_id)
    await _edit(context, result.battle.chat_id, result.item.message_id, reveal_text(result, lang))


async def _next(context: ContextTypes.DEFAULT_TYPE, battle_id: int, position: int) -> None:
    async with _db(context) as db:
        battle = await bt.advance(db, battle_id, position, now=utcnow())
    if battle is None:
        return
    if battle.status == bt.FINISHED:
        await _post_results(context, battle_id)
    else:
        await _post_question(context, battle_id)


async def job_question_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    battle_id = context.job.data["battle_id"]
    async with _lock(context, battle_id):
        await _reveal(context, battle_id, context.job.data["position"])


async def job_next(context: ContextTypes.DEFAULT_TYPE) -> None:
    battle_id = context.job.data["battle_id"]
    async with _lock(context, battle_id):
        await _next(context, battle_id, context.job.data["position"])


async def _post_results(context: ContextTypes.DEFAULT_TYPE, battle_id: int) -> None:
    async with _db(context) as db:
        battle = await bt.get_battle(db, battle_id)
        table = await bt.standings(db, battle_id)
        reviews = {s.user_id: await bt.player_review(db, battle_id, s.user_id) for s in table}
        last = await bt.get_question(db, battle_id, battle.question_count - 1)
    lang = await _group_lang(context, battle.chat_id)
    await context.bot.send_message(battle.chat_id, results_text(battle, table, lang), parse_mode="HTML")
    # Only the results stay in the chat.
    await _delete(context, battle.chat_id, last.message_id if last else None)
    await _delete(context, battle.chat_id, battle.lobby_message_id)

    users = {p.user_id: p.user for p in battle.players}
    for s in table:
        await send_review(context, battle, s, len(table), users[s.user_id], reviews[s.user_id])


async def send_review(context: ContextTypes.DEFAULT_TYPE, battle, standing: bt.Standing, total: int,
                      user: User, review: list[bt.ReviewItem]) -> None:
    lang = normalize_language(user.language)
    blocks = [t(lang, "battle_dm_title", theme=esc(battle.theme.name), rank=standing.rank, total=total,
                points=_fmt_points(standing.points), c=standing.correct, n=battle.question_count)]
    if not review:
        blocks.append(t(lang, "review_perfect"))
    else:
        blocks.append(t(lang, "review_title"))
    for r in review:
        yours = f"{r.chosen_letter}) {esc(r.chosen_text)}" if r.chosen_letter else f"<i>{t(lang, 'not_answered')}</i>"
        blocks.append(
            f"<b>{r.position + 1}. {esc(r.question)}</b>\n"
            f"❌ {t(lang, 'review_yours')}: {yours}\n"
            f"✅ {t(lang, 'review_correct')}: {r.correct_letter}) {esc(r.correct_text)}"
        )
    chunks, current = [], ""
    for block in blocks:
        if current and len(current) + len(block) + 2 > MAX_MESSAGE:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{block}" if current else block
    chunks.append(current)
    try:
        for chunk in chunks:
            await context.bot.send_message(user.id, chunk, parse_mode="HTML")
    except (Forbidden, BadRequest) as e:  # user blocked the bot or never opened a private chat
        log.info("could not send battle review to %s: %s", user.id, e)
    except NetworkError as e:
        log.warning("network error sending battle review to %s: %s", user.id, e)


async def _drop_duplicate(context: ContextTypes.DEFAULT_TYPE, battle_id: int, position: int, query) -> None:
    """Delete a stray copy of a question message.

    If posting a question hits a network error after Telegram already delivered it, the bot never
    learns that message's id and the watchdog posts the question again. The stray copy has the same
    buttons, so the first tap on it tells us its id: answer as usual, then delete it.
    """
    message_id = getattr(query.message, "message_id", None)
    if message_id is None:
        return
    async with _db(context) as db:
        item = await bt.get_question(db, battle_id, position)
        battle = await db.get(bt.Battle, battle_id) if item else None
    if item is None or item.message_id is None or item.message_id == message_id:
        return  # the real message (or its id isn't saved yet)
    log.info("battle %s: deleting duplicate copy %s of question %s", battle_id, message_id, position + 1)
    await _delete(context, battle.chat_id, message_id)


async def on_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, battle_id: int, position: int,
                    option_index: int) -> None:
    query, tg_user = update.callback_query, update.effective_user
    ulang = await _user_lang(context, tg_user)
    async with _db(context) as db:
        try:
            outcome = await bt.answer(db, battle_id, position, tg_user.id, option_index, now=utcnow())
        except bt.BattleError as e:
            await query.answer(t(ulang, f"toast_{e.code}"))
            await _drop_duplicate(context, battle_id, position, query)
            return
    await query.answer(t(ulang, "toast_answer_saved", letter=bt.letter(option_index)))
    await _drop_duplicate(context, battle_id, position, query)
    if outcome.everyone_answered:
        async with _lock(context, battle_id):
            await _reveal(context, battle_id, position)
        return
    # Live "Answered: x/y" counter, throttled to respect Telegram's per-group limits.
    counters = context.application.bot_data.setdefault("battle_counter", {})
    now = time.monotonic()
    if now - counters.get((battle_id, position), 0.0) < COUNTER_EDIT_INTERVAL:
        return
    counters[(battle_id, position)] = now
    async with _db(context) as db:
        battle = await bt.get_battle(db, battle_id)
        item = await bt.get_question(db, battle_id, position)
        answered, players = await bt.answered_count(db, battle_id, position)
    if battle.status != bt.RUNNING or item.revealed:
        return
    text, markup = question_view(battle, item, await _group_lang(context, battle.chat_id), answered, players)
    await _edit(context, battle.chat_id, item.message_id, text, markup)


async def cancel_battle(update: Update, context: ContextTypes.DEFAULT_TYPE, battle_id: int | None) -> None:
    chat, tg_user, query = update.effective_chat, update.effective_user, update.callback_query
    ulang = await _user_lang(context, tg_user)
    lang = await _group_lang(context, chat.id)
    async with _db(context) as db:
        battle = await bt.get_battle(db, battle_id) if battle_id else await bt.active_battle(db, chat.id)
    if battle is None or battle.status not in bt.ACTIVE or battle.chat_id != chat.id:
        if query:
            await query.answer(t(ulang, "toast_not_lobby"))
        else:
            await chat.send_message(t(lang, "battle_no_battle"))
        return
    if battle.created_by != tg_user.id and not await _is_admin(context, chat.id, tg_user.id):
        if query:
            await query.answer(t(ulang, "toast_not_allowed"))
        else:
            await chat.send_message(t(lang, "toast_not_allowed"))
        return
    if query:
        await query.answer()
    async with _lock(context, battle.id):
        async with _db(context) as db:
            was_running = (await bt.get_battle(db, battle.id)).status == bt.RUNNING
            cancelled = await bt.cancel(db, battle.id, now=utcnow())
            item = await bt.get_question(db, battle.id, battle.current_index) if was_running else None
        if not cancelled:
            return
        _cancel_jobs(context.job_queue, battle.id)
        if not was_running:
            await _edit(context, chat.id, battle.lobby_message_id, t(lang, "battle_cancelled"))
            return
        await chat.send_message(t(lang, "battle_cancelled"))
        await _delete(context, chat.id, item.message_id if item else None)
        await _delete(context, chat.id, battle.lobby_message_id)


# ---------------------------------------------------------------- watchdog (self-healing + restart recovery)

async def heal_battle(context: ContextTypes.DEFAULT_TYPE, battle_id: int) -> str | None:
    """Redo whatever step of this battle is overdue. Returns what it did (for logs/tests)."""
    lock = _lock(context, battle_id)
    if lock.locked():
        return None  # a step is in progress right now
    async with lock:
        async with _db(context) as db:
            battle = await bt.get_battle(db, battle_id)
            if battle is None or battle.status not in bt.ACTIVE:
                return None
            item = await bt.get_question(db, battle_id, battle.current_index) if battle.status == bt.RUNNING else None
        now, grace = utcnow(), timedelta(seconds=WATCHDOG_GRACE)
        jq = context.job_queue

        if battle.status == bt.LOBBY:
            if now > bt.as_utc(battle.lobby_deadline) + grace and not _has_job(jq, battle_id, "lobby"):
                await _lobby_timeout(context, battle_id)
                return "lobby_timeout"
            return None
        if item is None:
            return None
        if item.message_id is None or battle.question_started_at is None:
            log.warning("battle %s: question %s wasn't confirmed as posted; posting it again (if the first "
                        "attempt did reach Telegram, its copy is deleted when someone taps it)",
                        battle_id, item.position + 1)
            await _post_question(context, battle_id)
            return f"post q{item.position}"
        if not item.revealed:
            if now > bt.as_utc(battle.question_deadline) + grace:
                await _reveal(context, battle_id, item.position)
                return f"reveal q{item.position}"
            if not _has_job(jq, battle_id, f"q{item.position}"):  # timer lost (e.g. restart): re-arm it
                left = (bt.as_utc(battle.question_deadline) - now).total_seconds()
                _schedule(jq, job_question_timeout, left, battle_id, f"q{item.position}", position=item.position)
                return f"rearm q{item.position}"
            return None
        if not _has_job(jq, battle_id, "next"):
            await _next(context, battle_id, item.position)
            return f"next after q{item.position}"
        return None


async def job_watchdog(context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _db(context) as db:
        ids = [b.id for b in await bt.battles_to_recover(db)]
    for battle_id in ids:
        try:
            did = await heal_battle(context, battle_id)
            if did:
                log.info("battle %s watchdog: %s", battle_id, did)
        except Exception:  # keep watching the other battles
            log.exception("battle %s watchdog step failed (will retry)", battle_id)


async def recover_battles(app: Application) -> None:
    """Start the watchdog; it also resumes battles that were running before a restart."""
    app.job_queue.run_repeating(job_watchdog, interval=WATCHDOG_INTERVAL, first=1, name="battle-watchdog")


# ---------------------------------------------------------------- commands & routing

async def cmd_battle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_theme_picker(update, context)


async def cmd_battle_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cancel_battle(update, context, None)


async def cmd_group_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _ensure_group(context, update.effective_chat)
    markup = InlineKeyboardMarkup([[Btn(t(lang, "btn_battle_new"), callback_data="bt:new")]])
    await update.effective_chat.send_message(
        t(lang, "grp_help", n=bt.QUESTION_COUNT, s=bt.SECONDS_PER_QUESTION), reply_markup=markup, parse_mode="HTML"
    )


async def cmd_group_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, tg_user = update.effective_chat, update.effective_user
    lang = await _ensure_group(context, chat)
    if not await _is_admin(context, chat.id, tg_user.id):
        await chat.send_message(t(lang, "grp_language_admin_only"))
        return
    markup = InlineKeyboardMarkup([[Btn(name, callback_data=f"gl:{code}")] for code, name in LANGUAGES.items()])
    await chat.send_message(t(lang, "choose_language"), reply_markup=markup)


async def on_group_language(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    query, chat, tg_user = update.callback_query, update.effective_chat, update.effective_user
    if not await _is_admin(context, chat.id, tg_user.id):
        await query.answer(t(await _user_lang(context, tg_user), "grp_language_admin_only"))
        return
    code = normalize_language(code)
    async with _db(context) as db:
        await bt.get_or_create_group(db, chat.id, chat.title)
        await bt.set_group_language(db, chat.id, code)
    await query.answer()
    await _edit(context, chat.id, query.message.message_id, t(code, "grp_language_set", name=LANGUAGES[code]))


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The bot was added to a group: introduce battles."""
    change = update.my_chat_member
    if change.chat.type not in GROUP_TYPES:
        return
    was_in = change.old_chat_member.status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER)
    is_in = change.new_chat_member.status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR)
    if was_in or not is_in:
        return
    lang = await _ensure_group(context, change.chat)
    markup = InlineKeyboardMarkup([[Btn(t(lang, "btn_battle_new"), callback_data="bt:new")]])
    await context.bot.send_message(change.chat.id, t(lang, "grp_intro", n=bt.QUESTION_COUNT,
                                                     s=bt.SECONDS_PER_QUESTION),
                                   reply_markup=markup, parse_mode="HTML")


async def on_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if update.effective_chat is None or update.effective_chat.type not in GROUP_TYPES:
        await query.answer()
        return
    parts = (query.data or "").split(":")
    kind, action = parts[0], parts[1] if len(parts) > 1 else ""
    if kind == "ba":
        await on_answer(update, context, int(parts[1]), int(parts[2]), int(parts[3]))
    elif kind == "gl":
        await on_group_language(update, context, action)
    elif action == "new":
        await query.answer()
        await show_theme_picker(update, context)
    elif action == "theme":
        await on_theme_chosen(update, context, int(parts[2]), int(parts[3]))
    elif action == "join":
        await on_join(update, context, int(parts[2]))
    elif action == "start":
        await on_start_pressed(update, context, int(parts[2]))
    elif action == "cancel":
        await cancel_battle(update, context, int(parts[2]))
    else:
        await query.answer()


def register(app: Application) -> None:
    groups = filters.ChatType.GROUPS
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("battle", cmd_battle, filters=groups))
    app.add_handler(CommandHandler("battle_stop", cmd_battle_stop, filters=groups))
    app.add_handler(CommandHandler("language", cmd_group_language, filters=groups))
    app.add_handler(CommandHandler(["help", "start"], cmd_group_help, filters=groups))
    app.add_handler(CallbackQueryHandler(on_group_callback, pattern=r"^(bt|ba|gl):"))
