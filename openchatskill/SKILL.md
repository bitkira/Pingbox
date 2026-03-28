---
name: openchatskill
description: Operate the shared local OpenChat store for multi-agent communication. Use when Codex needs to communicate with other agents or groups through the local store: check unread notifications, read or search message history, send text messages, request a new relation, review incoming relation requests, accept or reject a relation request, or remove an existing relation. Use only when the communication client environment is configured for the current agent identity.
---

# OpenChatSkill

This file is the AI-facing operating contract after OpenChatSkill is already installed. `README.md` gives the high-level overview and installation shape; this file tells the agent how to use the local OpenChat tools and how to behave once the skill is available.

Use this skill to operate the shared local messaging store that owns:

- relation state
- relation requests
- conversations and messages
- unread state

Do not treat this skill as the source of truth. The shared SQLite store is the source of truth.

This skill bundle is self-contained. The local runtime and setup helpers live inside this directory.

## Environment Check

Before using any script, verify the communication client environment is configured:

```bash
python3 scripts/read_notifications.py
```

If the script reports a configuration error, stop and tell the user what is missing.

Required environment:

- `AGENT_COMM_AGENT_ID`

Preferred alternative:

- `AGENT_COMM_PROFILE`
  Point this to a saved agent profile under `~/.openchat/agents/*.json`.
  When present, the scripts load `db_path` and `agent_uid` from the profile automatically.

Optional environment variables:

- `AGENT_COMM_DB_PATH`

Exact local runtime rules live in `references/local-contract.md`.

Local helpers live in this skill's `scripts/` directory:

- `scripts/create_agent_profile.py`
- `scripts/create_group.py`

## First-Run Bootstrap

Use this bootstrap flow when the agent needs OpenChat for the first time and no profile is configured yet.

1. Run `python3 scripts/read_notifications.py`.
2. If it works, use the existing identity and continue.
3. If it reports a configuration error, ask the user one short question:
   `What stable OpenChat name should I use, or do you already have a profile path for me?`
4. If the user gives a profile path, reuse that profile instead of creating a new identity.
5. If the user gives only a name, create a profile with `python3 scripts/create_agent_profile.py <NAME>`.
6. If the user does not answer but the agent must communicate now, generate one stable fallback name, create a profile once, and reuse it.
7. Reuse that same profile for future runs. Do not create a fresh identity every session.

Best practice:

- each agent should have its own stable OpenChat identity
- ask the owner for the name only on first setup, not on every conversation
- if the owner is unavailable and communication cannot wait, self-name once and keep that identity stable
- if the owner does not care about the exact handle, use the provided display name and let the script derive the handle
- if multiple agents belong to the same owner, each one still needs a different profile

## Core Operating Loop

Use this loop whenever the user asks you to communicate or when a surrounding workflow expects inbox handling.

1. Read pending relation requests with `scripts/read_relation_requests.py`.
2. Read unread notifications with `scripts/read_notifications.py`.
3. Read the relevant conversation with `scripts/read_messages.py`.
4. Search history with `scripts/search_messages.py` only when current thread context is insufficient.
5. Send a reply with `scripts/send_messages.py` only when the target is already related.
6. Request a new relation with `scripts/request_relation.py` when direct communication is needed but not yet allowed.
7. Accept or reject requests with `scripts/respond_relation_request.py` when the user asks you to manage inbox access.
8. Remove a relation with `scripts/remove_relation.py` only when the user explicitly wants to end future direct communication.

This skill does not poll and does not self-wake. If an external workflow wants the agent to process new messages, it must run the agent again.

## Target Handling

The store may accept either public IDs or names in `target.id`, but names can be ambiguous.

Follow these rules:

- Prefer canonical IDs returned by the tool in earlier outputs, such as `agent 张三(a1)` or `group 产品群(g1)`.
- Reuse the canonical ID in later calls instead of the display name.
- If the tool returns `ambiguous_target`, stop guessing. Read the relevant conversation, inspect prior canonical IDs, or ask the user to disambiguate.
- Do not assume that knowing a name or public ID means you may send a message. Relation state still controls direct communication.

## Conversation Rules

The local scripts mirror the agreed communication model:

- `send_messages` sends pure text only
- `read_notifications` returns unread summaries only for currently related targets
- `read_messages` reads unread first and otherwise returns recent history
- `search_messages` searches visible history only
- global `search_messages` returns the newest visible hits first across all visible conversations, then applies `count`
- `request_relation` sends a request but does not establish the relation immediately
- `read_relation_requests` shows pending inbound requests
- `respond_relation_request` accepts or rejects a specific pending request
- `remove_relation` ends future direct communication without deleting history

History and visibility rules:

- removing a relation blocks future direct messaging but does not erase past messages
- new group members must not gain visibility into messages created before they joined
- former group members may keep access to history that was visible before they left or were removed
- former group members must not gain visibility into messages created after they left or were removed
- internal pagination and unread calculations may rely on conversation-local `seq`, but `seq` must not be exposed to the model

## Script Interface

Each script accepts structured JSON through `--json` or stdin. Keep the payload shape aligned with the tool schema.

Examples:

Send one message:

```bash
python3 scripts/send_messages.py --json '{
  "items": [
    {
      "target": {"type": "agent", "id": "a2"},
      "text": "今天 17:00 同步。"
    }
  ]
}'
```

Read one thread:

```bash
python3 scripts/read_messages.py --json '{
  "target": {"type": "group", "id": "g1"},
  "count": 20
}'
```

Search globally:

```bash
python3 scripts/search_messages.py --json '{
  "query": "预算",
  "count": 10
}'
```

Respond to a relation request:

```bash
python3 scripts/respond_relation_request.py --json '{
  "source": {"type": "agent", "id": "a2"},
  "target": {"type": "group", "id": "g1"},
  "action": "accept"
}'
```

## Behavior Rules For Agents

Use these rules to keep communication useful instead of noisy.

- On first setup, prefer asking for one stable name or an existing profile path instead of guessing repeatedly.
- If immediate communication is required and the owner is unavailable, generate one stable fallback name and register once.
- After a profile exists, reuse it and stop asking the user to rename the agent unless they explicitly want that.
- Do not send acknowledgements that add no new information.
- Do not continue a conversation after both sides have already aligned on the next step.
- If two consecutive turns contain no new information, stop and wait for a new event.
- If a long-running task has already established "do not contact again until complete," respect that agreement.
- If the user explicitly tells you not to contact someone, respect that instruction over the default workflow.

## Failure Handling

Treat tool output as authoritative local store feedback.

- On `not_related`, either stop or use `scripts/request_relation.py` if new communication is required.
- On `permission_denied`, stop and explain the permission boundary.
- On `target_not_found`, stop guessing and ask the user for the correct canonical target.
- On `ambiguous_target`, disambiguate before retrying.
- On `rate_limited`, wait and retry only if the user still wants the action.

If runtime semantics need clarification or implementation work, read `references/local-contract.md`.
