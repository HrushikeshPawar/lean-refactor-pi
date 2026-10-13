"""Source-grounded, persistent state for one Arena proof-search run."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from arena import goalstate, lean_health, lean_session, routes, text
from arena import text as agent_text
from arena.engine import (
    ROOT,
    candidate_file,
    evaluate,
    force_cold,
    measure_version,
    problem,
    source_path,
    validate_proof,
    versions,
    workspace,
)
from arena.graph import (
    FILING_MIN_SIMILARITY,
    Graph,
    Node,
    common_base,
    edit_fingerprint,
    measured_parent,
    merge_steps,
    merge_text,
    ranked_frontier,
    similarity,
    splice_text,
    stall_fires,
    stall_target,
)
from arena.graph import map_view as graph_map_view
from arena.profile import heartbeat_floor, profile
from arena.salvage import fill_cost, fill_text
from arena.salvage import holes as find_holes
from arena.salvage import salvage as salvage_proof


def run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", run_id):
        raise ValueError(text.render("messages/errors.invalid_run_id"))
    return ROOT / "runs" / "pi-budget" / run_id


class AmbiguousDeclaration(ValueError):
    """More than one distinct qualified declaration matches an unqualified or partial name."""

    def __init__(self, symbol: str, candidates: list[str]):
        super().__init__(
            text.render("messages/errors.ambiguous_symbol", symbol=symbol, candidates=", ".join(candidates[:12]))
        )
        self.candidates = candidates


_SESSION: ContextVar[_Session | None] = ContextVar("arena_source_session", default=None)
_BATCH_FOCUS: ContextVar[tuple[bool, str | None]] = ContextVar("arena_batch_focus", default=(False, None))
_BATCH_NEWLY_FILED: ContextVar[set[str] | None] = ContextVar("arena_batch_newly_filed", default=None)
_SALVAGE_DIRECTORY: ContextVar[Path | None] = ContextVar("arena_salvage_directory", default=None)


class _Session:
    """Per-call pinned-source reader: one `git cat-file --batch` per root, with cached blobs."""

    def __init__(self) -> None:
        self.processes: dict[str, subprocess.Popen] = {}
        self.blobs: dict[tuple[str, str, str], str | None] = {}
        self.contexts: dict[str, dict] = {}
        self.roots: dict[str, list[tuple[Path, str, str]]] = {}
        self.scans: dict[tuple[str, str, str], tuple[list[str], list[tuple[int, str]]]] = {}

    def read(self, root: Path, pin: str, path: str) -> str:
        key = (str(root), pin, path)
        if key not in self.blobs:
            self.blobs[key] = self._fetch(root, f"{pin}:{path}")
        text = self.blobs[key]
        if text is None:
            raise subprocess.CalledProcessError(128, ["git", "cat-file", f"{pin}:{path}"])
        return text

    def _fetch(self, root: Path, spec: str) -> str | None:
        process = self.processes.get(str(root))
        if process is None:
            process = self.processes[str(root)] = subprocess.Popen(
                ["git", "cat-file", "--batch"],
                cwd=root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        process.stdin.write(spec.encode() + b"\n")
        process.stdin.flush()
        header = process.stdout.readline().split()
        if len(header) != 3 or header[1] != b"blob":
            return None
        data = process.stdout.read(int(header[2]))
        process.stdout.read(1)
        return data.decode("utf-8", errors="replace")

    def close(self) -> None:
        for process in self.processes.values():
            try:
                process.stdin.close()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait()
            process.stdout.close()


@contextmanager
def _session():
    """Share one reader and context cache across a lookup call; nested calls reuse it."""
    current = _SESSION.get()
    if current is not None:
        yield current
        return
    session = _Session()
    token = _SESSION.set(session)
    try:
        yield session
    finally:
        _SESSION.reset(token)
        session.close()


def _git_source(project: Path, commit: str, path: str) -> str:
    if not path.endswith(".lean") or Path(path).is_absolute() or ".." in Path(path).parts:
        raise ValueError(text.render("messages/errors.pinned_project_path"))
    session = _SESSION.get()
    if session is not None:
        return session.read(project, commit, path)
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=project, text=True, capture_output=True, check=True
    ).stdout


def _context(name: str) -> dict:
    """The kickoff inventory, read once per lookup call."""
    from arena.context import lean_context

    session = _SESSION.get()
    if session is None:
        return lean_context(name)
    if name not in session.contexts:
        session.contexts[name] = lean_context(name)
    return session.contexts[name]


MAX_SOURCE_LINES = int(text.numbers()["source_lines_per_call"])
MAX_DRAFTS = int(text.numbers()["max_drafts"])
MAX_DECLARATION_PAGE_CHARS = 16_000


def declarations(name: str, items: list[str] | None = None, cursor: str | None = None) -> dict:
    """Resolve a batch of declaration handles against the kickoff's tagged constant index."""
    if bool(items) == bool(cursor):
        raise ValueError(text.render("messages/errors.declarations_usage"))
    with _session():
        return _declarations(name, items, cursor)


def _declarations(name: str, items: list[str] | None, cursor: str | None) -> dict:
    from arena.context import constant_index

    if cursor:
        try:
            state = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if state.get("version") != 1 or state.get("theorem") != name:
                raise ValueError
            items, offset = state["items"], state["offset"]
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            raise ValueError(text.render("messages/errors.invalid_declaration_cursor")) from None
    else:
        offset = 0
    if not isinstance(items, list) or not items or not all(isinstance(item, str) and item for item in items):
        raise ValueError(text.render("messages/errors.declaration_items"))

    inventory = _context(name)
    if inventory.get("error"):
        return {
            "items": [
                {"input": item, "kind": "unavailable", "reason": "unavailable", "detail": inventory["error"]}
                for item in items[offset:]
            ],
            "next_cursor": None,
        }
    constants = constant_index(inventory)
    locals_by_name = {item["name"]: item for item in inventory.get("local", [])}
    results: list[dict] = []
    size = 0
    index = offset
    while index < len(items):
        original = items[index]
        query = original[5:] if original.startswith("decl:") else original
        if query in locals_by_name:
            local = locals_by_name[query]
            result = {"input": original, "kind": "local", "name": query, "type": local["type"], "scope": local["scope"]}
        else:
            matches = constant_index(inventory, name=query)
            if not matches and "." not in query:
                matches = [item for item in constants if item["name"].split(".")[-1] == query]
            if len(matches) > 1:
                result = {
                    "input": original,
                    "kind": "ambiguous",
                    "suggestions": [item["name"] for item in matches[:12]],
                }
            elif not matches:
                found = _source_declaration(name, query)
                if not found.get("found") and re.search(r"(?:^|\.)_[A-Za-z0-9_']", query):
                    # Generated elaborator names can be absent from source indexes and still resolve in Lean.
                    found = declaration(name, query)
                if found.get("ambiguous"):
                    result = {"input": original, "kind": "ambiguous", "suggestions": found["ambiguous"]}
                elif not found.get("found"):
                    result = {
                        "input": original,
                        "kind": "error",
                        "error": "not_found",
                        "hint": found.get("hint"),
                        "suggestions": _declaration_suggestions(query, constants),
                    }
                elif found.get("alternatives"):
                    result = {
                        "input": original,
                        "kind": "ambiguous",
                        "suggestions": [found["name"], *found["alternatives"]],
                    }
                elif found.get("source_text"):
                    result = {"input": original, "kind": "declaration", **found}
                else:
                    entry = {"name": found.get("name", query), "kind": found.get("kind", "generated")}
                    result = {
                        "input": original,
                        **found,
                        "kind": "unavailable",
                        "reason": _unavailable_reason(entry, found),
                        "handle": f"decl:{entry['name']}",
                    }
            else:
                entry = matches[0]
                found = declaration(name, entry["name"])
                if found.get("source_text"):
                    result = {"input": original, "kind": "declaration", **found, "index": entry}
                else:
                    result = {
                        "input": original,
                        "kind": "unavailable",
                        "reason": _unavailable_reason(entry, found),
                        "name": entry["name"],
                        "handle": f"decl:{entry['name']}",
                        "index": entry,
                        "module": found.get("module") or entry.get("module"),
                        "signature": found.get("signature") or entry.get("sig"),
                        "location": found.get("source"),
                    }
        encoded_size = len(json.dumps(result, ensure_ascii=False))
        if results and size + encoded_size > MAX_DECLARATION_PAGE_CHARS:
            break
        results.append(result)
        size += encoded_size
        index += 1
    next_cursor = None
    if index < len(items):
        raw = json.dumps({"version": 1, "theorem": name, "items": items, "offset": index}).encode()
        next_cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return {"items": results, "next_cursor": next_cursor}


def _declaration_suggestions(query: str, constants: list[dict]) -> list[str]:
    """Offer qualified-name suggestions using name overlap, without claiming lemma relevance."""
    parts = {part.lower() for part in query.split(".") if part}
    ranked = []
    for item in constants:
        name = item["name"]
        overlap = len(parts & {part.lower() for part in name.split(".")})
        if overlap:
            ranked.append((-overlap, name))
    return [name for _, name in sorted(ranked)[:8]]


def _unavailable_reason(entry: dict, found: dict) -> str:
    if entry.get("tag") == "generated" or "._" in entry["name"]:
        return "generated"
    if entry["name"].startswith("_private."):
        return "private"
    if found.get("kind") == "opaque" or entry.get("kind") == "opaque":
        return "opaque"
    if found.get("module") not in (None, "this file"):
        return "external"
    return "unavailable"


def source_range(name: str, path: str, first: int | None = None, last: int | None = None) -> dict:
    """Read pinned source; `next_first` continues a range cut at the limit.

    Without `first`, a `decl:` handle starts at its declaration and a path at the top of the file.
    """
    # Lines are 1-based; some models send 0 to mean "not given".
    first, last = (first or None), (last or None)
    with _session():
        return _source_range(name, path, first, last)


def _source_range(name: str, path: str, first: int | None, last: int | None) -> dict:
    row = problem(name)
    version, commit = measure_version(row)
    project = workspace(row, version, commit)
    if path.startswith("decl:"):
        source_symbol, module, span = _source_hint(name, path[5:])
        try:
            located = _resolve_declaration_source(name, source_symbol, module, span)
        except AmbiguousDeclaration as error:
            return {"kind": "ambiguous", "handle": path, "candidates": error.candidates}
        project, commit, path = located["root"], located["pin"], located["path"]
        first = located["line"] if first is None else first
    else:
        path, suffix_first, suffix_last = _split_source_handle(path, commit)
        first = suffix_first if first is None else first
        last = suffix_last if last is None else last
        if path.startswith(STDLIB_ALIAS):
            # lean_local_search reports Lean's own library under this alias; it is not a Git root.
            lines, commit = _stdlib_source(version, path).splitlines(), f"lean4-{version}"
        else:
            project, commit, path = _source_target(project, commit, _canonical_source_path(row, path))
    try:
        if not path.startswith(STDLIB_ALIAS):
            lines = _git_source(project, commit, path).splitlines()
    except subprocess.CalledProcessError:
        raise ValueError(text.render("messages/errors.project_file_missing", path=path, commit=commit[:8])) from None
    first = 1 if first is None else first
    if first < 1 or first > len(lines):
        raise ValueError(text.render("messages/errors.source_line_range", path=path, count=len(lines), first=first))
    wanted = last if last is not None else first + 199
    end = min(wanted, len(lines), first + MAX_SOURCE_LINES - 1)
    if end < first:
        raise ValueError(text.render("messages/errors.source_range_order"))
    return {
        "source": f"{row['source']}@{commit}:{path}:{first}-{end}",
        "pin": commit,
        "path": path,
        "file_lines": len(lines),
        "first": first,
        "last": end,
        "next_first": end + 1 if end < len(lines) and wanted > end else None,
        "text": "\n".join(f"{i}: {lines[i - 1]}" for i in range(first, end + 1)),
    }


def find(name: str, queries: list[str], limit: int = 20) -> dict:
    """Search declaration lines of the pinned trees and the kickoff index, counting each qualified declaration once."""
    if not queries or not all(isinstance(query, str) and query.strip() for query in queries):
        raise ValueError(text.render("messages/errors.find_queries"))
    if limit < 1:
        raise ValueError(text.render("messages/errors.find_limit"))
    limit = min(limit, 100)
    with _session():
        return _find(name, queries, limit)


def _find(name: str, queries: list[str], limit: int) -> dict:
    from arena.context import constant_index

    inventory = _context(name)
    indexed = constant_index(inventory) if not inventory.get("error") else []
    entries = indexed + [
        {**item, "kind": item.get("decl")} for item in inventory.get("source", []) if not inventory.get("error")
    ]
    row = problem(name)
    version, commit = measure_version(row)
    project = workspace(row, version, commit)
    roots = _roots(project, commit)
    needles = [query[5:] if query.startswith("decl:") else query for query in queries]
    named = [bool(re.fullmatch(_LEAN_NAME, needle)) for needle in needles]
    # A name the kickoff index holds exactly resolves without searching the source trees.
    pending = [
        needle
        for needle, is_name in zip(needles, named, strict=False)
        if not (is_name and any(item["name"] == needle for item in entries))
    ]
    hits = _declaration_hits(roots, list(dict.fromkeys(pending))) if pending else []
    per_query = []
    for query, needle, is_name in zip(queries, needles, named, strict=False):
        exact_only = query.startswith("decl:")
        folded = needle.casefold()
        found: dict[str, dict] = {}
        if is_name:
            for item in entries:
                if (
                    not (item["name"] == needle if exact_only else folded in item["name"].casefold())
                    or item["name"] in found
                ):
                    continue
                matched = _indexed_row(item, roots, (project, commit, row["file_path"]))
                if matched is None and item["name"] == needle:
                    matched = _unavailable_row(item)
                if matched is not None:
                    found[item["name"]] = matched
        files_truncated = False
        scanned = 0
        if needle in pending:
            candidates = _candidate_files(hits, needle, is_name, exact_only)
            files_truncated = len(candidates) > MAX_SCAN_FILES
            for index, pin, path in candidates[:MAX_SCAN_FILES]:
                read = _scan(roots[index][0], pin, path)
                if read is None:
                    continue
                scanned += 1
                lines, starts = read
                for number, (line_number, qualified) in enumerate(starts):
                    if qualified in found:
                        continue
                    end = _declaration_end(lines, starts, number)
                    if exact_only:
                        matched = qualified == needle
                    elif is_name:
                        matched = folded in qualified.casefold()
                    else:
                        matched = folded in "\n".join(lines[line_number - 1 : end]).casefold()
                    if matched:
                        found[qualified] = _declaration_row(
                            pin, path, lines, qualified, _declaration_start(lines, line_number), end
                        )
        if not found:
            per_query.append(
                {
                    "query": query,
                    "matches": [],
                    "error": "not_found",
                    "suggestions": _declaration_suggestions(needle, indexed),
                    "files_scanned": scanned,
                    "files_truncated": files_truncated,
                }
            )
            continue
        selected = sorted(
            found.values(),
            key=lambda item: (
                0 if item["name"].casefold() == folded else 1 if item["name"].casefold().endswith("." + folded) else 2,
                item["name"],
            ),
        )[:limit]
        per_query.append(
            {
                "query": query,
                "matches": selected,
                "distinct_count": len(found),
                "truncated": len(found) > len(selected),
                "files_scanned": scanned,
                "files_truncated": files_truncated,
            }
        )
    return {"queries": per_query, "pin": commit, "limit": limit}


def _indexed_row(item: dict, roots: list[tuple[Path, str, str]], own_file: tuple) -> dict | None:
    """Locate one kickoff-index declaration in pinned source, or None when its source cannot be found."""
    module = item.get("module")
    if item.get("tag") == "generated" or module is None:
        return None
    if module == "this file":
        read = _scan(*own_file)
        if read is None:
            return None
        lines, starts = read
        for number, (line_number, qualified) in enumerate(starts):
            if qualified == item["name"] or qualified.endswith("." + item["name"]):
                return _declaration_row(
                    own_file[1],
                    own_file[2],
                    lines,
                    item["name"],
                    _declaration_start(lines, line_number),
                    _declaration_end(lines, starts, number),
                )
        return None
    if "start_line" not in item:
        return None
    located = _module_file(roots, module)
    if located is None:
        return None
    root, pin, path = located
    lines = _git_source(root, pin, path).splitlines()
    return _declaration_row(pin, path, lines, item["name"], item["start_line"], item["end_line"])


def _unavailable_row(item: dict) -> dict:
    """An index-only match for a declaration whose source is not in the pinned trees (core, generated)."""
    matched = {
        "name": item["name"],
        "handle": f"decl:{item['name']}",
        "kind": item.get("kind"),
        "module": item.get("module"),
        "source_unavailable": _unavailable_reason(item, item),
    }
    for key in ("type", "signature"):
        if item.get(key):
            matched[key] = item[key]
    return matched


def _declaration_row(pin: str, path: str, lines: list[str], qualified: str, start: int, end: int) -> dict:
    return {
        "name": qualified,
        "handle": f"decl:{qualified}",
        "path": path,
        "line": start,
        "end_line": end,
        "pin": pin,
        "signature": _signature(lines, start, end),
    }


def _candidate_files(
    hits: list[tuple[int, str, str, int, str]], needle: str, is_name: bool, exact_only: bool
) -> list[tuple[int, str, str]]:
    """Files worth reading for one query, best first: exact leaf names, then prefixes, then substrings."""
    folded = needle.casefold()
    parts = needle.split(".")
    leaf = parts[-1].casefold()
    namespaced = {
        (index, path)
        for index, _, path, _, source_text in hits
        if len(parts) > 1
        and re.match(r"^\s*namespace\s", source_text, re.I)
        and parts[-2].casefold() in source_text.casefold()
    }
    ranked: dict[tuple[int, str, str], int] = {}
    for index, pin, path, _, source_text in hits:
        declared = _DECLARATION_PATTERN.match(source_text)
        if is_name:
            if not declared:
                continue
            local = declared.group(1).casefold()
            if leaf not in local or (len(parts) > 1 and folded not in local and (index, path) not in namespaced):
                continue
            tier = 0 if local.split(".")[-1] == leaf else 1 if local.split(".")[-1].startswith(leaf) else 2
        elif folded in source_text.casefold():
            tier = 2
        else:
            continue
        key = (index, pin, path)
        ranked[key] = min(ranked.get(key, tier), tier)
    return [key for key, _ in sorted(ranked.items(), key=lambda item: (item[1], item[0][0], item[0][2]))]


_HANDLE_SUFFIX = re.compile(r"^(.*\.lean):(\d+)(?:-(\d+))?$")
_HANDLE_PIN = re.compile(r"^[A-Za-z0-9_.-]+@([0-9a-fA-F]+):")


def _split_source_handle(path: str, pin: str) -> tuple[str, int | None, int | None]:
    """Split `[src@commit:]path.lean[:N[-M]]` into the path and its optional line range."""
    first = last = None
    suffix = _HANDLE_SUFFIX.match(path)
    if suffix:
        path, first = suffix.group(1), int(suffix.group(2))
        last = int(suffix.group(3)) if suffix.group(3) else None
    printed = _HANDLE_PIN.match(path)
    if printed:
        if not pin.startswith(printed.group(1)):
            raise ValueError(
                text.render(
                    "messages/errors.source_commit_mismatch", source_commit=printed.group(1)[:12], pinned_commit=pin[:8]
                )
            )
        path = path[printed.end() :]
    return path, first, last


STDLIB_ALIAS = ".lean-stdlib/lean/"


def _stdlib_source(version: str, path: str) -> str:
    """Lean's own library source from the measured toolchain, which elan installs read-only per version."""
    relative = Path(path[len(STDLIB_ALIAS) :])
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".lean":
        raise ValueError(text.render("messages/errors.library_path"))
    target = Path.home() / ".elan" / "toolchains" / f"leanprover--lean4---{version}" / "src" / "lean" / relative
    if not target.is_file():
        raise ValueError(text.render("messages/errors.library_file_missing", path=path, version=version))
    return target.read_text()


def _canonical_source_path(row: dict, path: str) -> str:
    """Normalize documented project aliases to a path inside the pinned checkout."""
    for alias in ("strata", "physlib", "mathlib", "cslib", "arklib"):
        if path.startswith(alias + ":") or path.startswith(alias + "/"):
            path = path[len(alias) + 1 :]
            break
    path = path.removeprefix("./")
    if path.startswith("/") or ".." in Path(path).parts or not path.endswith(".lean"):
        raise ValueError(text.render("messages/errors.pinned_project_path"))
    return path


def _package_roots(project: Path) -> list[tuple[Path, str, str]]:
    roots = []
    manifest = project / "lake-manifest.json"
    try:
        locked = json.loads(manifest.read_text()).get("packages", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return roots
    packages = project / ".lake" / "packages"
    for entry in locked:
        if not isinstance(entry, dict) or entry.get("type", "git") != "git":
            continue
        package_name, revision = entry.get("name"), entry.get("rev")
        if not isinstance(package_name, str) or not isinstance(revision, str) or not revision:
            continue
        package = packages / package_name
        if not package.is_dir():
            continue
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=package, text=True, capture_output=True, check=False)
        if head.returncode == 0 and head.stdout.strip() == revision:
            roots.append((package, revision, package_name))
    return roots


def _source_target(project: Path, commit: str, path: str, module: str | None = None) -> tuple[Path, str, str]:
    """Resolve a canonical project or dependency path to its pinned Git root."""
    if isinstance(project, Path) and (project / path).is_file():
        exists = (
            subprocess.run(
                ["git", "cat-file", "-e", f"{commit}:{path}"], cwd=project, capture_output=True, check=False
            ).returncode
            == 0
        )
        if exists:
            return project, commit, path
    module_path = module.replace(".", "/") + ".lean" if module else None
    for root, pin, _package in _package_roots(project):
        for candidate in (module_path, path):
            if candidate and (root / candidate).is_file():
                return root, pin, candidate
    raise ValueError(text.render("messages/errors.source_path_missing", path=path))


# One Lean 4 identifier: dotted components, each a Unicode letter or `_` followed by letters, digits,
# subscripts, `_`, `'`, `!`, `?`, or a «...» escape.
_LEAN_COMPONENT = r"(?:[^\W\d]\w*(?:['!?]\w*)*['!?]*|«[^«»\r\n]+»)"
_LEAN_NAME_BODY = _LEAN_COMPONENT + r"(?:\." + _LEAN_COMPONENT + r")*"
_LEAN_NAME = re.compile(_LEAN_NAME_BODY)
_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:private|protected|noncomputable|nonrec|unsafe|partial)\s+)*"
    r"(?:theorem|lemma|def|opaque|example|instance|abbrev|inductive|structure|class|axiom)\s+"
    r"(" + _LEAN_NAME_BODY + r")"
)
_SCOPE_PATTERN = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:public|noncomputable|meta)\s+)*(namespace|section)\b(?:\s+("
    + _LEAN_NAME_BODY
    + r"))?\s*$"
)
_END_PATTERN = re.compile(r"^\s*end(?:\s+(" + _LEAN_NAME_BODY + r"))?\s*$")
# The same shape for `git grep -E`, which only needs declaration lines and never body text.
_DECLARATION_GREP = (
    r"^[[:space:]]*(@\[[^]]*\][[:space:]]*)*((private|protected|noncomputable|nonrec|unsafe|partial)"
    r"[[:space:]]+)*(theorem|lemma|def|opaque|instance|abbrev|inductive|structure|class|axiom)[[:space:]]+"
)
MAX_SCAN_FILES = int(text.numbers()["find_files_per_query"])


def _source_declarations(lines: list[str]) -> list[tuple[int, str]]:
    """Return named Lean declarations with names qualified by their namespace and section blocks."""
    scopes: list[tuple[str | None, str]] = []  # (label, namespace prefix it adds); sections add none
    declarations = []
    for line_number, line in enumerate(lines, 1):
        code = line.split("--", 1)[0]
        scope = _SCOPE_PATTERN.match(code)
        if scope:
            scopes.append(
                (scope.group(2), scope.group(2) or "") if scope.group(1) == "namespace" else (scope.group(2) or "", "")
            )
            continue
        closed = _END_PATTERN.match(code)
        if closed:
            label = closed.group(1)
            index = next(
                (
                    i
                    for i in range(len(scopes) - 1, -1, -1)
                    if label is not None and (scopes[i][0] == label or (scopes[i][0] or "").endswith("." + label))
                ),
                None,
            )
            if label is None or index is None:
                index = len(scopes) - 1
            del scopes[max(index, 0) :]
            continue
        match = _DECLARATION_PATTERN.match(line)
        if match:
            local = match.group(1)
            if local.startswith("_root_."):
                qualified = local[len("_root_.") :]
            else:
                qualified = ".".join([prefix for _, prefix in scopes if prefix] + [local])
            declarations.append((line_number, qualified))
    return declarations


def _declaration_start(lines: list[str], line: int) -> int:
    """Include the attribute lines and doc comment that belong to a declaration."""
    start = line
    while start > 1 and lines[start - 2].lstrip().startswith("@["):
        start -= 1
    if start > 1 and lines[start - 2].rstrip().endswith("-/"):
        opener = next(
            (i for i in range(start - 2, max(start - 80, -1), -1) if lines[i].lstrip().startswith("/--")), None
        )
        if opener is not None:
            start = opener + 1
    return start


def _declaration_end(lines: list[str], starts: list[tuple[int, str]], index: int) -> int:
    """The last line of a declaration: before the next one's docs and attributes, ignoring blank lines."""
    following = starts[index + 1][0] if index + 1 < len(starts) else len(lines) + 1
    end = _declaration_start(lines, following) - 1 if following <= len(lines) else len(lines)
    while end > starts[index][0] and (
        not lines[end - 1].strip()
        or lines[end - 1].lstrip().startswith("--")
        or _SCOPE_PATTERN.match(lines[end - 1])
        or _END_PATTERN.match(lines[end - 1])
    ):
        end -= 1
    return end


def _signature(lines: list[str], start: int, end: int) -> str:
    """The first declaration lines after any doc comment and attributes, up to the line that opens the body."""
    shown = []
    keyword = next((i for i in range(start, end + 1) if _DECLARATION_PATTERN.match(lines[i - 1])), start)
    for line_text in lines[keyword - 1 : min(end, keyword + 5)]:
        shown.append(line_text.rstrip())
        if ":=" in line_text or line_text.rstrip().endswith("where") or line_text.strip().startswith("|"):
            break
    return "\n".join(shown)


def _roots(project: Path, commit: str) -> list[tuple[Path, str, str]]:
    session = _SESSION.get()
    key = str(project)
    if session is not None and key in session.roots:
        return session.roots[key]
    roots = [(project, commit, ""), *_package_roots(project)]
    if session is not None:
        session.roots[key] = roots
    return roots


def _module_file(roots: list[tuple[Path, str, str]], module: str) -> tuple[Path, str, str] | None:
    """The pinned root that holds module `A.B.C` as `A/B/C.lean`; its own package is tried first."""
    path = module.replace(".", "/") + ".lean"
    head = module.split(".")[0].casefold()
    for root, pin, _package in sorted(roots, key=lambda item: item[2].casefold() != head):
        try:
            _git_source(root, pin, path)
        except subprocess.CalledProcessError:
            continue
        return root, pin, path
    return None


def _alternation(needle: str) -> str:
    return re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", needle)


def _declaration_hits(roots: list[tuple[Path, str, str]], needles: list[str]) -> list[tuple[int, str, str, int, str]]:
    """Declaration lines naming any needle, plus namespace lines for dotted needles, from pinned trees only.

    One `git grep` per root; hits are (root index, pin, path, line, text).
    """
    alternatives = []
    for needle in needles:
        if re.fullmatch(_LEAN_NAME, needle):
            parts = needle.split(".")
            alternatives.append(_DECLARATION_GREP + r"[^[:space:]]*" + _alternation(parts[-1]))
            if len(parts) > 1:
                alternatives.append(r"^[[:space:]]*namespace[[:space:]]+[^[:space:]]*" + _alternation(parts[-2]))
        else:
            alternatives.append(_alternation(needle))
    if not alternatives:
        return []
    pattern = "|".join(f"({item})" for item in alternatives)

    def grep(entry: tuple[int, tuple[Path, str, str]]) -> list[tuple[int, str, str, int, str]]:
        index, (root, pin, _) = entry
        result = subprocess.run(
            ["git", "grep", "-n", "-I", "-i", "-E", "-e", pattern, pin, "--", "*.lean"],
            cwd=root,
            text=True,
            errors="replace",
            capture_output=True,
            check=False,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip() or text.render("messages/errors.source_search_failed"))
        hits = []
        for raw in result.stdout.splitlines():
            parts = raw[len(pin) + 1 :].split(":", 2)
            if len(parts) == 3 and parts[1].isdigit():
                hits.append((index, pin, parts[0], int(parts[1]), parts[2]))
        return hits

    with ThreadPoolExecutor(max_workers=min(len(roots), 8)) as pool:
        return [hit for hits in pool.map(grep, enumerate(roots)) for hit in hits]


def _scan(root: Path, pin: str, path: str) -> tuple[list[str], list[tuple[int, str]]] | None:
    session = _SESSION.get()
    key = (str(root), pin, path)
    if session is not None and key in session.scans:
        return session.scans[key]
    try:
        lines = _git_source(root, pin, path).splitlines()
    except subprocess.CalledProcessError:
        return None
    scanned = lines, _source_declarations(lines)
    if session is not None:
        session.scans[key] = scanned
    return scanned


def _resolve_declaration_source(
    name: str, symbol: str, module: str | None = None, span: tuple[int, int] | None = None
) -> dict:
    """Find one declaration's pinned file and lines, excluding scratch copies.

    `module` and `span` come from the kickoff index and resolve the declaration exactly with no
    search; otherwise only declaration lines mentioning the name are searched. An exact qualified
    match wins; several distinct qualified matches raise AmbiguousDeclaration.
    """
    if not re.fullmatch(_LEAN_NAME, symbol):
        raise ValueError(agent_text.render("messages/errors.invalid_declaration"))
    row = problem(name)
    version, commit = measure_version(row)
    project = workspace(row, version, commit)
    roots = _roots(project, commit)
    leaf = symbol.split(".")[-1]
    if module == "this file":
        files = [(project, commit, row["file_path"])]
        span = None
    elif module:
        located = _module_file(roots, module)
        if located is None:
            raise ValueError(agent_text.render("messages/errors.module_missing", symbol=symbol, module=module))
        files = [located]
    else:
        hits = _declaration_hits(roots, [symbol])
        files = []
        for index, pin, path, _, text in hits:
            declared = _DECLARATION_PATTERN.match(text)
            if (
                declared
                and leaf.casefold() in declared.group(1).casefold()
                and (roots[index][0], pin, path) not in files
            ):
                files.append((roots[index][0], pin, path))
    scanned = 0
    found: dict[str, dict] = {}
    for root, pin, path in files:
        if scanned >= MAX_SCAN_FILES:
            break
        scanned += 1
        read = _scan(root, pin, path)
        if read is None:
            continue
        lines, starts = read
        if (
            span is not None
            and 1 <= span[0] <= span[1] <= len(lines)
            and leaf in "\n".join(lines[span[0] - 1 : span[1]])
        ):
            return {
                "root": root,
                "pin": pin,
                "path": path,
                "line": span[0],
                "end": span[1],
                "qualified": symbol,
                "file_lines": len(lines),
            }
        for index, (line_number, qualified) in enumerate(starts):
            if qualified == symbol or qualified.endswith("." + symbol):
                start = _declaration_start(lines, line_number)
                found.setdefault(
                    qualified,
                    {
                        "root": root,
                        "pin": pin,
                        "path": path,
                        "line": start,
                        "end": _declaration_end(lines, starts, index),
                        "qualified": qualified,
                        "file_lines": len(lines),
                    },
                )
    if symbol in found:
        return found[symbol]
    if len(found) > 1:
        raise AmbiguousDeclaration(symbol, sorted(found))
    if found:
        return next(iter(found.values()))
    raise ValueError(agent_text.render("messages/errors.declaration_missing", symbol=symbol))


def _indexed_entry(name: str, symbol: str) -> dict | None:
    """The kickoff index entry for an exact qualified name, with its module and line span when known."""
    from arena.context import constant_index

    inventory = _context(name)
    if inventory.get("error"):
        return None
    matches = constant_index(inventory, name=symbol)
    if len(matches) == 1:
        return matches[0]
    sources = [item for item in inventory.get("source", []) if item.get("name") == symbol]
    return {**sources[0], "kind": sources[0].get("decl")} if sources else None


def _source_hint(name: str, symbol: str) -> tuple[str, str | None, tuple[int, int] | None]:
    """Source symbol, module and exact line span for a name; constructors live in their inductive's block."""
    entry = _indexed_entry(name, symbol)
    if entry is None:
        return symbol, None, None
    module = entry.get("module")
    if entry.get("kind") == "constructor" and "." in symbol:
        return symbol.rsplit(".", 1)[0], module, None
    span = (entry["start_line"], entry["end_line"]) if "start_line" in entry and "end_line" in entry else None
    return symbol, module, span


def declaration(name: str, symbol: str) -> dict:
    with _session():
        return _declaration(name, symbol)


def _declaration(name: str, symbol: str) -> dict:
    found = _source_declaration(name, symbol)
    if found.get("found"):
        return found
    return _declaration_in_lean(name, symbol.removeprefix("decl:"))


def _source_declaration(name: str, symbol: str) -> dict:
    """Resolve a source-backed declaration without invoking Lean for a missing name."""
    if symbol.startswith("decl:"):
        symbol = symbol[5:]
    if not re.fullmatch(_LEAN_NAME, symbol):
        raise ValueError(text.render("messages/errors.invalid_declaration"))
    source_symbol, module, span = _source_hint(name, symbol)
    try:
        located = _resolve_declaration_source(name, source_symbol, module, span)
    except AmbiguousDeclaration as error:
        return {"symbol": symbol, "found": True, "ambiguous": error.candidates}
    except ValueError:
        located = None
    if located is not None:
        lines = _git_source(located["root"], located["pin"], located["path"]).splitlines()
        qualified = located["qualified"] if module is None else symbol
        return {
            "symbol": symbol,
            "handle": f"decl:{qualified}",
            "name": qualified,
            "found": True,
            "pin": located["pin"],
            "path": located["path"],
            "line": located["line"],
            "end_line": located["end"],
            "file_lines": located["file_lines"],
            "source_text": "\n".join(lines[located["line"] - 1 : located["end"]]),
        }
    entry = _indexed_entry(name, symbol)
    if entry is not None and module not in (None, "this file"):
        # Indexed, but no pinned source root holds its module (for example the Lean toolchain).
        return {
            "symbol": symbol,
            "found": True,
            "name": symbol,
            "kind": entry.get("kind"),
            "module": module,
            "signature": entry.get("sig"),
        }
    return {"symbol": symbol, "found": False, "hint": text.render("messages/errors.no_source_declaration")}


def _declaration_in_lean(name: str, symbol: str) -> dict:
    """Resolve a name the way the theorem's own file does (namespaces, opens, imported libraries)."""
    from arena.engine import candidate_file, run_lean

    row = problem(name)
    version, commit = measure_version(row)
    built = candidate_file(row, row["src"], version, commit)
    inserted = (Path(__file__).with_name("lean") / "declaration.lean").read_text() + f"arena_decl {symbol}\n\n"
    text = built["text"][: built["head"]] + inserted + built["text"][built["head"] :]
    ran = run_lean(row, built["path"], text, prefix_end=built["head"])
    if ran is None:
        raise ValueError(agent_text.render("messages/errors.resolve_name_timeout"))
    records = [json.loads(raw) for raw in re.findall(r"^ARENA_DECL (\{.*\})$", ran[1], re.M)]
    found = [item for item in records if item.get("found")]
    if not found:
        return {
            "symbol": symbol,
            "found": False,
            "hint": agent_text.render("messages/errors.name_not_visible"),
        }
    best = found[0]
    return {
        "symbol": symbol,
        "found": True,
        "name": best["name"],
        "kind": best["kind"],
        "module": best["module"],
        "source": f"{best['module']}" + (f":{best['line']}" if best.get("line") else ""),
        "signature": best["signature"],
        **({"alternatives": [item["name"] for item in found[1:]]} if len(found) > 1 else {}),
    }


def packet(name: str) -> str:
    """Kickoff packet: task, exchange rates, source-derived context. Built once per row and cached."""
    from arena.context import render_packet

    return render_packet(name)


def _append(directory: Path, event: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "ledger.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        data = (json.dumps({"ts": time.time(), **event}, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _evaluate(name: str, proof: str, mode: str, known: dict | None = None, lane: str = "model") -> dict:
    """`engine.evaluate`, sending background-lane work (full checks, cold verification) to the Lean session's
    background lane when the engine supports lanes, so it never takes a model worker."""
    if lane != "model" and "lane" in inspect.signature(evaluate).parameters:
        return evaluate(name, proof, mode, known=known, lane=lane)
    return evaluate(name, proof, mode, known=known)


def _refuse_if_tripped(directory: Path) -> None:
    """After the Lean circuit breaker tripped, model-lane work is refused: the runner is stopping the run."""
    if lean_health.tripped(directory):
        raise ValueError(text.render("messages/errors.stopped_run"))


def _check_breaker(directory: Path) -> None:
    lean_health.trip_if_unhealthy(directory, events(directory))


def events(directory: Path) -> list[dict]:
    file = directory / "ledger.jsonl"
    if not file.exists():
        return []
    with file.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        data = handle.read().decode()
    rows = []
    for line in data.splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn final line from a killed writer must not make the run unreadable
    return rows


@contextmanager
def lean_lock(directory: Path, lane: str = "model"):
    """One Lean job at a time per lane and run.

    The model's own work (evaluate, probe, profile) shares the `model`
    lane. Harness checks run in the `background` lane, so they never delay the
    model. Heartbeats count allocations, not time, so two concurrent compiles
    do not change each other's measurement; the lanes only bound CPU and RAM.
    """
    directory.mkdir(parents=True, exist_ok=True)
    name = "lean.lock" if lane == "model" else f"lean-{lane}.lock"
    with (directory / name).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _snapshot(directory: Path, candidate_id: str, proof: str) -> Path:
    proof_path = directory / "proofs" / f"{candidate_id}.lean"
    if proof_path.exists():
        return proof_path
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = proof_path.with_name(f"{candidate_id}.{os.getpid()}.tmp")
    temporary.write_text(proof)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(proof_path)
    return proof_path


@contextmanager
def _candidate_lock(directory: Path, candidate_id: str):
    locks = directory / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / f"{candidate_id}.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _copy_tracked(project: Path, shadow: Path) -> None:
    """Copy only the files git tracks in the pinned checkout into the run's Lean project.

    Shared workspaces accumulate untracked candidate files from earlier compiles (other runs' proofs);
    copying the directory would let a new run find them with lean_local_search.
    """
    listed = (
        subprocess.run(["git", "-C", str(project), "ls-files", "-z"], check=True, capture_output=True)
        .stdout.decode()
        .split("\0")
    )
    for relative in filter(None, listed):
        source = project / relative
        if not source.is_file():
            continue
        target = shadow / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def init(name: str, run_id: str, extra: str = "") -> dict:
    directory = run_dir(run_id)
    # The runner may already have started the run's Lean session here; nothing else counts as a run.
    if directory.exists() and any(
        item.name not in lean_session.SESSION_FILES and item.name != "lean-session.log" for item in directory.iterdir()
    ):
        raise ValueError(agent_text.render("messages/errors.run_exists", directory=directory))
    row = problem(name)
    version, commit = versions(row)[0]
    project = workspace(row, version, commit)
    directory.mkdir(parents=True, exist_ok=True)
    text = packet(name) + ("\nAdditional instructions:\n" + extra + "\n" if extra else "")
    (directory / "packet.txt").write_text(text)
    shadow = directory / "scratch" / "project"
    _copy_tracked(project, shadow)
    (shadow / ".lake").symlink_to(project / ".lake", target_is_directory=True)
    _append(
        directory,
        {
            "kind": "init",
            "theorem": name,
            "version": version,
            "commit": commit,
            "versions": versions(row),
            "packet_sha256": hashlib.sha256(text.encode()).hexdigest(),
        },
    )
    reference_id = hashlib.sha256((name + "\0" + row["src"]).encode()).hexdigest()
    _snapshot(directory, reference_id, row["src"])
    _append(
        directory,
        {
            "kind": "candidate",
            "candidate_id": reference_id,
            "parents": [],
            "hypothesis": agent_text.render("replies/candidate.original_reference"),
            "origin": "reference",
            "source_versions": versions(row),
            "evaluator_sha256": hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest(),
        },
    )
    _file_node(directory, events(directory), reference_id, row["src"], operation={"type": "root", "from": []})
    _append(directory, {"kind": "focus", "proof_id": reference_id, "reason": "start"})
    materialize(name, run_id, row["src"])
    _append(directory, {"kind": "current", "candidate_id": reference_id})
    return {
        "packet": str(directory / "packet.txt"),
        "shadow": str(shadow),
        "candidate_path": str(shadow / source_path(row)),
    }


def _externalize_output(directory: Path, key: str, result: dict) -> dict:
    """Keep full Lean output beside the ledger; results carry only a reference."""
    for version, item in (result.get("compat") or {}).items():
        raw = item.pop("raw_output", None)
        if raw:
            path = directory / "diagnostics" / f"{key[:16]}-{result.get('mode', 'eval')}-{version}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw + "\n")
            item["full_diagnostics_ref"] = str(path.relative_to(directory))
    return result


def _evaluator_sha() -> str:
    return hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest()


def materialize(name: str, run_id: str, proof: str) -> dict:
    """Write the exact file the evaluator compiles (minus the heartbeat wrapper)."""
    row = problem(name)
    version, commit = versions(row)[0]
    built = candidate_file(row, proof, version, commit)
    path = run_dir(run_id) / "scratch" / "project" / source_path(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(built["text"])
    return {"candidate_path": str(path), "start_line": built["start_line"], "end_line": built["end_line"]}


def _candidate_ids(history: list[dict]) -> list[str]:
    return [item["candidate_id"] for item in history if item.get("kind") == "candidate"]


def _label(history: list[dict], candidate_id: str) -> str | None:
    ids = _candidate_ids(history)
    return f"#{ids.index(candidate_id) + 1}" if candidate_id in ids else None


def node_label(history: list[dict], proof_id: str) -> str:
    """Return the stable candidate or probe label used by graph views."""
    candidate = _label(history, proof_id)
    return candidate or _probe_numbers(history).get(proof_id, f"p{proof_id[:8]}")


def _graph_node_id(history: list[dict], proof_id: str) -> str:
    """Resolve the projection's nK id without rebuilding route signatures."""
    seen: set[str] = set()
    for item in history:
        if item.get("kind") == "candidate":
            current = item["candidate_id"]
        elif item.get("kind") == "probe":
            current = item["proof_id"]
        else:
            continue
        if current in seen:
            continue
        seen.add(current)
        if current == proof_id:
            return f"n{len(seen)}"
    raise KeyError(proof_id)


def resolve_candidate_ref(history: list[dict], reference: str) -> str:
    candidates = _candidate_ids(history)
    reference = reference.strip()
    if re.fullmatch(r"#?[1-9][0-9]*", reference):
        index = int(reference.lstrip("#"))
        if index <= len(candidates):
            return candidates[index - 1]
    elif reference in candidates:
        return reference
    elif re.fullmatch(r"[0-9a-f]{8,63}", reference):
        matches = [candidate for candidate in candidates if candidate.startswith(reference)]
        if len(matches) == 1:
            return matches[0]
    raise ValueError(text.render("messages/errors.unknown_candidate", reference=reference, count=len(candidates)))


def _current(history: list[dict]) -> str | None:
    """Candidate whose file was most recently materialized."""
    for item in reversed(history):
        if item.get("kind") == "current":
            return item["candidate_id"]
    return None


def _probe_numbers(history: list[dict]) -> dict[str, str]:
    """Short `pN` IDs in order of first appearance of each distinct draft."""
    numbers: dict[str, str] = {}
    for item in history:
        if item.get("kind") == "probe" and item["proof_id"] not in numbers:
            numbers[item["proof_id"]] = f"p{len(numbers) + 1}"
    return numbers


def resolve_probe_ref(history: list[dict], reference: str) -> str:
    reference = reference.strip().lower()
    for proof_id, label in _probe_numbers(history).items():
        if reference in (label, proof_id):
            return proof_id
    raise ValueError(
        text.render("messages/errors.unknown_probe", reference=reference, count=len(_probe_numbers(history)))
    )


def resolve_parent_ref(history: list[dict], reference: str) -> str:
    """A parent given as a candidate (#N) or as a probe (pN); a probe stands for the candidate it was built on."""
    if re.fullmatch(r"\s*[pP][1-9][0-9]*\s*", reference):
        proof_id = resolve_probe_ref(history, reference)
        parent = next(
            (
                item.get("parent")
                for item in reversed(history)
                if item.get("kind") == "probe" and item["proof_id"] == proof_id
            ),
            None,
        )
        if parent:
            return parent
        raise ValueError(text.render("messages/errors.probe_parent_missing", reference=reference.strip()))
    return resolve_candidate_ref(history, reference)


def _graph_proof_ids(history: list[dict]) -> list[str]:
    found: list[str] = []
    for event in history:
        if event.get("kind") == "candidate":
            proof_id = event["candidate_id"]
        elif event.get("kind") == "probe":
            proof_id = event["proof_id"]
        else:
            continue
        if proof_id not in found:
            found.append(proof_id)
    return found


def resolve_node_ref(history: list[dict], reference: str) -> str:
    value = reference.strip()
    proof_ids = _graph_proof_ids(history)
    if re.fullmatch(r"n[1-9][0-9]*", value):
        index = int(value[1:])
        if index <= len(proof_ids):
            return proof_ids[index - 1]
    elif re.fullmatch(r"#[1-9][0-9]*", value):
        try:
            return resolve_candidate_ref(history, value)
        except ValueError:
            pass
    elif re.fullmatch(r"[pP][1-9][0-9]*", value):
        try:
            return resolve_probe_ref(history, value)
        except ValueError:
            pass
    elif re.fullmatch(r"[0-9a-fA-F]{8,64}", value):
        matches = [proof_id for proof_id in proof_ids if proof_id.startswith(value.lower())]
        if len(matches) == 1:
            return matches[0]
    raise ValueError(text.render("messages/errors.node_reference_invalid", reference=value))


def _named_parent_id(history: list[dict], reference: str | None) -> str | None:
    if not reference:
        return None
    try:
        if re.fullmatch(r"\s*[pP][1-9][0-9]*\s*", reference):
            return resolve_probe_ref(history, reference)
        return resolve_candidate_ref(history, reference)
    except ValueError:
        return None


def _proof_reader(directory: Path) -> Callable[[str], str | None]:
    """Read a stored proof by id, or None when the file is missing."""

    def read(ident: str) -> str | None:
        path = directory / "proofs" / f"{ident}.lean"
        return path.read_text() if path.is_file() else None

    return read


def _file_node(
    directory: Path,
    history: list[dict],
    proof_id: str,
    proof: str,
    named_parent: str | None = None,
    operation: dict | None = None,
    projection_out: list[Graph] | None = None,
) -> tuple[dict, bool]:
    """Append exactly one graph edge per proof id under the run's graph lock."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "graph.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        history = events(directory)
        existing = next(
            (event for event in history if event.get("kind") == "edge" and event.get("proof_id") == proof_id), None
        )
        if existing:
            if projection_out is not None:
                projection_out.append(Graph.from_history(history, _proof_reader(directory)))
            return existing, False
        read = _proof_reader(directory)
        graph = Graph.from_history(history, read)
        recent = [
            node.proof_id
            for node in graph.nodes
            if node.proof_id != proof_id and (directory / "proofs" / f"{node.proof_id}.lean").is_file()
        ][-20:]
        prior_texts = [(ident, read(ident)) for ident in recent]
        measured_id, measured_score = measured_parent(prior_texts, proof)
        focus_similarity = None
        if operation is not None:
            edge_type = operation["type"]
            sources = list(operation.get("from", []))
            exact = True
            operation_data = (
                {"hole": operation["hole"], "text": operation["text"]}
                if edge_type == "filled_from"
                else dict(operation)
            )
        else:
            in_batch, batch_focus = _BATCH_FOCUS.get()
            focus_id = batch_focus if in_batch else graph.focus
            focus_proof = read(focus_id) if focus_id else None
            focus_similarity = similarity(focus_proof, proof) if focus_proof is not None else None
            if focus_id and focus_similarity is not None and focus_similarity >= FILING_MIN_SIMILARITY:
                edge_type, sources, exact = "filed_under_focus", [focus_id], False
            else:
                edge_type, sources, exact = "root", [], False
            operation_data = None
        event = {
            "kind": "edge",
            "proof_id": proof_id,
            "type": edge_type,
            "from": sources,
            "exact": exact,
            "similarity": focus_similarity,
            "named_parent": named_parent,
            "measured_parent": measured_id,
            "measured_similarity": measured_score,
            "operation": operation_data,
        }
        _append(directory, event)
        earlier: dict[str, list[dict]] = {}
        graph_nodes = {node.proof_id: node for node in graph.nodes}
        for node in graph.nodes:
            if node.route is not None:
                earlier.setdefault(node.route, []).append(node.signature)
        parent = sources[0] if sources else None
        parent_node = graph_nodes.get(parent)
        assignment = routes.assign(
            earlier,
            routes.signature(proof),
            parent_node.route if parent_node else None,
            routes.line_diff(parent_node.proof_text, proof) if parent_node and parent_node.route else None,
        )
        origin = next(
            (
                item.get("origin", "model")
                for item in history
                if item.get("kind") == "candidate" and item.get("candidate_id") == proof_id
            ),
            "model",
        )
        attempt_kind = (
            "probe"
            if any(item.get("kind") == "probe" and item.get("proof_id") == proof_id for item in history)
            else "candidate"
        )
        _append(
            directory,
            {
                "kind": "route",
                "proof_id": proof_id,
                **assignment,
                "assigned_by": "signature",
                "parent": parent,
                "holes": len(re.findall(r"\bsorry\b", proof)),
                "credited": assignment["new"] and origin == "model",
                "label": assignment["route"],
                "short_label": assignment["route"],
                "attempt_kind": attempt_kind,
            },
        )
        batch_newly_filed = _BATCH_NEWLY_FILED.get()
        if batch_newly_filed is not None:
            batch_newly_filed.add(proof_id)
        if projection_out is not None:
            projection_out.append(Graph.from_history(events(directory), read))
        return event, True


def _settle_focus(directory: Path, proof_ids: list[str], graph: Graph | None = None) -> Graph:
    history = events(directory)
    graph = graph or Graph.from_history(history, _proof_reader(directory))
    nodes = {node.proof_id: node for node in graph.nodes}
    eligible = [nodes[ident] for ident in proof_ids if ident in nodes and nodes[ident].status in ("closed", "sketch")]
    if not eligible:
        return graph

    def rank(node: Node) -> tuple[int, float]:
        if node.status == "closed":
            return (1, node.score if node.score is not None else 0.0)
        proof = (directory / "proofs" / f"{node.proof_id}.lean").read_text()
        return (0, -len(re.findall(r"\bsorry\b", proof)))

    winner = max(eligible, key=rank)
    if winner.proof_id != graph.focus:
        _append(directory, {"kind": "focus", "proof_id": winner.proof_id, "reason": "batch_best"})
        graph.focus = winner.proof_id
    return graph


def _check_stall(directory: Path, graph: Graph, newly_filed: set[str]) -> None:
    raw_threshold = os.environ.get("ARENA_STALL_M", "12")
    try:
        threshold = int(raw_threshold)
    except ValueError as error:
        raise ValueError(text.render("messages/errors.stall_threshold")) from error
    mode = os.environ.get("ARENA_STALL_TARGET", "best_other_cell")
    if mode not in ("best_other_cell", "least_visited", "map_only"):
        raise ValueError(text.render("messages/errors.stall_target", mode=mode))
    current_focus = graph.focus
    for fired in stall_fires(graph, threshold):
        if fired["after"] not in newly_filed:
            continue
        target = stall_target(graph, fired, mode)
        _append(
            directory,
            {
                "kind": "stall",
                "root": fired["root"],
                "count": fired["count"],
                "mode": mode,
                "target": target.node.proof_id if target else None,
            },
        )
        if target is None or target.node.proof_id == current_focus:
            continue
        _append(
            directory,
            {
                "kind": "focus",
                "proof_id": target.node.proof_id,
                "reason": "stall",
                "root": fired["root"],
                "cell": target.letter,
                "visits": target.visits,
            },
        )
        current_focus = target.node.proof_id


IDEA_STATUSES = ("active", "parked", "succeeded", "abandoned")


def _current_active_idea(history: list[dict]) -> str | None:
    """The latest idea still marked active, derived from append-only idea events."""
    statuses: dict[str, str] = {}
    for item in history:
        if item.get("kind") == "idea":
            statuses[item["id"]] = item.get("status", "active")
        elif item.get("kind") == "idea_update" and item.get("id") in statuses:
            statuses[item["id"]] = item.get("status", statuses[item["id"]])
    return next((idea_id for idea_id, status in reversed(list(statuses.items())) if status == "active"), None)


def _region(text: str) -> list[int] | str:
    """Proof lines such as "12-30", "lines 12–30", "L12..L30" or "line 7"; anything else is kept as text."""
    numbers = [int(n) for n in re.findall(r"\d+", text)][:2]
    if not numbers:
        return text.strip()[:120]
    return [min(numbers), max(numbers)]


def record_idea(
    run_id: str,
    title: str | None = None,
    hypothesis: str = "",
    region: str | None = None,
    expected_effect: dict | None = None,
    idea_id: str | None = None,
    status: str | None = None,
    reason: str = "",
) -> dict:
    """Create or update a model-owned idea. The harness never authors or schedules ideas."""
    directory = run_dir(run_id)
    history = events(directory)
    if not history or not history[0].get("theorem"):
        raise ValueError(text.render("messages/errors.run_uninitialized"))
    if status is not None and status not in IDEA_STATUSES:
        raise ValueError(text.render("messages/errors.idea_statuses", statuses=", ".join(IDEA_STATUSES)))
    if status in ("parked", "abandoned", "succeeded") and not reason.strip():
        raise ValueError(text.render("messages/errors.idea_reason", status=status))
    effect = {
        str(k): str(v)[:80] for k, v in (expected_effect or {}).items() if k in ("tokens", "heartbeats", "compat")
    }
    span = _region(region) if region and region.strip() else None
    known = {item["id"]: item for item in history if item.get("kind") == "idea"}
    if idea_id:
        idea_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", idea_id.strip())[:40] or None
    if idea_id and idea_id not in known and not (title and title.strip()):
        raise ValueError(
            text.render("messages/errors.idea_id_unknown", idea_id=idea_id, ideas=", ".join(known) or "none yet")
        )
    if idea_id and idea_id in known:
        update = {"kind": "idea_update", "id": idea_id}
        if title:
            update["title"] = title.strip()[:120]
        if hypothesis:
            update["hypothesis"] = hypothesis.strip()[:600]
        if span:
            update["region"] = span
        if effect:
            update["expected_effect"] = effect
        if status:
            update["status"] = status
        if reason.strip():
            update["reason"] = reason.strip()[:300]
        _append(directory, update)
        return {"ok": True, **{k: v for k, v in update.items() if k != "kind"}}
    if not title or not title.strip():
        raise ValueError(text.render("messages/errors.idea_title_missing"))
    # Models often name their own ideas; keep that name so later updates by it work.
    identifier = idea_id or next(f"i{n}" for n in range(len(known) + 1, len(known) + 1000) if f"i{n}" not in known)
    item = {
        "kind": "idea",
        "id": identifier,
        "title": title.strip()[:120],
        "hypothesis": hypothesis.strip()[:600],
        "region": span,
        "expected_effect": effect,
        "status": status or "active",
        "reason": reason.strip()[:300],
    }
    _append(directory, item)
    return {"ok": True, **{k: v for k, v in item.items() if k != "kind"}}


def _metric_score(metrics: dict | None) -> float | None:
    if not metrics:
        return None
    value = metrics.get("proxy")
    return value if value is not None else metrics.get("estimated_proxy")


def _evaluation_status(result: dict, mode: str, total: int) -> str:
    compat = result.get("compat") or {}
    if mode == "full" and len(compat) == total and all(v.get("passed") for v in compat.values()):
        return "full"
    return "primary" if next(iter(compat.values()), {}).get("passed") else "fail"


def _summaries(history: list[dict]) -> list[dict]:
    """One row per candidate: best evaluation, status and score. Cheap; no Lean."""
    total = len((history[0].get("versions") if history else None) or [1])
    rows: dict[str, dict] = {}
    for item in history:
        if item.get("kind") == "candidate":
            rows[item["candidate_id"]] = {
                "id": item["candidate_id"],
                "n": len(rows) + 1,
                "idea_id": item.get("idea_id"),
                "origin": item.get("origin", "model"),
                "parents": item.get("parents", []),
                "evaluations": [],
            }
        elif item.get("kind") == "evaluation" and item["candidate_id"] in rows:
            result = item["result"]
            rows[item["candidate_id"]]["evaluations"].append(
                {
                    "mode": item["mode"],
                    "status": _evaluation_status(result, item["mode"], total),
                    "result": result,
                    "score": _metric_score(result.get("metrics")),
                }
            )
    for row in rows.values():
        full = [e for e in row["evaluations"] if e["status"] == "full"]
        primary = [e for e in row["evaluations"] if e["status"] == "primary"]
        chosen = (
            max(full, key=lambda e: e["score"] or -1)
            if full
            else max(primary, key=lambda e: e["score"] or -1)
            if primary
            else (row["evaluations"][-1] if row["evaluations"] else None)
        )
        row["status"] = chosen["status"] if chosen else "unevaluated"
        result = chosen["result"] if chosen else {}
        row.update(
            tokens=result.get("tokens"),
            heartbeats=result.get("heartbeat"),
            score=chosen["score"] if chosen else None,
            verified=bool(full),
            metrics=result.get("metrics"),
            evaluated=chosen is not None,
        )
    return list(rows.values())


def _brief(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "candidate": f"#{row['n']}",
        "tokens": row["tokens"],
        "heartbeats": row["heartbeats"],
        ("proxy" if row["verified"] else "estimated_proxy"): row["score"],
        "status": row["status"],
    }


def _best(rows: list[dict], exclude: str | None = None) -> dict | None:
    pool = [
        r
        for r in rows
        if r["id"] != exclude
        and r["score"] is not None
        and r["status"] in ("full", "primary")
        and r["origin"] != "reference"
    ]
    return max(pool, key=lambda r: (r["verified"], r["score"]), default=None)


def _delta(current: dict, other: dict | None) -> dict | None:
    if not other or other.get("tokens") is None or other.get("heartbeats") is None:
        return None
    out = {"tokens": current["tokens"] - other["tokens"], "heartbeats": current["heartbeats"] - other["heartbeats"]}
    if current.get("score") is not None and other.get("score") is not None:
        out["proxy"] = round(current["score"] - other["score"], 2)
    return out


def _advisory(rows: list[dict], window: int = 4) -> str | None:
    """Facts only: the last attempts all descend from one non-reference node with no gain."""
    model = [r for r in rows if r["origin"] == "model" and r["evaluated"]]
    if len(model) < window:
        return None
    by_id = {r["id"]: r for r in rows}

    def lineage(row: dict) -> set[str]:
        found: set[str] = set()
        stack = list(row["parents"])
        while stack:
            parent = stack.pop()
            if parent in by_id and parent not in found:
                found.add(parent)
                stack.extend(by_id[parent]["parents"])
        return found

    recent = model[-window:]
    shared = set.intersection(*(lineage(r) for r in recent)) - {r["id"] for r in rows if r["origin"] == "reference"}
    if not shared:
        return None
    root = max(shared, key=lambda i: by_id[i]["n"])
    base = by_id[root]["score"]
    if any(r["score"] is not None and (base is None or r["score"] > base) for r in recent):
        return None
    score_suffix = f" of {base}." if base is not None else "."
    return text.render(
        "replies/state.advisory",
        window=window,
        first=recent[0]["n"],
        last=recent[-1]["n"],
        root=by_id[root]["n"],
        score_suffix=score_suffix,
    )


def _model_view(result: dict) -> dict:
    """Compact, non-duplicated payload for the model; the ledger keeps the full result."""
    view = {
        key: result[key]
        for key in (
            "ok",
            "mode",
            "candidate",
            "probe",
            "tokens",
            "heartbeat",
            "idea_id",
            "cached",
            "candidate_path",
            "start_line",
            "end_line",
            "error",
            "notes",
            "full_check",
            "advisory",
            "scored",
            "contains_sorry",
            "goals",
        )
        if result.get(key) not in (None, [], "")
    }
    # `ok` says the tool ran; `compiled` says whether the draft compiled. On a failed compile the
    # heartbeat is only the work done before the error, not a cost of the draft.
    failed = any(not info.get("passed") for info in (result.get("compat") or {}).values())
    if failed:
        view = {("heartbeat_to_failure" if key == "heartbeat" else key): value for key, value in view.items()}
        view["compiled"] = False
    metrics = result.get("metrics")
    if metrics and metrics.get("axes"):
        view["metrics"] = {
            key: metrics[key] for key in ("proxy", "estimated_proxy", "assumes_full_compat", "deltas") if key in metrics
        }
        view["metrics"]["axes"] = {
            axis: {k: v for k, v in info.items() if k != "reference"} for axis, info in metrics["axes"].items()
        }
    elif metrics is not None and not metrics.get("compiled"):
        view["metrics"] = {"compiled": False}
    compat = {}
    for version, info in (result.get("compat") or {}).items():
        item = {"passed": bool(info.get("passed"))}
        for key in ("heartbeats", "diagnostics", "full_diagnostics_ref", "error"):
            if info.get(key) not in (None, [], ""):
                item["heartbeats_to_failure" if key == "heartbeats" and not item["passed"] else key] = info[key]
        lean = info.get("lean") or {}
        if lean.get("path") == "session":
            item["lean"] = "session"
        elif lean.get("path") == "cold-fallback":
            item["lean"] = text.render("messages/errors.cold_session_unavailable", reason=lean.get("reason"))
        counts = info.get("diagnostic_counts") or {}
        if counts.get("omitted"):
            item["omitted_diagnostics"] = counts["omitted"]
        outside = info.get("outside_target") or {}
        if outside.get("errors") or outside.get("warnings"):
            item["outside_target"] = {k: v for k, v in outside.items() if v}
        compat[version] = item
    if compat:
        view["compat"] = compat
    return view


def _evaluation_key(candidate_id: str, mode: str, row: dict) -> str:
    return hashlib.sha256((candidate_id + mode + _evaluator_sha() + json.dumps(versions(row))).encode()).hexdigest()


def _compiled_versions(history: list[dict], candidate_id: str, row: dict) -> dict:
    """Passing per-version results of this evaluator's fast check of a candidate, for reuse."""
    key = _evaluation_key(candidate_id, "fast", row)
    fast = next((item for item in history if item.get("kind") == "evaluation" and item.get("key") == key), None)
    return {
        version: info
        for version, info in ((fast or {}).get("result", {}).get("compat") or {}).items()
        if info.get("passed")
    }


def record_evaluation(
    name: str,
    run_id: str,
    proof: str,
    mode: str,
    parents: list[str] | None = None,
    hypothesis: str = "",
    origin: str = "model",
    merge: dict | None = None,
    materialize_live: bool = True,
    idea_id: str | None = None,
    lane: str = "model",
    trigger: str = "model",
    precomputed: dict | None = None,
    operation: dict | None = None,
) -> dict:
    """Record a candidate and its evaluation. `precomputed` is a result the caller already
    compiled for this exact proof and mode; `trigger` says whether the model or the
    harness asked for it."""
    if mode not in ("fast", "full"):
        raise ValueError(text.render("messages/errors.evaluation_mode"))
    directory = run_dir(run_id)
    if lane == "model" and trigger == "model":
        _refuse_if_tripped(directory)
    row = problem(name)
    # Forbidden constructs and statement edits are rejected before anything is recorded,
    # so `sorry` drafts can never become candidates.
    validate_proof(row, proof)
    candidate_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    notes: list[str] = []
    with _candidate_lock(directory, candidate_id):
        history = events(directory)
        if not history or history[0].get("theorem") != name:
            raise ValueError(text.render("messages/errors.run_theorem_mismatch"))
        if history[0].get("versions") and history[0]["versions"] != [list(pair) for pair in versions(row)]:
            raise ValueError(text.render("messages/errors.source_versions_changed"))
        known = set(_candidate_ids(history))
        if candidate_id not in known and idea_id is None:
            idea_id = _current_active_idea(history)
        explicit: list[str] = []
        for reference in parents or []:
            try:
                resolved = resolve_candidate_ref(history, reference)
            except ValueError as error:
                notes.append(text.render("messages/errors.parent_ignored", reference=reference, error=error))
                continue
            if resolved != candidate_id and resolved not in explicit:
                explicit.append(resolved)
        lineage = explicit or ([_current(history)] if candidate_id not in known and _current(history) else [])
        lineage = [parent for parent in lineage if parent != candidate_id]
        if candidate_id in known and idea_id is None:
            idea_id = next(
                item.get("idea_id")
                for item in history
                if item.get("kind") == "candidate" and item["candidate_id"] == candidate_id
            )
        if idea_id and idea_id not in {item["id"] for item in history if item.get("kind") == "idea"}:
            notes.append(text.render("messages/errors.idea_id_label", idea_id=idea_id))
        _snapshot(directory, candidate_id, proof)
        if candidate_id not in known:
            _append(
                directory,
                {
                    "kind": "candidate",
                    "candidate_id": candidate_id,
                    "parents": lineage,
                    "hypothesis": hypothesis,
                    "origin": origin,
                    "merge": merge,
                    "idea_id": idea_id,
                    "source_versions": versions(row),
                    "evaluator_sha256": _evaluator_sha(),
                },
            )
        elif explicit and not any(
            item.get("kind") == "derivation"
            and item.get("candidate_id") == candidate_id
            and item.get("parents") == explicit
            for item in history
        ):
            original = next(
                item for item in history if item.get("kind") == "candidate" and item["candidate_id"] == candidate_id
            )
            if original.get("parents", []) != explicit:
                _append(
                    directory,
                    {
                        "kind": "derivation",
                        "candidate_id": candidate_id,
                        "parents": explicit,
                        "origin": origin,
                        "merge": merge,
                    },
                )
        key = _evaluation_key(candidate_id, mode, row)
        prior = next(
            (item for item in reversed(history) if item.get("kind") == "evaluation" and item["key"] == key), None
        )
        if prior:
            result = json.loads(json.dumps(prior["result"]))
        elif precomputed is not None:
            result = precomputed
        else:
            try:
                with lean_lock(directory, lane):
                    result = _evaluate(
                        name,
                        proof,
                        mode,
                        known=_compiled_versions(history, candidate_id, row) if mode == "full" else None,
                        lane=lane,
                    )
            except (ValueError, FileNotFoundError) as error:
                result = {
                    "ok": False,
                    "name": name,
                    "mode": mode,
                    "error": str(error),
                    "compat": {},
                    "tokens": None,
                    "heartbeat": None,
                    "local_proxy": None,
                }
                if isinstance(error, FileNotFoundError):
                    result["lean_unavailable"] = True  # Lean (or the workspace) could not run: counts for the breaker
        if not prior:
            _externalize_output(directory, candidate_id, result)
            _append(
                directory,
                {
                    "kind": "evaluation",
                    "candidate_id": candidate_id,
                    "key": key,
                    "mode": mode,
                    "trigger": trigger,
                    "result": result,
                },
            )
    if lane == "model" and trigger == "model" and not prior:
        _check_breaker(directory)
    location = materialize(name, run_id, proof) if materialize_live and result.get("tokens") is not None else {}
    if location:
        _append(directory, {"kind": "current", "candidate_id": candidate_id})
    filing_history = events(directory)
    in_batch, _ = _BATCH_FOCUS.get()
    projection_out: list[Graph] = []
    _, newly_filed = _file_node(
        directory,
        filing_history,
        candidate_id,
        proof,
        _named_parent_id(filing_history, (parents or [None])[0]),
        operation,
        None if in_batch else projection_out,
    )
    if not in_batch:
        graph = _settle_focus(directory, [candidate_id], projection_out[0] if projection_out else None)
        _check_stall(directory, graph, {candidate_id} if newly_filed else set())
    history = events(directory)
    rows = _summaries(history)
    me = next((r for r in rows if r["id"] == candidate_id), None)
    result.setdefault("metrics", None)
    if me and result["metrics"] and result["metrics"].get("axes"):
        deltas = result["metrics"].setdefault("deltas", {})
        current = {
            "tokens": result["tokens"],
            "heartbeats": result["heartbeat"],
            "score": _metric_score(result["metrics"]),
        }
        first_parent = next((r for r in rows if r["id"] == (explicit or lineage or [None])[0]), None)
        if first_parent and first_parent["evaluated"]:
            deltas["vs_parent"] = {"candidate": f"#{first_parent['n']}", **(_delta(current, first_parent) or {})}
        best = _best(rows, exclude=candidate_id)
        if best:
            deltas["vs_best"] = {"candidate": f"#{best['n']}", **(_delta(current, best) or {})}
    verified = _best([r for r in rows if r["verified"]])
    fast = _best([r for r in rows if not r["verified"]])
    best_line = {"verified": _brief(verified)}
    if fast and (not verified or (fast["score"] or 0) > (verified["score"] or 0)):
        best_line["fast_only"] = _brief(fast)
    return {
        **result,
        "candidate_id": candidate_id,
        "candidate": _label(history, candidate_id),
        "node_number": _candidate_ids(history).index(candidate_id) + 1,
        "idea_id": idea_id,
        "cached": prior is not None,
        "notes": notes,
        "best_so_far": best_line,
        "advisory": _advisory(rows),
        **location,
    }


def evaluate_request(
    name: str,
    run_id: str,
    proof: str | None = None,
    mode: str = "fast",
    parents: list[str] | None = None,
    hypothesis: str = "",
    idea_id: str | None = None,
    candidate_ref: str | None = None,
    from_probe: str | None = None,
) -> dict:
    """Entry for the model: evaluate a proof, an existing `#N`, or a probe by ID."""
    if proof is not None and not proof.strip():
        proof = None
    candidate_ref = candidate_ref or None
    from_probe = from_probe or None
    if sum(value is not None for value in (proof, candidate_ref, from_probe)) != 1:
        raise ValueError(text.render("messages/errors.evaluation_reference"))
    directory = run_dir(run_id)
    history = events(directory)
    if candidate_ref:
        candidate_id = resolve_candidate_ref(history, candidate_ref)
        proof = (directory / "proofs" / f"{candidate_id}.lean").read_text()
    elif from_probe:
        proof_id = resolve_probe_ref(history, from_probe)
        source = next(
            item for item in reversed(history) if item.get("kind") == "probe" and item["proof_id"] == proof_id
        )
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
        idea_id = idea_id or source.get("idea_id")
        parents = parents or ([source["parent"]] if source.get("parent") else None)
    if not proof:
        raise ValueError(text.render("messages/errors.evaluation_proof_missing"))
    try:
        result = record_evaluation(name, run_id, proof, mode, parents, hypothesis, idea_id=idea_id)
    except ValueError as error:
        if str(error) in ("FORBIDDEN: sorry", "FORBIDDEN: admit"):
            raise ValueError(text.render("messages/errors.probe_forbidden", error=error)) from None
        raise
    return _model_view({**result, "full_check": _full_check_status(events(directory), result["candidate_id"])})


def _full_check_status(history: list[dict], candidate_id: str) -> str | None:
    """What the model needs to know about the other toolchains, without asking for it."""
    rows = {r["id"]: r for r in _summaries(history)}
    row = rows.get(candidate_id)
    if not row or row["status"] == "fail":
        return None
    total = len(history[0].get("versions") or [1])
    done = next((e for e in reversed(row["evaluations"]) if e["mode"] == "full"), None)
    if done:
        return _check_text(row["n"], done["result"], total)
    return text.render("replies/check.queued", count=total - 1)


# Results compiled ahead of time for the current batch, keyed by normalized draft text.
_PRECOMPILED: ContextVar[dict[str, dict] | None] = ContextVar("arena_precompiled_probes", default=None)
PROBE_GB = 2.0  # one Lean process compiling a Mathlib-sized file
PROBE_WORKERS = 4


def _probe_workers(count: int) -> int:
    """Concurrent compiles for a batch: bounded by CPUs, free memory and four; 1 if unmeasurable.

    With a Lean session the daemon owns that bound (its workers stay resident, so free memory no
    longer measures what a new one would cost); requests beyond its slots wait for a free one.
    """
    if lean_session.configured():
        return max(1, min(PROBE_WORKERS, count))
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                fit = int(int(line.split()[1]) / 1024 / 1024 // PROBE_GB)
                return max(1, min(PROBE_WORKERS, count, os.cpu_count() or 1, fit))
    except (OSError, ValueError):
        pass
    return 1


def _compile_probe(name: str, row: dict, proof: str) -> dict:
    """Compile one draft. A complete draft is compiled exactly as a fast evaluation would be,
    so if it passes it becomes a candidate without another compile."""
    complete = not _has_hole(row, proof)
    try:
        return evaluate(name, proof, "fast" if complete else "probe")
    except (ValueError, FileNotFoundError) as error:
        return {
            "ok": False,
            "mode": "probe",
            "error": str(error),
            "compat": {},
            **({"lean_unavailable": True} if isinstance(error, FileNotFoundError) else {}),
        }


def _compile_probes(name: str, directory: Path, drafts: list[str]) -> dict[str, dict]:
    """Compile the batch's new, distinct drafts concurrently under one hold of the model Lean lane.

    Nothing is recorded here. `probe` records outcomes in draft order afterwards, so IDs and
    parents match sequential execution. Drafts that cannot be prepared are left for `probe` to
    reject with its usual error.
    """
    history = events(directory)
    row = problem(name)
    known = set(_candidate_ids(history)) | {item["proof_id"] for item in history if item.get("kind") == "probe"}
    pending: dict[str, str] = {}
    for draft in drafts:
        try:
            proof = normalize_draft(name, draft)
            validate_proof(row, proof, allow_sorry=True)
        except ValueError:
            continue
        if hashlib.sha256((name + "\0" + proof).encode()).hexdigest() not in known:
            pending.setdefault(proof, proof)
    if not pending:
        return {}
    compiled: dict[str, dict] = {}
    with lean_lock(directory), ThreadPoolExecutor(max_workers=_probe_workers(len(pending))) as pool:
        futures = {proof: pool.submit(_compile_probe, name, row, proof) for proof in pending}
        for proof, future in futures.items():
            try:
                compiled[proof] = future.result()
            except Exception:
                continue  # `probe` recompiles this one on its own
    return compiled


def probe(
    name: str,
    run_id: str,
    proof: str,
    idea_id: str | None = None,
    parent: str | None = None,
    operation: dict | None = None,
    mode: str = "fast",
) -> dict:
    """Compile a draft (sorry allowed) in the shadow project without creating a candidate."""
    proof = normalize_draft(name, proof)
    directory = run_dir(run_id)
    _refuse_if_tripped(directory)
    history = events(directory)
    row = problem(name)
    notes: list[str] = []
    parent_id = None
    if parent:
        try:
            parent_id = resolve_parent_ref(history, parent)
        except ValueError as error:
            notes.append(text.render("messages/errors.parent_ignored", reference=parent, error=error))
    parent_id = parent_id or _current(history)
    proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    if proof_id in set(_candidate_ids(history)):
        return evaluate_request(name, run_id, proof, mode, parents=[parent] if parent else None, idea_id=idea_id)
    earlier = next(
        (item for item in reversed(history) if item.get("kind") == "probe" and item["proof_id"] == proof_id), None
    )
    newly_filed: set[str] = set()
    idea_id = idea_id or (earlier or {}).get("idea_id") or _current_active_idea(history)
    if earlier:
        result = earlier["result"]
    else:
        validate_proof(row, proof, allow_sorry=True)
        complete = not _has_hole(row, proof)
        result = (_PRECOMPILED.get() or {}).get(proof)
        if result is None:
            with lean_lock(directory):
                result = _compile_probe(name, row, proof)
        if complete and next(iter((result.get("compat") or {}).values()), {}).get("passed"):
            recorded = record_evaluation(
                name,
                run_id,
                proof,
                mode,
                [parent] if parent else None,
                idea_id=idea_id,
                precomputed=result if mode == "fast" else None,
                operation=operation,
            )
            view = _model_view(
                {**recorded, "full_check": _full_check_status(events(directory), recorded["candidate_id"])}
            )
            view.setdefault("notes", []).append(
                text.render("replies/probe.complete_candidate", candidate=recorded["candidate"])
            )
            return view
        result = {**result, "mode": "probe", "scored": False}
        _externalize_output(directory, proof_id, result)
        _snapshot(directory, proof_id, proof)
        _append(
            directory,
            {"kind": "probe", "proof_id": proof_id, "idea_id": idea_id, "parent": parent_id, "result": result},
        )
        filing_history = events(directory)
        in_batch, _ = _BATCH_FOCUS.get()
        projection_out: list[Graph] = []
        _, new_node = _file_node(
            directory,
            filing_history,
            proof_id,
            proof,
            _named_parent_id(history, parent),
            operation,
            None if in_batch else projection_out,
        )
        if new_node:
            newly_filed.add(proof_id)
        _check_breaker(directory)
        # A draft (holes, errors or a failed compile) never opens a route, so it is not queued for extraction.
    if earlier:
        filing_history = events(directory)
        in_batch, _ = _BATCH_FOCUS.get()
        projection_out = []
        _, new_node = _file_node(
            directory,
            filing_history,
            proof_id,
            proof,
            _named_parent_id(history, parent),
            operation,
            None if in_batch else projection_out,
        )
        if new_node:
            newly_filed.add(proof_id)
    in_batch, _ = _BATCH_FOCUS.get()
    if not in_batch:
        graph = _settle_focus(directory, [proof_id], projection_out[0] if projection_out else None)
        _check_stall(directory, graph, newly_filed)
    location = materialize(name, run_id, proof) if result.get("tokens") is not None else {}
    label = _probe_numbers(events(directory))[proof_id]
    return _model_view(
        {
            **result,
            "probe": label,
            "idea_id": idea_id or (earlier or {}).get("idea_id"),
            "cached": earlier is not None,
            "notes": notes,
            **location,
        }
    )


def normalize_draft(name: str, draft: str) -> str:
    """Add the exact benchmark declaration to a proof body without altering complete proofs."""
    if not isinstance(draft, str) or not draft.strip():
        raise ValueError(text.render("messages/errors.draft_missing"))
    statement = problem(name)["statement"]
    body = draft.lstrip()
    if body.startswith(statement):
        return body
    if body.startswith(":="):
        return statement + " " + body
    if re.match(r"by\b", body):
        return statement + " := " + body
    # Anything else is a bare tactic block.
    block = draft.strip("\n").rstrip()
    if not block[:1].isspace():
        block = "\n".join("  " + line if line.strip() else line for line in block.splitlines())
    return statement + " := by\n" + block


def probe_batch(
    name: str, run_id: str, drafts: list[str], idea_id: str | None = None, parent: str | None = None
) -> dict:
    """Probe one to four drafts in order, keeping their parent fixed across promotions."""
    if not isinstance(drafts, list) or not 1 <= len(drafts) <= MAX_DRAFTS:
        word = {1: "one", 2: "two", 3: "three", 4: "four"}.get(MAX_DRAFTS, str(MAX_DRAFTS))
        raise ValueError(text.render("messages/errors.draft_limit", max_drafts_word=word))
    history = events(run_dir(run_id))
    fixed_parent = resolve_parent_ref(history, parent) if parent else _current(history)
    starting_focus = next((item["proof_id"] for item in reversed(history) if item.get("kind") == "focus"), None)
    outcomes = []
    token = _PRECOMPILED.set(_compile_probes(name, run_dir(run_id), drafts) if len(drafts) > 1 else {})
    focus_token = _BATCH_FOCUS.set((True, starting_focus))
    newly_filed: set[str] = set()
    filed_token = _BATCH_NEWLY_FILED.set(newly_filed)
    try:
        for index, draft in enumerate(drafts, 1):
            try:
                outcome = probe(name, run_id, draft, idea_id, fixed_parent)
            except (OSError, ValueError, RuntimeError) as error:
                outcome = {"ok": False, "mode": "probe", "error": " ".join(str(error).split())[:400]}
            outcomes.append({"index": index, **outcome})
    finally:
        _BATCH_FOCUS.reset(focus_token)
        _BATCH_NEWLY_FILED.reset(filed_token)
        _PRECOMPILED.reset(token)
    directory = run_dir(run_id)
    filed = []
    for draft in drafts:
        try:
            proof = normalize_draft(name, draft)
        except ValueError:
            continue
        proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
        if proof_id not in filed:
            filed.append(proof_id)
    graph = _settle_focus(directory, filed)
    _check_stall(directory, graph, newly_filed)
    return {"ok": True, "drafts": outcomes}


def compile_operation(
    name: str,
    run_id: str,
    operation: dict,
    mode: str = "fast",
    idea_id: str | None = None,
) -> dict:
    """Build, compile and file one operation-derived proof."""
    if mode not in ("fast", "full"):
        raise ValueError(text.render("messages/errors.evaluation_mode"))
    directory = run_dir(run_id)
    history = events(directory)

    def proof_for(reference: str) -> str:
        proof_id = resolve_node_ref(history, reference)
        return (directory / "proofs" / f"{proof_id}.lean").read_text()

    kind = operation.get("type")
    if kind == "draft":
        base_id = resolve_node_ref(history, operation.get("base", ""))
        proof = operation.get("text")
        if not isinstance(proof, str):
            raise ValueError(text.render("messages/errors.draft_operation_text"))
        edge_operation = {"type": "edited_from", "from": [base_id]}
    elif kind == "splice":
        base_id = resolve_node_ref(history, operation.get("base", ""))
        base = proof_for(operation.get("base", ""))
        proof = splice_text(base, operation.get("steps", ""), operation.get("text", ""))
        edge_operation = {
            "type": "edited_from",
            "from": [base_id],
            "steps": operation["steps"],
        }
    elif kind == "merge":
        base_ref = operation.get("base", "")
        base_id = resolve_node_ref(history, base_ref)
        base = proof_for(base_ref)
        takes = operation.get("take")
        if not isinstance(takes, list):
            raise ValueError(text.render("messages/errors.merge_operation_take"))
        resolved_takes = []
        sources = [base_id]
        operation_takes = []
        for take in takes:
            donor_id = resolve_node_ref(history, take.get("from", ""))
            sources.append(donor_id)
            resolved_takes.append({"text": proof_for(take["from"]), "step": take.get("step", "")})
            operation_takes.append({"from": donor_id, "step": take.get("step")})
        proof = merge_steps(base, resolved_takes)
        edge_operation = {"type": "merged_from", "from": sources, "take": operation_takes}
    elif kind == "fill":
        hole_ref = operation.get("hole", "")
        if not isinstance(hole_ref, str):
            hole_ref = str(hole_ref)
        projection = Graph.from_history(history, _proof_reader(directory))
        sketch = next((node for node in projection.nodes if hole_ref.startswith(f"{node.id}.h")), None)
        valid_holes = [
            f"{hole['id']} line {hole['line']}"
            for node in projection.nodes
            if node.status == "sketch"
            for hole in node.holes
        ]
        if sketch is None or sketch.status != "sketch":
            raise ValueError(
                text.render("messages/errors.fill_hole", hole=hole_ref, valid=", ".join(valid_holes) or "none")
            )
        hole = next((row for row in sketch.holes if row["id"] == hole_ref), None)
        if hole is None:
            raise ValueError(
                text.render("messages/errors.fill_hole", hole=hole_ref, valid=", ".join(valid_holes) or "none")
            )
        fill = operation.get("text")
        if not isinstance(fill, str):
            raise ValueError(text.render("messages/errors.fill_text"))
        base_id = sketch.proof_id
        proof = fill_text(sketch.proof_text, hole, fill)
        edge_operation = {"type": "filled_from", "from": [base_id], "hole": hole_ref, "text": fill}
    else:
        raise ValueError(text.render("messages/errors.operation_type_invalid", kind=kind))

    proof = normalize_draft(name, proof)
    result = probe(name, run_id, proof, idea_id=idea_id, operation=edge_operation, mode=mode)
    proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    filed = next(
        event for event in events(directory) if event.get("kind") == "edge" and event.get("proof_id") == proof_id
    )
    node = _graph_node_id(events(directory), proof_id)
    return {**result, "node": node, "edge": {"type": filed["type"], "from": filed["from"]}}


def candidate(name: str, run_id: str, reference: str) -> dict:
    """Restore a candidate (`#N`) or a probe (`pN`) into the shadow project."""
    directory = run_dir(run_id)
    history = events(directory)
    if re.fullmatch(r"p[0-9]+", reference.strip().lower()):
        proof_id = resolve_probe_ref(history, reference)
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
        entry = next(item for item in reversed(history) if item.get("kind") == "probe" and item["proof_id"] == proof_id)
        _append(directory, {"kind": "focus", "proof_id": proof_id, "reason": "restore"})
        return {
            "ok": True,
            "probe": reference.strip().lower(),
            "proof": proof,
            "last_result": _model_view({**entry["result"], "probe": reference}),
            **materialize(name, run_id, proof),
        }
    candidate_id = resolve_candidate_ref(history, reference)
    proof_path = directory / "proofs" / f"{candidate_id}.lean"
    if not proof_path.exists():
        raise ValueError(text.render("messages/errors.unknown_candidate_short"))
    proof = proof_path.read_text()
    location = materialize(name, run_id, proof)
    _append(directory, {"kind": "current", "candidate_id": candidate_id})
    _append(directory, {"kind": "focus", "proof_id": candidate_id, "reason": "restore"})
    row = next((r for r in _summaries(events(directory)) if r["id"] == candidate_id), None)
    return {
        "ok": True,
        "candidate": _label(history, candidate_id),
        "proof": proof,
        "idea_id": row and row["idea_id"],
        "evaluations": [
            {
                "mode": e["mode"],
                "status": e["status"],
                "tokens": e["result"].get("tokens"),
                "heartbeats": e["result"].get("heartbeat"),
                "score": e["score"],
            }
            for e in (row["evaluations"] if row else [])
        ],
        **location,
    }


def profile_request(name: str, run_id: str, reference: str | None = None, proof: str | None = None) -> dict:
    """Per-tactic heartbeat profile of a compiling candidate (`#N`), probe (`pN`) or proof text.

    Defaults to the candidate whose file is currently materialized.
    """
    directory = run_dir(run_id)
    history = events(directory)
    label = None
    if proof is not None and not proof.strip():
        proof = None  # models often send an empty optional string alongside `candidate`
    if proof is None:
        if reference and re.fullmatch(r"p[0-9]+", reference.strip().lower()):
            proof_id = resolve_probe_ref(history, reference)
            label = reference.strip().lower()
        else:
            proof_id = resolve_candidate_ref(history, reference) if reference else _current(history)
            if proof_id is None:
                raise ValueError(text.render("messages/errors.profile_candidate_missing"))
            label = _label(history, proof_id)
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
    proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    cached = next(
        (item for item in reversed(history) if item.get("kind") == "profile" and item["proof_id"] == proof_id), None
    )
    if cached:
        return {**cached["result"], "target": label, "cached": True}
    measured = next(
        (
            e["result"].get("heartbeat")
            for row in _summaries(history)
            if row["id"] == proof_id
            for e in row["evaluations"]
            if e["result"].get("heartbeat") is not None
        ),
        None,
    )
    with lean_lock(directory):
        result = profile(name, proof, measured)
        result["statement_floor_hb"] = heartbeat_floor(name)["heartbeats"]
    _append(directory, {"kind": "profile", "proof_id": proof_id, "result": result})
    return {**result, "target": label, "cached": False}


def set_decision(run_id: str, candidate_id: str, decision: str, reason: str) -> dict:
    if decision not in ("pursue", "park") or not reason.strip():
        raise ValueError(text.render("messages/errors.decision_invalid"))
    directory = run_dir(run_id)
    candidate_id = resolve_candidate_ref(events(directory), candidate_id)
    record = {"kind": "decision", "candidate_id": candidate_id, "decision": decision, "reason": reason.strip()}
    _append(directory, record)
    return record


def map_view(run_id: str) -> dict:
    """Return the hidden JSON map without rendering it into model-facing prose."""
    directory = run_dir(run_id)
    graph = Graph.from_history(events(directory), _proof_reader(directory))
    return graph_map_view(graph)


def graph_state(run_id: str) -> dict:
    directory = run_dir(run_id)
    history = events(directory)
    if not history:
        return {
            "run_id": run_id,
            "nodes": [],
            "evaluations": 0,
            "merge_checks": [],
            "milestones": [],
            "frontier": [],
            "focus": None,
        }
    theorem = history[0]["theorem"]
    total_versions = len(history[0].get("versions") or versions(problem(theorem)))
    nodes: dict[str, dict] = {}
    order: list[str] = []
    checks: list[dict] = []
    ideas: list[dict] = []
    probes: list[dict] = []
    timeline: list[dict] = []
    for event in history:
        kind = event.get("kind")
        if kind == "idea":
            ideas.append(
                {
                    key: event.get(key)
                    for key in ("id", "title", "hypothesis", "region", "expected_effect", "status", "reason")
                }
            )
        elif kind == "idea_update":
            target = next((i for i in ideas if i["id"] == event["id"]), None)
            if target:
                target.update({k: v for k, v in event.items() if k not in ("kind", "id", "ts")})
        elif kind == "probe":
            probes.append(
                {
                    "proof_id": event["proof_id"],
                    "idea_id": event.get("idea_id"),
                    "parent": event.get("parent"),
                    "result": event["result"],
                    "ts": event.get("ts"),
                }
            )
        elif kind == "candidate":
            identifier = event["candidate_id"]
            nodes[identifier] = {
                "id": identifier,
                "index": len(order) + 1,
                "parents": event.get("parents", []),
                "derivations": [event],
                "origin": event.get("origin", "model"),
                "hypothesis": event.get("hypothesis", ""),
                "idea_id": event.get("idea_id"),
                "merge": event.get("merge"),
                "evaluations": [],
                "source_versions": event.get("source_versions", []),
                "evaluator_sha256": event.get("evaluator_sha256"),
                "proof": (directory / "proofs" / f"{identifier}.lean").read_text(),
                "children": [],
                "decision": "pursue",
                "route": None,
            }
            order.append(identifier)
        elif kind == "derivation" and event["candidate_id"] in nodes:
            nodes[event["candidate_id"]]["derivations"].append(event)
        elif kind == "evaluation" and event["candidate_id"] in nodes:
            index = len(timeline) + 1
            nodes[event["candidate_id"]]["evaluations"].append(
                {"number": index, "mode": event["mode"], "result": event["result"]}
            )
            result = event["result"]
            timeline.append(
                {
                    "number": index,
                    "candidate_id": event["candidate_id"],
                    "mode": event["mode"],
                    "tokens": result.get("tokens"),
                    "heartbeat": result.get("heartbeat"),
                    "local_proxy": result.get("local_proxy"),
                    "ts": event.get("ts"),
                }
            )
        elif kind == "merge_check":
            checks.append(event)
        elif kind == "route" and event["proof_id"] in nodes:
            nodes[event["proof_id"]]["route"] = event["route"]
        elif kind == "decision" and event.get("candidate_id") in nodes:
            nodes[event["candidate_id"]]["decision"] = event["decision"]
    best_proxy = float("-inf")
    milestones = []
    for row in timeline:
        node = nodes[row["candidate_id"]]
        evaluation = next(e for e in node["evaluations"] if e["number"] == row["number"])
        result = evaluation["result"]
        compat = result.get("compat", {})
        row["status"] = (
            "full"
            if evaluation["mode"] == "full"
            and len(compat) == total_versions
            and all(version.get("passed") for version in compat.values())
            else ("primary" if next(iter(compat.values()), {}).get("passed") else "fail")
        )
        if row["status"] == "full" and row["local_proxy"] is not None and row["local_proxy"] > best_proxy:
            best_proxy = row["local_proxy"]
            milestones.append(row.copy())
    fingerprints: dict[str, set[str]] = {}
    for identifier in order:
        node = nodes[identifier]
        for parent in node["parents"]:
            if parent in nodes:
                nodes[parent]["children"].append(identifier)
        full = [
            e
            for e in node["evaluations"]
            if next((row["status"] for row in timeline if row["number"] == e["number"]), "fail") == "full"
        ]
        primary = [
            e
            for e in node["evaluations"]
            if next((row["status"] for row in timeline if row["number"] == e["number"]), "fail") == "primary"
        ]
        selected = (
            max(full, key=lambda e: e["result"].get("local_proxy") or -1)
            if full
            else (
                min(primary, key=lambda e: e["result"].get("tokens") or 10**9)
                if primary
                else (node["evaluations"][-1] if node["evaluations"] else None)
            )
        )
        result = selected["result"] if selected else {}
        node["status"] = "full" if full else "primary" if primary else "fail" if selected else "unevaluated"
        node["tokens"] = result.get("tokens")
        node["heartbeat"] = result.get("heartbeat")
        node["local_proxy"] = result.get("local_proxy") if full else None
        parent_attempts = [nodes[p].get("attempts_since_gain", 0) for p in node["parents"] if p in nodes]
        node["attempts_since_gain"] = (
            0
            if node["status"] == "full" and any(m["candidate_id"] == identifier for m in milestones)
            else 1 + (min(parent_attempts) if parent_attempts else 0)
        )
        first_parent = nodes.get(node["parents"][0]) if node["parents"] else None
        fingerprint = edit_fingerprint(first_parent["proof"], node["proof"]) if first_parent else {node["proof"]}
        node["novelty"] = 1.0 - max(
            (
                len(fingerprint & earlier) / len(fingerprint | earlier)
                for earlier in fingerprints.values()
                if fingerprint | earlier
            ),
            default=0.0,
        )
        fingerprints[identifier] = fingerprint
        node["merge_partners"] = 0
    checked_pairs = {tuple(sorted(check["parents"])) for check in checks}
    open_nodes = [
        node for node in nodes.values() if node["status"] in ("full", "primary") and node["decision"] != "park"
    ]
    ancestry = {node["id"]: node["parents"] for node in nodes.values()}
    reference = next((node for node in nodes.values() if node["origin"] == "reference"), None)
    for index, left in enumerate(open_nodes):
        for right in open_nodes[index + 1 :]:
            if tuple(sorted((left["id"], right["id"]))) in checked_pairs:
                continue
            common = common_base(left["id"], right["id"], ancestry)
            base = common["base"] or (reference["id"] if common["reason"] == "no_common_base" and reference else None)
            if base and merge_text(nodes[base]["proof"], left["proof"], right["proof"])["text"]:
                left["merge_partners"] += 1
                right["merge_partners"] += 1
    rows = [nodes[identifier] for identifier in order]
    ranked = ranked_frontier(rows)
    for idea in ideas:
        idea["attempts"] = sum(1 for node in rows if node["idea_id"] == idea["id"] and node["origin"] == "model")
        idea["probes"] = sum(1 for item in probes if item["idea_id"] == idea["id"])
    idea_rows = ideas
    projection = Graph.from_history(history, _proof_reader(directory))
    projected = {node.proof_id: node for node in projection.nodes}
    for node in rows:
        graph_node = projected.get(node["id"])
        node["node"] = graph_node.id if graph_node else None
        node["edge"] = graph_node.edge if graph_node else None
    for probe_row in probes:
        graph_node = projected.get(probe_row["proof_id"])
        probe_row["node"] = graph_node.id if graph_node else None
        probe_row["edge"] = graph_node.edge if graph_node else None
    return {
        "run_id": run_id,
        "theorem": theorem,
        "nodes": rows,
        "ledger_events": len(history),
        "evaluations": len(timeline),
        "timeline": timeline,
        "merge_checks": checks,
        "milestones": milestones,
        "frontier": ranked,
        "ideas": idea_rows,
        "probes": probes,
        "routes": (route_rows := route_table(history)),
        "route_progress": _route_progress(route_rows),
        "focus": projection.focus,
    }


def merge_once(run_id: str, graph: dict | None = None) -> dict | None:
    """Process one unchecked good pair; repeated calls exhaust the queue."""
    graph = graph if graph is not None else graph_state(run_id)
    if not graph["nodes"]:
        return None
    directory = run_dir(run_id)
    nodes = {node["id"]: node for node in graph["nodes"]}
    good = [node for node in graph["nodes"] if node["status"] in ("full", "primary") and node["decision"] != "park"]
    checked = {tuple(sorted(check["parents"])) for check in graph["merge_checks"]}
    ancestry = {node["id"]: node["parents"] for node in graph["nodes"]}
    reference = next((node for node in graph["nodes"] if node["origin"] == "reference"), None)
    for fresh in reversed(good):
        for other in good:
            if fresh["id"] == other["id"]:
                continue
            pair = sorted((fresh["id"], other["id"]))
            if tuple(pair) in checked:
                continue
            base = common_base(pair[0], pair[1], ancestry)
            inferred = base["base"] is None and base["reason"] == "no_common_base" and reference is not None
            if inferred:
                base = {"base": reference["id"], "reason": None}
            outcome = {"kind": "merge_check", "parents": pair, "base": base["base"]}
            if inferred:
                outcome["base_inferred_from_reference"] = True
            if base["base"] is None:
                outcome["reason"] = base["reason"]
            else:
                merged = merge_text(nodes[base["base"]]["proof"], nodes[pair[0]]["proof"], nodes[pair[1]]["proof"])
                outcome["edits"] = {"left": merged["left_edits"], "right": merged["right_edits"]}
                if merged["text"] is None:
                    outcome["reason"] = merged["reason"]
                else:
                    recorded = record_evaluation(
                        graph["theorem"],
                        run_id,
                        merged["text"],
                        "fast",
                        pair,
                        text.render("replies/merge.hypothesis"),
                        origin="auto_merge",
                        merge={
                            "base": base["base"],
                            "base_inferred_from_reference": inferred,
                            "edits": outcome["edits"],
                        },
                        materialize_live=False,
                        operation={"type": "merged_from", "from": pair},
                    )
                    outcome["candidate_id"] = recorded["candidate_id"]
                    outcome["node_number"] = recorded["node_number"]
                    outcome["fast_passed"] = any(v.get("passed") for v in recorded.get("compat", {}).values())
                    if outcome["fast_passed"]:
                        full = record_evaluation(
                            graph["theorem"],
                            run_id,
                            merged["text"],
                            "full",
                            pair,
                            text.render("replies/merge.hypothesis"),
                            origin="auto_merge",
                            merge={
                                "base": base["base"],
                                "base_inferred_from_reference": inferred,
                                "edits": outcome["edits"],
                            },
                            materialize_live=False,
                            operation={"type": "merged_from", "from": pair},
                        )
                        outcome["full_passed"] = all(v.get("passed") for v in full.get("compat", {}).values())
            _append(directory, outcome)
            graph["merge_checks"].append(outcome)
            return outcome
    return None


def merge_batch(run_id: str, max_checks: int = 64) -> dict:
    """Reuse one graph snapshot for cheap skipped pairs; refresh after a new node."""
    graph = graph_state(run_id)
    checks = 0
    last = None
    for _ in range(max_checks):
        outcome = merge_once(run_id, graph)
        if outcome is None:
            break
        checks += 1
        last = outcome
        if outcome.get("candidate_id"):
            break
    return {"checks": checks, "last": last}


def _has_hole(row: dict, proof: str) -> bool:
    try:
        validate_proof(row, proof)
    except ValueError as error:
        if str(error) in ("FORBIDDEN: sorry", "FORBIDDEN: admit"):
            return True
        raise
    return False


def _check_text(number: int, result: dict, total: int) -> str:
    compat = result.get("compat") or {}
    if result.get("ok") is False or not compat:
        return text.render(
            "replies/check.could_not_run", number=number, error=str(result.get("error") or "unknown error")[:160]
        )
    failing = [version for version, info in compat.items() if not info.get("passed")]
    if not failing and len(compat) == total:
        proxy = (result.get("metrics") or {}).get("proxy", result.get("local_proxy"))
        return text.render("replies/check.passed", number=number, total=total, proxy=proxy)
    first = compat[failing[0]]
    reason = (first.get("error_headlines") or [first.get("error") or "compile failed"])[0]
    return text.render(
        "replies/check.failed",
        number=number,
        failing=", ".join(failing),
        passed=len(compat) - len(failing),
        total=total,
        reason=str(reason)[:160],
    )


def _autocheck_jobs(rows: list[dict], closing: bool = False) -> list[dict]:
    """Candidates that compile on the primary version but were never checked on every version,
    most promising first."""
    jobs = [
        r
        for r in rows
        if r["origin"] != "reference"
        and r["status"] == "primary"
        and not any(e["mode"] == "full" for e in r["evaluations"])
    ]
    if not closing:
        verified = [row for row in rows if row["verified"]]
        best_verified = _best(verified) if verified else None
        bar = best_verified["score"] if best_verified else None
        if bar is not None:
            jobs = [row for row in jobs if row["score"] is None or row["score"] >= bar]
    return sorted(jobs, key=lambda r: (r["score"] if r["score"] is not None else float("-inf"), r["n"]), reverse=True)


def _step_goal_jobs(history: list[dict], directory: Path) -> list[str]:
    """Proof ids whose closed or sketch states have no terminal step-goal event."""
    done = {
        event["proof_id"]
        for event in history
        if event.get("kind") == "step_goals" and ("goals" in event or "error" in event)
    }
    candidate_ids = _candidate_ids(history)
    rows = {row["id"]: row for row in _summaries(history)}
    jobs: list[str] = []
    for proof_id in candidate_ids:
        if proof_id in done:
            continue
        row = rows[proof_id]
        eligible = [item for item in row["evaluations"] if item["status"] in ("full", "primary")]
        if not eligible:
            continue
        full = [item for item in eligible if item["status"] == "full"]
        selected = max(full or eligible, key=lambda item: item["score"] if item["score"] is not None else -1)
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
        if goalstate.closed(selected["result"]) and not re.search(r"\bsorry\b", proof):
            jobs.append(proof_id)

    seen = set(candidate_ids)
    latest_probes: dict[str, dict] = {}
    for event in history:
        if event.get("kind") == "probe":
            latest_probes[event["proof_id"]] = event["result"]
    for proof_id, result in latest_probes.items():
        if proof_id in seen or proof_id in done:
            continue
        proof_path = directory / "proofs" / f"{proof_id}.lean"
        if not proof_path.is_file():
            continue
        proof = proof_path.read_text()
        passed = next(iter((result.get("compat") or {}).values()), {}).get("passed", False)
        if (goalstate.closed(result) and not re.search(r"\bsorry\b", proof)) or (
            passed and re.search(r"\bsorry\b", proof)
        ):
            jobs.append(proof_id)
    return jobs


def _salvage_jobs(history: list[dict], directory: Path, graph: Graph | None = None) -> list[Node]:
    """Broken, filed graph nodes with no terminal salvage event yet."""
    done = {item.get("proof_id") for item in history if item.get("kind") == "salvage"}
    graph = graph or Graph.from_history(history, _proof_reader(directory))
    return [node for node in graph.nodes if node.status == "broken" and node.edge and node.proof_id not in done]


def _assembly_jobs(history: list[dict], directory: Path, graph: Graph | None = None) -> list[Node]:
    """Sketch nodes whose every hole has a closing fill and no assembly event."""
    done = {item.get("sketch") for item in history if item.get("kind") == "assembly"}
    graph = graph or Graph.from_history(history, _proof_reader(directory))
    return [
        node
        for node in graph.nodes
        if node.status == "sketch"
        and node.holes
        and all(hole["status"] == "filled" for hole in node.holes)
        and node.proof_id not in done
    ]


def _salvage_compile(name: str, text_value: str) -> dict:
    """Compile one salvage attempt in the background lane and normalize its diagnostics."""
    directory = _SALVAGE_DIRECTORY.get()
    if directory is None:
        raise ValueError
    with lean_lock(directory, "background"):
        result = _evaluate(name, text_value, "probe", lane="background")
    compat = result.get("compat") or {}
    first = next(iter(compat.values()), {})
    diagnostics = first.get("diagnostics") or []
    clean = bool(first.get("passed")) and not any(item.get("severity") == "error" for item in diagnostics)
    lines = [
        item.get("proof_line") for item in diagnostics if item.get("severity") == "error" and item.get("proof_line")
    ]
    return {"clean": clean, "error_lines": lines, "unlocated": not clean and not lines, "result": result}


def _run_salvage(name: str, run_id: str, node: Node) -> dict:
    directory = run_dir(run_id)
    proof = node.proof_text
    token = _SALVAGE_DIRECTORY.set(directory)
    try:
        outcome = salvage_proof(name, proof, lambda candidate: _salvage_compile(name, candidate))
    except (ValueError, FileNotFoundError):
        outcome = {"status": "unavailable", "compiles": 0, "rounds": [], "text": None, "result": None, "kept": None}
    finally:
        _SALVAGE_DIRECTORY.reset(token)
    sketch_id = None
    if outcome["status"] == "salvaged":
        sketch_text = outcome["text"]
        sketch_id = hashlib.sha256((name + "\0" + sketch_text).encode()).hexdigest()
        _snapshot(directory, sketch_id, sketch_text)
        history = events(directory)
        has_node = any(
            item.get("proof_id") == sketch_id and item.get("kind") in ("probe", "candidate") for item in history
        )
        if not has_node:
            result = dict(outcome["result"] or {})
            result["mode"] = "probe"
            result["scored"] = False
            result["salvaged"] = True
            _append(directory, {"kind": "probe", "proof_id": sketch_id, "parent": node.proof_id, "result": result})
            _file_node(
                directory,
                events(directory),
                sketch_id,
                sketch_text,
                operation={"type": "salvaged_from", "from": [node.proof_id]},
            )
    _append(
        directory,
        {
            "kind": "salvage",
            "proof_id": node.proof_id,
            "status": outcome["status"],
            "compiles": outcome["compiles"],
            "rounds": outcome["rounds"],
            "kept": outcome["kept"],
            "sketch_id": sketch_id,
        },
    )
    write_state(run_id)
    return outcome


def _run_assembly(name: str, run_id: str, sketch: Node) -> None:
    directory = run_dir(run_id)
    fills: dict[str, str] = {}
    alternatives: dict[str, list[str]] = {}
    chosen: list[tuple[dict, Node]] = []
    try:
        graph = Graph.from_history(events(directory), _proof_reader(directory))
        by_id = {node.id: node for node in graph.nodes}
        for hole in sketch.holes:
            candidates = [by_id[node_id] for node_id in hole["fills"]]
            chosen_node = candidates[0]
            chosen.append((hole, chosen_node))
            fills[hole["id"]] = chosen_node.proof_id
            alternatives[hole["id"]] = [node.proof_id for node in candidates[1:]]
        proof = sketch.proof_text
        operation_fills = []
        for hole, fill_node in chosen:
            operation = (fill_node.edge or {}).get("operation") or {}
            operation_fills.append((hole, operation.get("text", ""), fill_node))
        for hole, value, _ in sorted(operation_fills, key=lambda item: item[0]["line"], reverse=True):
            proof = fill_text(proof, hole, value)
        sources = [sketch.proof_id, *(node.proof_id for _, node in chosen)]
        result = record_evaluation(
            name,
            run_id,
            proof,
            "fast",
            lane="background",
            trigger="auto",
            origin="assembly",
            materialize_live=False,
            operation={"type": "merged_from", "from": sources, "assembly": True},
        )
        proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
        passed = next(iter((result.get("compat") or {}).values()), {}).get("passed", False)
        status = "closed" if passed and not _has_hole(problem(name), proof) else "broken"
        _append(
            directory,
            {
                "kind": "assembly",
                "sketch": sketch.proof_id,
                "node": proof_id,
                "fills": fills,
                "alternatives": alternatives,
                "status": status,
            },
        )
    except Exception as error:
        _append(
            directory,
            {
                "kind": "assembly",
                "sketch": sketch.proof_id,
                "node": None,
                "fills": fills,
                "alternatives": alternatives,
                "status": "error",
                "error": str(error)[:300],
            },
        )
    write_state(run_id)


def autocheck(name: str, run_id: str, max_seconds: float | None = None, closing: bool = False) -> dict:
    """Drain salvage, assembly, full checks and step goals in the background lane.

    Only one checker runs per run; both queues are derived from the ledger, so a
    killed checker loses nothing.
    """
    directory = run_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    checked: list[str] = []
    with (directory / "autocheck.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": True, "checked": [], "running_elsewhere": True}
        while max_seconds is None or time.monotonic() - started < max_seconds:
            if lean_health.tripped(directory):
                break  # Lean is unhealthy: background checks pause with the model's work
            history = events(directory)
            projection = Graph.from_history(history, _proof_reader(directory))
            salvage_jobs = _salvage_jobs(history, directory, projection)
            if salvage_jobs:
                _run_salvage(name, run_id, salvage_jobs[0])
                continue
            assembly_jobs = _assembly_jobs(history, directory, projection)
            if assembly_jobs:
                _run_assembly(name, run_id, assembly_jobs[0])
                continue
            jobs = _autocheck_jobs(_summaries(history), closing=closing)
            if jobs:
                job = jobs[0]
                try:
                    proof = (directory / "proofs" / f"{job['id']}.lean").read_text()
                    record_evaluation(name, run_id, proof, "full", materialize_live=False, lane="batch", trigger="auto")
                except Exception as error:  # record the failure so the queue moves on
                    _append(
                        directory,
                        {
                            "kind": "evaluation",
                            "candidate_id": job["id"],
                            "key": f"auto-error-{job['id']}",
                            "mode": "full",
                            "trigger": "auto",
                            "result": {"ok": False, "mode": "full", "error": str(error)[:300], "compat": {}},
                        },
                    )
                checked.append(f"#{job['n']}")
                write_state(run_id)
                continue

            goal_jobs = _step_goal_jobs(history, directory)
            if not goal_jobs:
                break
            proof_id = goal_jobs[0]
            try:
                proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
                from arena import step_goals

                with lean_lock(directory, "background"):
                    goals = step_goals.step_goals(name, proof, lane="background")
                _append(directory, {"kind": "step_goals", "proof_id": proof_id, "goals": goals})
            except Exception as error:  # record the failure so this node does not block later jobs
                _append(
                    directory,
                    {"kind": "step_goals", "proof_id": proof_id, "error": str(error)[:300]},
                )
            write_state(run_id)
    return {
        "ok": True,
        "checked": checked,
        "remaining": [f"#{r['n']}" for r in _autocheck_jobs(_summaries(events(directory)), closing=closing)],
    }


def state(run_id: str) -> dict:
    """Everything the model should know without asking: the best verified candidate, a
    better unverified one if any, what is being checked, and the harness's check results."""
    history = events(run_dir(run_id))
    if not history:
        raise ValueError(text.render("messages/errors.run_uninitialized"))
    rows = _summaries(history)
    total = len(history[0].get("versions") or [1])
    numbers = {r["id"]: r["n"] for r in rows}
    assembly_candidates = {
        item["candidate_id"] for item in history if item.get("kind") == "candidate" and item.get("origin") == "assembly"
    }
    verified = _best([r for r in rows if r["verified"]])
    unverified = _best([r for r in rows if not r["verified"]])
    leading = (
        unverified if unverified and (not verified or (unverified["score"] or 0) > (verified["score"] or 0)) else None
    )
    updates = [
        {"seq": seq, "text": _check_text(numbers[item["candidate_id"]], item["result"], total)}
        for seq, item in enumerate(history)
        if item.get("kind") == "evaluation"
        and item.get("trigger") == "auto"
        and item["candidate_id"] in numbers
        and not (item.get("mode") == "fast" and item["candidate_id"] in assembly_candidates)
    ]
    graph_ids: dict[str, str] = {}
    for item in history:
        proof_id = item.get("candidate_id") if item.get("kind") == "candidate" else item.get("proof_id")
        if item.get("kind") not in ("candidate", "probe") or proof_id in graph_ids.values():
            continue
        graph_ids[f"n{len(graph_ids) + 1}"] = proof_id
    probes = {item["proof_id"]: item for item in history if item.get("kind") == "probe"}
    directory = run_dir(run_id)
    for seq, item in enumerate(history):
        if item.get("kind") == "salvage" and item.get("status") == "salvaged" and item.get("sketch_id"):
            sketch_id = item["sketch_id"]
            sketch_path = directory / "proofs" / f"{sketch_id}.lean"
            sketch_text = sketch_path.read_text() if sketch_path.is_file() else ""
            compile_result = (probes.get(sketch_id) or {}).get("result", {})
            hole_rows = find_holes(sketch_text, compile_result.get("goals") or [])
            line_numbers = [hole["line"] for hole in hole_rows]
            lines_text = (
                f"line {line_numbers[0]}" if len(line_numbers) == 1 else "lines " + ", ".join(map(str, line_numbers))
            )
            count = len(hole_rows)
            updates.append(
                {
                    "seq": seq,
                    "text": text.render(
                        "messages/salvage.salvaged",
                        sketch=node_label(history, sketch_id),
                        source=node_label(history, item["proof_id"]),
                        holes=f"{count} hole" if count == 1 else f"{count} holes",
                        lines=lines_text,
                    ),
                }
            )
        elif item.get("kind") == "assembly" and item.get("status") in ("closed", "broken"):
            sketch_id = item["sketch"]
            sketch_ref = next((key for key, value in graph_ids.items() if value == sketch_id), "")
            sketch_path = directory / "proofs" / f"{sketch_id}.lean"
            sketch_text = sketch_path.read_text() if sketch_path.is_file() else ""
            sketch_goals = (probes.get(sketch_id) or {}).get("result", {}).get("goals") or []
            sketch_holes = find_holes(sketch_text, sketch_goals)
            holes_by_id = {f"{sketch_ref}.h{hole['index']}": hole for hole in sketch_holes}
            fill_events = {
                event.get("proof_id"): event
                for event in history
                if event.get("kind") == "edge" and event.get("type") == "filled_from"
            }
            used = []
            alternatives = []
            for hole_id, fill_id in (item.get("fills") or {}).items():
                hole = holes_by_id.get(hole_id, {})
                label = node_label(history, fill_id)
                used.append(f"line {hole.get('line', '?')}: {label}")  # not-model-facing
                for alternate in (item.get("alternatives") or {}).get(hole_id, []):
                    operation = (fill_events.get(alternate) or {}).get("operation") or {}
                    cost = fill_cost(operation.get("text", ""))
                    alternatives.append(
                        f"line {hole.get('line', '?')}: {node_label(history, alternate)} ({cost} tokens)"  # not-model-facing
                    )
            if item["status"] == "broken":
                notice = text.render("messages/assembly.assembly_failed", sketch=node_label(history, sketch_id))
            else:
                row = next((row for row in rows if row["id"] == item.get("node")), {})
                notice = text.render(
                    "messages/assembly.assembled",
                    node=node_label(history, item["node"]),
                    sketch=node_label(history, sketch_id),
                    tokens=row.get("tokens") or 0,
                    score=row.get("score") or 0,
                    used=", ".join(used) or "none",
                    alternatives=", ".join(alternatives) or "none",
                )
            updates.append({"seq": seq, "text": notice})
    candidate_rows = {row["id"]: row for row in rows}
    route_events = {item["proof_id"]: item for item in history if item.get("kind") == "route"}
    for seq, item in enumerate(history):
        if item.get("kind") != "focus" or item.get("reason") != "stall":
            continue
        proof_id = item["proof_id"]
        row = candidate_rows.get(proof_id)
        probe_event = probes.get(proof_id)
        result = (
            row["evaluations"][-1]["result"] if row and row["evaluations"] else (probe_event or {}).get("result", {})
        )
        hole_count = (route_events.get(proof_id) or {}).get("holes", 0)
        score = "sketch" if hole_count else _metric_score(result.get("metrics"))
        if score is None:
            score = 0.0
        updates.append(
            {
                "seq": seq,
                "text": text.render(
                    "messages/phase.stall_focus",
                    label=node_label(history, proof_id),
                    letter=item["cell"],
                    score=score,
                    visits=item["visits"],
                ),
            }
        )
    updates.sort(key=lambda update: update["seq"])
    reference_row = next((r for r in rows if r["origin"] == "reference"), None)
    baseline = None
    if reference_row:
        from arena.scoring import reference

        try:
            tokens, heartbeats = reference(history[0]["theorem"])
        except ValueError:
            # Synthetic protocol tests and imported legacy runs may have no published denominator.
            pass
        else:
            baseline = {
                "candidate": "#1",
                "tokens": tokens,
                "heartbeats": heartbeats,
                "proxy": round(100 / 3, 2),
                "status": "pinned original baseline",
            }
    return {
        "ok": True,
        "seq": len(history),
        "versions": total,
        "best": _brief(verified),
        "baseline": baseline,
        "leading_unverified": _brief(leading),
        "checking": [f"#{r['n']}" for r in _autocheck_jobs(rows)],
        "updates": updates[-10:],
    }


def write_state(run_id: str) -> None:
    """Publish `state` atomically for the Pi extension, which reads it on every tool result."""
    directory = run_dir(run_id)
    target = directory / "state.json"
    temporary = target.with_name(f"state.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state(run_id), ensure_ascii=False))
    temporary.replace(target)


COLD_TOLERANCE = 0.05  # same drift tolerance as arena certify


def _used_session(row: dict) -> bool:
    """Whether the evaluation that made this candidate verified relied on a Lean session."""
    full = [e for e in row["evaluations"] if e["status"] == "full"]
    chosen = max(full, key=lambda e: e["score"] or -1, default=None)
    return chosen is not None and any(
        (info.get("lean") or {}).get("path") == "session" for info in (chosen["result"].get("compat") or {}).values()
    )


def cold_verify(run_id: str, row: dict) -> dict:
    """Clean cold compile of a candidate on every toolchain; recorded so it runs once.

    A session result is only a fast estimate. A candidate chosen as the answer must also pass
    a fresh `lake env lean` on every version, with heartbeats within tolerance of what was recorded.
    """
    directory = run_dir(run_id)
    history = events(directory)
    done = next(
        (
            item
            for item in reversed(history)
            if item.get("kind") == "cold_verification" and item["candidate_id"] == row["id"]
        ),
        None,
    )
    if done:
        return done
    if lean_health.tripped(directory):
        # Paused, not recorded: the verification can still run once Lean is healthy again.
        return {
            "kind": "cold_verification",
            "candidate_id": row["id"],
            "confirmed": False,
            "error": text.render("messages/errors.cold_verification_paused"),
            "recorded_heartbeats": row["heartbeats"],
            "paused": True,
        }
    name = history[0]["theorem"]
    proof = (directory / "proofs" / f"{row['id']}.lean").read_text()
    try:
        with lean_lock(directory, "background"), force_cold():
            cold = _evaluate(name, proof, "full", lane="background")
        compat = cold["compat"]
        passed = {version: bool(info.get("passed")) for version, info in compat.items()}
        total = len(history[0].get("versions") or [1])
        recorded, measured = row["heartbeats"], cold.get("heartbeat")
        close = (
            recorded is not None
            and measured is not None
            and abs(measured - recorded) <= COLD_TOLERANCE * max(recorded, 1)
        )
        confirmed = len(passed) == total and all(passed.values()) and close
        event = {
            "kind": "cold_verification",
            "candidate_id": row["id"],
            "confirmed": confirmed,
            "passed": passed,
            "recorded_heartbeats": recorded,
            "cold_heartbeats": measured,
        }
    except Exception as error:  # an unverifiable candidate must not be submitted
        event = {
            "kind": "cold_verification",
            "candidate_id": row["id"],
            "confirmed": False,
            "error": str(error)[:300],
            "recorded_heartbeats": row["heartbeats"],
        }
    _append(directory, event)
    return event


def submission(run_id: str) -> dict:
    """The run's answer: the best candidate that passes every version. Written by the harness so
    nothing depends on the model remembering to submit.

    A candidate whose checks ran in a Lean session is re-verified by a clean cold compile first; one
    that fails it is skipped and listed under `rejected_on_cold`."""
    directory = run_dir(run_id)
    history = events(directory)
    rows = _summaries(history)
    # Harness-combined proofs (auto_merge) are reported by arena.merges but never submitted: the answer is model-written.
    pool = sorted(
        (
            r
            for r in rows
            if r["verified"]
            and r["score"] is not None
            and r["status"] == "full"
            and r["origin"] not in ("reference", "auto_merge")
        ),
        key=lambda r: (r["score"], -r["n"]),
        reverse=True,
    )
    best, rejected, cold = None, [], None
    for row in pool:
        if not _used_session(row):
            best = row
            break
        cold = cold_verify(run_id, row)
        if cold["confirmed"]:
            best = row
            break
        rejected.append(
            {
                "candidate": f"#{row['n']}",
                "recorded_heartbeats": cold.get("recorded_heartbeats"),
                "cold_heartbeats": cold.get("cold_heartbeats"),
                "passed": cold.get("passed"),
                "error": cold.get("error"),
            }
        )
    if best is None:
        answer = {
            "ok": True,
            "candidate": None,
            "reason": text.render("replies/state.no_candidate_passed"),
        }
        if rejected:
            answer["reason"] = text.render("replies/state.no_candidate_cold_passed")
    else:
        proof = (directory / "proofs" / f"{best['id']}.lean").read_text()
        (directory / "submission.lean").write_text(proof)
        answer = {
            "ok": True,
            "candidate": f"#{best['n']}",
            "candidate_id": best["id"],
            "tokens": best["tokens"],
            "heartbeats": best["heartbeats"],
            "proxy": best["score"],
            "proof_file": "submission.lean",
            "verified_by": "cold compile"
            if cold and cold["confirmed"]
            else text.render("replies/state.cold_compile_without_session"),
        }
        if cold and cold["confirmed"]:
            # The clean compile is the certified measurement; the session figure is kept for audit.
            answer["session_heartbeats"] = best["heartbeats"]
            answer["heartbeats"] = cold["cold_heartbeats"]
    if rejected:
        answer["rejected_on_cold"] = rejected
    (directory / "submission.json").write_text(json.dumps(answer, indent=2) + "\n")
    return answer


def _route_progress(rows: list[dict]) -> dict:
    from arena.routes import progress

    return progress(rows)


def route_table(history: list[dict]) -> list[dict]:
    from arena.routes import route_table as table

    return table(history)


def frontier(run_id: str) -> dict:
    """Compact status: best candidates, the model's ideas with their attempts, recent failures."""
    history = events(run_dir(run_id))
    if not history:
        raise ValueError(text.render("messages/errors.run_uninitialized"))
    rows = _summaries(history)
    ideas: dict[str, dict] = {}
    for item in history:
        if item.get("kind") == "idea":
            ideas[item["id"]] = {
                "id": item["id"],
                "title": item["title"],
                "status": item["status"],
                "reason": item.get("reason") or None,
            }
        elif item.get("kind") == "idea_update" and item["id"] in ideas:
            ideas[item["id"]].update({k: item[k] for k in ("title", "status", "reason") if k in item})
    probe_numbers = _probe_numbers(history)
    failures: list[dict] = []
    for idea in ideas.values():
        mine = [r for r in rows if r["idea_id"] == idea["id"] and r["origin"] == "model"]
        drafts = [item for item in history if item.get("kind") == "probe" and item.get("idea_id") == idea["id"]]
        idea["attempts"] = len({r["id"] for r in mine} | {d["proof_id"] for d in drafts})
        idea["probes"] = len({d["proof_id"] for d in drafts})
        idea["best"] = _brief(_best(mine))
        failed = [r for r in mine if r["status"] == "fail" and r["evaluations"]]
        last = failed[-1] if failed else None
        idea["last_failure"] = (f"#{last['n']}: " + _failure_text(last["evaluations"][-1]["result"])) if last else None
    failures.extend(
        {
            "ref": f"#{row['n']}",
            "idea_id": row["idea_id"],
            "error": _failure_text(row["evaluations"][-1]["result"]),
        }
        for row in rows
        if row["status"] == "fail" and row["evaluations"]
    )
    failures.extend(
        {
            "ref": probe_numbers[item["proof_id"]],
            "idea_id": item.get("idea_id"),
            "error": _failure_text(item["result"]),
        }
        for item in history
        if item.get("kind") == "probe" and _probe_failed(item["result"])
    )
    top = sorted(
        (r for r in rows if r["status"] in ("full", "primary") and r["origin"] != "reference"),
        key=lambda r: (r["verified"], r["score"] or -1),
        reverse=True,
    )[:5]
    evaluations = sum(len(r["evaluations"]) for r in rows)
    current_id = _current_active_idea(history)
    current_idea = next((idea for idea in ideas.values() if idea["id"] == current_id), None)
    return {
        "best": _brief(_best(rows)),
        "top": [_brief(r) | {"idea_id": r["idea_id"]} for r in top],
        "ideas": list(ideas.values()),
        "recent_failures": failures[-3:],
        "current_idea": current_idea,
        "candidates": len(rows),
        "evaluations": evaluations,
        "probes": len(probe_numbers),
        "advisory": _advisory(rows),
        "routes": route_table(history),
    }


def _probe_failed(result: dict) -> bool:
    primary = next(iter((result.get("compat") or {}).values()), None)
    return result.get("ok") is False or (primary is not None and not primary.get("passed"))


def _failure_text(result: dict) -> str:
    if result.get("error"):
        return str(result["error"])[:160]
    for info in (result.get("compat") or {}).values():
        if info.get("error_headlines"):
            return info["error_headlines"][0][:160]
        if info.get("error"):
            return str(info["error"])[:160]
    return "compile failed"
