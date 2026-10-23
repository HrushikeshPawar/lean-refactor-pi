# Plan: OpenCode v2 worker backend over MCP (2026-10-23)

Goal: run harness workers inside OpenCode v2 (its free models only work there) while the arena tools stay ours,
exposed over MCP. Workers must be as isolated as Pi workers: no old findings, no repo, no user config.

## How Pi workers are isolated today (arena/pi_rpc.py `worker_launch`)
`--offline --no-builtin-tools --no-context-files --no-extensions --no-skills --no-prompt-templates`,
`--tools compile,goal,search,read,scratch,card` (the six arena tools only), the arena extension only,
a per-run `--session-dir`, and per-worker `ARENA_*` env. The arena `read`/`search` tools see only the theorem's
workspace and hide harness declarations.

## OpenCode equivalents (P0 = verify each before building)
| Pi control | OpenCode v2 plan | Leak it closes |
|---|---|---|
| `--no-context-files` | cwd = empty per-run dir OUTSIDE the repo (OpenCode walks up for AGENTS.md/CLAUDE.md) | repo AGENTS.md, CLAUDE.md, notes |
| `--no-skills/extensions/prompt-templates` | isolated config home (XDG_CONFIG_HOME or a config-path env) with a generated opencode.jsonc: no plugins, no skills, no commands | ~/.config/opencode/skills (gitbutler), commands, plugins |
| `--no-builtin-tools`, `--tools …` | agent `arena-worker` with every built-in tool denied (bash, read, edit, write, glob, grep, list, webfetch, websearch, task, todo, patch); only `arena_*` MCP tools allowed | reading runs/, submissions, earlier proofs |
| `--offline` | deny webfetch/websearch; no share, no autoupdate | web lookups of our own repo/LB |
| `--session-dir` | isolated XDG_DATA_HOME/XDG_STATE_HOME per run (own opencode.db); `--standalone` private server; never `--continue` | earlier sessions in ~/.local/share/opencode/opencode.db, the shared background service |
| `ARENA_*` env | one `arena mcp` stdio server per worker, launched with the same env | — |

## Phases
- **P0 verify (docs + `opencode debug config/paths/agents`, no runs):** config-home override that really drops
  ~/.config/opencode; agent tool/permission schema in v2; MCP stdio server config; SDK or `serve` API for prompt,
  steer, abort and event stream; JSON event format with token usage; free model ids (`opencode models`).
- **P1 `arena mcp` server:** a long-lived Python stdio MCP server exposing the six worker tools through the same code
  path as `arena protocol`. It doubles as the persistent protocol server (E4): no Python start-up per tool call.
- **P2 isolated launcher + canary test (the gate):** plant canaries (a fake "best proof" file one directory up, a
  canary line in a global AGENTS.md and in a global skill, an earlier session in the default db). Start an isolated
  worker; ask it what instructions/files/tools it has and to read the canary file. Pass = no canary in any reply or
  tool call, built-in tools refused, only `arena_*` tools listed.
- **P3 backend adapter:** `worker_backend: pi | opencode` in run config; orchestration starts/steers/cancels workers
  through either. Orchestrator stays Pi (Sol) at first. Ledger: tokens from OpenCode events, priced from models.yaml
  (free models record $0 and their token counts).
- **P4 smoke (owner starts it):** Sol orchestrator + 2 OpenCode free-model workers on one theorem, from scratch.

## Notes
- Free models are for experiments only; the closed-track final still needs OpenRouter at list price.
- Same golden-session rule as Pi: no "ready" until a fake session drives every tool form end to end.
