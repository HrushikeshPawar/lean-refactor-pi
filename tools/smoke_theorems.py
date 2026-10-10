"""Offline end-to-end smoke test per theorem: real Pi, real Lean and the Lean MCP server, scripted provider.

Costs nothing and uses no model. Per theorem it calls arena_declarations and arena_source, probes a batch
of complete drafts, evaluates and profiles the reference, and inspects its goal through Lean MCP.

    PYTHONPATH=. uv run --no-project python tools/smoke_theorems.py Core.InitsUpdatesComm CallElimCorrect.substOldPostSubset
"""

import json
import sys

from arena.campaign import problem, run_dir
from arena.engine import candidate_file, versions
from tests.pi_support import FakeRun, message_text


def tool(name, args):
    return {
        "tool_calls": [{"name": name, "arguments": args}],
        "usage": {"input": 300, "output": 40, "cacheRead": 4000, "cacheWrite": 100},
    }


ok = True
for name in sys.argv[1:]:
    row = problem(name)
    run = FakeRun([], timeout=1500)
    run.command = [item for item in run.command if item != "--no-mcp"]  # the real Lean MCP server
    run.command[run.command.index("--theorem") + 1] = name
    built = candidate_file(row, row["src"], *versions(row)[0])
    path = str(run_dir(run.run_id) / "scratch" / "project" / (row.get("file_path") or ""))
    calls = [
        ("arena_declarations", {"items": [name]}),
        ("arena_source", {"handle": f"decl:{name}"}),
        ("arena_probe", {"drafts": [row["src"] + "\n-- route smoke draft 1", row["src"] + "\n-- route smoke draft 2"]}),
        ("arena_evaluate", {"proof": row["src"]}),
        ("mcp__arena_lean__lean_goal", {"file_path": path, "line": built["start_line"] + 1}),
        ("arena_profile", {"proof": row["src"]}),
    ]
    run.script.write_text(json.dumps([tool(n, a) for n, a in calls] + [{"text": "done"}]))
    try:
        run.run()
        last = run.requests[-1]["messages"] if run.requests else []
        results = {m["toolName"]: m for m in last if m["role"] == "toolResult"}
        errors = {n: message_text(results[n])[:160] for n, _ in calls if n not in results or results[n].get("isError")}
        summary = run.json("summary.json")
        print(
            f"{'PASS' if not errors else 'FAIL'}  {name}  requests {len(run.requests)}  tool errors {summary['tools']['error_total']}  "
            f"evaluations {summary['evaluations']}  {errors if errors else ''}",
            flush=True,
        )
        ok &= not errors
    except Exception as error:
        print(f"FAIL  {name}  {error}  {run.result.stderr[-400:] if run.result else ''}", flush=True)
        ok = False
    finally:
        run.cleanup()
sys.exit(0 if ok else 1)
