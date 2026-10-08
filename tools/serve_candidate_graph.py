"""Serve static graph assets and live run data on loopback only.

One run: the candidate graph at `/` (dashboard at `/dashboard.html`). Several runs (more than one
ID, or `--match` with a glob over run IDs that is re-scanned on every request, so new runs appear
while a matrix starts them): a hub at `/` with a filterable run table; clicking a row opens its dashboard in a closable tab, each
showing that run's dashboard from `/run/<id>/dashboard.html` (graph at `/run/<id>/`).

Per-run data: graph.json, dashboard.json, langfuse.json. Langfuse is queried server-side with the
keys in ~/.pi/agent/langfuse.json (never sent to the browser) and cached; `--no-langfuse` disables it.

    uv run python tools/serve_candidate_graph.py --match 'v6*'
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # allow `python tools/serve_candidate_graph.py`
    sys.path.insert(0, str(ROOT))

from arena.campaign import graph_state, run_dir  # noqa: E402
from arena.viewer_data import Langfuse, campaign_of, hub_row, run_dashboard  # noqa: E402

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
    payload["baseline"] = baseline_point(payload)
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


def baseline_point(payload: dict) -> dict | None:
    """The original proof (node #1) as evaluation 0: published tokens and heartbeats, every version
    passing, so every score chart starts where the run started."""
    reference = next((node for node in payload.get("nodes", []) if node.get("origin") == "reference"), None)
    if not reference or not payload.get("theorem"):
        return None
    try:
        from arena.scoring import reference as published
        tokens, heartbeats = published(payload["theorem"])
    except (ValueError, ImportError, KeyError):
        return None
    return {"number": 0, "candidate_id": reference["id"], "mode": "reference", "status": "full",
            "tokens": tokens, "heartbeat": heartbeats, "local_proxy": round(100 / 3, 2), "is_reference": True}


VIEWER_FILES = {"": ("index.html", "text/html; charset=utf-8"),
                "index.html": ("index.html", "text/html; charset=utf-8"),
                "app.js": ("app.js", "text/javascript; charset=utf-8"),
                "highlight.js": ("highlight.js", "text/javascript; charset=utf-8"),
                "style.css": ("style.css", "text/css; charset=utf-8"),
                "dashboard.html": ("dashboard.html", "text/html; charset=utf-8"),
                "dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
                "charts.js": ("charts.js", "text/javascript; charset=utf-8"),
                "dashboard.css": ("dashboard.css", "text/css; charset=utf-8")}
HUB_FILES = {"": ("hub.html", "text/html; charset=utf-8"),
             "index.html": ("hub.html", "text/html; charset=utf-8"),
             "hub.js": ("hub.js", "text/javascript; charset=utf-8"),
             "hub.css": ("hub.css", "text/css; charset=utf-8")}


class Runs:
    """The runs a server shows: explicit IDs plus any run directory matching a glob."""

    def __init__(self, run_ids: list[str], pattern: str | None = None):
        self.explicit = list(dict.fromkeys(run_ids))
        self.pattern = pattern

    @property
    def hub(self) -> bool:
        return self.pattern is not None or len(self.explicit) != 1

    def ids(self) -> list[str]:
        found = list(self.explicit)
        if self.pattern:
            root = run_dir("x").parent
            for path in sorted(root.iterdir()) if root.is_dir() else []:
                if (fnmatch.fnmatchcase(path.name, self.pattern) and path.name not in found
                        and (path / "ledger.jsonl").exists()):
                    found.append(path.name)
        return found


def run_card(run_id: str, langfuse: Langfuse | None = None) -> dict:
    """One hub row per run: cheap status from files the run writes (see arena.viewer_data)."""
    directory = run_dir(run_id)
    row = hub_row(run_id, directory, campaign_of(run_id, directory.parent))
    row["langfuse_url"] = langfuse.session_url(run_id) if langfuse else None
    return row


def run_dashboard_start(run_id: str) -> float | None:
    from arena.viewer_data import _start_end
    return _start_end(run_dir(run_id))[0]


def handler_for(runs: Runs | str, langfuse: Langfuse | None = None):
    if isinstance(runs, str):
        runs = Runs([runs])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; frame-src 'self'; frame-ancestors 'self'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def viewer(self, run_id: str, rest: str) -> None:
            if rest == "graph.json":
                self.send(json.dumps(graph_payload(run_id), ensure_ascii=False).encode(),
                          "application/json; charset=utf-8")
            elif rest == "dashboard.json":
                self.send(json.dumps(run_dashboard(run_id, run_dir(run_id)), ensure_ascii=False).encode(),
                          "application/json; charset=utf-8")
            elif rest == "langfuse.json":
                started = run_dashboard_start(run_id)
                body = (langfuse.session(run_id, started, refresh="refresh=1" in self.path) if langfuse else
                        {"available": False, "error": "Langfuse is not configured for this server", "run_id": run_id})
                self.send(json.dumps(body, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            elif rest in VIEWER_FILES:
                filename, content_type = VIEWER_FILES[rest]
                self.send((ASSETS / filename).read_bytes(), content_type)
            else:
                self.send_error(404)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            try:
                if not runs.hub:
                    self.viewer(runs.ids()[0], path.lstrip("/"))
                    return
                if path == "/runs.json":
                    self.send(json.dumps([run_card(run_id, langfuse) for run_id in runs.ids()], ensure_ascii=False).encode(),
                              "application/json; charset=utf-8")
                    return
                match = re.fullmatch(r"/run/([A-Za-z0-9._-]+)(/(.*))?", path)
                if match:
                    if match[1] not in runs.ids():
                        self.send_error(404, "Unknown run")
                    elif match[2] is None:
                        # Relative asset URLs need the trailing slash.
                        self.send_response(301)
                        self.send_header("Location", f"/run/{match[1]}/")
                        self.end_headers()
                    else:
                        self.viewer(match[1], match[3])
                    return
                rest = path.lstrip("/")
                if rest in HUB_FILES:
                    filename, content_type = HUB_FILES[rest]
                    self.send((ASSETS / filename).read_bytes(), content_type)
                else:
                    self.send_error(404)
            except (BrokenPipeError, ConnectionResetError):
                # The browser closed the connection (refresh, tab closed); nothing is left to answer.
                return
            except (OSError, ValueError, KeyError) as error:
                try:
                    self.send_error(500, str(error))
                except (BrokenPipeError, ConnectionResetError):
                    return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_ids", nargs="*", help="One run (single viewer) or several (hub with tabs)")
    parser.add_argument("--match", help="Glob over run IDs, re-scanned live, e.g. 'v5-rep-20261006-r3-*'")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-langfuse", action="store_true", help="Never contact Langfuse")
    parser.add_argument("--langfuse-ttl", type=float, default=45.0, help="Seconds to cache Langfuse answers")
    args = parser.parse_args()
    if not args.run_ids and not args.match:
        parser.error("give at least one run ID or --match")
    runs = Runs(args.run_ids, args.match)
    langfuse = None if args.no_langfuse else Langfuse(ttl=args.langfuse_ttl)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(runs, langfuse))
    # Open browser connections must not keep the process alive after Ctrl+C.
    server.daemon_threads = True
    kind = "hub" if runs.hub else "viewer"
    print(f"Arena graph {kind}: http://127.0.0.1:{server.server_port}/ ({len(runs.ids())} run(s) now); "
          "press Ctrl+C to stop", flush=True)

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping the Arena graph server…", flush=True)
    finally:
        server.server_close()
        print("Stopped.", flush=True)


if __name__ == "__main__":
    main()
