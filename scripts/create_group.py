#!/usr/bin/env python3
from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from openchat.client import load_agent_context
from openchat.common import canonical_group_label
from openchat.store import OpenChatError


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a local group in the shared OpenChat store.")
    parser.add_argument("name", help="Display name for the group")
    parser.add_argument("--handle", help="Unique public handle. Defaults to a normalized form of the name.")
    parser.add_argument("--profile", help="Agent profile used as the creator/admin.")
    args = parser.parse_args()

    store, context = load_agent_context(args.profile)
    try:
        data = store.create_group(
            context["agent_uid"],
            args.handle or args.name,
            args.name,
        )
    except OpenChatError as exc:
        raise SystemExit(f"failure:\n{exc.code}") from exc
    print(canonical_group_label(data["display_name"], data["handle"]))


if __name__ == "__main__":
    main()
