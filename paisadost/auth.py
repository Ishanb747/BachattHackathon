"""Basic auth: the dataset's users sign in with their email and one shared
demo password; a signed cookie carries the session. Nothing more.

``.env``: DEMO_PASSWORD, SESSION_SECRET.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Dict, Optional

from paisadost.config import _get
from paisadost.sources import read_rows

COOKIE = "pd_session"
MAX_AGE = 12 * 3600
DEMO_PASSWORD = _get("DEMO_PASSWORD", "paisadost")
_SECRET = (_get("SESSION_SECRET", "") or secrets.token_hex(32)).encode()


def users() -> Dict[str, Dict]:
    return {r["email"].lower(): {"id": r["user_id"], "email": r["email"],
                                 "name": f"{r['first_name'].title()} {r['last_name'].title()}".strip()}
            for r in read_rows("emails/users_data.csv")}


def check(email: str, password: str) -> Optional[Dict]:
    user = users().get((email or "").strip().lower())
    if user and hmac.compare_digest(password or "", DEMO_PASSWORD):
        return user
    return None


def sign(user_id: str) -> str:
    payload = f"{user_id}|{int(time.time()) + MAX_AGE}"
    mac = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{mac}".encode()).decode()


def verify(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        user_id, exp, mac = base64.urlsafe_b64decode(token.encode()).decode().split("|")
    except Exception:   # noqa: BLE001
        return None
    good = hmac.new(_SECRET, f"{user_id}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, good) or int(exp) < time.time():
        return None
    return user_id


def user_by_id(user_id: str) -> Optional[Dict]:
    return next((u for u in users().values() if u["id"] == user_id), None)
