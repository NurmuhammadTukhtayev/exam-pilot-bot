import html
import logging

from telegram import InlineKeyboardButton as Btn
from telegram import (
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    WebAppInfo,
)
from telegram.error import BadRequest, NetworkError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import services as svc
from bot.i18n import LANGUAGES, normalize_language, t
from bot.models import QuizSession, SessionQuestion, User

log = logging.getLogger(__name__)

PRACTICE_PRESETS = (10, 20, 30, 50)
MAX_MESSAGE = 3800  # Telegram limit is 4096; keep headroom for formatting
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def esc(text: str) -> str:
    """Escape for Telegram HTML (only <, > and & are special)."""
    return html.escape(text, quote=False)


# ---------------------------------------------------------------- helpers

def _db(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["sessionmaker"]()


def _settings(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["settings"]


def _exam_count(context: ContextTypes.DEFAULT_TYPE) -> int:
    return _settings(context).exam_question_count


async def _get_user(db, update: Update) -> User:
    u = update.effective_user
    user = await db.get(User, u.id)
    if user is None:
        user = await svc.upsert_user(db, u.id, u.username, u.first_name)
    return user


async def _lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    lang = context.user_data.get("lang")
    if lang:
        return lang
    async with _db(context) as db:
        user = await db.get(User, update.effective_user.id)
    if user and user.language:
        context.user_data["lang"] = user.language
        return user.language
    return normalize_language(update.effective_user.language_code)


async def _show(update: Update, text: str, markup, edit: bool) -> Message | None:
    """Edit the callback's message when possible, otherwise send a new one."""
    query = update.callback_query
    if edit and query and query.message and not isinstance(markup, (ReplyKeyboardMarkup, ReplyKeyboardRemove)):
        try:
            return await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return None
            log.warning("edit failed, sending new message: %s", e)
    return await update.effective_chat.send_message(text, reply_markup=markup, parse_mode="HTML")


def _mode_label(lang: str, mode: str) -> str:
    return t(lang, "mode_exam_short" if mode == svc.EXAM else "mode_practice_short")


def _chunks(blocks: list[str]) -> list[str]:
    out, current = [], ""
    for block in blocks:
        if current and len(current) + len(block) + 2 > MAX_MESSAGE:
            out.append(current)
            current = ""
        current = f"{current}\n\n{block}" if current else block
    if current:
        out.append(current)
    return out


def _webapp_url(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    url = _settings(context).webapp_url
    return url if url.startswith("https://") else None


# ---------------------------------------------------------------- access control

def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[Btn(name, callback_data=f"lang:{code}")] for code, name in LANGUAGES.items()])


async def prompt_registration(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User,
                              intro: bool = False) -> None:
    lang = user.language or await _lang(update, context)
    step = svc.registration_step(user)
    if intro:
        await update.effective_chat.send_message(t(lang, "reg_intro"))
    if step == svc.STEP_NAME:
        await update.effective_chat.send_message(t(lang, "reg_ask_name"), reply_markup=ReplyKeyboardRemove())
    elif step == svc.STEP_PHONE:
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton(t(lang, "reg_share_phone"), request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True,
        )
        await update.effective_chat.send_message(t(lang, "reg_ask_phone"), reply_markup=keyboard)
    elif step == svc.STEP_GROUP:
        await update.effective_chat.send_message(t(lang, "reg_ask_group"), reply_markup=ReplyKeyboardRemove())


async def _registration_finished(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str) -> None:
    await update.effective_chat.send_message(t(lang, "reg_done"), reply_markup=ReplyKeyboardRemove())
    if context.user_data.pop("from_battle", False):
        await update.effective_chat.send_message(t(lang, "battle_dm_registered"))
    await show_main_menu(update, context)


async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> User | None:
    """Return the user if they may use the bot; otherwise send the next required step and return None."""
    async with _db(context) as db:
        user = await _get_user(db, update)
    if not user.language:
        lang = normalize_language(update.effective_user.language_code)
        await update.effective_chat.send_message(t(lang, "choose_language"), reply_markup=language_keyboard())
        return None
    context.user_data["lang"] = user.language
    if not user.is_registered:
        await prompt_registration(update, context, user, intro=True)
        return None
    if not user.is_logged_in:
        markup = InlineKeyboardMarkup([[Btn(t(user.language, "btn_login"), callback_data="login")]])
        await update.effective_chat.send_message(t(user.language, "logged_out"), reply_markup=markup)
        return None
    return user


def gated(handler):
    """Run the handler only for registered, logged-in users."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if await gate(update, context) is None:
            return None
        return await handler(update, context, *args, **kwargs)
    wrapper.__name__ = handler.__name__
    return wrapper


# ---------------------------------------------------------------- views

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False) -> None:
    lang = await _lang(update, context)
    context.user_data.pop("awaiting_count", None)
    async with _db(context) as db:
        themes = await svc.list_themes(db)
        active = await svc.get_active_session(db, update.effective_user.id)
        user = await db.get(User, update.effective_user.id)

    rows = []
    if active:
        rows.append([Btn(t(lang, "continue", i=active.current_index + 1, n=active.total), callback_data="resume")])
    rows += [[Btn(f"📚 {th.name} ({th.question_count})", callback_data=f"theme:{th.id}")] for th in themes]
    rows.append([Btn(t(lang, "btn_top"), callback_data="top"), Btn(t(lang, "btn_results"), callback_data="results")])
    rows.append([Btn(t(lang, "btn_profile"), callback_data="profile"),
                 Btn(t(lang, "btn_language"), callback_data="language")])
    if url := _webapp_url(context):
        rows.append([Btn(t(lang, "btn_webapp"), web_app=WebAppInfo(url))])

    name = esc(user.display_name if user else update.effective_user.first_name or "")
    text = t(lang, "welcome", name=name, exam=_exam_count(context))
    text += "\n\n" + (t(lang, "choose_theme") if themes else t(lang, "no_themes"))
    await _show(update, text, InlineKeyboardMarkup(rows), edit)


def _question_header(item: SessionQuestion, session: QuizSession, lang: str) -> str:
    return t(
        lang, "question_header",
        mode=_mode_label(lang, session.mode), theme=esc(session.theme.name),
        i=item.position + 1, n=session.total,
    )


def render_question(item: SessionQuestion, session: QuizSession, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    options = svc.ordered_options(item)
    lines = [f"<i>{_question_header(item, session, lang)}</i>", "", f"<b>{esc(item.question.text)}</b>", ""]
    lines += [f"<b>{svc.letter(i)})</b> {esc(o.text)}" for i, o in enumerate(options)]
    buttons = [
        Btn(svc.letter(i), callback_data=f"ans:{session.id}:{item.position}:{i}") for i in range(len(options))
    ]
    markup = InlineKeyboardMarkup([buttons, [Btn(t(lang, "stop"), callback_data="stop")]])
    return "\n".join(lines), markup


def render_answered(result: svc.AnswerResult, lang: str) -> str:
    item, session = result.item, result.session
    options = svc.ordered_options(item)
    lines = [f"<i>{_question_header(item, session, lang)}</i>", "", f"<b>{esc(item.question.text)}</b>", ""]
    for i, o in enumerate(options):
        if session.mode == svc.PRACTICE:
            mark = "✅" if o.is_correct else ("❌" if o.id == result.chosen.id else "▫️")
        else:
            mark = "👉" if o.id == result.chosen.id else "▫️"
        lines.append(f"{mark} <b>{svc.letter(i)})</b> {esc(o.text)}")
    lines.append("")
    if session.mode == svc.PRACTICE:
        if result.is_correct:
            lines.append(t(lang, "correct"))
        else:
            lines.append(t(lang, "wrong", letter=svc.letter(options.index(result.correct))))
    else:
        lines.append(t(lang, "answer_saved", letter=svc.letter(options.index(result.chosen))))
    return "\n".join(lines)


async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, session_id: int, edit: bool) -> None:
    lang = await _lang(update, context)
    async with _db(context) as db:
        session = await db.get(QuizSession, session_id)
        item = await svc.get_item(db, session_id, session.current_index) if session else None
    if item is None:
        await _show(update, t(lang, "no_active"), None, edit)
        return
    text, markup = render_question(item, item.session, lang)
    await _show(update, text, markup, edit)


async def send_result(update: Update, context: ContextTypes.DEFAULT_TYPE, session_id: int) -> None:
    lang = await _lang(update, context)
    async with _db(context) as db:
        summary = await svc.session_summary(db, session_id)
    session = summary.session

    lines = [
        t(lang, "result_title", mode=_mode_label(lang, session.mode), theme=esc(session.theme.name)),
        "",
        t(lang, "result_score", c=session.correct_count, n=summary.base, p=summary.percent),
    ]
    if session.status != svc.FINISHED:
        lines.insert(0, t(lang, "stopped"))
        lines.append(t(lang, "result_answered", a=summary.answered, n=session.total))

    again_count = session.total if session.mode == svc.PRACTICE else 0
    markup = InlineKeyboardMarkup([[
        Btn(t(lang, "again"), callback_data=f"again:{session.theme_id}:{session.mode}:{again_count}"),
        Btn(t(lang, "menu"), callback_data="menu"),
    ]])

    if session.mode == svc.EXAM and summary.answered:
        blocks = [t(lang, "review_title")]
        if not summary.mistakes:
            blocks.append(t(lang, "review_perfect"))
        for m in summary.mistakes:
            blocks.append(
                f"<b>{m.position + 1}. {esc(m.question)}</b>\n"
                f"❌ {t(lang, 'review_yours')}: {m.chosen_letter}) {esc(m.chosen_text)}\n"
                f"✅ {t(lang, 'review_correct')}: {m.correct_letter}) {esc(m.correct_text)}"
            )
        await update.effective_chat.send_message("\n".join(lines), parse_mode="HTML")
        chunks = _chunks(blocks)
        for n, chunk in enumerate(chunks):
            last = n == len(chunks) - 1
            await update.effective_chat.send_message(chunk, parse_mode="HTML", reply_markup=markup if last else None)
        return

    await update.effective_chat.send_message("\n".join(lines), parse_mode="HTML", reply_markup=markup)


async def start_and_send(
    update: Update, context: ContextTypes.DEFAULT_TYPE, theme_id: int, mode: str, count: int, edit: bool
) -> None:
    context.user_data.pop("awaiting_count", None)
    async with _db(context) as db:
        session = await svc.start_quiz(db, update.effective_user.id, theme_id, mode, count)
    if session is None:
        await show_main_menu(update, context, edit=edit)
        return
    await send_question(update, context, session.id, edit=edit)


async def show_top_themes(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool) -> None:
    lang = await _lang(update, context)
    async with _db(context) as db:
        themes = await svc.list_themes(db)
    rows = [[Btn(f"🏆 {th.name}", callback_data=f"top:{th.id}")] for th in themes]
    rows.append([Btn(t(lang, "menu"), callback_data="menu")])
    await _show(update, t(lang, "top_choose_theme") if themes else t(lang, "no_themes"),
                InlineKeyboardMarkup(rows), edit)


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, theme_id: int) -> None:
    lang = await _lang(update, context)
    async with _db(context) as db:
        theme = await svc.get_theme(db, theme_id)
        if theme is None:
            await show_top_themes(update, context, edit=True)
            return
        top, mine = await svc.leaderboard(db, theme_id, update.effective_user.id)

    lines = [t(lang, "top_title", theme=esc(theme.name)), ""]
    if not top:
        lines.append(t(lang, "top_empty"))
    for e in top:
        place = MEDALS.get(e.rank, f"{e.rank}.")
        group = f" ({esc(e.group)})" if e.group else ""
        you = " 👈" if mine and e.user_id == mine.user_id else ""
        lines.append(
            f"{place} {esc(e.name)}{group} — <b>{e.correct}/{e.total}</b> ({e.percent}%) "
            f"· ⏱ {svc.format_duration(e.seconds)}{you}"
        )
    lines.append("")
    if mine:
        lines.append(t(lang, "top_you", rank=mine.rank, c=mine.correct, n=mine.total, p=mine.percent))
    else:
        lines.append(t(lang, "top_you_none"))
    markup = InlineKeyboardMarkup([
        [Btn(t(lang, "mode_exam", n=min(_exam_count(context), theme.question_count)),
             callback_data=f"mode:{theme_id}:{svc.EXAM}")],
        [Btn(t(lang, "back"), callback_data="top"), Btn(t(lang, "menu"), callback_data="menu")],
    ])
    await _show(update, "\n".join(lines), markup, edit=True)


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool) -> None:
    lang = await _lang(update, context)
    async with _db(context) as db:
        user = await db.get(User, update.effective_user.id)
    text = t(lang, "profile", name=esc(user.full_name or ""), phone=esc(user.phone or ""),
             group=esc(user.group_name or ""))
    markup = InlineKeyboardMarkup([
        [Btn(t(lang, "btn_edit_profile"), callback_data="edit_profile"),
         Btn(t(lang, "btn_logout"), callback_data="logout")],
        [Btn(t(lang, "menu"), callback_data="menu")],
    ])
    await _show(update, text, markup, edit)


# ---------------------------------------------------------------- commands

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    async with _db(context) as db:
        await svc.upsert_user(db, u.id, u.username, u.first_name)
    if context.args and context.args[0] == "battle":
        # Came from a group battle's Join/Register button (t.me/<bot>?start=battle).
        context.user_data["from_battle"] = True
    if await gate(update, context):
        if context.user_data.pop("from_battle", False):
            await update.effective_chat.send_message(t(context.user_data["lang"], "battle_dm_registered"))
        await show_main_menu(update, context)


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _lang(update, context)
    await _show(update, t(lang, "choose_language"), language_keyboard(), edit=update.callback_query is not None)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_message(t(await _lang(update, context), "help"))


@gated
async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_main_menu(update, context)


@gated
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _lang(update, context)
    async with _db(context) as db:
        session = await svc.stop_active(db, update.effective_user.id)
    query = update.callback_query
    if query and query.message:
        try:
            await query.edit_message_reply_markup(None)
        except BadRequest:
            pass
    if session is None:
        await update.effective_chat.send_message(t(lang, "no_active"))
        return
    await send_result(update, context, session.id)


@gated
async def cmd_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _lang(update, context)
    async with _db(context) as db:
        sessions = await svc.recent_results(db, update.effective_user.id)
    if not sessions:
        text = t(lang, "results_empty")
    else:
        lines = [t(lang, "results_title"), ""]
        for s in sessions:
            percent = round(s.correct_count * 100 / s.total) if s.total else 0
            when = (s.finished_at or s.started_at).strftime("%d.%m.%Y")
            lines.append(
                f"{when} · {_mode_label(lang, s.mode)} · {esc(s.theme.name)} — "
                f"<b>{s.correct_count}/{s.total}</b> ({percent}%)"
            )
        text = "\n".join(lines)
    markup = InlineKeyboardMarkup([[Btn(t(lang, "menu"), callback_data="menu")]])
    await _show(update, text, markup, edit=update.callback_query is not None)


@gated
async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_top_themes(update, context, edit=update.callback_query is not None)


@gated
async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_profile(update, context, edit=update.callback_query is not None)


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _lang(update, context)
    async with _db(context) as db:
        user = await _get_user(db, update)
        await svc.set_logged_in(db, user, False)
    context.user_data.pop("awaiting_count", None)
    await _show(update, t(lang, "logout_done"), None, edit=update.callback_query is not None)


# ---------------------------------------------------------------- callbacks

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if update.effective_chat is not None and update.effective_chat.type != "private":
        await query.answer()
        return
    parts = (query.data or "").split(":")
    action = parts[0]

    if action == "ans":
        await on_answer(update, context, *map(int, parts[1:4]))
        return

    await query.answer()

    # Actions available before registration / login
    if action == "lang":
        await on_language_chosen(update, context, parts[1])
        return
    if action == "login":
        async with _db(context) as db:
            user = await _get_user(db, update)
            if user.is_registered:
                await svc.set_logged_in(db, user, True)
        if await gate(update, context):
            await show_main_menu(update, context, edit=True)
        return
    if action == "language":
        await cmd_language(update, context)
        return

    if await gate(update, context) is None:
        return
    lang = context.user_data["lang"]

    if action == "menu":
        await show_main_menu(update, context, edit=True)
    elif action == "results":
        await cmd_results(update, context)
    elif action == "stop":
        await cmd_stop(update, context)
    elif action == "top":
        if len(parts) > 1:
            await show_leaderboard(update, context, int(parts[1]))
        else:
            await show_top_themes(update, context, edit=True)
    elif action == "profile":
        await show_profile(update, context, edit=True)
    elif action == "edit_profile":
        async with _db(context) as db:
            user = await _get_user(db, update)
            await svc.restart_registration(db, user)
        await prompt_registration(update, context, user)
    elif action == "logout":
        await cmd_logout(update, context)
    elif action == "resume":
        async with _db(context) as db:
            active = await svc.get_active_session(db, update.effective_user.id)
        if active:
            await send_question(update, context, active.id, edit=True)
        else:
            await show_main_menu(update, context, edit=True)
    elif action == "theme":
        await on_theme(update, context, int(parts[1]), lang)
    elif action == "mode":
        await on_mode(update, context, int(parts[1]), parts[2], lang)
    elif action == "count":
        await start_and_send(update, context, int(parts[1]), svc.PRACTICE, int(parts[2]), edit=True)
    elif action == "again":
        theme_id, mode, count = int(parts[1]), parts[2], int(parts[3])
        if mode == svc.EXAM:
            count = _exam_count(context)
        await start_and_send(update, context, theme_id, mode, count, edit=False)


async def on_language_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    code = normalize_language(code)
    async with _db(context) as db:
        user = await _get_user(db, update)
        await svc.set_language(db, user.id, code)
    context.user_data["lang"] = code
    query = update.callback_query
    try:
        await query.edit_message_text(LANGUAGES[code])
    except BadRequest:
        pass
    if await gate(update, context):
        await show_main_menu(update, context)


async def on_theme(update: Update, context: ContextTypes.DEFAULT_TYPE, theme_id: int, lang: str) -> None:
    async with _db(context) as db:
        theme = await svc.get_theme(db, theme_id)
    if theme is None:
        await show_main_menu(update, context, edit=True)
        return
    exam_n = min(_exam_count(context), theme.question_count)
    markup = InlineKeyboardMarkup([
        [Btn(t(lang, "mode_practice"), callback_data=f"mode:{theme.id}:{svc.PRACTICE}")],
        [Btn(t(lang, "mode_exam", n=exam_n), callback_data=f"mode:{theme.id}:{svc.EXAM}")],
        [Btn(t(lang, "back"), callback_data="menu")],
    ])
    text = t(lang, "choose_mode", theme=esc(theme.name), n=theme.question_count)
    await _show(update, text, markup, edit=True)


async def on_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, theme_id: int, mode: str, lang: str) -> None:
    async with _db(context) as db:
        theme = await svc.get_theme(db, theme_id)
    if theme is None:
        await show_main_menu(update, context, edit=True)
        return
    if mode == svc.EXAM:
        await start_and_send(update, context, theme_id, svc.EXAM, _exam_count(context), edit=True)
        return

    total = theme.question_count
    presets = [Btn(str(n), callback_data=f"count:{theme_id}:{n}") for n in PRACTICE_PRESETS if n < total]
    rows = [presets] if presets else []
    rows.append([Btn(t(lang, "all_questions", n=total), callback_data=f"count:{theme_id}:{total}")])
    rows.append([Btn(t(lang, "back"), callback_data=f"theme:{theme_id}")])
    context.user_data["awaiting_count"] = theme_id
    await _show(update, t(lang, "choose_count", max=total), InlineKeyboardMarkup(rows), edit=True)


async def on_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE, session_id: int, position: int, option_index: int
) -> None:
    # No gate here: logging out stops active sessions, so svc.answer rejects presses from logged-out users.
    query = update.callback_query
    lang = await _lang(update, context)
    async with _db(context) as db:
        result = await svc.answer(db, update.effective_user.id, session_id, position, option_index)
    if result is None:
        await query.answer(t(lang, "stale_button"))
        return
    await query.answer()
    await _show(update, render_answered(result, lang), None, edit=True)
    if result.finished:
        await send_result(update, context, session_id)
    else:
        await send_question(update, context, session_id, edit=False)


# ---------------------------------------------------------------- messages

async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Phone number shared via the bot's button or the Mini App's requestContact()."""
    contact = update.message.contact
    lang = await _lang(update, context)
    if contact.user_id != update.effective_user.id:
        await update.message.reply_text(t(lang, "reg_phone_not_own"))
        return
    async with _db(context) as db:
        user = await _get_user(db, update)
        was_registered = user.is_registered
        await svc.update_registration(db, user, phone=svc.normalize_phone(contact.phone_number))
    if not user.language:
        await gate(update, context)
    elif user.is_registered and not was_registered:
        await _registration_finished(update, context, lang)
    elif not user.is_registered:
        await prompt_registration(update, context, user)
    else:
        await update.message.reply_text("✅", reply_markup=ReplyKeyboardRemove())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _db(context) as db:
        user = await _get_user(db, update)
    if not user.language:
        await gate(update, context)
        return
    lang = user.language
    raw = (update.message.text or "").strip()

    if not user.is_registered:
        step = svc.registration_step(user)
        if step == svc.STEP_NAME:
            value = svc.clean_full_name(raw)
            if value is None:
                await update.message.reply_text(t(lang, "reg_invalid_name"))
                return
            async with _db(context) as db:
                user = await _get_user(db, update)
                await svc.update_registration(db, user, full_name=value)
        elif step == svc.STEP_GROUP:
            value = svc.clean_group(raw)
            if value is None:
                await update.message.reply_text(t(lang, "reg_invalid_group"))
                return
            async with _db(context) as db:
                user = await _get_user(db, update)
                await svc.update_registration(db, user, group_name=value)
        # STEP_PHONE: typed text isn't accepted, the prompt below re-sends the share button
        if user.is_registered:
            await _registration_finished(update, context, lang)
        else:
            await prompt_registration(update, context, user)
        return

    if await gate(update, context) is None:
        return
    theme_id = context.user_data.get("awaiting_count")
    if theme_id is None:
        await cmd_help(update, context)
        return
    async with _db(context) as db:
        theme = await svc.get_theme(db, theme_id)
    if theme is None:
        context.user_data.pop("awaiting_count", None)
        await show_main_menu(update, context)
        return
    if not raw.isdigit() or not 1 <= int(raw) <= theme.question_count:
        await update.message.reply_text(t(lang, "invalid_count", max=theme.question_count))
        return
    await start_and_send(update, context, theme_id, svc.PRACTICE, int(raw), edit=False)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    job = getattr(context, "job", None)
    network = isinstance(err, NetworkError) and not isinstance(err, BadRequest)  # BadRequest is a real bug
    if job is not None:
        # Timer jobs (battles) are not retried by the library; the battle watchdog redoes the step.
        if network:
            log.warning("Telegram network error in job %s: %s (the battle watchdog will retry)", job.name, err)
        else:
            log.error("Error in job %s", job.name, exc_info=err)
        return
    if network and update is None:
        # Dropped connection while polling for updates; python-telegram-bot retries polling itself.
        log.warning("Telegram network error while polling (retrying automatically): %s", err)
        return
    log.error("Unhandled error while processing update %s", update, exc_info=err)


def register(app: Application) -> None:
    """Private-chat handlers. Register bot.group_handlers first so group buttons are routed there."""
    private = filters.ChatType.PRIVATE
    for name, callback in (
        ("start", cmd_start), ("menu", cmd_menu), ("language", cmd_language), ("stop", cmd_stop),
        ("results", cmd_results), ("top", cmd_top), ("profile", cmd_profile), ("logout", cmd_logout),
        ("help", cmd_help),
    ):
        app.add_handler(CommandHandler(name, callback, filters=private))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(private & filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
