"""Where the data lives and what "today" is.

The dataset is a snapshot that ends on 16 Oct 2026, so "due within 2 days"
is measured from a fixed as-of date, not the wall clock. Both can be
overridden from ``.env`` / the environment.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from cascadevoice.defaults import PROJECT_ROOT, _read_env_file

_env = _read_env_file(PROJECT_ROOT / ".env")


def _get(name: str, default: str) -> str:
    return os.environ.get(name) or _env.get(name) or default


DATA_DIR = Path(_get("PAISA_DATA_DIR", str(PROJECT_ROOT / "buildathon")))
STORE_DIR = Path(_get("PAISA_STORE_DIR", str(PROJECT_ROOT / "data")))
AS_OF = date.fromisoformat(_get("AS_OF", "2026-10-16"))
DEMO_USER = _get("DEMO_USER", "1749913629362473")
