"""Validation of Telegram Mini App initData.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class InitDataError(Exception):
    pass


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Build a signed initData string (used by tests and local tooling)."""
    from urllib.parse import urlencode

    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    digest = hmac.new(_secret_key(bot_token), data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


def validate_init_data(init_data: str, bot_token: str, max_age: int, now: float | None = None) -> dict:
    """Return the Telegram user dict if `init_data` is authentic and fresh, else raise InitDataError."""
    if not init_data or not bot_token:
        raise InitDataError("missing")
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as e:
        raise InitDataError("malformed") from e

    received_hash = fields.pop("hash", "")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    expected = hmac.new(_secret_key(bot_token), data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("bad signature")

    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError as e:
        raise InitDataError("bad auth_date") from e
    now = time.time() if now is None else now
    if max_age and now - auth_date > max_age:
        raise InitDataError("expired")

    try:
        user = json.loads(fields["user"])
        int(user["id"])
    except (KeyError, ValueError, TypeError) as e:
        raise InitDataError("no user") from e
    return user
