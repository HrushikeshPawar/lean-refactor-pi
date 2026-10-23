# OpenCode v2 P0 verification (2026-10-23, opencode v2.0.24)

Scratch env: /tmp/claude-1000/-mnt-SharedDrive-ActiveProjects-lean-refactor-pi/208df1a4-b197-4fba-a806-efacf953b06d/scratchpad/oc-p0/ (env.sh sets HOME + XDG_*).
User's ~/.config/opencode, ~/.local/share/opencode and background service (port 49374) were not modified; service confirmed still listening at the end.

## Status summary
- Q1 free ids: verified (ids), login: PARTLY. Q2 config isolation: verified. Q4 deny-all + MCP-only agent: verified at config level (`debug agents`), NOT at model-call level.
- Q5 MCP shape: docs + `opencode mcp list` shows the mock server "connected". Q6 API/events: schema verified from OpenAPI, no live stream.
- Q3 context files and Q7 canary: UNVERIFIED. BLOCKER below.

## BLOCKER: the free model did not work from an isolated data dir
With moved XDG dirs and no credentials, `opencode run --standalone --model opencode/deepseek-v4.1-flash-free` returns
`provider.auth 403 FreeTierError: "OpenCode's free tier can only be used from within OpenCode"` (same text as Pi gets).
So the free tier needs an authenticated OpenCode Console account (the user has "OpenCode Console / Default" stored; isolated env shows "No authenticated integrations").
I imported only that credential into the isolated data dir with `opencode auth export "OpenCode Console" | auth import --standalone` (never printed). The first model run then hung with no output (300 s, nothing emitted) and I did not get to diagnose it: the auto-mode classifier blocked further credential-related commands (sqlite read of the user's db, then the retry run), so I stopped, deleted the exported file and did not retry. The hang could be the free tier, models fetch, a pending permission, or the MCP server; unknown.
Needs the owner's OK to retry with a copied credential (see Q2 for the mechanism). The 403 itself is evidence that credentials must travel into each isolated data dir.

## Q1 Models / login
- `opencode models | grep -iE 'deepseek|free'`: `opencode/deepseek-v4.1-flash-free` (target), also `opencode/mimo-v2.6-flash-free`, `opencode/glm-5.3-flash-free`, `opencode/flint-40b-free`, `opencode/nemotron-3-ultra-free`, `opencode/nemotron-3.5-lightning-free`, `opencode/nemotron-3.5-super-vl-free`, `opencode/beam-free`; paid: `opencode/deepseek-v4.1-flash`, `opencode/deepseek-v4-pro`, `opencode-go/deepseek-v4.1-flash`, `opencode-go/deepseek-v4-pro`, `opencode-go/beam-free`.
- Format: `--model provider/model[#variant]` (from `opencode run --help`): `opencode/deepseek-v4.1-flash-free`.
- Logged in (read-only `opencode auth list`): OpenCode Go (API key, stored), OpenCode Console (Default, stored). Isolated env lists none.
- Note: legacy `~/.local/share/opencode/auth.json` holds only an `opencode-go` key; v2 does not read it (isolated `auth list` stayed empty after copying it). The Console credential lives in v2's own store (not inspected; classifier denied db access).

## Q2 Config isolation
- `opencode debug paths` with `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME` set: config/data/db/state/cache/log all move under the temp dir. Verified output.
- `opencode debug config`: real env lists /home/hrushikesh/.config/opencode/opencode.jsonc; isolated env lists only the temp config dir (and my generated file once written). Skills/commands/node_modules in the real dir are not in the isolated listing; `debug agents` shows no user agents.
- Binary strings show more knobs (undocumented, UNVERIFIED semantics): `OPENCODE_CONFIG`, `OPENCODE_CONFIG_DIR`, `OPENCODE_CONFIG_CONTENT`, `OPENCODE_CONFIG_PROJECT_DISABLE`, `OPENCODE_DISABLE_PROJECT_CONFIG`, `OPENCODE_DB`, `OPENCODE_DISABLE_AUTOUPDATE`, `OPENCODE_DISABLE_MODELS_FETCH`, `OPENCODE_MODELS_PATH`.
- Gotchas: (a) `debug config|agents|paths` and non-`--standalone` commands go through the managed background service; in the isolated env they try to start their own service on the default port 49374 and fail ("port in use"). Fix: `opencode service set port <free>` in the isolated env (writes only isolated service.json); that starts a private managed service (I stopped it with `opencode service stop`). `debug` subcommands have no `--standalone` flag. `run`, `models`, `api`, `auth` do. (b) HOME must be moved too, or `~` expansions and some global paths still point at the real home.
- Credentials: the data dir holds them. Safe transfer: `opencode auth export "<name>" > f` (secrets!) then `opencode auth import --standalone f` under the isolated env, then delete f; or pipe directly. Env var `OPENCODE_API_KEY` exists in the binary (UNVERIFIED if it applies to the free tier; it is an API key, probably not the Console login).

## Q3 Context files: UNVERIFIED
- Docs (opencode.ai/v2/docs/config): AGENTS.md files are "discovered automatically"; `instructions` adds more; docs do not say how to disable. The /v2/docs/rules page is 404.
- Binary strings: the v2 read tool carries an "AGENTS.md" constant, suggesting instructions are attached when the read tool touches a directory; no strings for global discovery. Not tested because the model run failed. API `session.context` and `experimental.session.instructions.entry.list` return [] on a fresh session (before any prompt), so they cannot show loading without a model call.
- Mitigation if untested: cwd outside any repo AND outside any dir with AGENTS.md/CLAUDE.md in its ancestors (e.g. /tmp/arena-oc/<run>/cwd with no parent files); agent denies all built-in tools incl. `read`, so file-attached instructions cannot be triggered. Our canary (parent AGENTS.md "CANARY-PARENT-7731") is planted at oc-p0/work/parent/AGENTS.md, cwd oc-p0/work/parent/cwd, ready to run once Q7 is unblocked.

## Q4 Tools: deny all built-ins, allow only MCP
- v2 schema (docs): `agents.<id>.permissions` is an ordered list of `{action, resource, effect}`; effect allow|ask|deny; last matching rule wins; `tools` field is legacy. Action names: read, edit (covers edit/write/patch), glob, grep, shell (was bash), subagent (was task), skill, question, webfetch, websearch, external_directory, execute, opencode_list_mcp_resources, opencode_read_mcp_resource, and `<server>_<tool>` for MCP. No separate list/todo/patch action.
- Verified with `opencode debug agents`: agent `arena-worker` ends with rules `[... base allow *, ..., {*,*,deny}, {arena_*,*,allow}, {browser,*,deny}]`; last-match gives only `arena_*` allowed. Default agents disabled with `"agents": {"build": {"disabled": true}, ...}`: the listing then shows only `arena-worker` plus hidden compaction/summary/title. Caveat: those hidden agents keep a base `*` allow rule; they run only for compaction/titles, so also set `steps`/avoid long contexts, or add the same deny to them (agent ids can be overridden).
- NOT verified: that a denied tool is absent from the model's tool list (needs a model call). Note the base agent rule list begins with `{*,*,allow}`; our deny-all comes after, so it wins.

## Q5 MCP
- Config (docs + working `opencode mcp list` -> "arena connected"): `mcp.servers.<name> = {type:"local", command:[exe,args...], cwd, environment:{K:V}, timeout:{startup,catalog,execution ms}, disabled}`. `{env:NAME}` substitution in strings. No `args`/`env` fields.
- Tool names to the model/permissions: `<server>_<tool>` with non [A-Za-z0-9_-] -> `_`. Server `arena`, tools card/scratch -> `arena_card`, `arena_scratch`. Docs mention "Code Mode" grouping by default (`tools.arena.card(...)`); set top-level `codemode: false` to expose tools directly. UNVERIFIED whether the flag is top-level, and I did not set it in the test config.
- Per-worker env (ARENA_*): either generate one config per run (recommended) or pass env through the parent process: `environment` values are added to the inherited env, so the launcher can export ARENA_* before `opencode` and omit them from config.

## Q6 Driving sessions
- `opencode run` flags: `--format default|json`, `--model`, `--agent`, `--session/-s`, `--continue`, `--fork`, `--file`, `--title`, `--thinking`, `--auto`, `--standalone`, `--server`. JSON event types: not documented. Observed event: `{"type":"error","timestamp":...,"sessionID":...,"error":{"type":"provider.auth","message":...,"status":403,...}}` (so events are JSONL with type+sessionID+timestamp). Success events unseen.
- Server API (`opencode api --standalone GET /openapi.json`, OpenAPI exact paths): `POST /api/session` (create; body e.g. {"agent":"arena-worker"}; verified live, returns id/cost/tokens/location), `POST /api/session/{id}/prompt` body `{text, files, agents, skills, metadata, delivery: "steer"|"queue", resume}` (durable inbox; "steer" = inject into the running turn, "queue" = after), `GET /api/session/{id}/inbox`, `POST /api/session/{id}/interrupt` (abort; `resume` flag), `GET /api/session/{id}/message` (list), `GET /api/session/{id}/message/{mid}`, `GET /api/event` (SSE across the server, volatile: slow consumers drop), `GET /api/mcp`, `POST /api/session/{id}/model|agent`, `/fork`, `/compact`, `GET /api/session/{id}/context`. `opencode serve --hostname --port [--stdio]`; password is generated and printed at start (OPENCODE_SERVER_PASSWORD in binary). SDK package name: UNVERIFIED (docs page /v2/docs/server 404).
- Token/cost: session object has `cost` and `tokens {input,output,reasoning,cache{read,write}}`; each assistant message has `cost` (USD), `tokens` (same shape), `finish`, `model`, `time`. This is enough for the ledger (free models should report 0 cost).
- So prompt, steer, abort and usage all exist in the HTTP API. Not exercised against a live turn.

## Q7 Canary: NOT RUN (see blocker)
Only result: unauthenticated isolated run -> 403 FreeTierError (no model output, so no leak data). Authenticated run hung without output and was not retried.

## Ready-to-use isolated config and launch (config verified by `debug config/agents/mcp list`; model path unverified)
Config: oc-p0/xdg/config/opencode/opencode.jsonc (template; replace paths per run)
```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "update": "disable",
  "plugins": [],
  "default_agent": "arena-worker",
  "mcp": { "servers": { "arena": {
    "type": "local",
    "command": ["python3", "-I", "<repo>/arena_mcp.py"],
    "cwd": "<run-cwd>",
    "environment": { "ARENA_ACTOR_ID": "<id>", "ARENA_RUN_ID": "<id>" },
    "timeout": { "startup": 20000 } } } },
  "agents": {
    "build": {"disabled": true}, "plan": {"disabled": true},
    "general": {"disabled": true}, "explore": {"disabled": true},
    "arena-worker": {
      "mode": "primary", "description": "Isolated arena worker",
      "system": "<worker system prompt>",
      "permissions": [
        {"action": "*", "resource": "*", "effect": "deny"},
        {"action": "arena_*", "resource": "*", "effect": "allow"} ] } }
}
```
Launch (per worker; R = per-run root under /tmp, outside any repo):
```
export HOME=$R/home XDG_CONFIG_HOME=$R/xdg/config XDG_DATA_HOME=$R/xdg/data XDG_STATE_HOME=$R/xdg/state XDG_CACHE_HOME=$R/xdg/cache
# one-time per run: opencode auth import --standalone <exported console credential> (delete file after)
cd $R/cwd   # empty dir, no AGENTS.md/CLAUDE.md in ancestors
opencode run --standalone --format json --model opencode/deepseek-v4.1-flash-free --agent arena-worker "<prompt>"
```
For steer/abort use `opencode serve --port N` in the same env and the /api/session endpoints above.

## P0b (with credential, 2026-10-23)

Credential "OpenCode Console" was already imported in the isolated env (`auth list --standalone` shows it). Private service/serve processes started here were stopped by PID (HOME verified); owner's PID 1052805 untouched.

### 1. The hang and the 403s (root causes)
- The earlier 300 s silent hang was NOT a permission prompt or first-run setup. Two causes found:
  1. **Free-tier quota**: after ~40 tiny calls the account returned `provider.quota 429 FreeUsageLimitError "Free usage limit reached"`. In several runs the process produced no output at all until killed, so quota/boot stalls look like hangs. Always use `--format json --print-logs` to stderr files and `timeout`; read the error event. Intermittent boot stalls (log ends after "cli starting", before "location services booted") also occurred ~50% of the time on the full config, then passed on retry; cause not isolated (suspect watcher on / and /tmp). Use timeout 60 + one retry.
  2. **Free-tier fingerprint**: `opencode/deepseek-v4.1-flash-free` returns `403 FreeTierError "free tier can only be used from within OpenCode"` whenever the active agent DENIES the `read` tool entirely (a bare `{action:read,resource:*,effect:deny}` triggers it; deny of edit/shell/glob/webfetch/question/skill is fine; `read ask` and `read allow` are fine). A blanket `deny *` therefore 403s. Workaround that works: keep `read` advertised but fence it: `allow read *` + `deny external_directory *`.
- A tiny prompt ("pong") was answered under: plain config, MCP only, custom agent, builtins disabled, and the final config below.

### 2. Canary (cwd=work/parent/child empty; parent has AGENTS.md CANARY-PARENT-7731 and canary.txt)
- Neither CANARY-PARENT-7731 nor canary-file-content-5519 appeared anywhere in any output/event (grep over all jsonl = 0). The model's list of received instructions: system prompt, model block, date, env block (cwd, "not a git repo", platform, a /tmp/opencode note), a Code Mode/execute note, formatting rule. Parent AGENTS.md was NOT loaded in a non-git cwd.
- `read ../canary.txt` -> "Permission denied: external_directory" (also `read ..`). `read .` inside cwd works ("0 entries"); `./AGENTS.md` "File not found".
- Tool visibility: denied built-ins are HIDDEN from the model (it listed exactly one tool, `read`, and noted shell/glob/edit absent). Caveat: the system prompt text still mentions `execute`/`tools.opencode.session_move` and "use grep" even though absent (prompt leak of tool names, harmless).
- MCP: tools are exposed through **Code Mode**: with `execute` denied, the model did not see arena_card/arena_scratch at all. The server, via system message, advertises `tools.arena.card()` and `tools.arena.scratch({text})` as TypeScript signatures called through the `execute` tool. So `allow execute` is required. Top-level `codemode:false` did nothing visible (read-only tool list unchanged). NOT verified: that the model's MCP call works end to end, nor what `execute` (a JS sandbox) can reach (fs? network? `tools.opencode.*` built-ins such as session_move are reachable through it). BLOCKED by the 429 quota before the final run with execute allowed; that config (final-arena.jsonc below) is untested at model level.
- Second canary run (fresh git repo, AGENTS.md at git root, cwd in subfolder): NOT RUN (quota).

### 3. Driving via `opencode serve` (no model needed, verified live)
- Start: `cd <cwd>; opencode serve --hostname 127.0.0.1 --port N` (prints "server password ..."). Auth: HTTP Basic, any user, e.g. `curl -u opencode:$PW`. Working directory per request via header `x-opencode-directory: <dir>`.
- `POST /api/session {"agent":"arena-worker"}` -> id, cost 0, tokens{input,output,reasoning,cache{read,write}}, location.directory. Note: without a model set the session defaulted to `opencode/flint-40b-free`; set the model explicitly (`POST /api/session/{id}/model`, body not checked) for deepseek.
- `POST .../prompt {"text":..,"delivery":"queue"|"steer"}` returns the stored user message. `POST .../interrupt {}` -> `{"interrupted":true}`, session gets `outcome:"interrupted"`, the running assistant message `finish:"error", error.type:"aborted"`. `GET .../message` lists user/assistant/system/idle entries (assistant: model, content, finish, error; idle: outcome failed|interrupted). A steer message was injected while a turn was starting; the 429 turn ended with `outcome:"failed"`. Quota/provider errors are visible in assistant.error (type provider.quota / provider.auth).
- Usage fields: session.cost / session.tokens; in `run --format json` each `step-finish` part carries `cost` and `tokens` (e.g. input 799, output 396, reasoning 642, cost 0 for free). Streaming of tool and text parts in `run` JSON: part.type text|tool|step-start|step-finish; tool parts have state status error|completed, input, output.
- NOT verified (quota): steer actually changing a live generation; GET /api/event stream.

### Final isolated config and launch (final-arena.jsonc; paths from env.sh)
Config (~/.. XDG_CONFIG_HOME/opencode/opencode.jsonc), copy at /tmp/claude-1000/-mnt-SharedDrive-ActiveProjects-lean-refactor-pi/208df1a4-b197-4fba-a806-efacf953b06d/scratchpad/oc-p0/final-arena.jsonc:
```jsonc
{ "mcp": {"servers": {"arena": {"type":"local","command":["python3","-I","<mcp.py>"],"environment":{"ARENA_ACTOR_ID":"a1"},"timeout":{"startup":20000}}}},
  "default_agent": "arena-worker",
  "agents": { "build":{"disabled":true},"plan":{"disabled":true},"general":{"disabled":true},"explore":{"disabled":true},
    "arena-worker": {"mode":"primary","description":"Isolated arena worker","system":"<worker prompt>",
      "permissions":[ {"action":"*","resource":"*","effect":"deny"},
                      {"action":"read","resource":"*","effect":"allow"},          // required: free tier 403s if read is denied
                      {"action":"external_directory","resource":"*","effect":"deny"},
                      {"action":"execute","resource":"*","effect":"allow"},       // Code Mode gateway to tools.arena.*
                      {"action":"arena_*","resource":"*","effect":"allow"} ] } } }
```
Launch: `source env.sh; cd <empty cwd>; timeout 600 opencode run --standalone --auto --format json --model opencode/deepseek-v4.1-flash-free "<prompt>" > out.jsonl 2> err.log` (add `--print-logs --log-level debug` when diagnosing). Serve mode: as in section 3.
Open risks: read remains available (inside cwd) and Code Mode `execute` surface unaudited; re-run the canary with execute allowed after the free quota resets.
