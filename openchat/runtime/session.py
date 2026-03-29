from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..common import (
    RUNTIME_AGENTS_DIR,
    RUNTIME_CONFIG_PATH,
    RUNTIME_DAEMON_STATE_PATH,
    RUNTIME_PID_PATH,
    RUNTIME_SESSIONS_DIR,
    ensure_app_dirs,
    normalize_handle,
)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_runtime_config() -> dict[str, Any] | None:
    ensure_app_dirs()
    return _read_json(RUNTIME_CONFIG_PATH)


def save_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    ensure_app_dirs()
    _write_json(RUNTIME_CONFIG_PATH, config)
    return config


def runtime_agent_path(handle: str) -> Path:
    ensure_app_dirs()
    return RUNTIME_AGENTS_DIR / f"{normalize_handle(handle)}.json"


def runtime_session_path(handle: str) -> Path:
    ensure_app_dirs()
    return RUNTIME_SESSIONS_DIR / f"{normalize_handle(handle)}.json"


def load_agent_manifest(handle: str) -> dict[str, Any] | None:
    return _read_json(runtime_agent_path(handle))


def save_agent_manifest(handle: str, manifest: dict[str, Any]) -> dict[str, Any]:
    _write_json(runtime_agent_path(handle), manifest)
    return manifest


def list_agent_manifests() -> list[dict[str, Any]]:
    ensure_app_dirs()
    manifests: list[dict[str, Any]] = []
    for path in sorted(RUNTIME_AGENTS_DIR.glob("*.json")):
        data = _read_json(path)
        if data:
            manifests.append(data)
    return manifests


def load_session(handle: str) -> dict[str, Any] | None:
    return _read_json(runtime_session_path(handle))


def save_session(handle: str, session: dict[str, Any]) -> dict[str, Any]:
    _write_json(runtime_session_path(handle), session)
    return session


def clear_session(handle: str) -> None:
    path = runtime_session_path(handle)
    if path.exists():
        path.unlink()


def list_sessions() -> list[dict[str, Any]]:
    ensure_app_dirs()
    sessions: list[dict[str, Any]] = []
    for path in sorted(RUNTIME_SESSIONS_DIR.glob("*.json")):
        data = _read_json(path)
        if data:
            sessions.append(data)
    return sessions


def is_pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def load_daemon_pid() -> int | None:
    ensure_app_dirs()
    if not RUNTIME_PID_PATH.exists():
        return None
    raw = RUNTIME_PID_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def save_daemon_pid(pid: int) -> None:
    ensure_app_dirs()
    RUNTIME_PID_PATH.write_text(f"{pid}\n", encoding="utf-8")


def clear_daemon_pid() -> None:
    if RUNTIME_PID_PATH.exists():
        RUNTIME_PID_PATH.unlink()


def load_daemon_state() -> dict[str, Any] | None:
    ensure_app_dirs()
    return _read_json(RUNTIME_DAEMON_STATE_PATH)


def save_daemon_state(state: dict[str, Any]) -> dict[str, Any]:
    ensure_app_dirs()
    _write_json(RUNTIME_DAEMON_STATE_PATH, state)
    return state


def clear_daemon_state() -> None:
    if RUNTIME_DAEMON_STATE_PATH.exists():
        RUNTIME_DAEMON_STATE_PATH.unlink()


def ensure_codex_session_stub(
    *,
    thread_id: str,
    thread_path: str,
    cwd: str,
    cli_version: str | None = None,
    model_provider: str | None = None,
) -> Path:
    path = Path(thread_path).expanduser()
    if path.exists():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    session_meta = {
        "timestamp": timestamp,
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "timestamp": timestamp,
            "cwd": cwd,
            "originator": "codex_cli_rs",
            "cli_version": cli_version or "unknown",
            "source": "cli",
            "model_provider": model_provider or "unknown",
        },
    }
    path.write_text(json.dumps(session_meta, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
