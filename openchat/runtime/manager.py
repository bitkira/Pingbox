from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..admin import register_agent_profile
from ..client import load_profile, resolve_db_path
from ..common import RUNTIME_LOGS_DIR, ensure_app_dirs, normalize_handle, now_iso
from .app_server import app_server_ready, thread_start
from .session import (
    clear_daemon_state,
    clear_session,
    is_pid_alive,
    load_agent_manifest,
    load_daemon_state,
    load_daemon_pid,
    load_runtime_config,
    load_session,
    list_agent_manifests,
    save_agent_manifest,
    save_runtime_config,
    save_session,
)


DEFAULT_APP_SERVER_PORT = 61337
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def init_runtime(
    *,
    app_server_port: int | None = None,
    db_path_value: str | None = None,
    default_workdir: str | None = None,
) -> dict[str, Any]:
    ensure_app_dirs()
    config = load_runtime_config() or {}
    previous_url = str(config.get("app_server_url") or "")
    config.setdefault("created_at", now_iso())
    config["updated_at"] = now_iso()
    config["app_server_port"] = int(
        app_server_port if app_server_port is not None else config.get("app_server_port") or DEFAULT_APP_SERVER_PORT
    )
    config["app_server_url"] = f"ws://127.0.0.1:{config['app_server_port']}"
    config["db_path"] = str(resolve_db_path(db_path_value or config.get("db_path")))
    config["default_workdir"] = str(Path(default_workdir or config.get("default_workdir") or os.getcwd()).resolve())
    save_runtime_config(config)
    if previous_url and previous_url != config["app_server_url"]:
        shutdown_daemon_if_running()
    ensure_daemon_running(config)
    return config


def ensure_daemon_running(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_runtime_config()
    if not cfg:
        cfg = init_runtime()
    url = str(cfg["app_server_url"])
    pid = load_daemon_pid()
    state = load_daemon_state() or {}
    if pid and is_pid_alive(pid) and app_server_ready(url):
        if not state:
            return cfg
        if (
            state.get("status") == "ready"
            and int(state.get("daemon_pid") or 0) == pid
            and str(state.get("app_server_url") or "") == url
        ):
            return cfg
    if pid and is_pid_alive(pid):
        deadline = time.time() + 5.0
        while time.time() < deadline:
            state = load_daemon_state() or {}
            if app_server_ready(url):
                if not state:
                    return cfg
                if (
                    state.get("status") == "ready"
                    and int(state.get("daemon_pid") or 0) == pid
                    and str(state.get("app_server_url") or "") == url
                ):
                    return cfg
            if not is_pid_alive(pid):
                break
            time.sleep(0.25)
        shutdown_daemon_if_running()

    clear_daemon_state()
    log_path = RUNTIME_LOGS_DIR / "daemon.log"
    with log_path.open("a", encoding="utf-8") as handle:
        subprocess.Popen(
            [sys.executable, "-m", "openchat", "daemon", "run"],
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(PACKAGE_ROOT),
            start_new_session=True,
        )

    deadline = time.time() + 15.0
    while time.time() < deadline:
        pid = load_daemon_pid()
        state = load_daemon_state() or {}
        if (
            pid
            and is_pid_alive(pid)
            and app_server_ready(url)
            and state.get("status") == "ready"
            and int(state.get("daemon_pid") or 0) == pid
            and str(state.get("app_server_url") or "") == url
        ):
            return cfg
        if state.get("status") == "error":
            detail = str(state.get("last_error") or "daemon startup failed")
            raise SystemExit(f"failed to start the OpenChat runtime daemon: {detail}")
        time.sleep(0.25)
    raise SystemExit("failed to start the OpenChat runtime daemon")


def register_managed_agent(
    name: str,
    *,
    handle: str | None = None,
    db_path_value: str | None = None,
    profile_path: str | None = None,
    workdir: str | None = None,
) -> dict[str, Any]:
    config = init_runtime(db_path_value=db_path_value)
    profile, saved_profile_path = register_agent_profile(
        name,
        handle=handle,
        db_path_value=str(config["db_path"]),
        profile_path=profile_path,
    )
    normalized_handle = str(profile["handle"])
    existing = load_agent_manifest(normalized_handle) or {}
    manifest = {
        "agent_uid": profile["agent_uid"],
        "handle": normalized_handle,
        "display_name": profile["display_name"],
        "profile_path": str(saved_profile_path),
        "db_path": profile["db_path"],
        "workdir": str(Path(workdir or existing.get("workdir") or config["default_workdir"]).resolve()),
        "thread_id": existing.get("thread_id"),
        "created_at": existing.get("created_at") or now_iso(),
        "updated_at": now_iso(),
    }
    save_agent_manifest(normalized_handle, manifest)
    return manifest


def _resolve_agent_manifest(identifier: str) -> dict[str, Any] | None:
    manifest = load_agent_manifest(identifier)
    if manifest:
        return manifest
    normalized_identifier = normalize_handle(identifier)
    for candidate in list_agent_manifests():
        if str(candidate.get("handle") or "") == normalized_identifier:
            return candidate
        if normalize_handle(str(candidate.get("display_name") or "")) == normalized_identifier:
            return candidate
    return None


def _bootstrap_turn_text(manifest: dict[str, Any]) -> str:
    profile_path = manifest["profile_path"]
    handle = manifest["handle"]
    display_name = manifest["display_name"]
    workdir = manifest["workdir"]
    helper_root = Path(workdir) / "openchatskill" / "scripts"
    helper_hint = (
        f"Use the OpenChat tool scripts under {helper_root} with --profile {profile_path} on every command."
        if helper_root.exists()
        else f"Use the local OpenChat scripts available in your workspace with --profile {profile_path} on every command."
    )
    return "\n".join(
        [
            "OpenChat managed runtime bootstrap.",
            f"You are agent {display_name}({handle}).",
            f"Your OpenChat profile path is {profile_path}.",
            "This runtime uses a shared remote Codex app-server, so do not rely on process-level AGENT_COMM_PROFILE.",
            "When another agent contacts you, the runtime may inject an OpenChat notification as a new user turn.",
            "Treat those notifications as real external input and use explicit OpenChat script commands before responding.",
            helper_hint,
            f"Your workspace root is {workdir}.",
        ]
    )


def start_managed_agent(handle: str, *, persist_session: bool = True) -> dict[str, Any]:
    config = ensure_daemon_running()
    manifest = _resolve_agent_manifest(handle)
    if not manifest:
        raise SystemExit(f"unknown agent: {handle}")
    resolved_handle = manifest["handle"]

    session = load_session(resolved_handle)
    if session and is_pid_alive(int(session.get("codex_pid") or 0)):
        raise SystemExit(f"agent session already running for {resolved_handle}")
    if session:
        clear_session(resolved_handle)

    url = str(config["app_server_url"])
    thread_id = str(manifest.get("thread_id") or "").strip()
    bootstrap_prompt: str | None = None
    if not thread_id:
        thread = thread_start(url, manifest["workdir"])["thread"]
        thread_id = str(thread["id"])
        manifest["thread_id"] = thread_id
        manifest["updated_at"] = now_iso()
        save_agent_manifest(resolved_handle, manifest)
        bootstrap_prompt = _bootstrap_turn_text(manifest)

    if persist_session:
        save_session(
            resolved_handle,
            {
                "agent_uid": manifest["agent_uid"],
                "handle": manifest["handle"],
                "thread_id": thread_id,
                "codex_pid": os.getpid(),
                "started_at": now_iso(),
                "updated_at": now_iso(),
            },
        )
    profile = load_profile(manifest["profile_path"])
    argv = [
        "codex",
        "resume",
        "--remote",
        url,
        "-C",
        manifest["workdir"],
        "--no-alt-screen",
        thread_id,
    ]
    if bootstrap_prompt:
        argv.append(bootstrap_prompt)
    launch_env = {
        "AGENT_COMM_PROFILE": manifest["profile_path"],
        "AGENT_COMM_DB_PATH": str(profile.get("db_path") or manifest["db_path"]),
    }
    return {
        "argv": argv,
        "env": launch_env,
        "thread_id": thread_id,
        "handle": manifest["handle"],
        "bootstrap_prompt": bootstrap_prompt,
    }


def shutdown_daemon_if_running() -> None:
    pid = load_daemon_pid()
    if pid and is_pid_alive(pid):
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if not is_pid_alive(pid):
                return
            time.sleep(0.1)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return
