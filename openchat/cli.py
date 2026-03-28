from __future__ import annotations

import argparse
import json
import os

from .runtime.manager import init_runtime, register_managed_agent, start_managed_agent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenChat runtime control plane.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize the managed OpenChat runtime.")
    init_parser.add_argument("--app-server-port", type=int, help="Local port for codex app-server.")
    init_parser.add_argument("--db-path", help="Optional shared SQLite path.")
    init_parser.add_argument("--workdir", help="Default workspace root for managed agents.")

    agent_parser = subparsers.add_parser("agent", help="Manage OpenChat agents.")
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", required=True)

    register_parser = agent_subparsers.add_parser("register", help="Register or reuse a managed agent identity.")
    register_parser.add_argument("name", help="Agent display name.")
    register_parser.add_argument("--handle", help="Optional explicit public handle.")
    register_parser.add_argument("--db-path", help="Optional shared SQLite path.")
    register_parser.add_argument("--profile-path", help="Optional explicit profile path.")
    register_parser.add_argument("--workdir", help="Workspace root for this agent. Defaults to the current directory.")

    start_parser = agent_subparsers.add_parser("start", help="Start a managed Codex session for an agent.")
    start_parser.add_argument("name", help="Registered agent display name or handle.")
    start_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the launch spec instead of replacing the current process with Codex.",
    )

    daemon_parser = subparsers.add_parser("daemon", help="Internal daemon controls.")
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command", required=True)
    daemon_subparsers.add_parser("run", help="Run the OpenChat background daemon.")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "init":
        config = init_runtime(
            app_server_port=args.app_server_port,
            db_path_value=args.db_path,
            default_workdir=args.workdir,
        )
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return

    if args.command == "agent" and args.agent_command == "register":
        manifest = register_managed_agent(
            args.name,
            handle=args.handle,
            db_path_value=args.db_path,
            profile_path=args.profile_path,
            workdir=args.workdir,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    if args.command == "agent" and args.agent_command == "start":
        launch = start_managed_agent(args.name, persist_session=not args.dry_run)
        if args.dry_run:
            print(json.dumps(launch, ensure_ascii=False, indent=2))
            return
        env = os.environ.copy()
        env.update(launch["env"])
        os.execvpe(launch["argv"][0], launch["argv"], env)

    if args.command == "daemon" and args.daemon_command == "run":
        from .runtime.daemon import main as daemon_main

        daemon_main()
        return

    raise SystemExit("invalid command")
