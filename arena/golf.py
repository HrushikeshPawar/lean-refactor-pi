"""Mechanical golf: one bounded greedy pass of single deletions and small rewrites over a verified proof.

Lean only, one check at a time. It runs after the model has stopped (never beside it) and feeds the submission;
nothing it does is sent to a model.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from arena import campaign, engine, lean_health
from arena.prices import snippet_tokens

EPSILON = 0.005  # a variant must beat the current proxy by more than this
MAX_FULL_CHECKS = 3  # accepted proofs full-checked, newest first, until one passes every toolchain
MAX_FAILURES_IN_A_ROW = 4  # Lean answering nothing this many times ends the pass

DELETIONS = ("list", "line", "segment")
_OPEN, _CLOSE = "([{⟨", ")]}⟩"
_SEPARATORS = (" <;> ", "; ")
_INTRO_CLEAR = re.compile(r"\bintro (\w+)(?:; |\n[ \t]*)clear \1\b")
_RINTRO_PAIR = re.compile(r"\brintro ((?:-|\w+)(?: (?:-|\w+))*)(?:; |\n[ \t]*)rintro ")


@dataclass(frozen=True)
class Variant:
    kind: str  # "list", "line", "segment" (pure deletions) or "rewrite"
    text: str
    note: str


@dataclass
class Outcome:
    proof: str
    start_score: float | None = None
    score: float | None = None
    tried: int = 0
    accepted: list[tuple[str, float, Variant]] = field(default_factory=list)
    seconds: float = 0.0
    timed_out: bool = False
    reason: str | None = None


def body_start(proof: str, statement: str) -> int:
    """Where the proof body (after the statement's `:=`) begins; the statement itself is never edited."""
    if not proof.startswith(statement):
        return 0
    found = re.match(r"\s*:=", proof[len(statement) :])
    return len(statement) + (found.end() if found else 0)


def body_tokens(proof: str, start: int) -> int:
    """Pinned token count of the body, offline."""
    return snippet_tokens(proof[start:].lstrip())


def _top_level_parts(inner: str) -> list[str]:
    parts, depth, begin = [], 0, 0
    for index, char in enumerate(inner):
        if char in _OPEN:
            depth += 1
        elif char in _CLOSE:
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(inner[begin:index])
            begin = index + 1
    parts.append(inner[begin:])
    return parts


def _list_variants(proof: str, start: int) -> list[Variant]:
    found = []
    for match in re.finditer(r"\[", proof[start:]):
        opening, depth = start + match.start(), 0
        closing = None
        for index in range(opening, len(proof)):
            if proof[index] in _OPEN:
                depth += 1
            elif proof[index] in _CLOSE:
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is None or proof[closing] != "]":
            continue
        inner = proof[opening + 1 : closing]
        parts = _top_level_parts(inner)
        if len(parts) < 2:
            continue
        for number, part in enumerate(parts):
            rest = parts[:number] + parts[number + 1 :]
            if number == 0:  # the new first item takes the deleted one's leading whitespace
                lead = part[: len(part) - len(part.lstrip())]
                rest[0] = lead + rest[0].lstrip()
            found.append(
                Variant("list", proof[: opening + 1] + ",".join(rest) + proof[closing:], f"list item {part.strip()}")
            )
    return found


def _line_spans(proof: str, start: int) -> list[tuple[int, int, str]]:
    """(begin, end, text) of each line after the one holding `start`, `end` past the newline."""
    spans, position = [], 0
    for line in proof.split("\n"):
        end = position + len(line) + 1
        if position > start and line.strip():
            spans.append((position, min(end, len(proof)), line))
        position = end
    return spans


def _segments(line: str) -> list[tuple[str, str]] | None:
    """The line's body cut at its top-level `;` and `<;>`, as (separator before, segment); None when it has none."""
    indent = len(line) - len(line.lstrip())
    pieces, depth, begin, index, before = [], 0, indent, indent, ""
    while index < len(line):
        char = line[index]
        if char in _OPEN:
            depth += 1
        elif char in _CLOSE:
            depth -= 1
        separator = next((s for s in _SEPARATORS if depth == 0 and line.startswith(s, index)), None)
        if separator:
            pieces.append((before, line[begin:index]))
            before, index = separator, index + len(separator)
            begin = index
            continue
        index += 1
    pieces.append((before, line[begin:]))
    return pieces if len(pieces) > 1 else None


def _segment_variants(proof: str, start: int) -> list[Variant]:
    found = []
    for begin, end, line in _line_spans(proof, start):
        pieces = _segments(line)
        if pieces is None:
            continue
        indent = line[: len(line) - len(line.lstrip())]
        for number, (_, segment) in enumerate(pieces):
            kept = pieces[:number] + pieces[number + 1 :]
            if number == 0:  # the separator that followed the deleted head goes with it
                kept[0] = ("", kept[0][1])
            text = indent + "".join(before + piece for before, piece in kept)
            tail = "\n" if proof[begin:end].endswith("\n") else ""
            found.append(Variant("segment", proof[:begin] + text + tail + proof[end:], f"segment {segment.strip()}"))
    return found


def _line_variants(proof: str, start: int) -> list[Variant]:
    return [
        Variant("line", proof[:begin] + proof[end:], f"line {line.strip()}")
        for begin, end, line in _line_spans(proof, start)
    ]


def _rewrite_variants(proof: str, start: int) -> list[Variant]:
    cleared = [
        Variant("rewrite", proof[: m.start()] + "rintro -" + proof[m.end() :], f"{m.group(0)!r} to rintro -")
        for m in _INTRO_CLEAR.finditer(proof, start)
    ]
    merged = [
        Variant("rewrite", proof[: m.start()] + f"rintro {m.group(1)} " + proof[m.end() :], "merge rintro")
        for m in _RINTRO_PAIR.finditer(proof, start)
    ]
    return cleared + merged


def variants(proof: str, start: int = 0) -> list[Variant]:
    """Every single edit of the proof after offset `start`, without duplicates and without the proof itself."""
    every = [
        *_list_variants(proof, start),
        *_line_variants(proof, start),
        *_segment_variants(proof, start),
        *_rewrite_variants(proof, start),
    ]
    seen, kept = {proof}, []
    for variant in every:
        if variant.text not in seen:
            seen.add(variant.text)
            kept.append(variant)
    return kept


def candidates(proof: str, start: int, tokens: Callable[[str, int], int] = body_tokens) -> list[Variant]:
    """The variants worth a Lean check, largest token saving first: a rewrite must cut tokens, a deletion may not."""
    current = tokens(proof, start)
    scored = []
    for variant in variants(proof, start):
        try:
            count = tokens(variant.text, start)
        except ValueError:
            continue  # the pinned counter cannot parse it; Lean would not accept it either
        if count < current or variant.kind in DELETIONS:
            scored.append((count - current, variant))
    scored.sort(key=lambda item: item[0])
    return [variant for _, variant in scored]


def greedy(
    proof: str,
    start: int,
    score: Callable[[str], float | None],
    seconds: float,
    tokens: Callable[[str, int], int] = body_tokens,
    accept: Callable[[str, float, Variant], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    stop: Callable[[], str | None] = lambda: None,
) -> Outcome:
    """Take the first variant that beats the current proxy, then start again from it, until none does or the time is up.

    `score` returns a proxy for a proof that passes and None for one that does not; `stop` returns a reason to end
    the pass early (Lean answering nothing) or None."""
    began = clock()
    outcome = Outcome(proof)
    outcome.start_score = outcome.score = score(proof)
    if outcome.score is None:
        outcome.reason = "the starting proof does not pass"  # log: internal record # not-model-facing
        outcome.seconds = clock() - began
        return outcome
    seen = {proof}
    improved = True
    while improved:
        improved = False
        for variant in candidates(outcome.proof, start, tokens):
            if variant.text in seen:
                continue
            if clock() - began >= seconds:
                outcome.timed_out = True
                break
            outcome.reason = stop()
            if outcome.reason is not None:
                break
            seen.add(variant.text)
            outcome.tried += 1
            value = score(variant.text)
            if value is not None and value > outcome.score + EPSILON:
                outcome.proof, outcome.score = variant.text, value
                outcome.accepted.append((variant.text, value, variant))
                if accept is not None:
                    accept(variant.text, value, variant)
                improved = True
                break
        if outcome.timed_out or outcome.reason:
            break
    outcome.seconds = clock() - began
    return outcome


def proxy_of(result: dict | None) -> float | None:
    """The proxy of an evaluation that passed its checked toolchains; None otherwise."""
    if not result or not result.get("ok", True):
        return None
    compat = result.get("compat") or {}
    if not compat or not all(item.get("passed") for item in compat.values()):
        return None
    return campaign._metric_score(result.get("metrics")) or result.get("local_proxy")


def summary_line(outcome: Outcome) -> str:
    if outcome.reason and not outcome.tried:
        return f"Golf pass: skipped ({outcome.reason})"
    gain = f"proxy {outcome.start_score:.2f} -> {outcome.score:.2f}" if outcome.score is not None else "no proxy"
    return f"Golf pass: tried {outcome.tried}, accepted {len(outcome.accepted)}, {outcome.seconds:.0f}s, {gain}" + (
        " (time cap reached)" if outcome.timed_out else f" ({outcome.reason})" if outcome.reason else ""
    )


def golf_run(name: str, run_id: str, seconds: float, clock: Callable[[], float] = time.monotonic) -> Outcome:
    """One pass over the run's best verified proof. Each accepted variant becomes a candidate (origin "golf") with its
    fast evaluation; the newest ones are then full-checked so `campaign.submission` can pick them up."""
    directory = campaign.run_dir(run_id)
    outcome = Outcome("")
    if lean_health.tripped(directory):
        outcome.reason = "Lean unhealthy"  # log: internal record # not-model-facing
        return outcome
    rows = campaign._summaries(campaign.events(directory))
    best = campaign._best([row for row in rows if row["verified"]])
    if best is None:
        outcome.reason = "no verified best"  # log: internal record # not-model-facing
        return outcome
    proof = (directory / "proofs" / f"{best['id']}.lean").read_text()
    outcome.proof = proof
    start = body_start(proof, campaign.problem(name)["statement"])
    results: dict[str, dict] = {}
    failures = 0

    def score(text: str) -> float | None:
        nonlocal failures
        try:
            with campaign.lean_lock(directory, "batch"):
                result = campaign._evaluate(name, text, "fast", lane="batch")
        except Exception:
            failures += 1
            return None
        failures = 0
        results[text] = result
        return proxy_of(result)

    chain = [best["id"]]

    def accept(text: str, value: float, variant: Variant) -> None:
        recorded = campaign.record_evaluation(
            name,
            run_id,
            text,
            "fast",
            parents=[chain[-1]],
            hypothesis=f"Golf pass: {variant.note}",  # log: internal record # not-model-facing
            origin="golf",
            materialize_live=False,
            lane="batch",
            trigger="golf",
            precomputed=results[text],
        )
        chain.append(recorded["candidate_id"])

    def lean_silent() -> str | None:
        return (
            "Lean gave no answer" if failures >= MAX_FAILURES_IN_A_ROW else None
        )  # log: internal record # not-model-facing

    outcome = greedy(proof, start, score, seconds, accept=accept, clock=clock, stop=lean_silent)
    outcome.proof = outcome.proof or proof
    verified = None
    for candidate_id in list(reversed(chain[1:]))[:MAX_FULL_CHECKS]:
        text = (directory / "proofs" / f"{candidate_id}.lean").read_text()
        campaign.record_evaluation(name, run_id, text, "full", materialize_live=False, lane="batch", trigger="golf")
        row = next((r for r in campaign._summaries(campaign.events(directory)) if r["id"] == candidate_id), None)
        if row and row["verified"]:
            verified = row
            break
    campaign._append(
        directory,
        {
            "kind": "golf",
            "tried": outcome.tried,
            "accepted": len(outcome.accepted),
            "start_proxy": outcome.start_score,
            "best_proxy": verified["score"] if verified else outcome.start_score,
            "verified": verified["id"] if verified else None,
            "timed_out": outcome.timed_out,
            "seconds": round(outcome.seconds, 2),
        },
    )
    return outcome


def golf_file(
    name: str, proof: str, seconds: float, clock: Callable[[], float] = time.monotonic
) -> tuple[Outcome, str]:
    """The same pass over a loose proof, every check cold. Returns the outcome and the proof to write: the newest
    accepted proof that passes every toolchain in a final full cold check, else the starting proof."""
    start = body_start(proof, engine.problem(name)["statement"])

    def score(text: str) -> float | None:
        try:
            with engine.force_cold():
                return proxy_of(engine.evaluate(name, text, "fast"))
        except (ValueError, FileNotFoundError):
            return None

    outcome = greedy(proof, start, score, seconds, clock=clock)
    if outcome.reason:
        return outcome, proof
    for text, _, _ in reversed(outcome.accepted):
        with engine.force_cold():
            full = engine.evaluate(name, text, "full")
        if proxy_of(full) is not None:
            outcome.score = proxy_of(full)
            return outcome, text
    return outcome, proof


def write_result(path: Path, proof: str) -> None:
    path.write_text(proof if proof.endswith("\n") else proof + "\n")
