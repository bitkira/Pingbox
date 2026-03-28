from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from ..client import open_store
from ..common import RUNTIME_LOGS_DIR, ensure_app_dirs, now_iso
from .app_server import AppServerError, app_server_ready, thread_read, thread_resume, turn_start
from .session import (
    clear_daemon_pid,
    is_pid_alive,
    list_sessions,
    load_agent_manifest,
    load_runtime_config,
    save_daemon_state,
    save_daemon_pid,
)


def _helper_command(manifest: dict[str, Any], script_name: str, payload: dict[str, Any] | None = None) -> str:
    helper_root = Path(manifest["workdir"]) / "openchatskill" / "scripts"
    helper_script = helper_root / script_name
    base = f"python3 {helper_script} --profile {manifest['profile_path']}"
    if payload is None:
        return base
    return f"{base} --json {json.dumps(payload, ensure_ascii=False)!r}"


def _format_event_text(event: dict[str, Any], manifest: dict[str, Any]) -> str:
    payload = event["payload"]
    source_label = payload["source_label"]
    if event["kind"] == "incoming_relation_request":
        command = _helper_command(manifest, "read_relation_requests.py")
        return "\n".join(
            [
                "OpenChat notification:",
                f"{source_label} sent you a relation request.",
                f"Inspect it with: {command}",
            ]
        )
    read_payload = {
        "target": {
            "type": payload["target_type"],
            "id": payload["target_handle"],
        }
    }
    command = _helper_command(manifest, "read_messages.py", read_payload)
    if payload["target_type"] == "group":
        return "\n".join(
            [
                "OpenChat notification:",
                f"{source_label} sent a new message in {payload['target_label']}.",
                f"Inspect it with: {command}",
            ]
        )
    return "\n".join(
        [
            "OpenChat notification:",
            f"{source_label} sent you a new message.",
            f"Inspect it with: {command}",
        ]
    )


def _active_session_map() -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    for session in list_sessions():
        pid = int(session.get("codex_pid") or 0)
        if is_pid_alive(pid):
            active[str(session["agent_uid"])] = session
    return active


def _save_runtime_state(
    config: dict[str, Any],
    *,
    status: str,
    app_server_pid: int | None = None,
    last_error: str | None = None,
) -> None:
    save_daemon_state(
        {
            "status": status,
            "daemon_pid": os.getpid(),
            "app_server_pid": app_server_pid,
            "app_server_url": config["app_server_url"],
            "updated_at": now_iso(),
            "last_error": last_error,
        }
    )


def _event_is_stale(store: Any, event: dict[str, Any]) -> bool:
    if event["kind"] != "incoming_relation_request":
        return False
    relation_request_uid = str(event.get("relation_request_uid") or "").strip()
    if not relation_request_uid:
        return True
    with store.tx() as conn:
        row = conn.execute(
            "SELECT status FROM relation_requests WHERE request_uid = ?",
            (relation_request_uid,),
        ).fetchone()
    return not row or row["status"] != "pending"


def _dispatch_once(config: dict[str, Any]) -> None:
    store = open_store(config["db_path"])
    pending = store.list_pending_wake_events()
    if not pending:
        return
    deliverable: list[dict[str, Any]] = []
    for event in pending:
        if _event_is_stale(store, event):
            store.mark_wake_event_delivered(event["event_uid"])
            continue
        deliverable.append(event)
    if not deliverable:
        return
    sessions = _active_session_map()
    if not sessions:
        return
    for event in deliverable:
        session = sessions.get(event["target_agent_uid"])
        if not session:
            continue
        manifest = load_agent_manifest(session["handle"])
        if not manifest:
            continue
        thread_id = str(session.get("thread_id") or "").strip()
        if not thread_id:
            continue
        try:
            thread = thread_read(config["app_server_url"], thread_id, include_turns=True)["thread"]
        except AppServerError as exc:
            if "includeTurns is unavailable before first user message" not in str(exc):
                store.record_wake_event_error(event["event_uid"], str(exc))
                continue
            try:
                thread = thread_read(config["app_server_url"], thread_id, include_turns=False)["thread"]
            except AppServerError as fallback_exc:
                store.record_wake_event_error(event["event_uid"], str(fallback_exc))
                continue
        try:
            status = thread["status"]["type"]
            if status == "notLoaded":
                thread_resume(config["app_server_url"], thread_id)
                continue
            if status != "idle":
                continue
            turns = thread.get("turns") or []
            if turns and turns[-1]["status"] == "inProgress":
                continue
            turn_start(config["app_server_url"], thread_id, _format_event_text(event, manifest))
            store.mark_wake_event_delivered(event["event_uid"])
        except AppServerError as exc:
            store.record_wake_event_error(event["event_uid"], str(exc))


def main() -> None:
    ensure_app_dirs()
    config = load_runtime_config()
    if not config:
        raise SystemExit("run `openchat init` first")

    save_daemon_pid(os.getpid())
    _save_runtime_state(config, status="starting")
    app_server_log = RUNTIME_LOGS_DIR / "app-server.log"
    child: subprocess.Popen[str] | None = None
    last_error: str | None = None
    try:
        with app_server_log.open("a", encoding="utf-8") as handle:
            handle.write(f"[{now_iso()}] starting codex app-server\n")
            handle.flush()
            child = subprocess.Popen(
                ["codex", "app-server", "--listen", config["app_server_url"]],
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
            )
            _save_runtime_state(config, status="starting", app_server_pid=child.pid)
            deadline = time.time() + 15.0
            while time.time() < deadline:
                if child.poll() is not None:
                    last_error = "codex app-server exited during startup"
                    _save_runtime_state(config, status="error", app_server_pid=child.pid, last_error=last_error)
                    raise SystemExit(last_error)
                if app_server_ready(config["app_server_url"]):
                    time.sleep(0.5)
                    if child.poll() is not None:
                        last_error = "codex app-server exited during startup"
                        _save_runtime_state(config, status="error", app_server_pid=child.pid, last_error=last_error)
                        raise SystemExit(last_error)
                    _save_runtime_state(config, status="ready", app_server_pid=child.pid)
                    break
                time.sleep(0.25)
            else:
                last_error = "codex app-server did not become ready"
                _save_runtime_state(config, status="error", app_server_pid=child.pid, last_error=last_error)
                raise SystemExit(last_error)

            while True:
                if child.poll() is not None:
                    last_error = "codex app-server exited"
                    _save_runtime_state(config, status="error", app_server_pid=child.pid, last_error=last_error)
                    raise SystemExit(last_error)
                _dispatch_once(config)
                _save_runtime_state(config, status="ready", app_server_pid=child.pid)
                time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        clear_daemon_pid()
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
        _save_runtime_state(
            config,
            status="error" if last_error else "stopped",
            app_server_pid=child.pid if child else None,
            last_error=last_error,
        )
