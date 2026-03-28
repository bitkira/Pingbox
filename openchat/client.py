from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .common import DEFAULT_DB_PATH, PROFILES_DIR, ensure_app_dirs
from .store import OpenChatStore


PROFILE_ENV = "AGENT_COMM_PROFILE"
AGENT_ID_ENV = "AGENT_COMM_AGENT_ID"
DB_PATH_ENV = "AGENT_COMM_DB_PATH"


def load_profile(profile_path: str | None = None) -> dict[str, Any]:
    ensure_app_dirs()
    path_value = profile_path or os.environ.get(PROFILE_ENV, "")
    if not path_value:
        return {}
    path = Path(path_value).expanduser()
    return json.loads(path.read_text(encoding="utf-8"))


def save_profile(profile: dict[str, Any], profile_path: str | None = None) -> Path:
    ensure_app_dirs()
    path = Path(profile_path).expanduser() if profile_path else PROFILES_DIR / f"{profile['handle']}.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def resolve_db_path(db_path_value: str | None = None, profile: dict[str, Any] | None = None) -> Path:
    raw = db_path_value or os.environ.get(DB_PATH_ENV) or (profile or {}).get("db_path") or str(DEFAULT_DB_PATH)
    return Path(str(raw)).expanduser()


def merged_env_and_profile(profile_path: str | None = None) -> dict[str, Any]:
    profile = load_profile(profile_path)
    return {
        "db_path": str(resolve_db_path(profile=profile)),
        "agent_uid": os.environ.get(AGENT_ID_ENV) or profile.get("agent_uid"),
        "handle": profile.get("handle"),
        "display_name": profile.get("display_name"),
        "profile": profile,
    }


def open_store(db_path_value: str | None = None, profile: dict[str, Any] | None = None) -> OpenChatStore:
    db_path = resolve_db_path(db_path_value, profile)
    ensure_app_dirs()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return OpenChatStore(db_path)


def load_agent_context(profile_path: str | None = None) -> tuple[OpenChatStore, dict[str, Any]]:
    merged = merged_env_and_profile(profile_path)
    agent_uid = str(merged.get("agent_uid") or "").strip()
    if not agent_uid:
        raise SystemExit("CONFIG ERROR: set AGENT_COMM_PROFILE or set AGENT_COMM_AGENT_ID.")
    store = open_store(profile=merged["profile"])
    agent = store.get_agent(agent_uid)
    if not agent:
        raise SystemExit("CONFIG ERROR: agent_uid was not found in the local Pingbox database.")
    merged["agent"] = agent
    return store, merged
