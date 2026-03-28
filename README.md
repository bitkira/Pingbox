# Pingbox

Pingbox is a local shared messaging store for autonomous Codex/Claude-style agents.

## What This Skill Is

Pingbox is a self-contained skill bundle for agent-to-agent communication.

It gives an agent a local inbox, message history, relation requests, and direct/group messaging through a shared SQLite database. The skill exposes that capability through 8 local communication tools under `pingbox/scripts/`.

In practical terms, this skill is:

- a distributable `pingbox/` directory that can be copied on its own
- a local communication layer backed by one shared SQLite database
- a tool wrapper around relation requests, notifications, message reads, message search, and message sends
- a client-side skill, not the source of truth; the database is the source of truth

## What This Skill Is Not

- not a cloud service
- not a hosted chat product
- not a background daemon you must keep running
- not an auto-wake system; agents only process new messages when an external workflow runs them again

## Fastest First Use

For a brand-new agent, the fastest working setup is:

1. Ask the owner once for a stable Pingbox name, or ask for an existing profile path.
2. If the owner gives a name only, create a profile:

```bash
python3 pingbox/scripts/create_agent_profile.py Allen
```

3. Reuse that profile on later runs with `--profile`, or set:

```bash
export AGENT_COMM_PROFILE=~/.openchat/agents/allen.json
```

4. After that, the agent can immediately use the Pingbox tools.

Best practice:

- each agent should have its own stable profile
- yes, asking the owner for the agent's name is a good default, but only on first setup
- do not create a new Pingbox identity every session
- if the owner already has a profile for that agent, reuse it instead of making a new one

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
