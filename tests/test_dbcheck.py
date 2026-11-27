import pytest

from bot.dbcheck import check


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("not a url", "can't be parsed"),
        ("postgresql+asyncpg://user:password@host:5432/dbname", "template placeholders"),
        # '@' in the password: everything after the first '@' would be read as the host
        ("postgresql+asyncpg://exampilot:pa@secret@localhost:5432/exampilot", "URL-encode"),
        ("postgresql+asyncpg://exampilot:secret@no-such-host.invalid:5432/exampilot", "can't be resolved"),
        ("postgresql+asyncpg://exampilot:secret@127.0.0.1:1/exampilot", "Nothing answers on 127.0.0.1:1"),
        ("postgresql+asyncpg://exampilot@localhost:5432", "incomplete"),
        ("mysql://u:p@localhost/db", "Unsupported database type"),
    ],
)
async def test_dbcheck_explains_bad_urls(url, expected):
    ok, message = await check(url)
    assert not ok
    assert expected in message
    assert "secret" not in message  # never print the password


async def test_dbcheck_sqlite_and_encoded_password():
    ok, message = await check("sqlite+aiosqlite:///./data/bot.db")
    assert ok and "SQLite" in message
    # correctly URL-encoded '@' (%40) parses fine and gets as far as the network
    ok, message = await check("postgresql+asyncpg://exampilot:p%40ss@127.0.0.1:1/exampilot")
    assert not ok and "Nothing answers" in message
