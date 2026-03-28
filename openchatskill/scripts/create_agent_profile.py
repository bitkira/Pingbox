#!/usr/bin/env python3
from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from openchat.client import open_store, resolve_db_path, save_profile
from openchat.store import OpenChatError


def main() -> None:
    parser = argparse.ArgumentParser(description="Register a new local agent and save a profile.")
    parser.add_argument("name", help="Display name for the new agent, e.g. Allen")
    parser.add_argument("--handle", help="Unique public handle. Defaults to a normalized form of the name.")
    parser.add_argument(
        "--db-path",
        help="Optional shared SQLite path. Defaults to AGENT_COMM_DB_PATH or ~/.openchat/openchat.db.",
    )
    parser.add_argument("--profile-path", help="Optional explicit profile path.")
    args = parser.parse_args()

    db_path = resolve_db_path(args.db_path)
    store = open_store(str(db_path))
    try:
        data = store.register_agent(
            args.handle or args.name,
            args.name,
        )
    except OpenChatError as exc:
        raise SystemExit(f"failure:\n{exc.code}") from exc
    profile = {
        "db_path": str(db_path),
        "agent_uid": data["agent_uid"],
        "handle": data["handle"],
        "display_name": data["display_name"],
    }
    path = save_profile(profile, args.profile_path)
    print(path)


if __name__ == "__main__":
    main()
