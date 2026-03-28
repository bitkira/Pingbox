#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import _bootstrap  # noqa: F401
from openchat.client import load_agent_context
from openchat.store import OpenChatError


TOOL_HELP = {
    "send_messages": "Send one or more text messages to related targets.",
    "read_notifications": "Read unread notification summaries.",
    "read_messages": "Read unread messages first, otherwise recent history.",
    "search_messages": "Search visible message history.",
    "request_relation": "Send a relation request to an agent or group.",
    "read_relation_requests": "Read pending inbound relation requests.",
    "respond_relation_request": "Accept or reject a pending relation request.",
    "remove_relation": "Remove an existing relation without deleting history.",
}


def _load_payload(raw_json: str | None) -> dict[str, Any]:
    raw = raw_json
    if raw is None and not sys.stdin.isatty():
        raw = sys.stdin.read().strip() or None
    if raw is None:
        return {}
    if raw.startswith("@"):
        with open(raw[1:], "r", encoding="utf-8") as handle:
            raw = handle.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"CONFIG ERROR: invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("CONFIG ERROR: payload must be a JSON object.")
    return payload


def _format_target_ref(target: Any, *, default_type: str | None = None) -> str | None:
    if not isinstance(target, dict):
        return None
    target_type = str(target.get("type") or default_type or "").strip()
    target_id = str(target.get("id") or "").strip()
    if target_type and target_id:
        return f"{target_type} {target_id}"
    return None


def _format_tool_failure(tool_name: str, payload: dict[str, Any], code: str) -> str:
    if tool_name in {"request_relation", "remove_relation", "read_messages", "search_messages"}:
        ref = _format_target_ref(payload.get("target"))
        if ref:
            return f"failure:\n{ref}: {code}"
        return f"failure:\n{code}"
    if tool_name == "respond_relation_request":
        source_ref = _format_target_ref(payload.get("source"), default_type="agent")
        target_ref = _format_target_ref(payload.get("target"))
        if source_ref and target_ref:
            return f"failure:\n{source_ref} -> {target_ref}: {code}"
        return f"failure:\n{code}"
    return f"failure:\n{code}"


def _dispatch_tool(tool_name: str, store: Any, caller_uid: str, payload: dict[str, Any]) -> str:
    if tool_name == "request_relation":
        return store.request_relation(caller_uid, payload)
    if tool_name == "read_relation_requests":
        return store.read_relation_requests(caller_uid)
    if tool_name == "respond_relation_request":
        return store.respond_relation_request(caller_uid, payload)
    if tool_name == "remove_relation":
        return store.remove_relation(caller_uid, payload)
    if tool_name == "send_messages":
        status, failures = store.send_messages(caller_uid, payload)
        if status == "success":
            return "success"
        return "failure:\n" + "\n".join(failures)
    if tool_name == "read_notifications":
        return store.read_notifications(caller_uid)
    if tool_name == "read_messages":
        return store.read_messages(caller_uid, payload)
    if tool_name == "search_messages":
        return store.search_messages(caller_uid, payload)
    raise OpenChatError("invalid_target")


def run_tool(tool_name: str) -> int:
    parser = argparse.ArgumentParser(description=TOOL_HELP[tool_name])
    parser.add_argument(
        "--json",
        help="JSON payload string or @path/to/payload.json. If omitted, read stdin or use {}.",
    )
    parser.add_argument(
        "--profile",
        help="Path to a saved agent profile. If omitted, use AGENT_COMM_PROFILE or env vars.",
    )
    args = parser.parse_args()
    payload = _load_payload(args.json)
    store, context = load_agent_context(args.profile)
    caller_uid = str(context["agent_uid"])

    try:
        print(_dispatch_tool(tool_name, store, caller_uid, payload))
        return 0
    except OpenChatError as exc:
        print(_format_tool_failure(tool_name, payload, exc.code))
        return 1
    except Exception as exc:  # pragma: no cover - defensive path
        print(f"failure:\ninternal_error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit("Import this module from a tool wrapper.")
