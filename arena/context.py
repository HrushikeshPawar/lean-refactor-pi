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
import math
import re
from pathlib import Path

from arena.engine import ROOT, candidate_file, is_standalone, measure_version, problem, run_lean, versions
from arena.profile import MAX_DEPTH, heartbeat_floor, profile
from arena.scoring import exchange_rates

LEAN_FILE = Path(__file__).with_name("lean") / "context.lean"
_RECORD = re.compile(r"^ARENA_CTX (\{.*\})$", re.M)
MAX_PACKET_CHARS = 40_000
CONTEXT_TIMEOUT = 360  # seconds; the library scan adds about 20-40 s to the largest environments
LIMITS = {"goals": 40, "goal_chars": 700, "used": 5, "used_chars": 320, "earlier": 60, "earlier_budget": 12_000,
          "earlier_chars": 240, "types": 8, "type_chars": 700, "profile_entries": 24,
          "scope": 25, "scope_chars": 600, "library": 20, "library_budget": 7_000, "library_chars": 340}
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
                                    "type": [], "earlier": [], "target": [], "library": [], "library_scan": []}
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
    ran = run_lean(row, built["path"], text, timeout=CONTEXT_TIMEOUT, prefix_end=built["head"])
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


def cached_context(name: str) -> dict:
    """The kickoff context if it is already cached, else {}; never starts Lean."""
    try:
        row = problem(name)
        version, commit = measure_version(row)
        cache = _cache("context", name, commit, LEAN_FILE.read_text() + row["src"])
        return json.loads(cache.read_text()) if cache.exists() else {}
    except (ValueError, OSError, KeyError):
        return {}


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


SCORING_FACTS = (
    "Scoring facts. Proxy = (token_reduction% + heartbeat_reduction% + compatibility%) / 3, where "
    "token_reduction% = (reference_tokens - tokens) / reference_tokens * 100, heartbeat_reduction% = "
    "(reference_heartbeats - heartbeats) / reference_heartbeats * 100 (heartbeats in `maxHeartbeats` units, "
    "measured with `maxHeartbeats 0`) and compatibility% = versions that compile / versions listed * 100; "
    "a proof that does not compile scores 0 on all three. Tokens are counted by the harness's pinned counter "
    "on the text after the statement's `:=`, with comments and attributes removed: each run of letters, digits, "
    "`.`, `_`, `'` is one token whatever its length, every other non-space character is one token (so `⟨a, b⟩` "
    "is 5), except the operators `:= != && -. -> ← .. ... :: :> <;> ;; == || => <= >= ⁻¹ ?_`, which count once. "
    "Spaces and line breaks are free; a tab counts as a token. `_` can replace any argument or term Lean infers; "
    "restating it, such as a lambda, costs tokens.")


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


EARLIER_TITLE = "Relevant lemmas from this file (ranked)"
CORE_FACTOR = 0.25  # library (Init/Std/Lean) constants count a quarter of project and Mathlib ones
GENERIC_SHARE = 0.2  # a constant in more than this share of earlier statements is infrastructure
WEIGHTS = {"overlap": 10.0, "head": 5.0, "equation": 3.0, "co_usage": 3.0, "distance": 0.5}


def _short(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _key_heads(item: dict) -> set[str]:
    """Constants a lemma is 'about' at its conclusion: both sides of an equation or iff, else the head."""
    heads = {item.get("lhs_head", ""), item.get("rhs_head", "")} if item.get("rel") else {item.get("concl_head", "")}
    return {head for head in heads if head}


def _stated(item: dict) -> set[str]:
    return set(item.get("consts", [])) | set(item.get("core_consts", []))


def score_earlier(context: dict) -> list[dict]:
    """Rank the file's earlier theorems and defs by relevance to the target (highest first).

    Each result is {"item", "score", "relevance", "reason"}. Pure function of the extracted context:
      overlap   (<=10) IDF mass of the lemma's statement constants shared with the target statement
                (weight 1) and the original proof's and goals' constants (weight 0.7), saturated
                against the lemma's own non-shared mass so long generic statements do not win;
      head      (<=5)  the lemma's conclusion (or equation-side) head constant is the head of a captured goal;
      equation  (<=3)  an Eq/Iff whose left side mentions those constants (rewrite-ready);
      co_usage  (<=3)  other relevant earlier lemmas use it in their proofs;
      distance  (<=0.5) nearness to the theorem, as a tie-break only.
    IDF is computed over the earlier statements; a constant in more than GENERIC_SHARE of them gets 0.
    """
    earlier = context.get("earlier", [])
    count = len(earlier)
    if not count:
        return []
    frequency: dict[str, int] = {}
    for item in earlier:
        for name in set(item.get("consts", [])) | set(item.get("core_consts", [])) | _key_heads(item):
            frequency[name] = frequency.get(name, 0) + 1
    core = {name for item in earlier for name in item.get("core_consts", [])}
    core |= {name for g in context.get("goal", []) for name in g.get("core_consts", [])}
    core |= set((context.get("target") or [{}])[0].get("core_consts", []))
    core |= {c["name"] for c in context.get("constant", [])
             if c.get("tag") == "core" or c.get("module", "").split(".")[0] in ("Init", "Std", "Lean")}
    def idf(name: str) -> float:
        seen = frequency.get(name, 0)
        if seen > GENERIC_SHARE * count:
            return 0.0
        return (CORE_FACTOR if name in core else 1.0) * math.log((count + 1) / (seen + 0.5))
    target = (context.get("target") or [{}])[0]
    wanted: dict[str, float] = {}
    for name in ([c["name"] for c in context.get("constant", [])] +
                 [n for g in context.get("goal", []) for n in g.get("consts", []) + g.get("core_consts", [])]):
        wanted[name] = 0.7
    for name in target.get("consts", []) + target.get("core_consts", []):
        wanted[name] = 1.0
    goal_heads = {head for g in context.get("goal", []) for head in _key_heads(g) | {g.get("concl_head", "")} if head}
    def shared(item: dict) -> dict[str, float]:
        return {n: wanted[n] * idf(n) for n in _stated(item) if n in wanted and idf(n) > 0}
    statement = set(target.get("consts", [])) | set(target.get("core_consts", []))
    overlap_mass = {item["name"]: sum(wanted[n] * idf(n) for n in _stated(item) & statement) for item in earlier}
    relevant_users = {item["name"]: min(1.0, overlap_mass[item["name"]] / 3.0) for item in earlier}
    used_by: dict[str, float] = {}
    for item in earlier:
        for used in item.get("uses", []):
            used_by[used] = used_by.get(used, 0.0) + relevant_users[item["name"]]
    top_line = max(item["line"] for item in earlier) or 1
    ranked = []
    for item in earlier:
        if item["decl"] not in ("theorem", "def"):
            continue
        mine = shared(item)
        total = sum(idf(n) for n in _stated(item))
        gained = sum(mine.values())
        overlap = WEIGHTS["overlap"] * gained / (gained + 0.5 * max(0.0, total - gained) + 3.0) if gained else 0.0
        matched = sorted(h for h in _key_heads(item) & goal_heads if idf(h) > 0)
        head = WEIGHTS["head"] * min(1.0, max((idf(h) for h in matched), default=0.0) / 2.0)
        left = sum(wanted[n] * idf(n) for n in set(item.get("lhs_consts", [])) if n in wanted)
        equation = WEIGHTS["equation"] * left / (left + 2.0) if item.get("rel") and left else 0.0
        co = WEIGHTS["co_usage"] * min(1.0, used_by.get(item["name"], 0.0) / 3.0)
        relevance = overlap + head + equation + co
        score = relevance + WEIGHTS["distance"] * item["line"] / top_line
        tags = []
        if mine:
            tags.append("mentions " + ", ".join(_short(n) for n in sorted(mine, key=lambda n: (-mine[n], n))[:3]))
        if matched:
            tags.append("concludes " + ", ".join(_short(h) for h in matched[:2]))
        if equation:
            tags.append("rw-ready")
        if co:
            tags.append("used by related lemmas")
        ranked.append({"item": item, "score": round(score, 3), "relevance": round(relevance, 3),
                       "reason": " · ".join(tags)})
    return sorted(ranked, key=lambda r: (-r["score"], r["item"]["name"]))


def _earlier_section(context: dict) -> list[str]:
    """Ranked lemma lines under the character budget; zero-relevance (distance-only) entries fill at most 5 slots."""
    lines, used, filler = [], 0, 0
    for entry in score_earlier(context):
        item = entry["item"]
        if not entry["relevance"]:
            filler += 1
            if filler > 5:
                continue
        tag = f" · {entry['reason']}" if entry["reason"] else ""
        line = (f"line {item['line']} [decl:{item['name']} · {item['decl']}{tag}] "
                f"{_clip(_readable(_one_line(item['sig'])), LIMITS['earlier_chars'])}")
        if used + len(line) > LIMITS["earlier_budget"] or len(lines) >= LIMITS["earlier"]:
            break
        lines.append(line)
        used += len(line) + 1
    return lines


GOALS_FLOOR = 8  # goals kept before library lines are shed when the packet is over budget
LIBRARY_TITLE = "Imported library lemmas matching the statement and goals (ranked)"


def _library_section(context: dict) -> list[str]:
    """Imported theorems ranked by the wrapper (rare constants shared with the statement, the goals and the
    lemmas the source names), minus those the reference proof already uses; fixed line and character budget."""
    known = {item["name"] for item in context.get("source", [])} | {item["name"] for item in context.get("dependency", [])}
    records = [item for item in context.get("library", []) if item["name"] not in known and item.get("sig")]
    if not records:
        return []
    lines = ["Rank by IDF over the imported environment of the constants shared with the theorem statement, its goals "
             "and the lemmas its source names; not already used by the reference proof. `mentions` lists the shared constants."]
    used = 0
    for rank, item in enumerate(records[:LIMITS["library"]], 1):
        shared = ", ".join(_short(name) for name in item.get("shared", [])[:3])
        line = (f"{rank}. [decl:{item['name']} · {item['module']}{' · mentions ' + shared if shared else ''}] "
                f"{_clip(_readable(_one_line(item['sig'])), LIMITS['library_chars'])}")
        if used + len(line) + 1 > LIMITS["library_budget"]:
            break
        lines.append(line)
        used += len(line) + 1
    return lines if len(lines) > 1 else []


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
    # Shed order: earlier-lemma lines, then goals beyond the first few (later goals mostly repeat the same
    # hypotheses), then library lines, then the remaining goals down to one.
    goals = "Goal before each top-level tactic of the reference proof"
    stages = [(EARLIER_TITLE, 0), (goals, GOALS_FLOOR), (LIBRARY_TITLE, 0), (goals, 1)]
    while len(render()) > limit:
        for title, floor in stages:
            target = next((body for t, body in sections if t.startswith(title)), None)
            if target and len(target) > floor:
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
        SCORING_FACTS,
        "Survey the supplied references and pinned source before recording a route with arena_idea. "
        "Then pursue the route and update its status with a reason as evidence arrives. "
        "arena_probe compiles drafts (sorry allowed, goals reported; a draft with `sorry` holes that elaborates is fingerprinted and opens a route, and filling the holes later stays on that route); arena_profile shows where heartbeats go; "
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
        (LIBRARY_TITLE, _library_section(context)),
        (EARLIER_TITLE, _earlier_section(context)),
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
