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
    unresolved: dict[str, float] = {}
    costs = []
    journal = directory / "cost-ledger.jsonl"
    if journal.exists():
        for line in journal.read_text().splitlines():
            event = json.loads(line)
            if event.get("kind") == "reserve":
                unresolved[str(event["id"])] = float(event["usd"])
            elif event.get("kind") == "settle":
                unresolved.pop(str(event["id"]), None)
                charged += float(event["usd"])
            else:
                continue
            outstanding = sum(unresolved.values())
            costs.append({"spent_usd": charged, "outstanding_usd": outstanding,
                          "committed_usd": charged + outstanding,
                          "kind": event["kind"], "ts": event.get("ts")})
    payload["cost_timeline"] = costs
    payload["cost"] = {"spent_usd": charged, "unresolved_usd": sum(unresolved.values())}
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
