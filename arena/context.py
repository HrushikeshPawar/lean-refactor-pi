"""Generic kickoff packet built from Lean elaboration data.

A Lean command wrapper (arena/lean/context.lean) elaborates the reference proof in the
pinned environment and reports, from the info trees and the environment rather than
from text patterns: the goal before each top-level tactic, every constant the proof
mentions with its type, the definitions of project types in the statement, and the
declarations that precede the theorem in its file. Nothing here is specific to one
theorem or corpus, and nothing suggests a proof strategy.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from arena.engine import ROOT, candidate_file, is_standalone, problem, run_lean, versions
from arena.profile import MAX_DEPTH, heartbeat_floor, profile
from arena.scoring import exchange_rates

LEAN_FILE = Path(__file__).with_name("lean") / "context.lean"
_RECORD = re.compile(r"^ARENA_CTX (\{.*\})$", re.M)
MAX_PACKET_CHARS = 30_000
LIMITS = {"goals": 40, "goal_chars": 700, "used": 50, "used_chars": 320, "earlier": 30,
          "earlier_chars": 240, "types": 8, "type_chars": 700, "profile_entries": 24}


def _cache(kind: str, name: str, commit: str, salt: str) -> Path:
    digest = hashlib.sha256(salt.encode()).hexdigest()[:12]
    return ROOT / "runs" / "cache" / kind / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}-{commit[:12]}-{digest}.json"


def parse_context(output: str, shift: int, start_line: int) -> dict:
    """Group the wrapper's JSON records. `shift` is the instrumentation's line count."""
    groups: dict[str, list[dict]] = {"goal": [], "used": [], "type": [], "earlier": []}
    complete = False
    for raw in _RECORD.findall(output):
        record = json.loads(raw)
        kind = record["kind"]
        if kind == "end":
            complete = True
        elif kind in groups:
            groups[kind].append(record)
    for item in groups["goal"]:
        item["proof_line"] = item["line"] - shift - start_line + 1
        item["end_proof_line"] = item["endLine"] - shift - start_line + 1
    for item in groups["used"]:
        item["proof_line"] = item["line"] - shift - start_line + 1
    return {"complete": complete, **groups}


def lean_context(name: str) -> dict:
    """Elaboration data for the reference proof; cached per row, commit and wrapper source."""
    row = problem(name)
    version, commit = versions(row)[0]
    source = LEAN_FILE.read_text()
    cache = _cache("context", name, commit, source + row["src"])
    if cache.exists():
        return json.loads(cache.read_text())
    roots = "" if is_standalone(row) else ", ".join(json.dumps(part) for part in sorted({row["file_path"].split("/")[0]}))
    inserted = source.replace("@@ROOTS@@", roots)
    built = candidate_file(row, row["src"], version, commit)
    text = built["text"][:built["offset"]] + inserted + built["text"][built["offset"]:]
    ran = run_lean(row, built["path"], text)
    if ran is None:
        return {"error": "Lean timed out while collecting context"}
    returncode, output = ran
    parsed = parse_context(output, inserted.count("\n"), built["start_line"])
    if not parsed["complete"]:
        reason = next((line for line in output.splitlines() if "error" in line), "no context records")
        return {"error": reason[:200]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(parsed, ensure_ascii=False, indent=1))
    return parsed


def reference_profile(name: str) -> dict:
    """Heartbeat profile of the reference proof, cached like the context."""
    row = problem(name)
    version, commit = versions(row)[0]
    salt = (Path(__file__).with_name("lean") / "profile.lean").read_text() + row["src"] + str(MAX_DEPTH)
    cache = _cache("profile", name, commit, salt)
    if cache.exists():
        return json.loads(cache.read_text())
    try:
        result = profile(name, row["src"])
        result["statement_floor_hb"] = heartbeat_floor(name)["heartbeats"]
    except ValueError as error:
        return {"error": str(error)}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _rates(name: str, total_versions: int) -> str:
    rates = exchange_rates(name, total_versions)
    return (f"Exchange rates for this problem (score points): 1 token = {rates['points_per_token']} pt "
            f"(about {rates['heartbeats_per_token']} heartbeats); 100 heartbeats = "
            f"{rates['points_per_100_heartbeats']} pt; one lost toolchain version = "
            f"{rates['points_per_lost_version']} pt (about {rates['tokens_per_lost_version']} tokens). "
            f"Reference: {rates['reference_tokens']} tokens, {rates['reference_heartbeats']} heartbeats.")


def _types_section(context: dict) -> list[str]:
    lines = []
    for item in context.get("type", [])[:LIMITS["types"]]:
        if item["decl"] in ("inductive", "structure"):
            body = "\n".join(f"  | {_clip(c, LIMITS['type_chars'])}" for c in item["ctors"])
            lines.append(f"{item['decl']} {_clip(item['sig'], LIMITS['type_chars'])}\n{body}")
        else:
            lines.append(f"def {_clip(item['sig'], LIMITS['type_chars'])}\n  := {_clip(item.get('value', ''), LIMITS['type_chars'])}")
    return lines


def _goal_section(context: dict) -> list[str]:
    lines = []
    for item in context.get("goal", [])[:LIMITS["goals"]]:
        span = (str(item["proof_line"]) if item["proof_line"] == item["end_proof_line"]
                else f"{item['proof_line']}-{item['end_proof_line']}")
        lines.append(f"-- before proof line {span}\n{_clip(item['text'], LIMITS['goal_chars'])}")
    return lines


def _used_section(context: dict) -> list[str]:
    def local(item: dict) -> bool:
        return item["module"] == "this file" or item["module"].split(".")[0] == context.get("root", "")
    items = [i for i in context.get("used", []) if not i["module"].startswith("Init.Prelude")]
    items.sort(key=lambda i: (0 if i["module"] == "this file" else 1 if local(i) else 2, i["proof_line"], i["name"]))
    return [f"[{i['decl']} · {i['module']}] {_clip(_one_line(i['sig']), LIMITS['used_chars'])}"
            for i in items[:LIMITS["used"]]]


def _earlier_section(context: dict) -> list[str]:
    return [f"line {i['line']} [{i['decl']}] {_clip(_one_line(i['sig']), LIMITS['earlier_chars'])}"
            for i in context.get("earlier", [])
            if i["decl"] in ("theorem", "def")][:LIMITS["earlier"]]


def _profile_section(prof: dict) -> list[str]:
    if prof.get("error"):
        return [f"(profile unavailable: {_clip(prof['error'], 160)})"]
    rows = [f"proof lines | heartbeats (incl.) | self | share | tactic"]
    kept = [e for e in prof["entries"] if e["share_pct"] >= 1.5 or e["depth"] == 0]
    for entry in kept[:LIMITS["profile_entries"]]:
        rows.append(f"{entry['lines']} | {entry['hb']} | {entry['self_hb']} | {entry['share_pct']}% | "
                    f"{'  ' * entry['depth']}{_clip(entry['text'], 60)}")
    top = ", ".join(f"{t['lines']} ({t['self_hb']} hb, cum. {t['cumulative_share_pct']}%)" for t in prof["top_self_cost"])
    rows.append(f"Top self costs: {top}")
    rows.append(f"Profiled total {prof['profiled_total']} vs measured whole-proof {prof['measured_total']} "
                f"(unattributed {prof['unattributed']}: term elaboration outside tactics, kernel check). "
                f"Statement alone elaborates in about {prof.get('statement_floor_hb')} heartbeats.")
    return rows


def _fit(parts: list[tuple[str, list[str]]], limit: int) -> str:
    """Join sections; if over budget drop entries from the end of the lowest-priority sections."""
    sections = [(title, list(body)) for title, body in parts]
    def render() -> str:
        return "\n\n".join((f"{title}\n" if title else "") + "\n".join(body) for title, body in sections if body)
    order = ["Lemmas declared earlier in this file", "Signatures of constants the reference proof mentions",
             "Goal before each top-level tactic of the reference proof"]
    while len(render()) > limit:
        for title in order:
            target = next((body for t, body in sections if t.startswith(title)), None)
            if target and len(target) > 3:
                target.pop()
                break
        else:
            break
    return render()


def render_packet(name: str) -> str:
    row = problem(name)
    targets = versions(row)
    context = lean_context(name)
    context["root"] = "" if is_standalone(row) else row["file_path"].split("/")[0]
    prof = reference_profile(name)
    commits = ", ".join(f"{v}:{c}" for v, c in targets)
    task = [
        f"Lean Refactor Arena: optimize {name} from its ORIGINAL proof.",
        "The statement must stay byte-exact. The score is the mean of three percentages: proof tokens saved, "
        "Lean heartbeats saved, and the share of listed toolchain versions the proof compiles on.",
        _rates(name, len(targets)),
        "Before editing, propose at least three structurally different ideas with arena_idea, stating the expected "
        "effect on each axis; then pursue them and update each idea's status with a reason as evidence arrives. "
        "arena_probe compiles drafts (sorry allowed, goals reported); arena_profile shows where heartbeats go; "
        "arena_evaluate scores a complete proof (fast = primary version, full = every version). Parents and idea ids "
        "are optional labels. The current candidate file is readable by lean_goal and lean_diagnostic_messages at the "
        "line numbers reported in diagnostics.",
        (f"Pinned source: {row['source']} standalone problem (file = header + statement + proof)\n" if is_standalone(row)
         else f"Pinned source: {row['source']}:{row['file_path']}:{row['start_line']}-{row['end_line']}\n") +
        f"Toolchain commits: {commits}",
    ]
    note = "" if not context.get("error") else f"(elaboration context unavailable: {_clip(context['error'], 160)})"
    parts: list[tuple[str, list[str]]] = [
        ("", task),
        ("Definitions of project types and predicates in the statement", _types_section(context)),
        (f"Reference proof ({row['proof_length']} tokens)", [f"```lean\n{row['src']}\n```"]),
        ("Heartbeat profile of the reference proof", _profile_section(prof)),
        ("Goal before each top-level tactic of the reference proof", _goal_section(context)),
        ("Signatures of constants the reference proof mentions", _used_section(context)),
        ("Lemmas declared earlier in this file", _earlier_section(context)),
    ]
    if note:
        parts.append(("", [note]))
    return _fit(parts, MAX_PACKET_CHARS) + "\n"
