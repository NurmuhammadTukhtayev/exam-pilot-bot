import os
from pathlib import Path

import pytest
from sqlalchemy import text

from bot.db import create_engine, create_sessionmaker, init_db
from bot.models import Base
from import_docs import import_parsed, parse_docx

DOCS = sorted((Path(__file__).parent.parent / "docs").glob("*.docx"))


@pytest.fixture
async def sessionmaker(tmp_path):
    # Set TEST_DATABASE_URL (e.g. a throwaway PostgreSQL) to run the suite against another DB.
    url = os.getenv("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await init_db(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
async def seeded(sessionmaker):
    for path in DOCS:
        async with sessionmaker() as db:
            await import_parsed(db, parse_docx(path))
    return sessionmaker
