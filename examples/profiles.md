# Agent profile examples

Create with `ohmypm agent profile-add NAME --agent TYPE --options JSON [--default] [--read-only]`,
the Web UI (Agent Runner → New profile) or `POST /api/agent-profiles`.

| Profile | Agent | Options | Notes |
|---|---|---|---|
| `claude-default` | claude | `{"model": "sonnet", "allowed_tools": ["Bash(npm test:*)", "Bash(git diff:*)", "Bash(git status:*)"], "max_budget_usd": 5}` | Edits + a few safe shell commands; everything else is denied |
| `claude-plan` | claude | `{"permission_mode": "plan"}` + `--read-only` | Analysis / planning only |
| `claude-yolo` | claude | `{"permission_mode": "bypassPermissions"}` | Dangerous: runner needs `allow_dangerous: true`; use only in sandboxed workspaces |
| `codex-default` | codex | `{"sandbox": "workspace-write", "reasoning_effort": "medium"}` | |
| `codex-readonly` | codex | `{"sandbox": "read-only"}` + `--read-only` | Reviews |
| `pi-local` | pi | `{"provider": "localai", "model": "qwen3-coder", "tools": ["read", "edit", "write", "grep", "find", "ls"]}` | No bash (Pi has no approval system) |
| `dsh-default` | dsh | `{"profile": "headless", "permission_mode": "workspace-write"}` | Needs `DEEPSEEK_API_KEY` in the runner environment |

```bash
ohmypm agent profile-add claude-default --agent claude --default \
  --options '{"model": "sonnet", "allowed_tools": ["Bash(npm test:*)", "Bash(git diff:*)"], "max_budget_usd": 5}'
ohmypm agent profile-add codex-readonly --agent codex --read-only --options '{"sandbox": "read-only"}'
```
