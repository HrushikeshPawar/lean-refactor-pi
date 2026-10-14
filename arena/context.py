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

from arena.engine import (
    ROOT,
    candidate_file,
    is_standalone,
    measure_version,
    problem,
    run_lean,
    versions,
)
from arena.prices import rates as price_rates
from arena.prices import snippet_tokens, step_table
from arena.profile import MAX_DEPTH, heartbeat_floor, profile
from arena.scoring import REFERENCE_SCORE, exchange_rates
from arena.scoring import reference as scoring_reference
from arena.steps import split_steps
from arena.text import numbers, template
from arena.text import render as render_text

LEAN_FILE = Path(__file__).with_name("lean") / "context.lean"
_RECORD = re.compile(r"^ARENA_CTX (\{.*\})$", re.M)
MAX_PACKET_CHARS = int(numbers()["packet_max_chars"])
CONTEXT_TIMEOUT = 360  # seconds; the library scan adds about 20-40 s to the largest environments
LIMITS = {
    name: int(numbers()[f"packet_{name}"])
    for name in (
        "goals",
        "goal_chars",
        "used",
        "used_chars",
        "earlier",
        "earlier_budget",
        "earlier_chars",
        "earlier_filler",
        "types",
        "profile_lines",
        "type_chars",
        "scope",
        "scope_chars",
        "library",
        "library_budget",
        "library_chars",
        "local_type_chars",
    )
}
DEPENDENCIES_TITLE = template("packet/sections.required.dependencies").strip()
REQUIRED_SECTIONS = (
    template("packet/sections.required.environment").strip(),
    template("packet/sections.required.source").strip(),
    DEPENDENCIES_TITLE,
    template("packet/sections.required.reference").strip(),
)


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
    groups: dict[str, list[dict]] = {
        "goal": [],
        "used": [],
        "source": [],
        "dependency": [],
        "constant": [],
        "local": [],
        "failure": [],
        "type": [],
        "earlier": [],
        "target": [],
        "library": [],
        "library_scan": [],
    }
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
            item["origin"] = "proof" if (item["proof_line"], item.get("column", 0)) >= proof_boundary else "statement"
    for item in groups["dependency"]:
        item["origin"] = "elaborated-proof"
    for item in groups["constant"]:
        item["kind"] = item.pop("decl", "generated/other")
    for item in groups["local"]:
        item["proof_line"] = item["line"] - shift - start_line + 1
    return {"complete": complete and not groups["failure"], **groups}


def constant_index(
    context: dict, name: str | None = None, kind: str | None = None, origin: str | None = None, tag: str | None = None
) -> list[dict]:
    """Query the full elaborated constant inventory by qualified name, kind, origin and tag."""
    items = context.get("constant", [])
    return [
        item
        for item in items
        if (name is None or item["name"] == name)
        and (kind is None or item["kind"] == kind)
        and (origin is None or item["origin"] == origin)
        and (tag is None or item.get("tag") == tag)
    ]


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
    roots = (
        "" if is_standalone(row) else ", ".join(json.dumps(part) for part in sorted({row["file_path"].split("/")[0]}))
    )
    inserted = source.replace("@@ROOTS@@", roots).replace("@@TARGET@@", _lean_name(name))
    built = candidate_file(row, row["src"], version, commit)
    text = built["text"][: built["head"]] + inserted + built["text"][built["head"] :]
    ran = run_lean(row, built["path"], text, timeout=CONTEXT_TIMEOUT, prefix_end=built["head"])
    if ran is None:
        return {"error": render_text("messages/errors.lean_context_timeout")}
    _returncode, output = ran
    parsed = parse_context(output, inserted.count("\n"), built["start_line"], _proof_boundary(row["src"], 1))
    if not parsed["complete"]:
        reason = (
            parsed["failure"][0].get("message")
            if parsed["failure"]
            else next((line for line in output.splitlines() if "error" in line), "no context records")
        )
        return {"error": reason[:200]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(parsed, ensure_ascii=False, indent=1))
    return parsed


def cached_context(name: str) -> dict:
    """The kickoff context if it is already cached, else {}; never starts Lean."""
    try:
        row = problem(name)
        _version, commit = measure_version(row)
        cache = _cache("context", name, commit, LEAN_FILE.read_text() + row["src"])
        return json.loads(cache.read_text()) if cache.exists() else {}
    except (ValueError, OSError, KeyError):
        return {}


def reference_profile(name: str, cache_only: bool = False) -> dict:
    """Heartbeat profile of the reference proof, cached like the context."""
    row = problem(name)
    _version, commit = measure_version(row)
    salt = (
        (Path(__file__).with_name("lean") / "profile.lean").read_text()
        + row["src"]
        + str(MAX_DEPTH)
        + "profile-schema-v3-innermost-span-token-hotspots"
    )
    cache = _cache("profile", name, commit, salt)
    if cache.exists():
        return json.loads(cache.read_text())
    if cache_only:
        return {}
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


_SCOPE = re.compile(
    r"^(?:@\[[^\]]*\]\s*)?(?:public\s+|private\s+)?(?:noncomputable\s+)?"
    r"(namespace|section|end|open|variable|universe|include|omit)\b(.*)$"
)
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
        source = built["text"][: built["head"]]
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
    body = [
        render_text("packet/sections.fixed.namespace", name=namespace)
        if namespace
        else template("packet/sections.fixed.root_namespace").strip()
    ] + [text for _, text in active]
    return [_clip(line, LIMITS["scope_chars"]) for line in body][: LIMITS["scope"]]


def _types_section(context: dict) -> list[str]:
    lines = []
    for item in context.get("type", [])[: LIMITS["types"]]:
        if item["decl"] in ("inductive", "structure"):
            body = "\n".join(f"  | {_clip(c, LIMITS['type_chars'])}" for c in item["ctors"])
            lines.append(
                render_text(
                    "packet/sections.fixed.type_construct",
                    name=item["name"],
                    kind=item["decl"],
                    signature=_clip(_readable(item["sig"]), LIMITS["type_chars"]),
                    body=_readable(body),
                )
            )
        else:
            lines.append(
                render_text(
                    "packet/sections.fixed.type_definition",
                    name=item["name"],
                    signature=_clip(item["sig"], LIMITS["type_chars"]),
                    value=_clip(item.get("value", ""), LIMITS["type_chars"]),
                )
            )
    return lines


def _profile_section(prof: dict, src: str, name: str) -> list[str]:
    """Per-line self heartbeats of the reference proof, the unattributed remainder, and own-name references."""
    lines = prof.get("line_profile") or []
    measured, attributed, remainder = prof.get("measured_total"), prof.get("profiled_total"), prof.get("unattributed")
    if not lines or measured is None or attributed is None or remainder is None:
        return []
    top = sorted((x for x in lines if x["self_hb"] > 0), key=lambda x: -x["self_hb"])[: LIMITS["profile_lines"]]
    body = [
        render_text(
            "packet/sections.fixed.profile_line",
            line=x["proof_line"],
            self_hb=x["self_hb"],
            tokens=x["tokens"],
            text=_clip(x["text"].strip(), 70),
        )
        for x in sorted(top, key=lambda x: x["proof_line"])
    ]
    body.append(
        render_text(
            "packet/sections.fixed.profile_total",
            measured=measured,
            attributed=attributed,
            shown=len(top),
            remainder=remainder,
            share=round(100 * remainder / measured, 1) if measured else 0,
        )
    )
    short = re.escape(name.rsplit(".", 1)[-1])
    own = re.compile(rf"(?<![\w.'])(?:{re.escape(name)}|{short})(?![\w'])")
    refs = [str(number) for number, text in enumerate(src.splitlines(), 1) if number > 1 and own.search(text)]
    if refs and remainder > 0:
        body.append(render_text("packet/sections.fixed.profile_selfref", lines=", ".join(refs), remainder=remainder))
    return body


def _goal_section(context: dict, proof: str) -> list[str]:
    lines = []
    goals = {item["proof_line"]: item for item in context.get("goal", [])}
    for step in split_steps(proof)[: LIMITS["goals"]]:
        item = goals.get(step.first_line)
        lines.append(
            render_text(
                "packet/sections.fixed.goal",
                step=step.id,
                text=_clip(item["text"], LIMITS["goal_chars"])
                if item
                else template("packet/sections.fixed.goal_unavailable").strip(),
            )
        )
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
    return sorted((i for i in items if i.get("tag", "helper") == "helper"), key=lambda i: _rank(i, root))[
        : LIMITS["used"]
    ]


def _used_section(context: dict) -> list[str]:
    occurrences: dict[str, list[dict]] = {}
    for item in context.get("source", []):
        occurrences.setdefault(item["name"], []).append(item)
    ordered = sorted(occurrences.items())
    lines = [template("packet/sections.fixed.used_intro").strip()]
    for name, items in ordered:
        statement = ",".join(str(i["proof_line"]) for i in items if i.get("origin") == "statement")
        proof = ",".join(str(i["proof_line"]) for i in items if i.get("origin") == "proof")
        unknown = ",".join(str(i["proof_line"]) for i in items if i.get("origin") == "unknown")
        lines.append(
            render_text(
                "packet/sections.fixed.used_line",
                name=name,
                kind=items[0]["decl"],
                statement=statement or "-",
                proof=proof or "-",
                unknown=f" U:{unknown}" if unknown else "",
            )
        )
    preview = _preview([items[0] for _, items in ordered], context.get("root", ""))
    lines.extend(
        [
            "",
            render_text(
                "packet/sections.fixed.used_preview",
                shown=sum(bool(i.get("sig")) for i in preview),
                distinct=len(ordered),
                unavailable=sum(not bool(items[0].get("sig")) for _, items in ordered),
            ),
        ]
    )
    lines.extend(
        render_text(
            "packet/sections.fixed.signature",
            name=i["name"],
            kind=i["decl"],
            module=i["module"],
            signature=_clip(_readable(_one_line(i["sig"])), LIMITS["used_chars"]),
        )
        for i in preview
        if i.get("sig")
    )
    return lines


def _dependency_section(context: dict) -> list[str]:
    helpers, counts, named = _extra_dependencies(context)
    if not helpers:
        return []
    lines = [template("packet/sections.fixed.dependency_intro").strip()]
    lines.extend(render_text("packet/sections.fixed.dependency_name", name=i["name"]) for i in helpers)
    lines += [
        "",
        render_text(
            "packet/sections.fixed.dependency_summary",
            counts=", ".join(f"{tag} {n}" for tag, n in counts.items()),
            named=named,
        ),
    ]
    preview = _preview(helpers, context.get("root", ""))
    lines += [
        render_text(
            "packet/sections.fixed.dependency_preview",
            shown=sum(bool(i.get("sig")) for i in preview),
            helpers=len(helpers),
            unavailable=sum(not bool(i.get("sig")) for i in helpers),
        ),
    ]
    lines.extend(
        render_text(
            "packet/sections.fixed.signature",
            name=i["name"],
            kind=i["decl"],
            module=i["module"],
            signature=_clip(_readable(_one_line(i["sig"])), LIMITS["used_chars"]),
        )
        for i in preview
        if i.get("sig")
    )
    return lines


def _local_section(context: dict) -> list[str]:
    scopes: dict[tuple[str, str, str], set[int]] = {}
    for item in context.get("local", []):
        scopes.setdefault((item["name"], item["type"], item["scope"]), set()).add(item["proof_line"])
    if not scopes:
        return []
    lines = [template("packet/sections.fixed.local_intro").strip()]
    lines.extend(
        render_text(
            "packet/sections.fixed.local_line",
            name=name,
            type=_clip(_one_line(ty), LIMITS["local_type_chars"]),
            scope=scope,
            lines=",".join(map(str, sorted(locations))),
        )
        for (name, ty, scope), locations in sorted(scopes.items())
    )
    return lines


def _imports(row: dict) -> list[str]:
    if is_standalone(row):
        source = row.get("header") or ""
    else:
        built = candidate_file(row, row["src"], *measure_version(row))
        source = built["text"][: built["head"]]
    return [match.group(0).strip() for match in re.finditer(r"(?m)^\s*import\s+[^\n]+", source)]


def packet_manifest(parts: list[tuple[str, list[str]]], inventory: dict) -> dict:
    present = {title for title, body in parts if body}
    # The dependencies section exists only when the proof uses helpers beyond the source-named declarations.
    helpers = bool(_extra_dependencies(inventory)[0])
    sections = {
        title: {
            "expected": helpers or title != DEPENDENCIES_TITLE,
            "present": any(p.startswith(title) for p in present),
        }
        for title in REQUIRED_SECTIONS
    }
    return {
        "schema": "arena-kickoff-manifest/v1",
        "sections": sections,
        "source_inventory": len(inventory.get("source", [])),
        "dependency_helpers": len(_extra_dependencies(inventory)[0]),
        "dependency_tags": _extra_dependencies(inventory)[1],
        "complete": bool(inventory.get("complete")),
    }


def certify_manifest(manifest: dict, expected: list[str] | None = None) -> dict:
    required = expected or list(REQUIRED_SECTIONS)
    sections = manifest.get("sections", {})
    missing = [
        name
        for name in required
        if sections.get(name, {}).get("expected", True) and not sections.get(name, {}).get("present")
    ]
    reasons = ["context extraction incomplete"] if not manifest.get("complete") else []
    if missing:
        reasons.append("required sections absent: " + ", ".join(missing))
    return {"certified": not reasons, "reasons": reasons}


EARLIER_TITLE = template("packet/sections.titles.earlier").strip()
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
    core |= {
        c["name"]
        for c in context.get("constant", [])
        if c.get("tag") == "core" or c.get("module", "").split(".")[0] in ("Init", "Std", "Lean")
    }

    def idf(name: str) -> float:
        seen = frequency.get(name, 0)
        if seen > GENERIC_SHARE * count:
            return 0.0
        return (CORE_FACTOR if name in core else 1.0) * math.log((count + 1) / (seen + 0.5))

    target = (context.get("target") or [{}])[0]
    wanted: dict[str, float] = {}
    for name in [c["name"] for c in context.get("constant", [])] + [
        n for g in context.get("goal", []) for n in g.get("consts", []) + g.get("core_consts", [])
    ]:
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
            tags.append(
                render_text(
                    "packet/sections.fixed.earlier_mention",
                    names=", ".join(_short(n) for n in sorted(mine, key=lambda n: (-mine[n], n))[:3]),
                )
            )
        if matched:
            tags.append(
                render_text("packet/sections.fixed.earlier_conclusion", names=", ".join(_short(h) for h in matched[:2]))
            )
        if equation:
            tags.append(template("packet/sections.fixed.earlier_rewrite").strip())
        if co:
            tags.append(template("packet/sections.fixed.earlier_usage").strip())
        ranked.append(
            {"item": item, "score": round(score, 3), "relevance": round(relevance, 3), "reason": " · ".join(tags)}
        )
    return sorted(ranked, key=lambda r: (-r["score"], r["item"]["name"]))


def _earlier_section(context: dict) -> list[str]:
    """Ranked lemma lines under the character budget; zero-relevance (distance-only) entries fill at most 5 slots."""
    lines, used, filler = [], 0, 0
    for entry in score_earlier(context):
        item = entry["item"]
        if not entry["relevance"]:
            filler += 1
            if filler > LIMITS["earlier_filler"]:
                continue
        tag = render_text("packet/sections.fixed.earlier_reason", text=entry["reason"]) if entry["reason"] else ""
        line = render_text(
            "packet/sections.fixed.earlier_line",
            line=item["line"],
            name=item["name"],
            kind=item["decl"],
            reason=tag,
            signature=_clip(_readable(_one_line(item["sig"])), LIMITS["earlier_chars"]),
        )
        if used + len(line) > LIMITS["earlier_budget"] or len(lines) >= LIMITS["earlier"]:
            break
        lines.append(line)
        used += len(line) + 1
    return lines


LOCAL_TITLE = template("packet/sections.titles.locals").strip()
GOALS_FLOOR = int(numbers()["packet_goal_floor"])
LIBRARY_TITLE = template("packet/sections.titles.library").strip()


def _library_section(context: dict) -> list[str]:
    """Imported theorems ranked by the wrapper (rare constants shared with the statement, the goals and the
    declarations the source names), minus those the reference proof already uses; fixed line and character budget."""
    known = {item["name"] for item in context.get("source", [])} | {
        item["name"] for item in context.get("dependency", [])
    }
    records = [item for item in context.get("library", []) if item["name"] not in known and item.get("sig")]
    lines: list[str] = []
    used = 0
    for rank, item in enumerate(records[: LIMITS["library"]], 1):
        line = render_text(
            "packet/sections.fixed.library_line",
            rank=rank,
            name=item["name"],
            module=item["module"],
            signature=_clip(_readable(_one_line(item["sig"])), LIMITS["library_chars"]),
        )
        if used + len(line) + 1 > LIMITS["library_budget"]:
            break
        lines.append(line)
        used += len(line) + 1
    return lines


def _join_sections(sections: list[tuple[str, list[str]]]) -> str:
    return "\n\n".join((f"{title}\n" if title else "") + "\n".join(body) for title, body in sections if body)


def _fit_sections(parts: list[tuple[str, list[str]]], limit: int) -> list[tuple[str, list[str]]]:
    """Shed entries from the end of the lowest-priority sections."""
    sections = [(title, list(body)) for title, body in parts]

    # Earlier declarations, excess goals, all locals, library entries, then remaining goals.
    goals = template("packet/sections.titles.goals").strip()
    stages = [(EARLIER_TITLE, 0), (goals, GOALS_FLOOR), (LOCAL_TITLE, 0), (LIBRARY_TITLE, 0), (goals, 1)]
    while len(_join_sections(sections)) > limit:
        for title, floor in stages:
            target = next((body for t, body in sections if t.startswith(title)), None)
            if target and len(target) > floor:
                target.pop()
                break
        else:
            break
    if len(_join_sections(sections)) > limit:
        raise ValueError(render_text("packet/sections.fixed.budget_certification_failed"))
    return [(title, body) for title, body in sections if body]


def _fit(parts: list[tuple[str, list[str]]], limit: int) -> str:
    return _join_sections(_fit_sections(parts, limit))


def _reference_price_table(table: dict) -> list[str]:
    """The step table (one renderer with the read view's prices) and its column legend; the rates are in Scoring."""
    from arena.campaign import render_price_table

    return [*render_price_table(table).splitlines(), *template("packet/price-table.legend").strip().splitlines()]


def packet_sections(name: str, *, cache_only: bool = False) -> list[tuple[str, str]]:
    row = problem(name)
    targets = versions(row)
    context = cached_context(name) if cache_only else lean_context(name)
    if cache_only and not context:
        raise ValueError(f"Cached context is unavailable for {name}")  # not-model-facing: CLI cache refusal.
    context["root"] = "" if is_standalone(row) else row["file_path"].split("/")[0]
    prof = reference_profile(name, cache_only=cache_only)
    if cache_only and not prof:
        raise ValueError(f"Cached reference profile is unavailable for {name}")  # not-model-facing: CLI cache refusal.
    pins = "; ".join(
        render_text("packet/sections.fixed.pin", version=version, commit=commit) for version, commit in targets
    )
    rates = exchange_rates(name, len(targets))
    task = render_text("packet/task", name=name, statement=row["statement"]).strip().splitlines()
    scoring = (
        render_text(
            "packet/scoring",
            points_per_token=rates["points_per_token"],
            points_per_100_heartbeats=rates["points_per_100_heartbeats"],
            points_per_lost_version=rates["points_per_lost_version"],
            reference_tokens=rates["reference_tokens"],
            reference_heartbeats=rates["reference_heartbeats"],
            example_short=snippet_tokens("exact foo"),
            example_pair=snippet_tokens("⟨a, b⟩"),
        )
        .strip()
        .splitlines()
    )
    table = step_table(
        row["src"],
        prof,
        price_rates(*scoring_reference(name), len(targets)),
        row["proof_length"],
        prof.get("measured_total"),
        f"{len(targets)}/{len(targets)}",
    )
    table["total"]["proxy"] = REFERENCE_SCORE
    price_lines = _reference_price_table(table)
    note = (
        ""
        if not context.get("error")
        else render_text("packet/sections.fixed.context_missing", error=_clip(context["error"], 160))
    )
    titles = {
        key: template(f"packet/sections.titles.{key}").strip()
        for key in ("pinned", "types", "scope", "goals", "source", "dependencies")
    }
    source_line = (
        render_text("packet/sections.fixed.standalone_source", source=row["source"])
        if is_standalone(row)
        else render_text(
            "packet/sections.fixed.source",
            source=row["source"],
            path=row["file_path"],
            start=row["start_line"],
            end=row["end_line"],
        )
    )
    parts: list[tuple[str, list[str]]] = [
        ("", task),
        ("", scoring),
        (
            titles["pinned"],
            [
                source_line,
                render_text("packet/sections.fixed.pins", pins=pins),
                render_text(
                    "packet/sections.fixed.imports",
                    imports=", ".join(_imports(row)) or template("packet/sections.fixed.none").strip(),
                ),
            ],
        ),
        (titles["scope"], _scope_section(row)),
        (
            render_text("packet/sections.titles.reference", count=row["proof_length"]),
            [f"```lean\n{row['src']}\n```", *price_lines],
        ),
        (template("packet/sections.titles.profile").strip(), _profile_section(prof, row["src"], name)),
        (titles["goals"], _goal_section(context, row["src"])),
        (LIBRARY_TITLE, _library_section(context)),
        (titles["types"], _types_section(context)),
        (titles["source"], _used_section(context)),
        (titles["dependencies"], _dependency_section(context)),
        (LOCAL_TITLE, _local_section(context)),
        (EARLIER_TITLE, _earlier_section(context)),
    ]
    if note:
        parts.append(("", [note]))
    manifest = packet_manifest(parts, context)
    result = certify_manifest(manifest)
    if not result["certified"]:
        raise ValueError(
            render_text("packet/sections.fixed.packet_not_certifiable", reasons="; ".join(result["reasons"]))
        )
    fitted = _fit_sections(parts, MAX_PACKET_CHARS)
    return [
        (
            title or ("Task" if index == 0 else "Scoring" if index == 1 else "Notice"),
            (f"{title}\n" if title else "") + "\n".join(body),
        )
        for index, (title, body) in enumerate(fitted)
    ]


def render_packet(name: str, *, cache_only: bool = False) -> str:
    return "\n\n".join(content for _title, content in packet_sections(name, cache_only=cache_only)) + "\n"
