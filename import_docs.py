"""Import test questions from .docx files into the database.

Expected document layout: a table where every row is one question.
    column 1      -> question text
    column 2      -> correct answer
    columns 3..N  -> wrong answers

Each file becomes one theme. The theme name is taken from the file name
("5-Kurs Dasturiy tizimlarni loyihalash KT uz IX.docx" -> "Dasturiy tizimlarni loyihalash")
unless --theme is given.

Re-running is safe: questions are matched by (theme, text). New ones are added, changed
options are updated, and questions that disappeared from the doc are deactivated (not
deleted, so users' past results stay intact).

Usage:
    python import_docs.py                       # import every .docx in ./docs
    python import_docs.py docs/file.docx --theme "My theme"
    python import_docs.py --dry-run             # parse and report only, no DB writes
"""

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import docx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.config import get_settings
from bot.db import create_engine, create_sessionmaker, init_db
from bot.models import Option, Question, Theme

MIN_OPTIONS = 2


@dataclass
class ParsedQuestion:
    text: str
    options: list[str]  # options[0] is the correct answer
    source_row: int


@dataclass
class ParsedDoc:
    path: Path
    theme_name: str
    questions: list[ParsedQuestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0


def clean_text(value: str) -> str:
    lines = (re.sub(r"[ \t ]+", " ", line).strip() for line in value.splitlines())
    return "\n".join(line for line in lines if line)


def theme_name_from_path(path: Path) -> str:
    name = path.stem.replace("_", " ").replace("`", "'")
    name = re.sub(r"^\s*\d+\s*-?\s*kurs\s+", "", name, flags=re.IGNORECASE)
    # "... KT uz IX" (course docs) or just "... KT uz" (non-course docs, e.g. "SQL KT uz.docx")
    name = re.sub(r"\s+KT\s+uz(\s+[IVXLC]+)?\s*$", "", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", name).strip() or path.stem


def _row_cells(row) -> list[str]:
    """Cell texts of a row, skipping repeats that python-docx yields for merged cells."""
    texts, seen = [], set()
    for cell in row.cells:
        if id(cell._tc) in seen:
            continue
        seen.add(id(cell._tc))
        texts.append(clean_text(cell.text))
    return texts


def parse_docx(path: Path, theme_name: str | None = None) -> ParsedDoc:
    result = ParsedDoc(path=path, theme_name=theme_name or theme_name_from_path(path))
    document = docx.Document(str(path))
    if not document.tables:
        result.warnings.append("no tables found")
        return result

    seen_texts: set[str] = set()
    row_no = 0
    for table in document.tables:
        for row in table.rows:
            row_no += 1
            cells = _row_cells(row)
            if not cells or not cells[0]:
                continue
            question, raw_options = cells[0], cells[1:]
            options = [o for o in raw_options if o]
            if not raw_options or not raw_options[0]:
                result.warnings.append(f"row {row_no}: no correct answer in column 2, skipped")
                continue
            if len(options) < MIN_OPTIONS:
                result.warnings.append(f"row {row_no}: fewer than {MIN_OPTIONS} options, skipped")
                continue
            if question in seen_texts:
                result.warnings.append(f"row {row_no}: duplicate question, skipped")
                continue
            if len(options) != len(raw_options):
                result.warnings.append(f"row {row_no}: empty option cell(s) ignored")
            if len(set(options)) != len(options):
                result.warnings.append(f"row {row_no}: duplicate options")
            seen_texts.add(question)
            result.questions.append(ParsedQuestion(text=question, options=options, source_row=row_no))
    return result


def _sync_options(question: Question, option_texts: list[str]) -> bool:
    """Update options in place by position so option ids (referenced by history) stay stable."""
    changed = False
    by_position = {o.position: o for o in question.options}
    for position, text in enumerate(option_texts):
        is_correct = position == 0
        option = by_position.get(position)
        if option is None:
            question.options.append(Option(text=text, position=position, is_correct=is_correct))
            changed = True
        elif option.text != text or option.is_correct != is_correct:
            option.text, option.is_correct = text, is_correct
            changed = True
    for option in list(question.options):
        if option.position >= len(option_texts):
            question.options.remove(option)
            changed = True
    return changed


async def import_parsed(db: AsyncSession, parsed: ParsedDoc) -> ImportStats:
    stats = ImportStats()
    theme = await db.scalar(select(Theme).where(Theme.name == parsed.theme_name))
    if theme is None:
        theme = Theme(name=parsed.theme_name, source_file=parsed.path.name)
        db.add(theme)
        await db.flush()
    theme.source_file = parsed.path.name
    theme.is_active = True

    existing = {
        q.text: q
        for q in await db.scalars(
            select(Question).where(Question.theme_id == theme.id).options(selectinload(Question.options))
        )
    }

    for pq in parsed.questions:
        question = existing.pop(pq.text, None)
        if question is None:
            question = Question(theme_id=theme.id, text=pq.text, source_row=pq.source_row, options=[])
            _sync_options(question, pq.options)
            db.add(question)
            stats.added += 1
            continue
        changed = _sync_options(question, pq.options)
        if not question.is_active or question.source_row != pq.source_row:
            changed = True
        question.is_active, question.source_row = True, pq.source_row
        if changed:
            stats.updated += 1
        else:
            stats.unchanged += 1

    for question in existing.values():
        if question.is_active:
            question.is_active = False
            stats.deactivated += 1

    await db.commit()
    return stats


def collect_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(f for f in p.glob("*.docx") if not f.name.startswith("~$")))
        elif p.suffix.lower() == ".docx" and p.exists():
            files.append(p)
        else:
            print(f"skip: {p} (not a .docx file or folder)", file=sys.stderr)
    return files


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import test questions from .docx files")
    parser.add_argument("paths", nargs="*", default=["docs"], help=".docx files or folders (default: docs)")
    parser.add_argument("--theme", help="theme name override (only with a single file)")
    parser.add_argument("--database-url", help="override DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="parse only, don't write to the DB")
    args = parser.parse_args(argv)

    files = collect_files(args.paths)
    if not files:
        print("No .docx files found.", file=sys.stderr)
        return 1
    if args.theme and len(files) > 1:
        print("--theme can only be used with a single file.", file=sys.stderr)
        return 1

    parsed_docs = [parse_docx(f, args.theme) for f in files]
    for doc in parsed_docs:
        print(f"[{doc.theme_name}] {doc.path.name}: {len(doc.questions)} questions parsed")
        for w in doc.warnings:
            print(f"    warning: {w}")
    if args.dry_run:
        return 0

    engine = create_engine(args.database_url or get_settings().database_url)
    try:
        await init_db(engine)
        sessionmaker = create_sessionmaker(engine)
        for doc in parsed_docs:
            async with sessionmaker() as db:
                s = await import_parsed(db, doc)
            print(
                f"[{doc.theme_name}] added={s.added} updated={s.updated} "
                f"unchanged={s.unchanged} deactivated={s.deactivated}"
            )
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
