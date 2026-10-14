"""Run an offline end-to-end smoke check for one or more theorem rows."""

from __future__ import annotations

import json
import sys


def execute(rows: list[str]) -> int:
    try:
        from arena.campaign import problem
        from tests.pi_support import FakeRun
    except ImportError:
        print("arena smoke needs a source checkout (tests/pi_support.py)", file=sys.stderr)
        return 2

    def tool(name, args, output=40):
        return {
            "tool_calls": [{"name": name, "arguments": args}],
            "usage": {"input": 300, "output": output, "cacheRead": 4000, "cacheWrite": 100},
        }

    ok = True
    for name in rows:
        row = problem(name)
        run = FakeRun([], timeout=1500)
        run.command[run.command.index("--theorem") + 1] = name
        calls = [
            ("compile", {"drafts": [row["src"]], "check": "lean"}),
            ("goal", {"node": "n1", "line": 1}),
            ("search", {"queries": [name], "kind": "name"}),
            ("read", {"node": "n1"}),
            ("read", {"node": "n1", "view": "prices"}),
            ("finish", {}),
        ]
        steps = [tool(n, args, 150_000 if n == "read" and args.get("view") == "prices" else 40) for n, args in calls]
        run.script.write_text(json.dumps(steps))
        try:
            run.run()
            summary = run.json("summary.json")
            errors = summary["tools"]["errors"]
            missing = {n for n, _ in calls} - set(summary["tools"]["calls"])
            failed = {**errors, **dict.fromkeys(missing, "not called")}
            print(
                f"{'PASS' if not failed else 'FAIL'}  {name}  requests {len(run.requests)}  "
                f"tool errors {summary['tools']['error_total']}  evaluations {summary['evaluations']}  "
                f"{failed if failed else ''}",
                flush=True,
            )
            ok &= not failed and summary["stop_reason"] == "finished"
        except Exception as error:
            print(f"FAIL  {name}  {error}  {run.result.stderr[-400:] if run.result else ''}", flush=True)
            ok = False
        finally:
            run.cleanup()
    return 0 if ok else 1
