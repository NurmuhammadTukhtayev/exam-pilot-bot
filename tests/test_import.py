from pathlib import Path

import docx
import pytest
from sqlalchemy import func, select

from bot.models import Option, Question, Theme
from import_docs import import_parsed, parse_docx, theme_name_from_path
from tests.conftest import DOCS, REAL_DOCS


def test_theme_names():
    assert (
        theme_name_from_path(Path("5-Kurs Dasturiy tizimlarni loyihalash KT uz IX.docx"))
        == "Dasturiy tizimlarni loyihalash"
    )
    assert theme_name_from_path(Path("5-Kurs Ma`naviyatshunoslik KT uz IX.docx")) == "Ma'naviyatshunoslik"
    assert (
        theme_name_from_path(Path("5_Kurs_Bulutli_texnologiyalar_va_taqsimlangan_tizimlar_KT_uz_IX.docx"))
        == "Bulutli texnologiyalar va taqsimlangan tizimlar"
    )
    assert theme_name_from_path(Path("Something else.docx")) == "Something else"


def test_parse_fixture_docs():
    counts = {p.name: len(parse_docx(p).questions) for p in DOCS}
    assert sum(counts.values()) == 547
    for path in DOCS:
        parsed = parse_docx(path)
        assert not parsed.warnings
        assert all(len(q.options) == 4 for q in parsed.questions)


@pytest.mark.skipif(not REAL_DOCS, reason="real question banks (docs/*.docx) are not in git")
@pytest.mark.parametrize("path", REAL_DOCS, ids=lambda p: p.name)
def test_real_docs_parse_cleanly(path):
    """When the real docs are present locally: every row is a valid question, nothing skipped."""
    parsed = parse_docx(path)
    assert parsed.questions, "no questions found"
    assert not parsed.warnings, parsed.warnings
    assert all(len(q.options) >= 2 for q in parsed.questions)


def _make_doc(path: Path, rows: list[list[str]]) -> Path:
    d = docx.Document()
    table = d.add_table(rows=len(rows), cols=max(len(r) for r in rows))
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            table.cell(r, c).text = text
    d.save(str(path))
    return path


def test_parse_skips_bad_rows(tmp_path):
    path = _make_doc(tmp_path / "t.docx", [
        ["Q1", "right", "w1", "w2"],
        ["", "x", "y", "z"],          # no question -> ignored
        ["Q2", "", "w1", "w2"],        # no correct answer -> skipped
        ["Q3", "only", "", ""],        # one option -> skipped
        ["Q1", "right", "w1", "w2"],   # duplicate -> skipped
        ["Q4", "right", "w1", ""],     # 2 options -> kept
    ])
    parsed = parse_docx(path, "T")
    assert [q.text for q in parsed.questions] == ["Q1", "Q4"]
    assert parsed.questions[1].options == ["right", "w1"]
    assert len(parsed.warnings) == 4


async def test_import_is_idempotent_and_syncs(sessionmaker, tmp_path):
    path = _make_doc(tmp_path / "t.docx", [["Q1", "a", "b", "c"], ["Q2", "a", "b", "c"]])
    async with sessionmaker() as db:
        s = await import_parsed(db, parse_docx(path, "T"))
    assert (s.added, s.updated, s.unchanged) == (2, 0, 0)

    async with sessionmaker() as db:
        s = await import_parsed(db, parse_docx(path, "T"))
    assert (s.added, s.updated, s.unchanged, s.deactivated) == (0, 0, 2, 0)

    async with sessionmaker() as db:
        q1_option_ids = list(await db.scalars(
            select(Option.id).join(Question).where(Question.text == "Q1").order_by(Option.position)
        ))

    # Q1 answer text changed, Q2 removed, Q3 added
    path = _make_doc(tmp_path / "t.docx", [["Q1", "a2", "b", "c"], ["Q3", "x", "y", "z"]])
    async with sessionmaker() as db:
        s = await import_parsed(db, parse_docx(path, "T"))
    assert (s.added, s.updated, s.unchanged, s.deactivated) == (1, 1, 0, 1)

    async with sessionmaker() as db:
        assert await db.scalar(select(func.count(Theme.id))) == 1
        active = set(await db.scalars(select(Question.text).where(Question.is_active)))
        assert active == {"Q1", "Q3"}
        opts = list(await db.scalars(
            select(Option).join(Question).where(Question.text == "Q1").order_by(Option.position)
        ))
        assert [o.id for o in opts] == q1_option_ids  # ids kept stable
        assert [(o.text, o.is_correct) for o in opts] == [("a2", True), ("b", False), ("c", False)]
