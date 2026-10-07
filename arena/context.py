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

from arena.engine import ROOT, candidate_file, is_standalone, measure_version, problem, run_lean, versions
from arena.profile import MAX_DEPTH, heartbeat_floor, profile
from arena.scoring import exchange_rates

LEAN_FILE = Path(__file__).with_name("lean") / "context.lean"
_RECORD = re.compile(r"^ARENA_CTX (\{.*\})$", re.M)
MAX_PACKET_CHARS = 40_000
LIMITS = {"goals": 40, "goal_chars": 700, "used": 5, "used_chars": 320, "earlier": 30,
          "earlier_chars": 240, "types": 8, "type_chars": 700, "profile_entries": 24,
          "scope": 25, "scope_chars": 600}
REQUIRED_SECTIONS = ("Pinned environment and candidate", "Source-named declarations",
                     "Elaborated proof dependencies", "Reference proof")


def _cache(kind: str, name: str, commit: str, salt: str) -> Path:
    digest = hashlib.sha256(salt.encode()).hexdigest()[:12]
    return ROOT / "runs" / "cache" / kind / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}-{commit[:12]}-{digest}.json"


def _lean_name(name: str) -> str:
    """Render a qualified Lean name as a syntax-safe Lean expression."""
    result = "Lean.Name.anonymous"
    for part in name.split("."):
        result = f"Lean.Name.str ({result}) {json.dumps(part)}"
    return result


def parse_context(output: str, shift: int, start_line: int, proof_boundary: tuple[int, int] | None = None) -> dict:
    """Group the wrapper's JSON records. `shift` is the instrumentation's line count."""
    groups: dict[str, list[dict]] = {"goal": [], "used": [], "source": [], "dependency": [], "constant": [],
                                    "local": [], "failure": [],
                                    "type": [], "earlier": []}
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
    for item in groups["source"]:
        item["proof_line"] = item["line"] - shift - start_line + 1
        if proof_boundary is None:
            item.setdefault("origin", "unknown")  # no top-level `:=` (e.g. equation-compiler proofs): do not guess
        else:
            item["origin"] = ("proof" if (item["proof_line"], item.get("column", 0)) >= proof_boundary else "statement")
    for item in groups["dependency"]:
        item["origin"] = "elaborated-proof"
    for item in groups["constant"]:
        item["kind"] = item.pop("decl", "generated/other")
    for item in groups["local"]:
        item["proof_line"] = item["line"] - shift - start_line + 1
    return {"complete": complete and not groups["failure"], **groups}


def constant_index(context: dict, name: str | None = None, kind: str | None = None,
                   origin: str | None = None, tag: str | None = None) -> list[dict]:
    """Query the full elaborated constant inventory by qualified name, kind, origin and tag."""
    items = context.get("constant", [])
    return [item for item in items if (name is None or item["name"] == name)
            and (kind is None or item["kind"] == kind)
            and (origin is None or item["origin"] == origin)
            and (tag is None or item.get("tag") == tag)]


def _proof_boundary(source: str, start_line: int) -> tuple[int, int] | None:
    """Find the first top-level-looking `:=` in a theorem source, ignoring comments/strings."""
    i = 0
    depth = 0
    block = 0
    in_string = False
    while i < len(source) - 1:
        if block:
            if source.startswith("/-", i):
                block += 1
                i += 2
            elif source.startswith("-/", i):
                block -= 1
                i += 2
            else:
                i += 1
            continue
        if in_string:
            if source[i] == "\\":
                i += 2
            elif source[i] == '"':
                in_string = False
                i += 1
            else:
                i += 1
            continue
        if source.startswith("/-", i):
            block, i = 1, i + 2
        elif source.startswith("--", i):
            end = source.find("\n", i)
            i = len(source) if end < 0 else end + 1
        elif source[i] == '"':
            in_string, i = True, i + 1
        elif source[i] in "([{":
            depth += 1
            i += 1
        elif source[i] in ")]}":
            depth = max(0, depth - 1)
            i += 1
        elif depth == 0 and source.startswith(":=", i):
            prefix = source[:i]
            return (start_line + prefix.count("\n"), len(prefix.rsplit("\n", 1)[-1]))
        else:
            i += 1
    return None


def lean_context(name: str) -> dict:
    """Elaboration data for the reference proof; cached per row, commit and wrapper source."""
    row = problem(name)
    version, commit = measure_version(row)
    source = LEAN_FILE.read_text()
    cache = _cache("context", name, commit, source + row["src"])
    if cache.exists():
        return json.loads(cache.read_text())
    roots = "" if is_standalone(row) else ", ".join(json.dumps(part) for part in sorted({row["file_path"].split("/")[0]}))
    inserted = source.replace("@@ROOTS@@", roots).replace("@@TARGET@@", _lean_name(name))
    built = candidate_file(row, row["src"], version, commit)
    text = built["text"][:built["head"]] + inserted + built["text"][built["head"]:]
    ran = run_lean(row, built["path"], text)
    if ran is None:
        return {"error": "Lean timed out while collecting context"}
    returncode, output = ran
    parsed = parse_context(output, inserted.count("\n"), built["start_line"],
                           _proof_boundary(row["src"], 1))
    if not parsed["complete"]:
        reason = (parsed["failure"][0].get("message") if parsed["failure"] else
                  next((line for line in output.splitlines() if "error" in line), "no context records"))
        return {"error": reason[:200]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(parsed, ensure_ascii=False, indent=1))
    return parsed


def reference_profile(name: str) -> dict:
    """Heartbeat profile of the reference proof, cached like the context."""
    row = problem(name)
    version, commit = measure_version(row)
    salt = ((Path(__file__).with_name("lean") / "profile.lean").read_text() + row["src"] +
            str(MAX_DEPTH) + "profile-schema-v3-innermost-span-token-hotspots")
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


_SCOPE = re.compile(r"^(?:@\[[^\]]*\]\s*)?(?:public\s+|private\s+)?(?:noncomputable\s+)?"
                    r"(namespace|section|end|open|variable|universe|include|omit)\b(.*)$")
_PRIVATE = re.compile(r"_private\.(?:[^.\s]+\.)*?\d+\.")


def _readable(text: str) -> str:
    """Show `private` declarations by their source name, not Lean's mangled internal name."""
    return _PRIVATE.sub("", text)


def _scope_section(row: dict) -> list[str]:
    """Namespace, `open`, `variable`, `universe`, `include` and `omit` in effect at the theorem.

    Read from the pinned source before the declaration (the header for standalone rows), tracking
    `namespace`/`section`/`end` so commands of closed scopes are dropped. Syntactic and generic.
    """
    if is_standalone(row):
        source = row.get("header") or ""
    else:
        built = candidate_file(row, row["src"], *measure_version(row))
        source = built["text"][:built["head"]]
    return scope_lines(source)


def scope_lines(source: str) -> list[str]:
    """The scope commands still in effect at the end of `source` (see `_scope_section`)."""
    source = re.sub(r"/-.*?-/", "", source, flags=re.S)
    source = re.sub(r"--[^\n]*", "", source)
    stack: list[tuple[str, str]] = []
    active: list[tuple[int, str]] = []
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        found = _SCOPE.match(lines[index])
        if not found:
            index += 1
            continue
        kind, rest = found[1], found[2].strip()
        if kind in ("namespace", "section"):
            stack.append((kind, rest))
        elif kind == "end":
            if stack:
                depth = len(stack)
                stack.pop()
                active = [item for item in active if item[0] < depth]
        elif kind == "open" and rest.endswith(" in"):
            pass  # `open … in` scopes only the next command; handled below if that is the theorem
        else:
            block = [lines[index].rstrip()]
            while index + 1 < len(lines) and lines[index + 1][:1] in (" ", "\t") and lines[index + 1].strip():
                index += 1
                block.append(lines[index].rstrip())
            active.append((len(stack), "\n".join(block)))
        index += 1
    tail = [line for line in lines if line.strip()]
    if tail and _SCOPE.match(tail[-1]) and tail[-1].rstrip().endswith(" in"):
        active.append((len(stack), tail[-1].rstrip()))
    namespace = ".".join(name for kind, name in stack if kind == "namespace" and name)
    body = [f"namespace {namespace}" if namespace else "(root namespace)"] + [text for _, text in active]
    return [_clip(line, LIMITS["scope_chars"]) for line in body][:LIMITS["scope"]]


def _types_section(context: dict) -> list[str]:
    lines = []
    for item in context.get("type", [])[:LIMITS["types"]]:
        if item["decl"] in ("inductive", "structure"):
            body = "\n".join(f"  | {_clip(c, LIMITS['type_chars'])}" for c in item["ctors"])
            lines.append(f"decl:{item['name']} [{item['decl']}] {_clip(_readable(item['sig']), LIMITS['type_chars'])}\n{_readable(body)}")
        else:
            lines.append(f"decl:{item['name']} [def] {_clip(item['sig'], LIMITS['type_chars'])}\n  := {_clip(item.get('value', ''), LIMITS['type_chars'])}")
    return lines


def _goal_section(context: dict) -> list[str]:
    lines = []
    for item in context.get("goal", [])[:LIMITS["goals"]]:
        span = (str(item["proof_line"]) if item["proof_line"] == item["end_proof_line"]
                else f"{item['proof_line']}-{item['end_proof_line']}")
        lines.append(f"-- before proof line {span}\n{_clip(item['text'], LIMITS['goal_chars'])}")
    return lines


TAGS = ("generated", "instance", "axiom", "tactic", "core")


def _rank(item: dict, root: str) -> tuple[int, str]:
    """Project and this-file declarations first, then other helper libraries."""
    module = item.get("module", "")
    return (0 if module == "this file" else 1 if root and module.split(".")[0] == root else 2, item["name"])


def _source_names(context: dict) -> dict[str, dict]:
    return {item["name"]: item for item in context.get("source", [])}


def _extra_dependencies(context: dict) -> tuple[list[dict], dict[str, int], int]:
    """Direct theorem/lemma dependencies beyond the source names: (helpers in display order,
    per-tag counts of the rest, how many were already source-named)."""
    source = _source_names(context)
    unique = {item["name"]: item for item in context.get("dependency", [])}
    extra = [unique[name] for name in unique if name not in source]
    root = context.get("root", "")
    helpers = sorted((i for i in extra if i.get("tag", "helper") == "helper"), key=lambda i: _rank(i, root))
    counts = {tag: sum(i.get("tag") == tag for i in extra) for tag in TAGS}
    return helpers, counts, len(unique) - len(extra)


def _preview(items: list[dict], root: str) -> list[dict]:
    """Up to LIMITS['used'] helper declarations in display order; never generated, instance, axiom, tactic or core glue."""
    return sorted((i for i in items if i.get("tag", "helper") == "helper"), key=lambda i: _rank(i, root))[:LIMITS["used"]]


def _used_section(context: dict) -> list[str]:
    occurrences: dict[str, list[dict]] = {}
    for item in context.get("source", []):
        occurrences.setdefault(item["name"], []).append(item)
    ordered = sorted(occurrences.items())
    lines = ["Qualified name [kind] S:statement lines P:proof lines U:lines whose position could not be placed "
             "(no top-level `:=` found); use `decl:<name>` as its source handle."]
    for name, items in ordered:
        def at(origin: str) -> str:
            return ",".join(str(i["proof_line"]) for i in items if i.get("origin") == origin)
        unknown = at("unknown")
        lines.append(f"decl:{name} [{items[0]['decl']}] S:{at('statement') or '-'} P:{at('proof') or '-'}"
                     + (f" U:{unknown}" if unknown else ""))
    preview = _preview([items[0] for _, items in ordered], context.get("root", ""))
    lines.extend(["", f"Signature preview: {sum(bool(i.get('sig')) for i in preview)} shown of {len(ordered)} distinct source names; "
                  f"{sum(not bool(items[0].get('sig')) for _, items in ordered)} unavailable."])
    lines.extend(f"[decl:{i['name']} · {i['decl']} · {i['module']}] {_clip(_readable(_one_line(i['sig'])), LIMITS['used_chars'])}"
                 for i in preview if i.get("sig"))
    return lines


def _dependency_section(context: dict) -> list[str]:
    helpers, counts, named = _extra_dependencies(context)
    lines = ["Qualified helper theorem name (project/this file first); origin: direct elaborated-proof use; "
             "source handle: `decl:<name>`."]
    lines.extend(f"decl:{i['name']}" for i in helpers)
    lines += ["", f"Tagged, not listed: {', '.join(f'{tag} {n}' for tag, n in counts.items())}; also source-named: {named}. "
              "Query the constant index or declaration lookup for these."]
    preview = _preview(helpers, context.get("root", ""))
    lines += [f"Signature preview: {sum(bool(i.get('sig')) for i in preview)} shown of {len(helpers)} helpers; "
              f"{sum(not bool(i.get('sig')) for i in helpers)} unavailable."]
    lines.extend(f"[decl:{i['name']} · {i['decl']} · {i['module']}] {_clip(_readable(_one_line(i['sig'])), LIMITS['used_chars'])}"
                 for i in preview if i.get("sig"))
    return lines


def _local_section(context: dict) -> list[str]:
    scopes: dict[tuple[str, str, str], set[int]] = {}
    for item in context.get("local", []):
        scopes.setdefault((item["name"], item["type"], item["scope"]), set()).add(item["proof_line"])
    if not scopes:
        return []
    lines = ["Local variable name : type; lines are where the Lean local context exposes the variable."]
    lines.extend(f"{name} : {_clip(_one_line(ty), 320)} [scope: {scope}; lines: {','.join(map(str, sorted(locations)))}]"
                 for (name, ty, scope), locations in sorted(scopes.items()))
    return lines


def _signature_counts(items: list[dict], root: str) -> tuple[int, int]:
    """(previewed signatures shown, signatures unavailable) over distinct names, as the sections report."""
    unique = list({item["name"]: item for item in items}.values())
    return sum(bool(i.get("sig")) for i in _preview(unique, root)), sum(not bool(i.get("sig")) for i in unique)


def _imports(row: dict) -> list[str]:
    if is_standalone(row):
        source = row.get("header") or ""
    else:
        built = candidate_file(row, row["src"], *measure_version(row))
        source = built["text"][:built["head"]]
    return [match.group(0).strip() for match in re.finditer(r"(?m)^\s*import\s+[^\n]+", source)]


def packet_manifest(parts: list[tuple[str, list[str]]], inventory: dict) -> dict:
    present = {title for title, body in parts if body}
    sections = {title: {"expected": True, "present": any(p.startswith(title) for p in present)}
                for title in REQUIRED_SECTIONS}
    return {"schema": "arena-kickoff-manifest/v1", "sections": sections,
            "source_inventory": len(inventory.get("source", [])),
            "dependency_helpers": len(_extra_dependencies(inventory)[0]),
            "dependency_tags": _extra_dependencies(inventory)[1],
            "complete": bool(inventory.get("complete"))}


def certify_manifest(manifest: dict, expected: list[str] | None = None) -> dict:
    required = expected or list(REQUIRED_SECTIONS)
    missing = [name for name in required if not manifest.get("sections", {}).get(name, {}).get("present")]
    reasons = (["context extraction incomplete"] if not manifest.get("complete") else [])
    if missing:
        reasons.append("required sections absent: " + ", ".join(missing))
    return {"certified": not reasons, "reasons": reasons}


def _earlier_section(context: dict) -> list[str]:
    return [f"line {i['line']} [decl:{i['name']} · {i['decl']}] {_clip(_readable(_one_line(i['sig'])), LIMITS['earlier_chars'])}"
            for i in context.get("earlier", [])
            if i["decl"] in ("theorem", "def")][:LIMITS["earlier"]]


def _profile_section(prof: dict) -> list[str]:
    if prof.get("error"):
        return [f"(profile unavailable: {_clip(prof['error'], 160)})"]
    rows = [f"Profile granularity: {prof['granularity']}",
            f"proof lines | file lines | heartbeats (incl.) | self | share | tactic"]
    kept = [e for e in prof["entries"] if e["share_pct"] >= 1.5 or e["depth"] == 0]
    for entry in kept[:LIMITS["profile_entries"]]:
        file_span = (str(entry["file_line"]) if entry["end_file_line"] == entry["file_line"]
                     else f"{entry['file_line']}-{entry['end_file_line']}")
        rows.append(f"{entry['lines']} | {file_span} | {entry['hb']} | {entry['self_hb']} | {entry['share_pct']}% | "
                    f"{'  ' * entry['depth']}{_clip(entry['text'], 60)}")
    rows.append("Top-ten starting lines by score-equivalent baseline cost (not predicted savings):")
    if not prof.get("token_attribution_available"):
        rows.append("(unavailable: proof-line tokens did not reconcile with the competition tokenizer)")
    else:
        for item in prof["hotspots"]:
            spans = ", ".join(f"proof {span['proof_line']}-{span['end_proof_line']} / "
                               f"file {span['file_line']}-{span['end_file_line']} (depth {span['depth']})"
                               for span in item["tactic_spans"])
            rows.append(f"proof {item['proof_line']}-{item['end_proof_line']} / file {item['file_line']}-{item['end_file_line']}"
                        f" (tactic spans: {_clip(spans, 180)}): {item['self_hb']} self hb, "
                        f"{item['tokens']} tokens, {item['baseline_cost_points']} baseline points")
    top = ", ".join(f"{t['lines']} ({t['self_hb']} hb, cum. {t['cumulative_share_pct']}%)" for t in prof["top_self_cost"])
    rows.append(f"Top self costs: {top}")
    measured = prof.get("measured_total")
    profiled = prof.get("profiled_total")
    coverage = round(100 * profiled / measured, 1) if measured else None
    rows.append(f"Measured whole-proof heartbeats: {measured}; attributed tactic heartbeats: {profiled} "
                f"({coverage}% coverage); statement floor: {prof.get('statement_floor_hb')}; "
                f"unattributed remainder: {prof.get('unattributed')}.")
    if prof.get("note"):
        rows.append(_clip(prof["note"], 180))
    return rows


def _fit(parts: list[tuple[str, list[str]]], limit: int) -> str:
    """Join sections; if over budget drop entries from the end of the lowest-priority sections."""
    sections = [(title, list(body)) for title, body in parts]
    def render() -> str:
        return "\n\n".join((f"{title}\n" if title else "") + "\n".join(body) for title, body in sections if body)
    order = ["Lemmas declared earlier in this file", "Goal before each top-level tactic of the reference proof"]
    while len(render()) > limit:
        for title in order:
            target = next((body for t, body in sections if t.startswith(title)), None)
            if target and (len(target) > 1 or not title.startswith("Goal before")):
                target.pop()
                break
        else:
            break
    if len(render()) > limit:
        raise ValueError("Required kickoff inventory exceeds packet budget; certification failed")
    return render()


def render_packet(name: str) -> str:
    row = problem(name)
    targets = versions(row)
    context = lean_context(name)
    context["root"] = "" if is_standalone(row) else row["file_path"].split("/")[0]
    prof = reference_profile(name)
    pins = "; ".join(f"Lean {version} / source revision {commit}" for version, commit in targets)
    task = [
        f"Lean Refactor Arena: optimize {name}. The original proof is candidate #1.",
        "The statement must stay byte-exact. The score is the mean of three percentages: proof tokens saved, "
        "Lean heartbeats saved, and the share of listed toolchain versions the proof compiles on.",
        _rates(name, len(targets)),
        "Survey the supplied references and pinned source before recording a route with arena_idea. "
        "Then pursue the route and update its status with a reason as evidence arrives. "
        "arena_probe compiles drafts (sorry allowed, goals reported); arena_profile shows where heartbeats go; "
        "arena_evaluate scores a complete proof on the primary version (a sorry-free probe that compiles is scored the "
        "same way). The harness checks every compiling candidate on the other versions in the background and appends "
        "an [arena] line with results and the best verified candidate to a later tool result whenever something "
        "changes; the best verified candidate is submitted automatically at the end. Parents and idea ids are optional "
        "labels. The current candidate file is readable by lean_goal and lean_diagnostic_messages at the line numbers "
        "reported in diagnostics.",
    ]
    note = "" if not context.get("error") else f"(elaboration context unavailable: {_clip(context['error'], 160)})"
    parts: list[tuple[str, list[str]]] = [
        ("", task),
        ("Pinned environment and candidate", [f"Source: {row['source']} standalone problem (file = header + statement + proof)" if is_standalone(row)
                                               else f"Source: {row['source']}:{row['file_path']}:{row['start_line']}-{row['end_line']}",
                                               f"Lean toolchain and source revisions: {pins}",
                                               f"Original proof: candidate #1",
                                               f"Available imports: {', '.join(_imports(row)) or '(none reported)'}"]),
        ("Definitions of project types and predicates in the statement", _types_section(context)),
        ("Scope at the theorem (namespace, open, variable, universe in effect before the statement)",
         _scope_section(row)),
        (f"Reference proof ({row['proof_length']} tokens)", [f"```lean\n{row['src']}\n```"]),
        ("Heartbeat profile of the reference proof", _profile_section(prof)),
        ("Goal before each top-level tactic of the reference proof", _goal_section(context)),
        ("Source-named declarations", _used_section(context)),
        ("Elaborated proof dependencies", _dependency_section(context)),
        ("Local variables", _local_section(context)),
        ("Lemmas declared earlier in this file", _earlier_section(context)),
    ]
    if note:
        parts.append(("", [note]))
    manifest = packet_manifest(parts, context)
    result = certify_manifest(manifest)
    if not result["certified"]:
        raise ValueError("Kickoff packet is not certifiable: " + "; ".join(result["reasons"]))
    root = context.get("root", "")
    helpers, tags, named = _extra_dependencies(context)
    parts.append(("Kickoff inventory manifest", [
        f"Source names: {len(context.get('source', []))} occurrences; "
        f"{len(_source_names(context))} distinct; signature preview "
        f"{_signature_counts(list(_source_names(context).values()), root)[0]}; "
        f"unavailable {_signature_counts(list(_source_names(context).values()), root)[1]}.",
        f"Extra direct theorem/lemma dependencies: {len(helpers)} helpers shown; tagged and not listed: "
        f"{', '.join(f'{tag} {n}' for tag, n in tags.items())}; already source-named: {named}; "
        f"signature preview {_signature_counts(helpers, root)[0]}; unavailable {_signature_counts(helpers, root)[1]}.",
        "Required sections: " + ", ".join(name for name, state in manifest["sections"].items() if state["present"]) + "."
    ]))
    return _fit(parts, MAX_PACKET_CHARS) + "\n"
