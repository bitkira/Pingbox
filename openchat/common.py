from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path


APP_DIR = Path.home() / ".openchat"
PROFILES_DIR = APP_DIR / "agents"
DEFAULT_DB_PATH = APP_DIR / "openchat.db"
RUNTIME_DIR = APP_DIR / "runtime"
RUNTIME_AGENTS_DIR = RUNTIME_DIR / "agents"
RUNTIME_SESSIONS_DIR = RUNTIME_DIR / "sessions"
RUNTIME_LOGS_DIR = RUNTIME_DIR / "logs"
RUNTIME_CONFIG_PATH = RUNTIME_DIR / "config.json"
RUNTIME_PID_PATH = RUNTIME_DIR / "daemon.pid"
RUNTIME_DAEMON_STATE_PATH = RUNTIME_DIR / "daemon-state.json"


def ensure_app_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_LOGS_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


_HANDLE_RE = re.compile(r"[^a-z0-9]+")


def normalize_handle(value: str) -> str:
    lowered = value.strip().lower()
    normalized = _HANDLE_RE.sub("-", lowered).strip("-")
    if not normalized:
        raise ValueError("handle cannot be empty")
    return normalized[:64]


def canonical_agent_label(display_name: str, handle: str) -> str:
    return f"agent {display_name}({handle})"


def canonical_group_label(display_name: str, handle: str) -> str:
    return f"group {display_name}({handle})"
