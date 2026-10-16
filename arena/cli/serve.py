"""Serve static graph assets and live run data on loopback only.

One run: the candidate graph at `/` (dashboard at `/dashboard.html`). Several runs (more than one
ID, or `--match` with a glob over run IDs that is re-scanned on every request, so new runs appear
while a matrix starts them): a hub at `/` with a filterable run table; clicking a row opens its dashboard in a closable tab, each
showing that run's dashboard from `/run/<id>/dashboard.html` (graph at `/run/<id>/`).

Per-run data: graph.json, dashboard.json, langfuse.json. Langfuse is queried server-side with the
keys in ~/.pi/agent/langfuse.json (never sent to the browser) and cached; `--no-langfuse` disables it.

    uv run arena serve --match 'v6*'
"""

from __future__ import annotations

import fnmatch
import json
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from arena.campaign import graph_state, run_dir
from arena.summary import configured_cap
from arena.viewer_data import Langfuse, campaign_of, hub_row, node_calls, read_jsonl, run_dashboard

ASSETS = Path(__file__).resolve().parents[1] / "graph_viewer"


def _clip(text, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def slim_probes(payload: dict, history: list[dict]) -> list[dict]:
    """Probes for the graph: one small row each (no diagnostics dump), with the harness route the
    ledger assigned to the probe's proof and a pass / skeleton / fail verdict.

    `skeleton` is a probe that compiles but still contains `sorry`: a valid proof skeleton whose
    holes are the next goals. A probe whose proof id later became a candidate is left to the node."""
    nodes = {node["id"] for node in payload.get("nodes", [])}
    routes = {e["proof_id"]: e.get("route") for e in history if e.get("kind") == "route" and e.get("proof_id")}
    rows = []
    for probe in payload.get("probes") or []:
        identifier = probe.get("proof_id")
        if not identifier or identifier in nodes:
            continue
        result = probe.get("result") or {}
        compat = result.get("compat") or {}
        first = next(iter(compat.values()), {}) if compat else {}
        diagnostics = first.get("diagnostics") or []
        sorry = any("sorry" in str(d.get("message", "")) for d in diagnostics if isinstance(d, dict))
        passed = bool(compat) and all(v.get("passed") for v in compat.values())
        goals = first.get("goals") or []
        counts = first.get("diagnostic_counts")
        headlines = first.get("error_headlines") or [
            d.get("message") for d in diagnostics if isinstance(d, dict) and d.get("severity") == "error"
        ]
        rows.append(
            {
                "proof_id": identifier,
                "parent": probe.get("parent"),
                "ts": probe.get("ts"),
                "route": routes.get(identifier),
                "status": "skeleton" if passed and sorry else "pass" if passed else "fail",
                "tokens": result.get("tokens"),
                "heartbeat": first.get("heartbeats"),
                "goals": len(goals),
                "first_goal": _clip(goals[0].get("goals") if goals and isinstance(goals[0], dict) else "", 600),
                "errors": counts.get("errors") if isinstance(counts, dict) else None,
                "headlines": [_clip(h, 220) for h in headlines[:3]],
                "result": {
                    "tokens": result.get("tokens"),
                    "compat": {v: {"passed": bool(r.get("passed"))} for v, r in compat.items()},
                },
            }
        )
    return rows


# A live run's ledger changes every few seconds, so file stamps never let a cache hit, and rebuilding a large graph
# takes seconds (v7-check4 Binius: graph 5.8 s, dashboard 4.8 s, polled by every open tab). Each run's payloads are
# rebuilt at most once per MEMO_SECONDS; concurrent requests for the same payload wait for one build.
MEMO_SECONDS = 10.0
_MEMO: dict[tuple[str, str], tuple[float, bytes]] = {}
_MEMO_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_MEMO_GUARD = threading.Lock()


def memo_json(kind: str, run_id: str, build) -> bytes:
    key = (kind, run_id)
    with _MEMO_GUARD:
        lock = _MEMO_LOCKS.setdefault(key, threading.Lock())
    with lock:
        hit = _MEMO.get(key)
        if hit and time.monotonic() - hit[0] < MEMO_SECONDS:
            return hit[1]
        body = json.dumps(build(), ensure_ascii=False).encode()
        _MEMO[key] = (time.monotonic(), body)
        return body


def graph_payload(run_id: str) -> dict:
    payload = graph_state(run_id)
    directory = run_dir(run_id)
    payload["probes"] = slim_probes(payload, read_jsonl(directory / "ledger.jsonl"))
    status = directory / "merge-worker.json"
    payload["worker"] = json.loads(status.read_text()) if status.exists() else None
    charged = 0.0
    pi_embedded = 0.0
    parts = {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0}
    names = {"input": "input", "output": "output", "cacheRead": "cache_read", "cacheWrite": "cache_write"}
    costs = []
    journal = directory / "cost-ledger.jsonl"
    if journal.exists():
        for line in journal.read_text().splitlines():
            event = json.loads(line)
            if event.get("kind") != "settle" or event.get("usage_known") is False:
                continue
            usd = float(event["usd"])
            charged += usd
            pi_embedded += float(event.get("pi_embedded_cost_usd") or 0)
            for key, value in (event.get("ledger_components_usd") or {}).items():
                if key in names:
                    parts[names[key]] += float(value)
            tokens = event.get("tokens") or {}
            # Cache hit rate: cache_read over every prompt token (input + cache_read + cache_write).
            prompt = tokens.get("input", 0) + tokens.get("cache_read", 0) + tokens.get("cache_write", 0)
            ts = event.get("ts")
            costs.append(
                {
                    "number": len(costs) + 1,
                    "spent_usd": charged,
                    "request_usd": usd,
                    "parts": dict(parts),
                    "tokens": tokens,
                    "reuse_pct": 100 * tokens.get("cache_read", 0) / prompt if prompt else None,
                    # The cost journal stamps milliseconds; the candidate ledger uses seconds.
                    "ts": ts / 1000 if ts and ts > 1e11 else ts,
                }
            )
    payload["cost_timeline"] = costs
    payload["cost"] = {"spent_usd": charged, "pi_embedded_usd": pi_embedded}
    payload["baseline"] = baseline_point(payload)
    give_reference_its_numbers(payload)
    config = directory / "run-config.json"
    payload["limit_usd"] = configured_cap(json.loads(config.read_text())) if config.exists() else None
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
            "usd": embedded_total,
            "priced_entries": priced_entries,
            "missing_entries": missing_entries,
        }
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
    return {
        "number": 0,
        "candidate_id": reference["id"],
        "mode": "reference",
        "status": "full",
        "tokens": tokens,
        "heartbeat": heartbeats,
        "local_proxy": round(100 / 3, 2),
        "is_reference": True,
    }


def give_reference_its_numbers(payload: dict) -> None:
    """Node #1 (the original proof) is never evaluated by the model; show its published tokens and
    heartbeats and the 33.33 baseline instead of "unevaluated"."""
    point = payload.get("baseline")
    node = next((n for n in payload.get("nodes", []) if n.get("origin") == "reference"), None)
    if not point or not node or node.get("tokens") is not None:
        return
    node.update(
        {
            "status": "full",
            "tokens": point["tokens"],
            "heartbeat": point["heartbeat"],
            "local_proxy": point["local_proxy"],
        }
    )


VIEWER_FILES = {
    "": ("index.html", "text/html; charset=utf-8"),
    "index.html": ("index.html", "text/html; charset=utf-8"),
    "app.js": ("app.js", "text/javascript; charset=utf-8"),
    "highlight.js": ("highlight.js", "text/javascript; charset=utf-8"),
    "style.css": ("style.css", "text/css; charset=utf-8"),
    "dashboard.html": ("dashboard.html", "text/html; charset=utf-8"),
    "dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
    "charts.js": ("charts.js", "text/javascript; charset=utf-8"),
    "dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
}
HUB_FILES = {
    "": ("hub.html", "text/html; charset=utf-8"),
    "index.html": ("hub.html", "text/html; charset=utf-8"),
    "hub.js": ("hub.js", "text/javascript; charset=utf-8"),
    "hub.css": ("hub.css", "text/css; charset=utf-8"),
}


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
                if (
                    fnmatch.fnmatchcase(path.name, self.pattern)
                    and path.name not in found
                    and (path / "ledger.jsonl").exists()
                ):
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


def assets_version() -> str:
    """Changes whenever a viewer asset is edited, so an already-open page can notice it runs stale code."""
    return str(max((f.stat().st_mtime_ns for f in ASSETS.iterdir() if f.is_file()), default=0))


def handler_for(runs: Runs | str, langfuse: Langfuse | None = None):
    if isinstance(runs, str):
        runs = Runs([runs])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Assets-Version", assets_version())
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; frame-src 'self'; frame-ancestors 'self'",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def viewer(self, run_id: str, rest: str) -> None:
            node_match = re.fullmatch(r"node/([A-Za-z0-9._-]+)\.json", rest)
            if rest == "graph.json":
                self.send(memo_json("graph", run_id, lambda: graph_payload(run_id)), "application/json; charset=utf-8")
            elif rest == "dashboard.json":
                self.send(
                    memo_json("dashboard", run_id, lambda: run_dashboard(run_id, run_dir(run_id))),
                    "application/json; charset=utf-8",
                )
            elif rest == "langfuse.json":
                started = run_dashboard_start(run_id)
                body = (
                    langfuse.session(run_id, started, refresh="refresh=1" in self.path)
                    if langfuse
                    else {"available": False, "error": "Langfuse is not configured for this server", "run_id": run_id}
                )
                self.send(json.dumps(body, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            elif rest in VIEWER_FILES:
                filename, content_type = VIEWER_FILES[rest]
                self.send((ASSETS / filename).read_bytes(), content_type)
            elif node_match:
                node_id = node_match.group(1)
                if ".." in node_id:
                    self.send_error(404)
                else:
                    body = node_calls(run_dir(run_id), node_id)
                    self.send(json.dumps(body, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            else:
                self.send_error(404)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            try:
                if not runs.hub:
                    self.viewer(runs.ids()[0], path.lstrip("/"))
                    return
                if path == "/runs.json":
                    self.send(
                        json.dumps([run_card(run_id, langfuse) for run_id in runs.ids()], ensure_ascii=False).encode(),
                        "application/json; charset=utf-8",
                    )
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


def execute(
    run_ids: list[str],
    match: str | None = None,
    port: int = 8765,
    no_langfuse: bool = False,
    langfuse_ttl: float = 45.0,
) -> int:
    if not run_ids and not match:
        print("error: give at least one run ID or --match", file=sys.stderr)
        return 2
    runs = Runs(run_ids, match)
    langfuse = None if no_langfuse else Langfuse(ttl=langfuse_ttl)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(runs, langfuse))
    # Open browser connections must not keep the process alive after Ctrl+C.
    server.daemon_threads = True
    kind = "hub" if runs.hub else "viewer"
    print(
        f"Arena graph {kind}: http://127.0.0.1:{server.server_port}/ ({len(runs.ids())} run(s) now); "
        "press Ctrl+C to stop",
        flush=True,
    )

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

    return 0
