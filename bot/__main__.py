"""Run the bot:  python -m bot"""

import logging
import sys
from dataclasses import replace

from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)
from telegram.error import BadRequest
from telegram.ext import AIORateLimiter, Application

from bot import group_handlers, handlers
from bot.config import get_settings
from bot.db import create_engine, create_sessionmaker, init_db
from bot.i18n import COMMAND_DESCRIPTIONS, DEFAULT_LANGUAGE, GROUP_COMMAND_DESCRIPTIONS, LANGUAGES


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # The battle watchdog runs every few seconds; don't log each run (warnings/errors still show).
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    settings = get_settings()
    if not settings.bot_token:
        sys.exit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    engine = create_engine(settings.database_url)

    async def post_init(app: Application) -> None:
        await init_db(engine)
        app.bot_data["settings"] = settings
        app.bot_data["sessionmaker"] = create_sessionmaker(engine)
        for lang in LANGUAGES:
            code = None if lang == DEFAULT_LANGUAGE else lang
            private = [BotCommand(cmd, desc[lang]) for cmd, desc in COMMAND_DESCRIPTIONS.items()]
            group = [BotCommand(cmd, desc[lang]) for cmd, desc in GROUP_COMMAND_DESCRIPTIONS.items()]
            await app.bot.set_my_commands(private, language_code=code)
            await app.bot.set_my_commands(private, scope=BotCommandScopeAllPrivateChats(), language_code=code)
            await app.bot.set_my_commands(group, scope=BotCommandScopeAllGroupChats(), language_code=code)
        url = settings.webapp_url
        if url and not url.startswith("https://"):
            logging.error("WEBAPP_URL must start with https:// (got %r) — Mini App disabled", url)
            url = ""
        if url:
            try:
                # The "menu" button next to the message box opens the Mini App.
                await app.bot.set_chat_menu_button(menu_button=MenuButtonWebApp("Mini App", WebAppInfo(url)))
                logging.info("Mini App enabled at %s", url)
            except BadRequest as e:
                logging.error("Telegram rejected WEBAPP_URL %r (%s) — Mini App disabled. "
                              "Put the exact https address printed by your tunnel/server in .env.", url, e)
                url = ""
        if not url:
            # Hide Mini App buttons and don't leave the menu button pointing at an old (e.g. expired tunnel) URL.
            app.bot_data["settings"] = replace(settings, webapp_url="")
            await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        await group_handlers.recover_battles(app)

    async def post_shutdown(_: Application) -> None:
        await engine.dispose()

    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .rate_limiter(AIORateLimiter(max_retries=3))  # stay within Telegram's flood limits (battles!)
        # Generous timeouts: on a slow link a short timeout can report failure for a message Telegram
        # actually delivered, which makes battles post a question twice.
        .connect_timeout(10).read_timeout(20).write_timeout(20).pool_timeout(10)
        .build()
    )
    group_handlers.register(app)  # first: group buttons must not reach the private-chat router
    handlers.register(app)
    app.run_polling(allowed_updates=["message", "callback_query", "my_chat_member"])


if __name__ == "__main__":
    main()
