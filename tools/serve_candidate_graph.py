"""Serve static graph assets and live run data on loopback only.

One run: the viewer at `/`. Several runs (more than one ID, or `--match` with a glob over run
IDs that is re-scanned on every request, so new runs appear while a matrix starts them): a hub
at `/` with one tab per run, each tab showing that run's viewer from `/run/<id>/`.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
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
                "style.css": ("style.css", "text/css; charset=utf-8")}
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


def run_card(run_id: str) -> dict:
    """Cheap per-run status for the hub's tabs and overview; read from files the run writes."""
    directory = run_dir(run_id)

    def read(name: str) -> dict:
        try:
            return json.loads((directory / name).read_text())
        except (OSError, ValueError):
            return {}
    config, state, summary, answer = (read("run-config.json"), read("state.json"),
                                      read("summary.json"), read("submission.json"))
    spent, requests = 0.0, 0
    journal = directory / "cost-ledger.jsonl"
    if journal.exists():
        for line in journal.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("kind") == "settle" and event.get("usage_known") is not False:
                spent += float(event.get("usd") or 0)
                requests += 1
    best = state.get("best") or {}
    reference = None
    if config.get("theorem"):
        try:
            from arena.scoring import reference as published
            tokens, heartbeats = published(config["theorem"])
            reference = {"tokens": tokens, "heartbeats": heartbeats, "proxy": round(100 / 3, 2)}
        except (ValueError, ImportError, KeyError):
            reference = None
    return {"run_id": run_id, "model": config.get("model"), "theorem": config.get("theorem"),
            "reference": reference,
            "thinking": config.get("thinking"), "cap_usd": config.get("hard_cap_usd"),
            "spent_usd": round(spent, 6), "requests": requests,
            "best": {"candidate": best.get("candidate"), "proxy": best.get("proxy"),
                     "tokens": best.get("tokens"), "heartbeats": best.get("heartbeats")} if best else None,
            "leading_unverified": state.get("leading_unverified"), "checking": state.get("checking", []),
            "finished": bool(summary), "stop_reason": summary.get("stop_reason"),
            "submission": answer.get("candidate")}


def handler_for(runs: Runs | str):
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
                    self.send(json.dumps([run_card(run_id) for run_id in runs.ids()], ensure_ascii=False).encode(),
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
            except (OSError, ValueError, KeyError) as error:
                self.send_error(500, str(error))

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_ids", nargs="*", help="One run (single viewer) or several (hub with tabs)")
    parser.add_argument("--match", help="Glob over run IDs, re-scanned live, e.g. 'v5-rep-20261006-r3-*'")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not args.run_ids and not args.match:
        parser.error("give at least one run ID or --match")
    runs = Runs(args.run_ids, args.match)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(runs))
    kind = "hub" if runs.hub else "viewer"
    print(f"Arena graph {kind}: http://127.0.0.1:{server.server_port}/ ({len(runs.ids())} run(s) now)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
