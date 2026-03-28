from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class AppServerError(RuntimeError):
    pass


def _rpc_script_path() -> Path:
    return Path(__file__).with_name("codex_rpc.mjs")


def app_server_ready(url: str) -> bool:
    ready_url = url.replace("ws://", "http://").rstrip("/") + "/readyz"
    try:
        with urllib.request.urlopen(ready_url, timeout=1.0) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def call_app_server(url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", str(_rpc_script_path()), url, method],
        input=json.dumps(params, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"{method} failed"
        raise AppServerError(detail)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AppServerError(f"{method} returned invalid JSON") from exc


def thread_start(url: str, cwd: str) -> dict[str, Any]:
    return call_app_server(url, "thread/start", {"cwd": cwd})


def thread_resume(url: str, thread_id: str) -> dict[str, Any]:
    return call_app_server(url, "thread/resume", {"threadId": thread_id})


def thread_read(url: str, thread_id: str, *, include_turns: bool = False) -> dict[str, Any]:
    return call_app_server(url, "thread/read", {"threadId": thread_id, "includeTurns": include_turns})


def turn_start(url: str, thread_id: str, text: str) -> dict[str, Any]:
    return call_app_server(
        url,
        "turn/start",
        {
            "threadId": thread_id,
            "input": [{"type": "text", "text": text, "text_elements": []}],
        },
    )
