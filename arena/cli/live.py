"""Live terminal progress for `arena run` and `arena campaign` (operator-facing only).

The view is on only when stdout is a terminal and neither `--plain` nor ARENA_PLAIN=1 asks for plain lines; piped,
captured or test output stays exactly the plain lines. Every figure comes from the Pi event stream or from files the
run already writes (run-config.json, cost-ledger.jsonl, ledger.jsonl): nothing here runs Lean or spends. Any error
while polling or rendering stops the view and the caller goes back to plain lines; the run itself never notices.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from rich.color import Color, blend_rgb
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.style import Style
from rich.table import Table
from rich.text import Text

PLAIN_ENV = "ARENA_PLAIN"
RECENT_EVENTS = 12
RECENT_NODES = 8
POLL_S = 1.0
REFRESH_S = 0.25
WIDE = 110  # at or above this console width panels sit side by side


def enabled(plain: bool = False, stream=None) -> bool:
    """True when the live view should replace plain lines."""
    if plain or os.environ.get(PLAIN_ENV, "").strip().lower() not in ("", "0", "false", "no"):
        return False
    stream = sys.stdout if stream is None else stream
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


# ---- run directory figures ---------------------------------------------------------------------------------------


class _Stamped:
    """A file's parsed contents, re-read only when its size or mtime changes."""

    def __init__(self, path: Path, load: Callable[[Path], object]):
        self.path, self.load = path, load
        self.key: tuple[int, int] | None = None
        self.value: object = None

    def get(self) -> object:
        try:
            stat = self.path.stat()
        except OSError:
            self.key, self.value = None, None
            return None
        key = (stat.st_mtime_ns, stat.st_size)
        if key != self.key:
            self.value, self.key = self.load(self.path), key
        return self.value


@dataclass
class NodeRow:
    id: str
    status: str
    origin: str
    score: float | None
    verified: bool
    tokens: int | None
    heartbeats: int | None
    parent: str | None


@dataclass
class RunFigures:
    theorem: str | None = None
    model: str | None = None
    limit_usd: float | None = None
    spent_usd: float = 0.0
    nodes: list[NodeRow] = field(default_factory=list)

    @property
    def reference(self) -> NodeRow | None:
        return next((node for node in self.nodes if node.origin == "reference"), self.nodes[0] if self.nodes else None)

    @property
    def best(self) -> NodeRow | None:
        """The best scored, compiling non-reference node; verified (full check) ranks first, as in `campaign._best`."""
        pool = [
            node
            for node in self.nodes
            if node.origin != "reference" and node.score is not None and node.status != "broken"
        ]
        if not pool:
            return None
        return max(pool, key=lambda node: (node.verified, node.score or 0.0))


def _settled_usd(path: Path) -> float:
    from arena.summary import _jsonl, ledger_spend

    return float(ledger_spend(_jsonl(path))["ledger_settled_usd"])


def _nodes(path: Path) -> list[NodeRow]:
    from arena.campaign import _proof_reader, events
    from arena.graph import Graph

    directory = path.parent
    graph = Graph.from_history(events(directory), _proof_reader(directory))
    ids = {node.proof_id: node.id for node in graph.nodes}
    rows = []
    for node in graph.nodes:
        parents = (node.edge or {}).get("from") or []
        rows.append(
            NodeRow(
                node.id,
                node.status,
                node.origin,
                node.score,
                node.verified,
                node.tokens,
                node.heartbeats,
                ids.get(parents[0], str(parents[0])[:8]) if parents else None,
            )
        )
    return rows


def _config(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class RunDirPoller:
    """Cheap, stamp-cached figures of one run directory."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.config = _Stamped(self.directory / "run-config.json", _config)
        self.spend = _Stamped(self.directory / "cost-ledger.jsonl", _settled_usd)
        self.ledger = _Stamped(self.directory / "ledger.jsonl", _nodes)

    def poll(self) -> RunFigures:
        from arena.summary import configured_cap

        config = self.config.get()
        config = config if isinstance(config, dict) else {}
        spent = self.spend.get()
        nodes = self.ledger.get()
        return RunFigures(
            config.get("theorem"),
            config.get("model"),
            configured_cap(config),
            float(spent) if isinstance(spent, (int, float)) else 0.0,
            list(nodes) if isinstance(nodes, list) else [],
        )


# ---- formatting helpers ------------------------------------------------------------------------------------------


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def _count(value: int | float | None) -> str:
    if value is None:
        return "-"
    value = float(value)
    for limit, suffix in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= limit:
            return f"{value / limit:.1f}{suffix}"
    return f"{value:.0f}"


def _score(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _signed(value: float) -> str:
    return f"{value:+.2f}"


GREEN, YELLOW, RED = (
    Color.parse("green").get_truecolor(),
    Color.parse("yellow").get_truecolor(),
    Color.parse("red").get_truecolor(),
)


def spend_colour(fraction: float) -> str:
    """Green at 0, yellow at half the limit, red at the limit."""
    fraction = min(1.0, max(0.0, fraction))
    rgb = blend_rgb(GREEN, YELLOW, fraction * 2) if fraction < 0.5 else blend_rgb(YELLOW, RED, (fraction - 0.5) * 2)
    return Color.from_triplet(rgb).name


def _status_text(node: NodeRow) -> Text:
    if node.origin == "reference":
        return Text("reference", style="cyan")
    if node.verified:
        return Text("verified", style="bold green")
    style = {"closed": "green", "sketch": "yellow", "broken": "red"}.get(node.status, "")
    return Text(node.status, style=style)


def _spend_bar(spent: float, limit: float | None, width: int | None = None) -> RenderableType:
    fraction = spent / limit if limit else 0.0
    colour = spend_colour(fraction)
    bar = ProgressBar(
        total=limit or 1.0,
        completed=min(spent, limit or 0.0),
        width=width,
        complete_style=Style(color=colour),
        finished_style=Style(color=colour),
    )
    label = Text(f"${spent:.4f} / " + (f"${limit:.2f}" if limit else "?") + f"  {fraction * 100:.1f}%", style=colour)
    grid = Table.grid(padding=(0, 1), expand=True)
    grid.add_column(ratio=1)
    grid.add_column(no_wrap=True, justify="right")
    grid.add_row(bar, label)
    return grid


# ---- the run view ------------------------------------------------------------------------------------------------


class RunView:
    """State of one `arena run`: Pi event counters, recent event lines and polled run-directory figures."""

    def __init__(
        self,
        run_id: str,
        directory: Path,
        theorem: str | None = None,
        model: str | None = None,
        limit_usd: float | None = None,
        lean: str = "off",
        merge_worker=None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.run_id, self.directory = run_id, Path(directory)
        self.clock, self.started = clock, clock()
        self.lean, self.merge_worker = lean, merge_worker
        self.poller = RunDirPoller(self.directory)
        self.figures = RunFigures(theorem, model, limit_usd)
        self.lines: deque[str] = deque(maxlen=RECENT_EVENTS)
        self.requests = self.tool_calls = self.retries = self.compactions = 0
        self.tokens_in = self.tokens_out = self.cache_read = 0
        self.tripped = False
        self.lock = threading.Lock()

    def on_event(self, event: dict) -> None:
        kind = event.get("type")
        with self.lock:
            if kind == "tool_execution_end":
                self.tool_calls += 1
            elif kind == "auto_retry_start":
                self.retries += 1
            elif kind == "compaction_start":
                self.compactions += 1
            elif kind == "message_end":
                message = event.get("message") or {}
                if message.get("role") != "assistant":
                    return
                usage = message.get("usage") or {}
                if usage.get("totalTokens") or message.get("errorMessage"):
                    self.requests += 1
                read = int(usage.get("cacheRead") or 0)
                self.cache_read += read
                self.tokens_in += int(usage.get("input") or 0) + read + int(usage.get("cacheWrite") or 0)
                self.tokens_out += int(usage.get("output") or 0)

    def add_line(self, line: str) -> None:
        with self.lock:
            self.lines.append(line)

    def poll(self) -> None:
        from arena import lean_health

        figures = self.poller.poll()
        tripped = lean_health.tripped(self.directory) is not None
        with self.lock:
            self.figures = RunFigures(
                figures.theorem or self.figures.theorem,
                figures.model or self.figures.model,
                figures.limit_usd or self.figures.limit_usd,
                figures.spent_usd,
                figures.nodes,
            )
            self.tripped = tripped

    # -- rendering

    def _merge_state(self) -> Text:
        worker = self.merge_worker
        if worker is None:
            return Text("off", style="dim")
        code = worker.poll()
        if code is None:
            return Text(f"pid {worker.pid} running", style="green")
        return Text(f"exited ({code})", style="red")

    def _header(self) -> RenderableType:
        figures = self.figures
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold")
        grid.add_column()
        grid.add_row("theorem", Text(figures.theorem or "?", style="bold cyan"))
        grid.add_row("model", Text(figures.model or "?", style="magenta"))
        grid.add_row("run", Text(self.run_id))
        grid.add_row("elapsed", Text(_clock(self.clock() - self.started)))
        lean = Text("breaker tripped", style="bold red") if self.tripped else Text(self.lean)
        grid.add_row("Lean", lean)
        grid.add_row("merge worker", self._merge_state())
        return Panel(grid, title="arena run", title_align="left", border_style="blue")

    def _spend(self) -> RenderableType:
        figures = self.figures
        cache_pct = 100 * self.cache_read / self.tokens_in if self.tokens_in else None
        counts = Text.assemble(
            ("requests ", "dim"),
            str(self.requests),
            ("  tool calls ", "dim"),
            str(self.tool_calls),
            ("  retries ", "dim"),
            (str(self.retries), "yellow" if self.retries else ""),
            ("  compactions ", "dim"),
            str(self.compactions),
        )
        tokens = Text.assemble(
            ("tokens in ", "dim"),
            _count(self.tokens_in),
            ("  out ", "dim"),
            _count(self.tokens_out),
            ("  cache-read ", "dim"),
            "-" if cache_pct is None else f"{cache_pct:.1f}%",
        )
        return Panel(
            Group(_spend_bar(figures.spent_usd, figures.limit_usd), counts, tokens),
            title="spend (settled)",
            title_align="left",
            border_style="green",
        )

    def _best(self) -> RenderableType:
        figures = self.figures
        best, reference = figures.best, figures.reference
        if best is None:
            body: RenderableType = Text("no scored node yet", style="dim")
        else:
            grid = Table.grid(padding=(0, 2))
            grid.add_column(style="bold")
            grid.add_column()
            score = Text(_score(best.score), style="bold green")
            if reference is not None and reference.score is not None and best.score is not None:
                delta = best.score - reference.score
                score.append(
                    f"  ({_signed(delta)} vs {reference.id})",
                    style="green" if delta > 0 else "red" if delta < 0 else "",
                )
            grid.add_row("node", Text(best.id, style="bold"))
            grid.add_row("score", score)
            grid.add_row("tokens", _count(best.tokens))
            grid.add_row("heartbeats", _count(best.heartbeats))
            grid.add_row("status", _status_text(best))
            body = grid
        return Panel(body, title="best node", title_align="left", border_style="yellow")

    def _nodes(self) -> RenderableType:
        table = Table(expand=True, box=None, pad_edge=False, show_edge=False)
        for name, justify in (
            ("node", "left"),
            ("status", "left"),
            ("score", "right"),
            ("tokens", "right"),
            ("HB", "right"),
            ("parent", "left"),
        ):
            table.add_column(name, justify=justify, no_wrap=True)
        best = self.figures.best
        recent = self.figures.nodes[-RECENT_NODES:]
        for node in recent:
            table.add_row(
                Text(node.id, style="bold" if best is not None and node.id == best.id else ""),
                _status_text(node),
                _score(node.score),
                _count(node.tokens),
                _count(node.heartbeats),
                node.parent or "-",
            )
        title = f"recent nodes ({len(recent)} of {len(self.figures.nodes)})"
        return Panel(table, title=title, title_align="left", border_style="cyan")

    def _events(self) -> RenderableType:
        lines = [Text(line, no_wrap=True, overflow="ellipsis") for line in self.lines]
        body: RenderableType = Group(*lines) if lines else Text("waiting for Pi", style="dim")
        return Panel(body, title="recent events", title_align="left", border_style="magenta")

    def render(self, width: int = 120) -> RenderableType:
        with self.lock:
            header, spend, best, nodes, events = (
                self._header(),
                self._spend(),
                self._best(),
                self._nodes(),
                self._events(),
            )
        if width < WIDE:
            return Group(header, spend, best, nodes, events)
        top = Table.grid(expand=True, padding=(0, 1))
        top.add_column(ratio=1)
        top.add_column(ratio=1)
        top.add_row(header, Group(spend, best))
        return Group(top, nodes, events)


# ---- Live driver -------------------------------------------------------------------------------------------------


class LiveDisplay:
    """Drives a `rich.live.Live` from a background thread. On any error it stops itself, prints one note to
    stderr, and `line`/`event` return False so the caller prints plain lines again."""

    def __init__(
        self,
        render: Callable[[int], RenderableType],
        poll: Callable[[], None] | None = None,
        console: Console | None = None,
        refresh_s: float = REFRESH_S,
        poll_s: float = POLL_S,
    ):
        self.render_fn, self.poll_fn = render, poll
        self.console = console or Console()
        self.refresh_s, self.poll_s = refresh_s, poll_s
        self.live: Live | None = None
        self.active = False
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> Self | None:
        try:
            self._poll()
            self.live = Live(
                self.render_fn(self.console.width),
                console=self.console,
                auto_refresh=False,
                redirect_stdout=True,
                redirect_stderr=True,
            )
            self.live.start(refresh=True)
        except Exception as error:
            self.active = True  # so `fail` gives the terminal back and says why
            self.fail(error)
            return None
        self.active = True
        self.thread = threading.Thread(target=self._loop, name="arena-live-view", daemon=True)
        self.thread.start()
        return self

    def _poll(self) -> None:
        if self.poll_fn is not None:
            self.poll_fn()

    def _loop(self) -> None:
        next_poll = time.monotonic() + self.poll_s
        while not self.stopping.wait(self.refresh_s):
            try:
                now = time.monotonic()
                if now >= next_poll:
                    self._poll()
                    took = time.monotonic() - now
                    next_poll = time.monotonic() + max(self.poll_s, 5 * took)  # a large ledger polls less often
                self.refresh()
            except Exception as error:
                self.fail(error)
                return

    def refresh(self) -> None:
        with self.lock:
            if self.active and self.live is not None:
                self.live.update(self.render_fn(self.console.width), refresh=True)

    def guard(self, action: Callable[[], None]) -> bool:
        """Run `action` against the view; False (and the view off) when it is inactive or fails."""
        with self.lock:
            if not self.active:
                return False
            try:
                action()
            except Exception as error:
                self.fail(error)
                return False
            return True

    def fail(self, error: BaseException) -> None:
        with self.lock:
            was_active = self.active
            self._shutdown()
        if was_active:
            print(f"live view stopped ({type(error).__name__}: {error}); plain output follows", file=sys.stderr)

    def _shutdown(self) -> None:
        self.active = False
        self.stopping.set()
        live, self.live = self.live, None
        if live is not None:
            with contextlib.suppress(Exception):
                live.stop()

    def stop(self) -> None:
        """Draw a last frame and give the terminal back."""
        self.stopping.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(2)
        with self.lock:
            if self.active:
                with contextlib.suppress(Exception):
                    self._poll()
                    self.refresh()
            self._shutdown()


class RunDisplay(LiveDisplay):
    """The live view of one `arena run`."""

    def __init__(self, view: RunView, console: Console | None = None, **kwargs):
        super().__init__(view.render, view.poll, console, **kwargs)
        self.view = view

    def line(self, text: str) -> bool:
        return self.guard(lambda: self.view.add_line(text))

    def event(self, event: dict) -> bool:
        return self.guard(lambda: self.view.on_event(event))


def start_run(
    run_id: str,
    directory: Path,
    *,
    plain: bool = False,
    theorem: str | None = None,
    model: str | None = None,
    limit_usd: float | None = None,
    lean: str = "off",
    merge_worker=None,
    console: Console | None = None,
) -> RunDisplay | None:
    """A started live view for this run, or None when output must stay plain."""
    if console is None and not enabled(plain):
        return None
    try:
        view = RunView(run_id, directory, theorem, model, limit_usd, lean, merge_worker)
        display = RunDisplay(view, console)
    except Exception:
        return None
    return display.start()


# ---- campaign view -----------------------------------------------------------------------------------------------


@dataclass
class CampaignRun:
    spec: dict
    status: str = "queued"
    started: float | None = None
    ended: float | None = None
    exit_code: int | None = None
    figures: RunFigures = field(default_factory=RunFigures)
    poller: RunDirPoller | None = None


class CampaignView:
    """Rows x models x replicates of one campaign, each run's figures polled from its directory."""

    def __init__(self, prefix: str, specs: list[dict], runs_root: Path, limit_usd: float, clock=time.monotonic):
        self.prefix, self.limit_usd, self.clock = prefix, limit_usd, clock
        self.started = clock()
        self.runs = [CampaignRun(spec, poller=RunDirPoller(Path(runs_root) / spec["run_id"])) for spec in specs]
        self.by_id = {run.spec["run_id"]: run for run in self.runs}
        self.lock = threading.Lock()

    def run_started(self, spec: dict) -> None:
        with self.lock:
            run = self.by_id[spec["run_id"]]
            run.status, run.started = "running", self.clock()

    def run_finished(self, spec: dict, exit_code: int | None) -> None:
        run = self.by_id[spec["run_id"]]
        self._poll_one(run)
        with self.lock:
            run.status = "done" if exit_code == 0 else "failed"
            run.exit_code, run.ended = exit_code, self.clock()

    def _poll_one(self, run: CampaignRun) -> None:
        if run.poller is None:
            return
        figures = run.poller.poll()
        with self.lock:
            run.figures = figures

    def poll(self) -> None:
        for run in self.runs:
            if run.status == "running":
                self._poll_one(run)

    def _elapsed(self, run: CampaignRun) -> str:
        if run.started is None:
            return "-"
        return _clock((run.ended if run.ended is not None else self.clock()) - run.started)

    def render(self, width: int = 120) -> RenderableType:
        with self.lock:
            table = Table(expand=True, box=None, pad_edge=False, show_edge=False)
            for name, justify in (
                ("theorem", "left"),
                ("model", "left"),
                ("r", "right"),
                ("status", "left"),
                ("spend", "right"),
                ("best", "right"),
                ("nodes", "right"),
                ("elapsed", "right"),
            ):
                table.add_column(name, justify=justify, no_wrap=name != "theorem", overflow="ellipsis")
            styles = {"queued": "dim", "running": "bold yellow", "done": "green", "failed": "bold red"}
            for run in self.runs:
                best = run.figures.best
                status = run.status if run.exit_code in (None, 0) else f"{run.status} ({run.exit_code})"
                table.add_row(
                    run.spec["row"],
                    run.spec["model"],
                    str(run.spec.get("replicate", "")),
                    Text(status, style=styles.get(run.status, "")),
                    "-" if run.started is None else f"${run.figures.spent_usd:.4f}",
                    "-" if best is None else f"{best.id} {_score(best.score)}",
                    str(len(run.figures.nodes)) if run.started is not None else "-",
                    self._elapsed(run),
                )
            done = sum(run.status in ("done", "failed") for run in self.runs)
            spent = sum(run.figures.spent_usd for run in self.runs)
            planned = self.limit_usd * len(self.runs)
            title = (
                f"campaign {self.prefix}: {done}/{len(self.runs)} finished, "
                f"${spent:.4f} of ${planned:.2f} planned, {_clock(self.clock() - self.started)}"
            )
            active = []
            for run in self.runs:
                if run.status != "running":
                    continue
                best = run.figures.best
                limit = run.figures.limit_usd or self.limit_usd
                active.append(
                    Text.assemble(
                        ("> ", "bold yellow"),
                        (run.spec["run_id"], "bold"),
                        f"  ${run.figures.spent_usd:.4f}/${limit:.2f}",
                        f"  {len(run.figures.nodes)} nodes",
                        f"  best {best.id} {_score(best.score)}" if best else "  no scored node yet",
                        f"  {self._elapsed(run)}",
                        no_wrap=True,
                        overflow="ellipsis",
                    )
                )
            parts: list[RenderableType] = [Panel(table, title=title, title_align="left", border_style="blue")]
            if active:
                parts.append(Panel(Group(*active), title="active", title_align="left", border_style="yellow"))
            return Group(*parts)


class CampaignDisplay(LiveDisplay):
    def __init__(self, view: CampaignView, console: Console | None = None, **kwargs):
        super().__init__(view.render, view.poll, console, **kwargs)
        self.view = view

    def run_started(self, spec: dict) -> None:
        self.guard(lambda: self.view.run_started(spec))

    def run_finished(self, spec: dict, exit_code: int | None) -> None:
        self.guard(lambda: self.view.run_finished(spec, exit_code))


def start_campaign(
    prefix: str,
    specs: list[dict],
    runs_root: Path,
    limit_usd: float,
    *,
    plain: bool = False,
    console: Console | None = None,
) -> CampaignDisplay | None:
    """A started campaign board, or None when output must stay plain."""
    if console is None and not enabled(plain):
        return None
    try:
        display = CampaignDisplay(CampaignView(prefix, specs, runs_root, limit_usd), console)
    except Exception:
        return None
    return display.start()
