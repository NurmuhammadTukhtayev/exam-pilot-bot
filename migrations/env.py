import asyncio
from logging.config import fileConfig

from alembic import context

from bot.config import get_settings
from bot.db import create_engine
from bot.models import Base

config = context.config
target_metadata = Base.metadata


def _configure_and_run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # lets ALTER-style migrations work on SQLite too
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_cli_command(connection) -> None:
    sqlite = connection.dialect.name == "sqlite"
    if sqlite:
        # Table rebuilds would otherwise cascade-delete child rows (see bot.db.run_migrations).
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        _configure_and_run(connection)
        connection.commit()
    finally:
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


async def _run_from_cli() -> None:
    engine = create_engine(get_settings().database_url)
    async with engine.connect() as conn:
        await conn.run_sync(_run_cli_command)
    await engine.dispose()


connection = config.attributes.get("connection")
if connection is not None:
    # Called from bot.db.run_migrations() with an open connection.
    _configure_and_run(connection)
else:
    if config.config_file_name:
        fileConfig(config.config_file_name)
    if context.is_offline_mode():
        context.configure(url=get_settings().database_url, target_metadata=target_metadata,
                          literal_binds=True, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        asyncio.run(_run_from_cli())
