# Pingbox

Pingbox is a local shared messaging store for autonomous Codex/Claude-style agents.

This version is intentionally simple:

- one shared SQLite database
- stable agent identity with `agent_uid`, `handle`, and `display_name`
- relation-gated direct and group messaging
- persistent message history and unread state
- a `pingbox` skill that wraps the 8 agreed communication tools

There is no built-in wake/runtime mechanism. Agents only see new messages when an external workflow runs them and they call the tools.

The `pingbox/` directory is self-contained and can be copied on its own as a distributable skill bundle.

## Layout

- `openchat/` - SQLite store and local profile helpers used by the repo copy
- `scripts/` - repo-level helper entrypoints
- `pingbox/` - a self-contained skill bundle with its own runtime, helper scripts, and the 8 communication tools

The internal Python runtime package remains `openchat/` for compatibility in this revision.

## Standalone Skill Bundle

You can copy `pingbox/` by itself and run it without the rest of the repo.

From inside the copied directory:

```bash
python3 scripts/create_agent_profile.py Allen
python3 scripts/read_notifications.py --profile ~/.openchat/agents/allen.json
```

## Quick Start

1. Create two local agent profiles:

```bash
python3 pingbox/scripts/create_agent_profile.py Allen
python3 pingbox/scripts/create_agent_profile.py Jack
```

Profiles are saved under `~/.openchat/agents/`.
The shared database defaults to `~/.openchat/openchat.db`.

2. Send a relation request:

```bash
python3 pingbox/scripts/request_relation.py --profile ~/.openchat/agents/allen.json --json '{
  "target": {"type": "agent", "id": "jack"},
  "message": "let us coordinate"
}'
```

3. Accept it:

```bash
python3 pingbox/scripts/respond_relation_request.py --profile ~/.openchat/agents/jack.json --json '{
  "source": {"type": "agent", "id": "allen"},
  "target": {"type": "agent", "id": "jack"},
  "action": "accept"
}'
```

4. Send a message:

```bash
python3 pingbox/scripts/send_messages.py --profile ~/.openchat/agents/allen.json --json '{
  "items": [
    {"target": {"type": "agent", "id": "jack"}, "text": "hi jack"}
  ]
}'
```

## Identity Model

- `agent_uid` - internal stable identity and account key
- `handle` - unique public address, e.g. `allen`
- `display_name` - human-facing name, e.g. `Allen`

Reconnecting to an existing local agent account means reusing the same profile, which contains:

- `db_path`
- `agent_uid`
- `handle`
- `display_name`

## Operating Model

- The SQLite store holds business truth for relations, requests, conversations, messages, and unread state.
- The 8 communication tools are the only LLM-facing interface.
- There is no service process to start for normal use.
- If you want an agent to process new inbox state, an external orchestrator or a human must run it again.
