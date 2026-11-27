import sqlite3

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from bot.db import ALEMBIC_INI, create_engine, init_db


def _upgrade_to(connection, revision):
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, revision)
    connection.commit()


async def test_legacy_database_is_upgraded_without_data_loss(tmp_path):
    """A DB created before migrations existed (0001 schema, no alembic_version) keeps all its rows."""
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.connect() as conn:
        await conn.run_sync(_upgrade_to, "0001")
    await engine.dispose()

    db = sqlite3.connect(path)
    db.executescript("""
        DROP TABLE alembic_version;
        INSERT INTO themes (id, name, is_active, created_at) VALUES (1, 'T', 1, '2026-01-01');
        INSERT INTO users (id, first_name, language, created_at) VALUES (111111111, 'Ali', 'en', '2026-01-01');
        INSERT INTO questions (id, theme_id, text, is_active) VALUES (1, 1, 'Q', 1);
        INSERT INTO options (id, question_id, text, position, is_correct) VALUES (1, 1, 'A', 0, 1);
        INSERT INTO quiz_sessions (id, user_id, theme_id, mode, status, total, current_index, correct_count, started_at)
            VALUES (1, 111111111, 1, 'exam', 'finished', 1, 1, 1, '2026-01-01');
        INSERT INTO session_questions (id, session_id, question_id, position, option_order, selected_option_id)
            VALUES (1, 1, 1, 0, '[1]', 1);
    """)
    db.commit()
    db.close()

    engine = create_engine(f"sqlite+aiosqlite:///{path}")
    await init_db(engine)
    await init_db(engine)  # second run is a no-op
    await engine.dispose()

    db = sqlite3.connect(path)
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    assert db.execute("SELECT version_num FROM alembic_version").fetchall() == [(head,)]
    assert db.execute("SELECT COUNT(*) FROM quiz_sessions").fetchone() == (1,)
    assert db.execute("SELECT COUNT(*) FROM session_questions").fetchone() == (1,)
    assert db.execute("SELECT is_logged_in, registered_at FROM users").fetchall() == [(1, None)]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
