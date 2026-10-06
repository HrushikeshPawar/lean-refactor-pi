"""Serve static graph assets and live run data on loopback only."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from arena.campaign import graph_state, run_dir

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "tools" / "graph_viewer"


def graph_payload(run_id: str) -> dict:
    payload = graph_state(run_id)
    directory = run_dir(run_id)
    status = directory / "merge-worker.json"
    payload["worker"] = json.loads(status.read_text()) if status.exists() else None
    charged = 0.0
    pi_embedded = 0.0
    unresolved: dict[str, float] = {}
    parts = {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0}
    names = {"input": "input", "output": "output", "cacheRead": "cache_read", "cacheWrite": "cache_write"}
    costs = []
    journal = directory / "cost-ledger.jsonl"
    if journal.exists():
        for line in journal.read_text().splitlines():
            event = json.loads(line)
            if event.get("kind") == "reserve":
                unresolved[str(event["id"])] = float(event["usd"])
            elif event.get("kind") in ("settle", "release"):
                unresolved.pop(str(event["id"]), None)
            if event.get("kind") != "settle" or event.get("usage_known") is False:
                continue
            usd = float(event["usd"])
            charged += usd
            pi_embedded += float(event.get("pi_embedded_cost_usd") or 0)
            for key, value in (event.get("ledger_components_usd") or {}).items():
                if key in names:
                    parts[names[key]] += float(value)
            tokens = event.get("tokens") or {}
            cached = tokens.get("cache_read", 0) + tokens.get("cache_write", 0)
            ts = event.get("ts")
            costs.append({"number": len(costs) + 1, "spent_usd": charged, "request_usd": usd,
                          "parts": dict(parts), "tokens": tokens,
                          "reuse_pct": 100 * tokens.get("cache_read", 0) / cached if cached else None,
                          # The cost journal stamps milliseconds; the candidate ledger uses seconds.
                          "ts": ts / 1000 if ts and ts > 1e11 else ts})
    payload["cost_timeline"] = costs
    payload["cost"] = {"spent_usd": charged, "unresolved_usd": sum(unresolved.values()),
                       "pi_embedded_usd": pi_embedded}
    config = directory / "run-config.json"
    payload["hard_cap_usd"] = json.loads(config.read_text()).get("hard_cap_usd") if config.exists() else None
    report = directory / "cost.json"
    payload["cost_report"] = json.loads(report.read_text()) if report.exists() else {}
    if "pi_embedded_estimate" not in payload["cost_report"]:
        embedded_total = 0.0
        priced_entries = 0
        missing_entries = 0
        for session_file in (directory / "session").glob("*.jsonl"):
            for line in session_file.read_text().splitlines():
                entry = json.loads(line)
                usage = (entry.get("message") or {}).get("usage") or entry.get("usage") or {}
                if not usage.get("totalTokens"):
                    continue
                cost = (usage.get("cost") or {}).get("total")
                if isinstance(cost, (int, float)):
                    embedded_total += cost
                    priced_entries += 1
                else:
                    missing_entries += 1
        payload["cost_report"]["pi_embedded_estimate"] = {
            "usd": embedded_total, "priced_entries": priced_entries,
            "missing_entries": missing_entries}
    return payload


def handler_for(run_id: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/index.html": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
            try:
                if path == "/graph.json":
                    body = json.dumps(graph_payload(run_id), ensure_ascii=False).encode()
                    content_type = "application/json; charset=utf-8"
                elif path in files:
                    filename, content_type = files[path]
                    body = (ASSETS / filename).read_bytes()
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ValueError, KeyError) as error:
                self.send_error(500, str(error))

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(args.run_id))
    print(f"Arena graph: http://127.0.0.1:{server.server_port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
