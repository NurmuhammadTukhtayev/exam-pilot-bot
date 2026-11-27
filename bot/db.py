from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
BASELINE_REVISION = "0001"
MIGRATION_LOCK_ID = 7_331_001  # arbitrary constant for pg_advisory_lock


def create_engine(database_url: str) -> AsyncEngine:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(database_url)

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # enforce FKs like PostgreSQL does
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_async_engine(database_url, pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


def run_migrations(connection: Connection, cfg: Config | None = None) -> None:
    """Upgrade to the latest revision on an open (sync) connection that has no transaction yet."""
    sqlite = connection.dialect.name == "sqlite"
    postgres = connection.dialect.name == "postgresql"
    if sqlite:
        # SQLite migrations rebuild tables (copy, drop, rename). With foreign keys on, dropping the old
        # table would cascade-delete child rows (e.g. users -> quiz_sessions). Must run outside a transaction.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("could not disable SQLite foreign keys for migration")
    if postgres:
        # The bot and every Mini App worker migrate on startup; make them take turns.
        connection.exec_driver_sql(f"SELECT pg_advisory_lock({MIGRATION_LOCK_ID})")
    try:
        cfg = cfg or Config(str(ALEMBIC_INI))
        cfg.attributes["connection"] = connection
        tables = set(inspect(connection).get_table_names())
        if "themes" in tables and "alembic_version" not in tables:
            # Database created before migrations were introduced (it has the 0001 schema).
            command.stamp(cfg, BASELINE_REVISION)
        command.upgrade(cfg, "head")
        connection.commit()
        if sqlite:
            problems = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if problems:
                raise RuntimeError(f"foreign key violations after migration: {problems[:5]}")
    finally:
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        if postgres:
            connection.rollback()  # leave any failed transaction before unlocking
            connection.exec_driver_sql(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_ID})")
            connection.commit()


async def init_db(engine: AsyncEngine) -> None:
    """Bring the database schema up to date (runs pending Alembic migrations)."""
    async with engine.connect() as conn:
        await conn.run_sync(run_migrations)
