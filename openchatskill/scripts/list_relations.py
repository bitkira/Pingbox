#!/usr/bin/env python3
from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from openchat.client import load_agent_context


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List the current direct agent relations and joined groups for an agent.",
    )
    parser.add_argument("--profile", help="Agent profile used to resolve the caller identity.")
    args = parser.parse_args()

    store, context = load_agent_context(args.profile)
    print(store.list_relations(context["agent_uid"]))


if __name__ == "__main__":
    main()
