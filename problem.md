1. `default_workdir` design issue

Current behavior:
- `openchat init` persists a global `default_workdir`.
- Later `agent register` without `--workdir` inherits that init-time directory.
- `agent start` then keeps using the agent manifest's stored `workdir`.

Why this is problematic:
- If the user opens a different project directory and expects an agent to inspect that project, the agent may still attach to the old init-time project path.
- This makes `init` incorrectly act like a project-level binding, when it should be machine/runtime-level setup.

Preferred direction:
- `openchat init` should not bind a project directory by default.
- `agent register` should default to the current shell `cwd` if no `--workdir` is provided.
- `agent start` should use the agent's saved `workdir`, but should support an explicit override such as `--workdir` or `--here`.
