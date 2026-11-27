import atexit
import os
import shutil
import tempfile
from pathlib import Path

import docx
import pytest
from sqlalchemy import text

from bot.db import create_engine, create_sessionmaker, init_db
from bot.models import Base
from import_docs import import_parsed, parse_docx

# The real question banks (docs/*.docx) are not in git. Tests use generated banks with the same
# layout, theme names and sizes; the real files, when present locally, are checked separately.
REAL_DOCS = sorted((Path(__file__).parent.parent / "docs").glob("*.docx"))

FIXTURE_THEMES = {  # file name -> number of questions
    "5-Kurs Dasturiy tizimlarni loyihalash KT uz IX.docx": 194,
    "5-Kurs Ma`naviyatshunoslik KT uz IX.docx": 159,
    "5_Kurs_Bulutli_texnologiyalar_va_taqsimlangan_tizimlar_KT_uz_IX.docx": 194,
}


def _build_fixture_docs() -> list[Path]:
    """One table per file: question | correct answer | 3 wrong answers (like the real docs)."""
    folder = Path(tempfile.mkdtemp(prefix="exam-docs-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    paths = []
    for name, count in FIXTURE_THEMES.items():
        tag = name.replace("5-Kurs ", "").replace("5_Kurs_", "")[0]  # D / M / B
        document = docx.Document()
        table = document.add_table(rows=0, cols=5)
        for n in range(1, count + 1):
            cells = table.add_row().cells
            cells[0].text = f"Q{n:03d}-{tag} savol matni {n}?"  # unique first word = document position
            cells[1].text = f"To'g'ri javob {tag}{n}"
            for k in range(3):
                cells[2 + k].text = f"Noto'g'ri javob {tag}{n}.{k + 1}"
        path = folder / name
        document.save(str(path))
        paths.append(path)
    return sorted(paths)


DOCS = _build_fixture_docs()


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
