import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    exam_question_count: int
    # Public HTTPS URL where the Mini App is served (empty = Mini App buttons hidden in the bot).
    webapp_url: str = ""
    # How long a Mini App initData signature stays valid.
    init_data_max_age: int = 24 * 3600
    # DEVELOPMENT ONLY: treat requests without Telegram initData as this user id (browser testing).
    webapp_dev_user_id: int | None = None


def get_settings() -> Settings:
    dev_user = os.getenv("WEBAPP_DEV_USER_ID", "").strip()
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/bot.db"),
        exam_question_count=int(os.getenv("EXAM_QUESTION_COUNT", "25")),
        webapp_url=os.getenv("WEBAPP_URL", "").strip(),
        init_data_max_age=int(os.getenv("INIT_DATA_MAX_AGE", str(24 * 3600))),
        webapp_dev_user_id=int(dev_user) if dev_user else None,
    )
