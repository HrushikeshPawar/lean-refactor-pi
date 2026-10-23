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
    LeanInconclusive,
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


def parse_context(
    output: str,
    shift: int,
    start_line: int,
    proof_boundary: tuple[int, int] | None = None,
    *,
    insertion_line: int | None = None,
) -> dict:
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
    insertion_line = start_line if insertion_line is None else insertion_line
    for raw in _RECORD.findall(output):
        record = json.loads(raw)
        kind = record["kind"]
        if kind == "end":
            complete = True
        elif kind in groups:
            groups[kind].append(record)
    def place(item: dict, *, end: bool = False) -> str:
        """`inside` the target span, or `external` with the original file line. Never a negative target-relative line."""
        if insertion_line <= item["line"] < insertion_line + shift:
            item["origin"] = "unknown"
            item.pop("proof_line", None)
            item.pop("source_line", None)
            return "unknown"
        file_line = item["line"] - (shift if item["line"] >= insertion_line + shift else 0)
        relative = file_line - start_line + 1
        if relative < 1:
            item["source_line"] = file_line
            item.pop("proof_line", None)
            return "external"
        item["proof_line"] = relative
        if end and not insertion_line <= item["endLine"] < insertion_line + shift:
            end_line = item["endLine"] - (shift if item["endLine"] >= insertion_line + shift else 0)
            item["end_proof_line"] = end_line - start_line + 1
        return "inside"

    for item in groups["goal"]:
        place(item, end=True)
    for item in groups["used"]:
        place(item)
    for item in groups["source"]:
        where = place(item)
        if where == "external":
            item["origin"] = "external"
        elif where == "unknown":
            item["origin"] = "unknown"
        elif proof_boundary is None:
            item.setdefault("origin", "unknown")  # no top-level `:=` (e.g. equation-compiler proofs): do not guess
        else:
            item["origin"] = "proof" if (item["proof_line"], item.get("column", 0)) >= proof_boundary else "statement"
    for item in groups["dependency"]:
        item["origin"] = "elaborated-proof"
    for item in groups["constant"]:
        item["kind"] = item.pop("decl", "generated/other")
    for item in groups["local"]:
        if place(item) == "external":
            item["origin"] = "external"
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
        elif source[i] in "([{⦃":
            depth += 1
            i += 1
        elif source[i] in ")]}⦄":
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
    try:
        ran = run_lean(
            row, built["path"], text, timeout=CONTEXT_TIMEOUT, prefix_end=built["head"], request_class="opportunistic"
        )
    except LeanInconclusive as error:
        return {"error": render_text("messages/errors.lean_admission", cause=error.cause, admission=error.admission)}
    if ran is None:
        return {"error": render_text("messages/errors.lean_context_timeout")}
    _returncode, output = ran
    parsed = parse_context(
        output,
        inserted.count("\n"),
        built["start_line"],
        _proof_boundary(row["src"], 1),
        insertion_line=built["text"][: built["head"]].count("\n") + 1,
    )
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


def _type_items(context: dict) -> tuple[list[dict], list[dict]]:
    """Statement predicates first. The count limit applies only after those are kept."""
    items = list(context.get("type", []))
    if not any("role" in item for item in items):
        # Older caches did not record roles: do not mistake inventory order for relevance.
        return items, []
    statement = [item for item in items if item.get("role") == "statement"]
    auxiliary = [item for item in items if item.get("role") != "statement"]
    if len(statement) >= LIMITS["types"]:
        return statement, auxiliary
    room = LIMITS["types"] - len(statement)
    return statement + auxiliary[:room], auxiliary[room:]


def _types_section(context: dict) -> list[str]:
    chosen, omitted = _type_items(context)
    lines = []
    catalog = _catalog_names(context)
    for item in chosen:
        if item["decl"] in ("inductive", "structure"):
            body = "\n".join(f"  | {_clip(c, LIMITS['type_chars'])}" for c in item["ctors"])
            lines.append(
                render_text(
                    "packet/sections.fixed.type_construct",
                    name=item["name"],
                    kind=item["decl"],
                    signature="" if item["name"] in catalog else _clip(_readable(item["sig"]), LIMITS["type_chars"]),
                    body=_readable(body),
                )
            )
        else:
            lines.append(
                render_text(
                    "packet/sections.fixed.type_definition",
                    name=item["name"],
                    kind=item["decl"],
                    signature="" if item["name"] in catalog else _clip(item["sig"], LIMITS["type_chars"]),
                    value=_clip(item.get("value", ""), LIMITS["type_chars"]),
                )
            )
    if chosen or omitted:
        lines.append(
            render_text(
                "packet/sections.fixed.type_coverage",
                shown=len(chosen),
                omitted=len(omitted),
                unknown=sum("role" not in item for item in context.get("type", [])),
            )
        )
    return lines


def _profile_section(prof: dict, src: str, name: str) -> list[str]:
    """Measured attribution coverage and own-name references; self costs stay in detail."""
    measured, attributed, remainder = prof.get("measured_total"), prof.get("profiled_total"), prof.get("unattributed")
    if measured is None or attributed is None or remainder is None:
        return []
    body = []
    body.append(
        render_text(
            "packet/sections.fixed.profile_total",
            measured=measured,
            attributed=attributed,
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


def _goal_blocks(text: str) -> list[tuple[str, list[str], str]]:
    """Keep each case's complete conclusion, including its indented continuation."""
    blocks: list[tuple[str, list[str], str]] = []
    case = ""
    hypotheses: list[str] = []
    conclusion: list[str] = []

    def finish() -> None:
        if conclusion:
            blocks.append((case, list(hypotheses), "\n".join(conclusion)))

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("case ") and "⊢" not in line:
            finish()
            case, hypotheses, conclusion = line, [], []
        elif "⊢" in line:
            if conclusion:
                # Unlabelled multiple goals are separated by a new turnstile.
                finish()
                case, hypotheses, conclusion = "", [], []
            before, _, after = line.partition("⊢")
            if before.strip():
                hypotheses.append(before.strip())
            conclusion = ["⊢ " + after.strip()]
        elif conclusion:
            if raw[:1].isspace():
                conclusion.append(raw)
            else:
                # A new unlabelled local context follows the previous goal.
                finish()
                case, hypotheses, conclusion = "", [line], []
        else:
            hypotheses.append(line)
    finish()
    return blocks


def _show_goal(text: str, limit: int) -> tuple[str, bool]:
    """Keep every scoped conclusion; the display budget may clip hypotheses only."""
    raw = text.strip()
    blocks = _goal_blocks(raw)
    if not blocks:
        return (_clip(raw, limit), len(raw) > limit)
    shared = (
        [line for line in blocks[0][1] if all(line in hypotheses for _, hypotheses, _ in blocks)]
        if len(blocks) > 1 else []
    )
    parts = [render_text("packet/sections.fixed.goal_shared", text=" ; ".join(shared))] if shared else []
    for case, hypotheses, conclusion in blocks:
        label = f"{case}: " if case else ""
        own = [line for line in hypotheses if line not in shared]
        local = ("; ".join(own) + " ") if own else ""
        parts.append(f"{label}{local}{conclusion}")
    shown = " | ".join(parts)
    if len(shown) <= limit:
        return shown, False
    conclusions = " | ".join(
        f"{case}: {conclusion}" if case else conclusion for case, _hypotheses, conclusion in blocks
    )
    prefix = parts[0] if shared else ""
    room = limit - len(conclusions) - 3
    if prefix and room > 1:
        return f"{prefix[:room - 1].rstrip()}… | {conclusions}", True
    return conclusions, True


def _goal_facts(context: dict, proof: str) -> tuple[list, list[tuple | None], int]:
    """One pass: rendered goal text per step, and how many displays were clipped."""
    steps = split_steps(proof)
    goals = {item["proof_line"]: item for item in context.get("goal", []) if "proof_line" in item}
    rendered: list[tuple | None] = []
    clipped = 0
    captured = 0
    for step in steps:
        item = goals.get(step.first_line)
        if not item or not item.get("text", "").strip():
            rendered.append(None)
            continue
        text, was_clipped = _show_goal(item.get("text", ""), LIMITS["goal_chars"])
        captured += 1
        clipped += int(was_clipped and captured <= LIMITS["goals"])
        rendered.append((step, text))
    return steps, rendered, clipped


def context_coverage(context: dict, proof: str, *, facts: tuple | None = None) -> dict:
    """Usable context coverage. Separate from extraction `complete`."""
    steps, rendered, clipped = facts if facts is not None else _goal_facts(context, proof)
    captured = sum(item is not None for item in rendered)
    _shown, omitted_types = _type_items(context)
    return {
        "extraction_complete": bool(context.get("complete")),
        "goals_captured": captured,
        "goals_expected": len(steps),
        "goals_omitted": len(steps) - captured,
        "display_clipped": clipped,
        "goals_displayed": min(captured, LIMITS["goals"]),
        "goal_display_omitted": max(0, captured - LIMITS["goals"]),
        "definitions_omitted": len(omitted_types),
    }


def _goal_section(context: dict, proof: str, *, facts: tuple | None = None) -> list[str]:
    steps, rendered, clipped = facts if facts is not None else _goal_facts(context, proof)
    captured = sum(item is not None for item in rendered)
    available = [item for item in rendered if item is not None]
    shown = available[: LIMITS["goals"]]
    lines = [
        render_text("packet/sections.fixed.goal", step=step.id, line=step.first_line, text=text) for step, text in shown
    ]
    lines.append(
        render_text(
            "packet/sections.fixed.goal_coverage",
            captured=captured,
            expected=len(steps),
            omitted=len(steps) - captured,
            extraction="complete" if context.get("complete") else "incomplete",
            clipped=clipped,
            displayed=len(shown),
            display_omitted=len(available) - len(shown),
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


def _catalog_names(context: dict) -> set[str]:
    helpers, _counts, _named = _extra_dependencies(context)
    return {item["name"] for item in context.get("source", [])} | {item["name"] for item in helpers}


def _used_section(context: dict, *, signatures: bool = True) -> list[str]:
    occurrences: dict[str, list[dict]] = {}
    for item in context.get("source", []):
        occurrences.setdefault(item["name"], []).append(item)
    helpers, _counts, _named = _extra_dependencies(context)
    for item in helpers:
        occurrences.setdefault(item["name"], [item])
    lines = [template("packet/sections.fixed.used_intro").strip()]
    unavailable = 0
    for name, items in sorted(occurrences.items()):
        item = next((item for item in items if item.get("sig")), items[0])
        role = item.get("decl") or item.get("tag") or "declaration"
        locations = []
        for origin in ("statement", "proof", "unknown"):
            places = sorted({i["proof_line"] for i in items
                             if i.get("proof_line") is not None and i.get("origin", "unknown") == origin})
            if places:
                locations.append(render_text(f"packet/sections.fixed.catalog_{origin}",
                                             lines=", ".join(map(str, places))))
        external = sorted({i["source_line"] for i in items if i.get("source_line") is not None})
        if external:
            locations.append(render_text("packet/sections.fixed.catalog_external", lines=", ".join(map(str, external)),
                                             module=item.get("module") or template("packet/sections.fixed.catalog_location_missing").strip()))
        where = "; ".join(locations) or item.get("module") or template("packet/sections.fixed.catalog_location_missing").strip()
        unavailable += not bool(item.get("sig"))
        signature = ("" if not signatures else
                     _clip(_readable(_one_line(item["sig"])), LIMITS["used_chars"]) if item.get("sig") else
                     template("packet/sections.fixed.catalog_signature_missing").strip())
        lines.append(render_text("packet/sections.fixed.catalog_line", name=name, role=role, where=where, signature=signature))
    lines.append(render_text("packet/sections.fixed.used_preview", shown=len(occurrences) - unavailable if signatures else 0,
                             distinct=len(occurrences), unavailable=unavailable))
    if not signatures:
        lines.append(render_text("packet/sections.fixed.catalog_signatures_omitted", count=len(occurrences) - unavailable))
    return lines


def _dependency_section(context: dict) -> list[str]:
    helpers, counts, named = _extra_dependencies(context)
    if not helpers:
        return []
    lines = [template("packet/sections.fixed.dependency_intro").strip()]
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
    return lines


def _imports(row: dict) -> list[str]:
    if is_standalone(row):
        source = row.get("header") or ""
    else:
        built = candidate_file(row, row["src"], *measure_version(row))
        source = built["text"][: built["head"]]
    return [
        match.group(0).strip()
        for match in re.finditer(r"(?m)^[ \t]*(?:public[ \t]+)?import\s+[^\n]+", source)  # log: regex # not-model-facing
    ]


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
    catalog = _catalog_names(context)
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
            signature="" if item["name"] in catalog else _clip(_readable(_one_line(item["sig"])), LIMITS["earlier_chars"]),
        )
        if used + len(line) > LIMITS["earlier_budget"] or len(lines) >= LIMITS["earlier"]:
            break
        lines.append(line)
        used += len(line) + 1
    return lines


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

    # Shed low-value bulk before useful earlier lemmas. Goals keep a floor, then a last line.
    goals = template("packet/sections.titles.goals").strip()
    stages = [(LIBRARY_TITLE, 0), (goals, GOALS_FLOOR), (EARLIER_TITLE, 0), (goals, 1)]
    coverage_prefix = template("packet/sections.fixed.goal_coverage").split("{")[0]
    footer = next((body[-1] for title, body in sections if title == goals and body
                   and body[-1].startswith(coverage_prefix)), None)
    goal_omissions = 0
    while len(_join_sections(sections)) > limit:
        for title, floor in stages:
            target = next((body for t, body in sections if t.startswith(title)), None)
            has_footer = title == goals and footer is not None
            if target and len(target) - int(has_footer) > floor:
                target.pop(-2 if has_footer else -1)
                if has_footer:
                    goal_omissions += 1
                    target[-1] = footer + " " + render_text(
                        "packet/sections.fixed.goal_fit_omissions", count=goal_omissions
                    )
                break
        else:
            break
    if len(_join_sections(sections)) > limit:
        raise ValueError(render_text("packet/sections.fixed.budget_certification_failed"))
    return [(title, body) for title, body in sections if body]


def _fit(parts: list[tuple[str, list[str]]], limit: int) -> str:
    return _join_sections(_fit_sections(parts, limit))


def _reference_price_table(table: dict, proof: str, profile: dict | None) -> list[str]:
    """Shared structural overview, nested hotspot, and full-detail pointer."""
    from arena.campaign import render_price_table

    return render_price_table(table, proof, profile, proof_id="reference").splitlines()


def _team_section(model: str | None, golf: dict | None = None) -> list[str]:
    """The orchestrator's team paragraph. Worker count, model and the output-price ratio are computed here.

    `golf` ({"workers", "worker_model"}) swaps in the polishing-session paragraph for a run that starts from a best proof."""
    if model is None:
        return []
    from arena.models import _SESSION_CONCURRENCY, load
    from arena.pi_rpc import WORKER_MODEL

    worker_model = golf["worker_model"] if golf else WORKER_MODEL
    workers = golf["workers"] if golf else _SESSION_CONCURRENCY[WORKER_MODEL]
    prices = load()["models"]
    # One simple rule: how many times cheaper a worker's output token is than the orchestrator's.
    ratio = round(prices[model]["price"]["output"] / prices[worker_model]["price"]["output"])
    cost = render_text("packet/team-cost", ratio=ratio) if ratio > 1 else ""
    return render_text(
        "packet/golf-team" if golf else "packet/team", workers=workers, worker_model=worker_model, cost=cost
    ).strip().splitlines()


def golf_start_section(node: str, score, proof: str) -> str:
    """The seeded best proof, appended to a polishing session's first prompt."""
    return render_text("packet/golf-start", node=node, score=score, proof=proof.strip()).strip()


def _scoring_lines(rates: dict) -> list[str]:
    """The scoring contract, shared by every actor's startup packet."""
    return (
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


def _pinned_part(row: dict, targets: list) -> tuple[str, list[str]]:
    """Source, required toolchains and imports, shared by every actor's startup packet."""
    pins = "; ".join(render_text("packet/sections.fixed.pin", version=version) for version, _commit in targets)
    pins = f"{len(targets)} required ({pins})"
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
    return (
        template("packet/sections.titles.pinned").strip(),
        [
            source_line,
            render_text("packet/sections.fixed.pins", pins=pins),
            render_text(
                "packet/sections.fixed.imports",
                imports=", ".join(_imports(row)) or template("packet/sections.fixed.none").strip(),
            ),
        ],
    )


def packet_sections(
    name: str, *, cache_only: bool = False, model: str | None = None, golf: dict | None = None
) -> list[tuple[str, str]]:
    row = problem(name)
    targets = versions(row)
    context = cached_context(name) if cache_only else lean_context(name)
    if cache_only and not context:
        raise ValueError(f"Cached context is unavailable for {name}")  # not-model-facing: CLI cache refusal.
    context["root"] = "" if is_standalone(row) else row["file_path"].split("/")[0]
    prof = reference_profile(name, cache_only=cache_only)
    if cache_only and not prof:
        raise ValueError(f"Cached reference profile is unavailable for {name}")  # not-model-facing: CLI cache refusal.
    rates = exchange_rates(name, len(targets))
    task = render_text("packet/task", name=name, statement=row["statement"]).strip().splitlines()
    scoring = _scoring_lines(rates)
    table = step_table(
        row["src"],
        prof,
        price_rates(*scoring_reference(name), len(targets)),
        row["proof_length"],
        prof.get("measured_total"),
        f"{len(targets)}/{len(targets)}",
    )
    table["total"]["proxy"] = REFERENCE_SCORE
    price_lines = _reference_price_table(table, row["src"], prof)
    note = (
        ""
        if not context.get("error")
        else render_text("packet/sections.fixed.context_missing", error=_clip(context["error"], 160))
    )
    titles = {
        key: template(f"packet/sections.titles.{key}").strip()
        for key in ("types", "scope", "goals", "source", "dependencies")
    }
    goal_facts = _goal_facts(context, row["src"])
    parts: list[tuple[str, list[str]]] = [
        ("", task),
        ("", scoring),
        _pinned_part(row, targets),
        (titles["scope"], _scope_section(row)),
        (
            render_text("packet/sections.titles.reference", count=row["proof_length"]),
            [f"```lean\n{row['src']}\n```", template("packet/sections.fixed.numbered_source").strip(), *price_lines],
        ),
        (template("packet/sections.titles.profile").strip(), _profile_section(prof, row["src"], name)),
        ("", template("packet/search").strip().splitlines()),
        (template("packet/sections.titles.team").strip(), _team_section(model, golf)),
        (titles["goals"], _goal_section(context, row["src"], facts=goal_facts)),
        (LIBRARY_TITLE, _library_section(context)),
        (titles["types"], _types_section(context)),
        (titles["source"], _used_section(context)),
        (titles["dependencies"], _dependency_section(context)),
        (EARLIER_TITLE, _earlier_section(context)),
    ]
    if note:
        parts.append(("", [note]))
    manifest = packet_manifest(parts, context)
    manifest["coverage"] = context_coverage(context, row["src"], facts=goal_facts)
    result = certify_manifest(manifest)
    if not result["certified"]:
        raise ValueError(
            render_text("packet/sections.fixed.packet_not_certifiable", reasons="; ".join(result["reasons"]))
        )
    try:
        fitted = _fit_sections(parts, MAX_PACKET_CHARS)
    except ValueError:
        # Keep every declaration and source coordinate when signature previews cannot fit.
        compact = [(title, _used_section(context, signatures=False) if title == titles["source"] else body)
                   for title, body in parts]
        fitted = _fit_sections(compact, MAX_PACKET_CHARS)
    return [
        (
            title or ("Task" if index == 0 else "Scoring" if index == 1 else "Notice"),
            (f"{title}\n" if title else "") + "\n".join(body),
        )
        for index, (title, body) in enumerate(fitted)
    ]


def render_packet(name: str, *, cache_only: bool = False, model: str | None = None, golf: dict | None = None) -> str:
    sections = packet_sections(name, cache_only=cache_only, model=model, golf=golf)
    return "\n\n".join(content for _title, content in sections) + "\n"


def _anchor_lines(anchor: dict, node, *, island: bool = False) -> list[str]:
    """Anchor description, then the recorded goal states it covers, from the saved node."""
    if island:
        return [render_text("packet/sections.fixed.anchor_island", node=node.id,
                            count=len(node.proof_text.splitlines()))]
    if "hole" in anchor:
        hole = next((item for item in node.holes if f"{node.id}.h{item['index']}" == anchor["hole"]), None)
        head = render_text("packet/sections.fixed.anchor_hole", node=node.id, hole=anchor["hole"],
                           line=anchor["source"]["line"])
        goal = (hole or {}).get("goal")
        text = _show_goal(goal, LIMITS["goal_chars"])[0] if goal else ""
        return [head, *([render_text("packet/sections.fixed.worker_hole_goal", hole=anchor["hole"], text=text)]
                        if text else [])]
    if "steps" not in anchor:
        return [render_text("packet/sections.fixed.anchor_proof", node=node.id,
                            count=len(node.proof_text.splitlines()))]
    start, end = anchor["steps"]
    chosen = node.steps[start - 1 : end]
    head = render_text("packet/sections.fixed.anchor_steps", node=node.id, start=start, end=end,
                       first=chosen[0].first_line, last=chosen[-1].last_line)
    recorded = [(step, _show_goal(step.before, LIMITS["goal_chars"])[0]) for step in chosen if step.before]
    lines = [
        render_text("packet/sections.fixed.goal", step=step.id, line=step.first_line, text=text)
        for step, text in recorded[: LIMITS["goals"]]
    ]
    if len(recorded) > LIMITS["goals"]:
        lines.append(render_text("packet/sections.fixed.worker_goal_omitted", count=len(recorded) - LIMITS["goals"]))
    return [head, *lines]


_ISLAND_PACKETS = {None: "packet/island", "tokens": "packet/island_tokens", "heartbeats": "packet/island_heartbeats"}


def worker_packet(name: str, *, task: str, anchor: dict, node, families: list[str] | None = None,
                  objective: str | None = None, trim: bool = False, golf: bool = False,
                  cards: tuple[str, str] | None = None) -> str:
    """First prompt of a delegated worker: the shared startup contract plus its anchor. No Sol-only sections.

    `node` is the graph node the anchor resolved to, so the proof text and goals are the saved ones.
    `families` (island jobs only) are the existing proof families, one `island_family` entry each; `objective`
    picks the axis packet. `trim` (trim jobs) gets the trim packet instead, with no island title.
    `cards` (runs with --cards) is (step id, rendered reference cards) for the anchor's costliest step.
    """
    island = families is not None
    row = problem(name)
    targets = versions(row)
    rates = exchange_rates(name, len(targets))
    numbered = [
        render_text("replies/tools.source_line", line=number, text=line)
        for number, line in enumerate(node.proof_text.splitlines(), 1)
    ]
    anchored = _anchor_lines(anchor, node, island=island)
    parts: list[tuple[str, list[str]]] = [
        ("", render_text("packet/task", name=name, statement=row["statement"]).strip().splitlines()),
        ("", _scoring_lines(rates)),
        _pinned_part(row, targets),
        (template("packet/sections.titles.scope").strip(), _scope_section(row)),
        (template("packet/sections.titles.worker").strip(), template("packet/worker").strip().splitlines()),
        *([(template("packet/sections.titles.island").strip(),
            render_text(_ISLAND_PACKETS[objective], families="\n".join(families or [])).strip().splitlines())]
          if island else []),
        *([("", template("packet/trim").strip().splitlines())] if trim else []),
        *([("", template("packet/golf-worker").strip().splitlines())] if golf else []),
        *([(render_text("packet/sections.titles.cards", step=cards[0]),
            [template("packet/cards-worker").strip(), "", *cards[1].splitlines()])] if cards else []),
        ("", template("packet/search").strip().splitlines()),
        (render_text("packet/sections.titles.anchored", node=node.id), numbered),
        ("", anchored[:1]),
        (template("packet/sections.titles.worker_goals").strip(), anchored[1:]),
        (template("packet/sections.titles.hypothesis").strip(), task.strip().splitlines()),
    ]
    return _join_sections(parts) + "\n"
