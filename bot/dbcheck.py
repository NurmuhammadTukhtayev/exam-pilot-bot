"""Check the database connection in DATABASE_URL and explain common mistakes.

    python -m bot.dbcheck

Prints where it connects (never the password) and, on failure, what is wrong: unparseable URL,
special characters in the password, unknown host, nothing listening, wrong password, missing
database or user. Exit code 0 = connection works.
"""

import asyncio
import socket
import sys

from sqlalchemy.engine import make_url

from bot.config import get_settings

URL_SPECIAL = "@:/?#%[] "
ENCODE_HINT = (
    "If the password contains special characters ({chars}), URL-encode them in DATABASE_URL "
    "(@ -> %40, : -> %3A, / -> %2F, # -> %23, ? -> %3F, % -> %25), or use a password made of "
    "letters and digits only."
).format(chars=" ".join(URL_SPECIAL.strip()))


def _safe(url) -> str:
    return url.render_as_string(hide_password=True)


async def check(raw: str) -> tuple[bool, str]:
    """Return (ok, message)."""
    try:
        url = make_url(raw)
    except Exception as e:  # noqa: BLE001 - any parse error is reported to the user
        return False, f"DATABASE_URL can't be parsed ({e}). {ENCODE_HINT}"

    if url.get_backend_name() == "sqlite":
        return True, f"SQLite database file: {url.database}"
    if url.get_backend_name() != "postgresql":
        return False, f"Unsupported database type '{url.get_backend_name()}' (use postgresql+asyncpg://)."

    where = _safe(url)
    host, port = url.host, url.port or 5432
    if not host or not url.database or not url.username:
        return False, f"DATABASE_URL is incomplete: {where}. Expected postgresql+asyncpg://user:password@host:5432/dbname"
    if host.lower() in {"host", "hostname", "your-host"} or url.database in {"dbname", "database"}:
        return False, f"DATABASE_URL still contains template placeholders: {where}"
    if "@" in host:
        # The password contains '@', so part of it was read as the host: don't print the URL at all.
        return False, (
            f"DATABASE_URL for user '{url.username}' has an '@' inside the password, so the host name "
            f"can't be read correctly. {ENCODE_HINT}"
        )

    try:
        socket.getaddrinfo(host, port)
    except socket.gaierror:
        return False, (
            f"Host '{host}' can't be resolved (from DATABASE_URL: {where}). Is it the database server's name? "
            f"For PostgreSQL on this server use 'localhost'. {ENCODE_HINT}"
        )

    import asyncpg  # PostgreSQL driver

    try:
        conn = await asyncpg.connect(
            user=url.username, password=url.password, host=host, port=port, database=url.database, timeout=10
        )
    except asyncpg.InvalidPasswordError:
        return False, f"Wrong password for user '{url.username}' ({where}). {ENCODE_HINT}"
    except asyncpg.InvalidAuthorizationSpecificationError as e:
        return False, f"User '{url.username}' can't log in ({e}). Create it: CREATE ROLE ... LOGIN PASSWORD '...';"
    except asyncpg.InvalidCatalogNameError:
        return False, (
            f"Database '{url.database}' doesn't exist on {host}:{port}. "
            f"Create it: CREATE DATABASE {url.database} OWNER {url.username} ENCODING 'UTF8';"
        )
    except (ConnectionRefusedError, OSError, TimeoutError) as e:
        return False, (
            f"Nothing answers on {host}:{port} ({e.__class__.__name__}). Is the PostgreSQL service running, "
            f"and is it listening on port {port}?"
        )
    except asyncpg.PostgresError as e:
        return False, f"PostgreSQL refused the connection: {e}"
    try:
        version = await conn.fetchval("SHOW server_version")
    finally:
        await conn.close()
    return True, f"Connected to PostgreSQL {version}: {where}"


def main() -> int:
    ok, message = asyncio.run(check(get_settings().database_url))
    print(("OK: " if ok else "DATABASE PROBLEM: ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
