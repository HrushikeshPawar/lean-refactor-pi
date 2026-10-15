"""Offline declaration search backed by the per-row SQLite index and ripgrep."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

from arena import campaign, engine, index, text

# Copied from campaign._LEAN_NAME to avoid making search depend on its private helper.
_LEAN_NAME = re.compile(
    r"(?:[^\W\d]\w*(?:['!?]\w*)*['!?]*|«[^«»\r\n]+»)(?:\.(?:[^\W\d]\w*(?:['!?]\w*)*['!?]*|«[^«»\r\n]+»))*"
)
_VISIBLE = "generated = 0 AND private = 0"


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _edit_distance(left: str, right: str, cutoff: int = 2) -> int:
    if abs(len(left) - len(right)) > cutoff:
        return cutoff + 1
    previous = list(range(len(right) + 1))
    for row, char in enumerate(left, 1):
        current = [row]
        for column, other in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[column] + 1, previous[column - 1] + (char != other)))
        if min(current) > cutoff:
            return cutoff + 1
        previous = current
    return previous[-1]


def _subsequence_pattern(query: str) -> str:
    return "*" + "*".join(query.casefold()) + "*"


def _visible_rows(connection: sqlite3.Connection, sql: str, parameters: tuple = ()) -> list[sqlite3.Row]:
    rows = connection.execute(f"SELECT * FROM declarations WHERE {_VISIBLE} AND {sql}", parameters)
    return [row for row in rows if not index.is_harness_name(row["name"])]


def _file_for(row: sqlite3.Row, theorem: dict) -> str:
    module = row["module"]
    if module == "(this file)":
        return theorem.get("file_path") or engine.source_path(theorem)
    return module.replace(".", "/") + ".lean"


def _hit(row: sqlite3.Row, theorem: dict, why: str, match: str | None = None) -> dict:
    name = row["name"]
    # Binders span several lines in the index; one line keeps implicit {x} and explicit (x) readable.
    raw_type = " ".join((row["type"] or "").split())
    signature = f"{name} : {raw_type}" if raw_type else name
    if len(signature) > 500:
        signature = signature[:499] + "…"
    result = {
        "handle": f"decl:{name}",
        "name": name,
        "decl_kind": row["kind"],
        "signature": signature,
        "module": row["module"],
        "file": _file_for(row, theorem),
        "line": row["line"],
        "why": why,
    }
    if row["end_line"] is not None:
        result["end_line"] = row["end_line"]
    if match is not None:
        result["match"] = match[:160]
    return result


def _trigram_candidates(connection: sqlite3.Connection, component: str) -> list[sqlite3.Row]:
    """Visible declarations whose folded last component is within the length band and either is short,
    shares a trigram with the query, or (for queries of 4+ characters) contains it as a subsequence."""
    folded = component.casefold()
    grams = sorted(index._trigrams(folded))
    placeholders = ",".join("?" for _ in grams)
    query_length = len(folded)
    predicate = (
        f"length BETWEEN ? AND ? AND (length <= 4 OR "
        f"id IN (SELECT component_id FROM component_grams WHERE gram IN ({placeholders}))"
    )
    parameters: tuple = (max(0, query_length - 2), query_length + 2, *grams)
    if query_length >= 4:
        predicate += " OR folded_last GLOB ?"
        parameters += (_subsequence_pattern(folded),)
    predicate += ")"
    return _visible_rows(connection, f"component_id IN (SELECT id FROM components WHERE {predicate})", parameters)


def _like_prefix(value: str) -> str:
    """A LIKE pattern matching names that start with `value` (case folded, `%` `_` `\\` escaped)."""
    return value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _siblings(connection: sqlite3.Connection, lookup: str) -> tuple[str, list[str]]:
    """Visible names under the longest prefix of `lookup` cut after a `.` or `_` that any name starts with.

    `Time.deriv_sub` tries `Time.deriv_`, then `Time.`. At most 12 names, shortest first; no index work beyond
    the prefix scans.
    """
    cuts = sorted({index_ + 1 for index_, char in enumerate(lookup) if char in "._"}, reverse=True)
    for cut in cuts:
        prefix = lookup[:cut]
        rows = _visible_rows(connection, "instr(name, ?) = 1", (prefix,))
        if rows:
            rows.sort(key=lambda row: (len(row["name"]), row["name"]))
            return prefix, [row["name"] for row in rows[:12]]
    return "", []


def sibling_names(theorem: str, name: str) -> tuple[str, list[str]]:
    """Index-only siblings of a name Lean did not find; empty when the index is missing. Never starts Lean."""
    if index.index_path(theorem) is None:
        return "", []
    try:
        connection = index.open_index(theorem)
    except (OSError, sqlite3.Error, ValueError):
        return "", []
    try:
        return _siblings(connection, name)
    finally:
        connection.close()


def _name_query(connection: sqlite3.Connection, theorem: dict, query: str, after: str | None, limit: int) -> dict:
    result = {"query": query, "hits": [], "hint": None, "truncated": False, "error": None}
    exact_only = query.startswith("decl:")
    lookup = query.removeprefix("decl:") if exact_only else query
    if not lookup and after is None:
        result["error"] = {"code": "empty_query", "input": query}
        return result

    if after is not None:
        # Completions are the dotted children and the `_` siblings of the prefix, never deeper dotted names.
        rows = _visible_rows(
            connection,
            "(folded_name LIKE ? ESCAPE '\\' OR folded_name LIKE ? ESCAPE '\\') AND instr(substr(name, ?), '.') = 0",
            (*(_like_prefix(f"{after}{separator}{lookup}") for separator in (".", "_")), len(after) + 2),
        )
        rows.sort(key=lambda row: (len(row["name"].rsplit(".", 1)[-1]), row["name"]))
        result["hits"] = [_hit(row, theorem, "completion") for row in rows[:limit]]
        result["truncated"] = len(rows) > limit
        return result

    exact = _visible_rows(connection, "name = ?", (lookup,))
    if not exact and not exact_only:
        prefix, siblings = _siblings(connection, lookup)
        result.update(missing=True, sibling_prefix=prefix, siblings=siblings)
    exact_last = [] if "." in lookup else _visible_rows(connection, "last_component = ?", (lookup,))
    exact_last.sort(key=lambda row: (len(row["name"]), row["name"]))
    candidates: list[tuple[sqlite3.Row, str]] = [(row, "exact") for row in exact]
    confusable = []
    if not exact_only:
        candidates.extend((row, "suffix") for row in exact_last)
    if not exact and not exact_only:
        confusable = _visible_rows(connection, "normalized_name = ?", (_normalized(lookup),))
        confusable = [row for row in confusable if row["name"] != lookup]
        statement = theorem.get("statement", "")
        confusable.sort(key=lambda row: (row["name"] not in statement, row["name"]))
        candidates.extend((row, "confusable") for row in confusable)
        if confusable:
            first_name = confusable[0]["name"]
            differing = [
                ord(char)
                for index_, char in enumerate(lookup)
                if index_ >= len(first_name) or first_name[index_] != char
            ]
            result["hint"] = {"query_char_codes": differing, "name": first_name}
    if not exact_only and not confusable:
        folded = lookup.casefold()
        prefix = _visible_rows(
            connection,
            "(folded_name LIKE ? ESCAPE '\\' OR folded_last LIKE ? ESCAPE '\\')",
            tuple(folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for _ in range(2)),
        )
        prefix.sort(key=lambda row: (len(row["name"]), row["name"]))
        candidates.extend((row, "prefix") for row in prefix)
        substring = _visible_rows(connection, "instr(folded_name, ?) > 0", (folded,))
        substring.sort(key=lambda row: (len(row["name"]), row["name"]))
        candidates.extend((row, "substring") for row in substring)
        fuzzy = []
        distances: dict[str, int] = {}
        for row in _trigram_candidates(connection, lookup.rsplit(".", 1)[-1]):
            component = row["folded_last"]
            if component not in distances:
                distances[component] = _edit_distance(folded.rsplit(".", 1)[-1], component)
            distance = distances[component]
            if distance <= 2 or (len(folded) >= 4 and _is_subsequence(folded, row["folded_name"])):
                fuzzy.append((distance, row))
        fuzzy.sort(key=lambda item: (item[0], len(item[1]["name"]), item[1]["name"]))
        # Once a real name match exists, only one-edit fuzzy matches stay: the rest is padding.
        real = bool(candidates)
        candidates.extend((row, "fuzzy") for distance, row in fuzzy if distance <= 1 or not real)

    seen = set()
    ranked = []
    for row, why in candidates:
        if row["name"] not in seen:
            ranked.append((row, why))
            seen.add(row["name"])
    if not ranked:
        result["error"] = {
            "code": "not_found",
            "input": query,
            "suggestions": _suggestions(connection, lookup),
        }
        return result
    result["hits"] = [_hit(row, theorem, why) for row, why in ranked[:limit]]
    result["truncated"] = len(ranked) > limit
    return result


def _is_subsequence(query: str, candidate: str) -> bool:
    iterator = iter(candidate)
    return all(any(char == item for item in iterator) for char in query)


def _suggestions(connection: sqlite3.Connection, query: str) -> list[str]:
    component = query.rsplit(".", 1)[-1].casefold()
    rows = _trigram_candidates(connection, component)
    if not rows:
        rows = _visible_rows(
            connection,
            "length(folded_last) BETWEEN ? AND ? ORDER BY name LIMIT 256",
            (max(0, len(component) - 3), len(component) + 3),
        )
    matches = []
    for row in rows:
        distance = _edit_distance(component, row["folded_last"])
        matches.append((distance, len(row["name"]), row["name"]))
    return [name for _distance, _length, name in sorted(matches)[:5]]


def _type_query(connection: sqlite3.Connection, theorem: dict, query: str, limit: int) -> dict:
    result = {"query": query, "hits": [], "hint": None, "truncated": False, "error": None}
    tokens = list(dict.fromkeys(_LEAN_NAME.findall(query)))
    resolved: set[str] = set()
    for token in tokens:
        exact = _visible_rows(connection, "name = ?", (token,))
        if exact:
            resolved.add(token)
            continue
        component = token.rsplit(".", 1)[-1]
        matches = _visible_rows(connection, "last_component = ?", (component,))
        if len(matches) == 1:
            resolved.add(matches[0]["name"])
    if not resolved:
        result["error"] = {"code": "no_constants", "input": query}
        return result

    placeholders = ",".join("?" for _ in resolved)
    weights = {
        row["name"]: row["idf"]
        for row in connection.execute(
            f"SELECT name, idf FROM constants WHERE name IN ({placeholders})", tuple(resolved)
        )
    }
    candidates: dict[str, tuple[sqlite3.Row, float]] = {}
    # decl_consts holds each declaration's consts plus its head, so this covers `head = constant` too.
    for row in _visible_rows(
        connection,
        "id IN (SELECT decl_id FROM decl_consts WHERE constant_id IN "
        f"(SELECT id FROM constants WHERE name IN ({placeholders})))",
        tuple(resolved),
    ):
        present = set(json.loads(row["consts"]))
        present.add(row["head"])
        score = sum(weights.get(value, 0.0) for value in resolved if value in present)
        if row["head"] in resolved:
            score += 2.0
        candidates[row["name"]] = (row, score)
    ranked = sorted(candidates.values(), key=lambda item: (-item[1], item[0]["name"]))
    result["hits"] = [_hit(row, theorem, "type") for row, _score in ranked[:limit]]
    result["truncated"] = len(ranked) > limit
    return result


def _rg_hits(query: str, roots: list[Path]) -> list[dict]:
    command = [
        "rg",
        "--json",
        "--fixed-strings",
        "--ignore-case",
        "--glob",
        "*.lean",
        "--max-count",
        "50",
        "--no-ignore",
        "--",
        query,
        *(str(root) for root in roots),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    if completed.returncode not in (0, 1):
        raise RuntimeError(completed.stderr.strip() or "ripgrep failed")
    return [
        json.loads(line)["data"] for line in completed.stdout.splitlines() if json.loads(line).get("type") == "match"
    ]


def _text_query(
    connection: sqlite3.Connection, theorem: dict, version: str, commit: str, query: str, limit: int
) -> dict:
    result = {"query": query, "hits": [], "hint": None, "truncated": False, "error": None, "dropped": 0}
    project = engine.workspace(theorem, version, commit)
    roots = [root for root, _pin, _package in campaign._roots(project, commit)]
    core = Path.home() / ".elan" / "toolchains" / f"leanprover--lean4---{version}" / "src" / "lean"
    core_source = core.is_dir()
    if core_source:
        roots.append(core)
    result["core_source"] = core_source
    try:
        raw_hits = _rg_hits(query, roots)
    except subprocess.TimeoutExpired:
        result["error"] = {"code": "search_failed", "input": query}
        return result
    except RuntimeError:
        result["error"] = {"code": "search_failed", "input": query}
        return result

    declarations_by_module: dict[str, list[sqlite3.Row]] = {}
    for declaration in connection.execute("SELECT * FROM declarations WHERE line IS NOT NULL AND end_line IS NOT NULL"):
        declarations_by_module.setdefault(declaration["module"], []).append(declaration)
    found: dict[str, tuple[sqlite3.Row, str]] = {}
    for raw in raw_hits:
        data = raw["path"]
        path = (
            Path(data.get("text", "")) if data.get("text") is not None else Path(data["bytes"].decode(errors="replace"))
        )
        absolute = path.resolve()
        line = raw["line_number"]
        module = None
        for root in roots:
            try:
                relative = absolute.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            if relative == theorem.get("file_path"):
                module = "(this file)"
            elif relative.endswith(".lean"):
                module = relative[:-5].replace("/", ".")
            break
        enclosing = [
            decl for decl in declarations_by_module.get(module or "", []) if decl["line"] <= line <= decl["end_line"]
        ]
        if not enclosing:
            result["dropped"] += 1
            continue
        declaration = max(enclosing, key=lambda decl: decl["line"])
        if declaration["generated"] or declaration["private"] or index.is_harness_name(declaration["name"]):
            result["dropped"] += 1
            continue
        found.setdefault(declaration["name"], (declaration, raw["lines"].get("text", "").strip()))
    ranked = sorted(found.values(), key=lambda item: (item[0]["name"], item[0]["line"]))
    result["hits"] = [_hit(row, theorem, "text", match) for row, match in ranked[:limit]]
    result["truncated"] = len(ranked) > limit
    return result


def _empty_error(kind: str, query: str, after: str | None) -> dict | None:
    if query or (kind == "name" and after is not None):
        return None
    return {"code": "empty_query", "input": query}


def _missing_index_result(kind: str, queries: list[str], after: str | None) -> dict:
    return {
        "kind": kind,
        "queries": [
            {
                "query": query,
                "hits": [],
                "hint": None,
                "truncated": False,
                "error": _empty_error(kind, query, after) or {"code": "no_index", "input": query},
            }
            for query in queries
        ],
    }


def search(
    theorem: str,
    queries: list[str],
    kind: str = "name",
    after: str | None = None,
    limit: int | None = None,
) -> dict:
    """Return per-query declaration data. This path never starts Lean."""
    if shutil.which("rg") is None:
        raise RuntimeError("ripgrep (rg) is required for declaration text search")
    valid_kinds = ["name", "type", "text"]
    selected_limit = limit if limit is not None else int(text.numbers().get("search_hits_default", 10))
    selected_limit = min(max(1, selected_limit), int(text.numbers().get("search_hits_max", 30)))
    if kind not in valid_kinds:
        return {
            "kind": kind,
            "queries": [
                {
                    "query": query,
                    "hits": [],
                    "hint": None,
                    "truncated": False,
                    "error": {"code": "bad_kind", "input": query, "valid": valid_kinds},
                }
                for query in queries
            ],
        }
    row = engine.problem(theorem)
    version, commit = engine.measure_version(row)
    if after is None:
        path = index.index_path(theorem)
        if path is None:
            return _missing_index_result(kind, queries, after)
    try:
        connection = index.open_index(theorem)
    except (OSError, sqlite3.Error, ValueError):
        return _missing_index_result(kind, queries, after)
    try:
        items = []
        for query in queries:
            if kind == "name":
                items.append(_name_query(connection, row, query, after, selected_limit))
            elif kind == "type":
                if not query:
                    items.append(
                        {
                            "query": query,
                            "hits": [],
                            "hint": None,
                            "truncated": False,
                            "error": {"code": "empty_query", "input": query},
                        }
                    )
                else:
                    items.append(_type_query(connection, row, query, selected_limit))
            else:
                if not query:
                    items.append(
                        {
                            "query": query,
                            "hits": [],
                            "hint": None,
                            "truncated": False,
                            "error": {"code": "empty_query", "input": query},
                            "dropped": 0,
                        }
                    )
                else:
                    items.append(_text_query(connection, row, version, commit, query, selected_limit))
        return {"kind": kind, "queries": items}
    finally:
        connection.close()


def resolve_handle(theorem: str, handle: str) -> dict | None:
    """Resolve a declaration handle, including private/generated entries."""
    if not handle.startswith("decl:"):
        return None
    try:
        connection = index.open_index(theorem)
    except (OSError, sqlite3.Error, ValueError):
        return None
    try:
        row = connection.execute(
            "SELECT * FROM declarations WHERE name = ?", (handle.removeprefix("decl:"),)
        ).fetchone()
        if row is None:
            return None
        hit = _hit(row, engine.problem(theorem), "exact")
        hit.pop("handle")
        hit.pop("why")
        return hit | {"generated": bool(row["generated"]), "private": bool(row["private"])}
    finally:
        connection.close()
