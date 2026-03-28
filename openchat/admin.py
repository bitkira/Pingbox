from __future__ import annotations

from pathlib import Path
from typing import Any

from .client import load_profile, open_store, resolve_db_path, save_profile
from .common import PROFILES_DIR, normalize_handle


def _existing_profile(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    profile = load_profile(str(path))
    if not profile:
        return None
    store = open_store(profile=profile)
    agent_uid = str(profile.get("agent_uid") or "").strip()
    if not agent_uid:
        return None
    if not store.get_agent(agent_uid):
        return None
    return profile


def register_agent_profile(
    name: str,
    *,
    handle: str | None = None,
    db_path_value: str | None = None,
    profile_path: str | None = None,
) -> tuple[dict[str, Any], Path]:
    normalized_handle = normalize_handle(handle or name)
    target_path = Path(profile_path).expanduser() if profile_path else PROFILES_DIR / f"{normalized_handle}.json"
    existing = _existing_profile(target_path)
    if existing:
        return existing, target_path

    db_path = resolve_db_path(db_path_value)
    store = open_store(str(db_path))
    data = store.register_agent(
        normalized_handle,
        name,
    )
    profile = {
        "db_path": str(db_path),
        "agent_uid": data["agent_uid"],
        "handle": data["handle"],
        "display_name": data["display_name"],
    }
    path = save_profile(profile, str(target_path))
    return profile, path
