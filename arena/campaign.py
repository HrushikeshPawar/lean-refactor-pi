"""Source-grounded, persistent state for one Arena proof-search run."""

from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import shutil
import subprocess
import fcntl
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from arena.engine import ROOT, candidate_file, evaluate, measure_version, problem, source_path, validate_proof, versions, workspace
from arena.polish import polish
from arena.profile import heartbeat_floor, profile
from arena.graph import common_base, edit_fingerprint, merge_text, ranked_frontier


def run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", run_id):
        raise ValueError("Invalid run ID")
    return ROOT / "runs" / "pi-budget" / run_id


class AmbiguousDeclaration(ValueError):
    """More than one distinct qualified declaration matches an unqualified or partial name."""

    def __init__(self, symbol: str, candidates: list[str]):
        super().__init__(f"{symbol} is ambiguous: {', '.join(candidates[:12])}")
        self.candidates = candidates


_SESSION: ContextVar["_Session | None"] = ContextVar("arena_source_session", default=None)


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
                ["git", "cat-file", "--batch"], cwd=root, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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
        raise ValueError("Only relative .lean paths inside the pinned project are allowed")
    session = _SESSION.get()
    if session is not None:
        return session.read(project, commit, path)
    return subprocess.run(["git", "show", f"{commit}:{path}"], cwd=project,
                          text=True, capture_output=True, check=True).stdout


def _context(name: str) -> dict:
    """The kickoff inventory, read once per lookup call."""
    from arena.context import lean_context

    session = _SESSION.get()
    if session is None:
        return lean_context(name)
    if name not in session.contexts:
        session.contexts[name] = lean_context(name)
    return session.contexts[name]


MAX_SOURCE_LINES = 400
MAX_DECLARATION_PAGE_CHARS = 16_000


def declarations(name: str, items: list[str] | None = None, cursor: str | None = None) -> dict:
    """Resolve a batch of declaration handles against the kickoff's tagged constant index."""
    if bool(items) == bool(cursor):
        raise ValueError("Pass exactly one of items (a nonempty list of declaration names or handles) "
                         "or cursor (next_cursor from a previous page)")
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
            raise ValueError("Invalid declaration cursor") from None
    else:
        offset = 0
    if not isinstance(items, list) or not items or not all(isinstance(item, str) and item for item in items):
        raise ValueError("items must be a nonempty list of declaration names or handles")

    inventory = _context(name)
    if inventory.get("error"):
        return {"items": [{"input": item, "kind": "unavailable", "reason": "unavailable",
                           "detail": inventory["error"]} for item in items[offset:]], "next_cursor": None}
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
            result = {"input": original, "kind": "local", "name": query,
                      "type": local["type"], "scope": local["scope"]}
        else:
            matches = constant_index(inventory, name=query)
            if not matches and "." not in query:
                matches = [item for item in constants if item["name"].split(".")[-1] == query]
            if len(matches) > 1:
                result = {"input": original, "kind": "ambiguous",
                          "suggestions": [item["name"] for item in matches[:12]]}
            elif not matches:
                found = _source_declaration(name, query)
                if not found.get("found") and re.search(r"(?:^|\.)_[A-Za-z0-9_']", query):
                    # Generated elaborator names can be absent from source indexes and still resolve in Lean.
                    found = declaration(name, query)
                if found.get("ambiguous"):
                    result = {"input": original, "kind": "ambiguous", "suggestions": found["ambiguous"]}
                elif not found.get("found"):
                    result = {"input": original, "kind": "error", "error": "not_found",
                              "hint": found.get("hint"),
                              "suggestions": _declaration_suggestions(query, constants)}
                elif found.get("alternatives"):
                    result = {"input": original, "kind": "ambiguous",
                              "suggestions": [found["name"], *found["alternatives"]]}
                elif found.get("source_text"):
                    result = {"input": original, "kind": "declaration", **found}
                else:
                    entry = {"name": found.get("name", query), "kind": found.get("kind", "generated")}
                    result = {"input": original, **found, "kind": "unavailable",
                              "reason": _unavailable_reason(entry, found),
                              "handle": f"decl:{entry['name']}"}
            else:
                entry = matches[0]
                found = declaration(name, entry["name"])
                if found.get("source_text"):
                    result = {"input": original, "kind": "declaration", **found, "index": entry}
                else:
                    result = {"input": original, "kind": "unavailable",
                              "reason": _unavailable_reason(entry, found), "name": entry["name"],
                              "handle": f"decl:{entry['name']}", "index": entry,
                              "module": found.get("module") or entry.get("module"),
                              "signature": found.get("signature") or entry.get("sig"),
                              "location": found.get("source")}
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
        project, commit, path = _source_target(project, commit, _canonical_source_path(row, path))
    try:
        lines = _git_source(project, commit, path).splitlines()
    except subprocess.CalledProcessError:
        raise ValueError(f"{path} does not exist in the pinned project at {commit[:8]}") from None
    first = 1 if first is None else first
    if first < 1 or first > len(lines):
        raise ValueError(f"{path} has {len(lines)} lines; first={first} is out of range")
    wanted = last if last is not None else first + 199
    end = min(wanted, len(lines), first + MAX_SOURCE_LINES - 1)
    if end < first:
        raise ValueError("last must not precede first")
    return {"source": f"{row['source']}@{commit}:{path}:{first}-{end}", "pin": commit,
            "path": path, "file_lines": len(lines),
            "first": first, "last": end, "next_first": end + 1 if end < len(lines) and wanted > end else None,
            "text": "\n".join(f"{i}: {lines[i-1]}" for i in range(first, end + 1))}


def find(name: str, queries: list[str], limit: int = 20) -> dict:
    """Search declaration lines of the pinned trees and the kickoff index, counting each qualified declaration once."""
    if not queries or not all(isinstance(query, str) and query.strip() for query in queries):
        raise ValueError("queries must be a nonempty list of names or search strings")
    if limit < 1:
        raise ValueError("limit must be positive")
    limit = min(limit, 100)
    with _session():
        return _find(name, queries, limit)


def _find(name: str, queries: list[str], limit: int) -> dict:
    from arena.context import constant_index

    inventory = _context(name)
    indexed = constant_index(inventory) if not inventory.get("error") else []
    entries = indexed + [{**item, "kind": item.get("decl")} for item in inventory.get("source", [])
                         if not inventory.get("error")]
    row = problem(name)
    version, commit = measure_version(row)
    roots = _roots(workspace(row, version, commit), commit)
    needles = [query[5:] if query.startswith("decl:") else query for query in queries]
    named = [bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_'.]*", needle)) for needle in needles]
    # A name the kickoff index holds exactly resolves without searching the source trees.
    pending = [needle for needle, is_name in zip(needles, named)
               if not (is_name and any(item["name"] == needle for item in entries))]
    hits = _declaration_hits(roots, list(dict.fromkeys(pending))) if pending else []
    per_query = []
    for query, needle, is_name in zip(queries, needles, named):
        exact_only = query.startswith("decl:")
        folded = needle.casefold()
        found: dict[str, dict] = {}
        if is_name:
            for item in entries:
                module = item.get("module")
                if (item["name"] == needle if exact_only else folded in item["name"].casefold()) \
                        and item["name"] not in found and module not in (None, "this file") \
                        and "start_line" in item and item.get("tag") != "generated":
                    located = _module_file(roots, module)
                    if located is None:
                        continue
                    root, pin, path = located
                    lines = _git_source(root, pin, path).splitlines()
                    found[item["name"]] = _declaration_row(pin, path, lines, item["name"],
                                                           item["start_line"], item["end_line"])
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
                        matched = folded in "\n".join(lines[line_number - 1:end]).casefold()
                    if matched:
                        found[qualified] = _declaration_row(pin, path, lines, qualified,
                                                            _declaration_start(lines, line_number), end)
        if not found:
            per_query.append({"query": query, "matches": [], "error": "not_found",
                              "suggestions": _declaration_suggestions(needle, indexed),
                              "files_scanned": scanned, "files_truncated": files_truncated})
            continue
        selected = sorted(found.values(), key=lambda item: (
            0 if item["name"].casefold() == folded else 1 if item["name"].casefold().endswith("." + folded) else 2,
            item["name"]))[:limit]
        per_query.append({"query": query, "matches": selected, "distinct_count": len(found),
                          "truncated": len(found) > len(selected), "files_scanned": scanned,
                          "files_truncated": files_truncated})
    return {"queries": per_query, "pin": commit, "limit": limit}


def _declaration_row(pin: str, path: str, lines: list[str], qualified: str, start: int, end: int) -> dict:
    return {"name": qualified, "handle": f"decl:{qualified}", "path": path, "line": start,
            "end_line": end, "pin": pin, "signature": _signature(lines, start, end)}


def _candidate_files(hits: list[tuple[int, str, str, int, str]], needle: str, is_name: bool,
                     exact_only: bool) -> list[tuple[int, str, str]]:
    """Files worth reading for one query, best first: exact leaf names, then prefixes, then substrings."""
    folded = needle.casefold()
    parts = needle.split(".")
    leaf = parts[-1].casefold()
    namespaced = {(index, path) for index, _, path, _, text in hits
                  if len(parts) > 1 and re.match(r"^\s*namespace\s", text, re.I)
                  and parts[-2].casefold() in text.casefold()}
    ranked: dict[tuple[int, str, str], int] = {}
    for index, pin, path, _, text in hits:
        declared = _DECLARATION_PATTERN.match(text)
        if is_name:
            if not declared:
                continue
            local = declared.group(1).casefold()
            if leaf not in local or (len(parts) > 1 and folded not in local and (index, path) not in namespaced):
                continue
            tier = 0 if local.split(".")[-1] == leaf else 1 if local.split(".")[-1].startswith(leaf) else 2
        elif folded in text.casefold():
            tier = 2
        else:
            continue
        key = (index, pin, path)
        ranked[key] = min(ranked.get(key, tier), tier)
    return [key for key, _ in sorted(ranked.items(), key=lambda item: (item[1], item[0][0], item[0][2]))]


def _canonical_source_path(row: dict, path: str) -> str:
    """Normalize documented project aliases to a path inside the pinned checkout."""
    for alias in ("strata", "physlib", "mathlib", "cslib", "arklib"):
        if path.startswith(alias + ":") or path.startswith(alias + "/"):
            path = path[len(alias) + 1:]
            break
    path = path.removeprefix("./")
    if path.startswith("/") or ".." in Path(path).parts or not path.endswith(".lean"):
        raise ValueError("Only relative .lean paths inside the pinned project are allowed")
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
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=package, text=True,
                              capture_output=True, check=False)
        if head.returncode == 0 and head.stdout.strip() == revision:
            roots.append((package, revision, package_name))
    return roots


def _source_target(project: Path, commit: str, path: str,
                   module: str | None = None) -> tuple[Path, str, str]:
    """Resolve a canonical project or dependency path to its pinned Git root."""
    if isinstance(project, Path) and (project / path).is_file():
        exists = subprocess.run(["git", "cat-file", "-e", f"{commit}:{path}"], cwd=project,
                                capture_output=True, check=False).returncode == 0
        if exists:
            return project, commit, path
    module_path = module.replace(".", "/") + ".lean" if module else None
    for root, pin, package in _package_roots(project):
        for candidate in (module_path, path):
            if candidate and (root / candidate).is_file():
                return root, pin, candidate
    raise ValueError(f"{path} does not exist in the pinned project or its dependency roots")


_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:private|protected|noncomputable|nonrec|unsafe|partial)\s+)*"
    r"(?:theorem|lemma|def|opaque|example|instance|abbrev|inductive|structure|class|axiom)\s+"
    r"([A-Za-z_][A-Za-z0-9_'.]*)")
_SCOPE_PATTERN = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:public|noncomputable|meta)\s+)*(namespace|section)\b(?:\s+([A-Za-z_][A-Za-z0-9_'.]*))?\s*$")
_END_PATTERN = re.compile(r"^\s*end(?:\s+([A-Za-z_][A-Za-z0-9_'.]*))?\s*$")
# The same shape for `git grep -E`, which only needs declaration lines and never body text.
_DECLARATION_GREP = (r"^[[:space:]]*(@\[[^]]*\][[:space:]]*)*((private|protected|noncomputable|nonrec|unsafe|partial)"
                     r"[[:space:]]+)*(theorem|lemma|def|opaque|instance|abbrev|inductive|structure|class|axiom)[[:space:]]+")
MAX_SCAN_FILES = 30


def _source_declarations(lines: list[str]) -> list[tuple[int, str]]:
    """Return named Lean declarations with names qualified by their namespace and section blocks."""
    scopes: list[tuple[str | None, str]] = []  # (label, namespace prefix it adds); sections add none
    declarations = []
    for line_number, line in enumerate(lines, 1):
        code = line.split("--", 1)[0]
        scope = _SCOPE_PATTERN.match(code)
        if scope:
            scopes.append((scope.group(2), scope.group(2) or "") if scope.group(1) == "namespace"
                          else (scope.group(2) or "", ""))
            continue
        closed = _END_PATTERN.match(code)
        if closed:
            label = closed.group(1)
            index = next((i for i in range(len(scopes) - 1, -1, -1) if label is not None and
                          (scopes[i][0] == label or (scopes[i][0] or "").endswith("." + label))), None)
            if label is None or index is None:
                index = len(scopes) - 1
            del scopes[max(index, 0):]
            continue
        match = _DECLARATION_PATTERN.match(line)
        if match:
            local = match.group(1)
            if local.startswith("_root_."):
                qualified = local[len("_root_."):]
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
        opener = next((i for i in range(start - 2, max(start - 80, -1), -1)
                       if lines[i].lstrip().startswith("/--")), None)
        if opener is not None:
            start = opener + 1
    return start


def _declaration_end(lines: list[str], starts: list[tuple[int, str]], index: int) -> int:
    """The last line of a declaration: before the next one's docs and attributes, ignoring blank lines."""
    following = starts[index + 1][0] if index + 1 < len(starts) else len(lines) + 1
    end = _declaration_start(lines, following) - 1 if following <= len(lines) else len(lines)
    while end > starts[index][0] and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("--")
                                      or _SCOPE_PATTERN.match(lines[end - 1]) or _END_PATTERN.match(lines[end - 1])):
        end -= 1
    return end


def _signature(lines: list[str], start: int, end: int) -> str:
    """The first declaration lines after any doc comment and attributes, up to the line that opens the body."""
    shown = []
    keyword = next((i for i in range(start, end + 1) if _DECLARATION_PATTERN.match(lines[i - 1])), start)
    for text in lines[keyword - 1:min(end, keyword + 5)]:
        shown.append(text.rstrip())
        if ":=" in text or text.rstrip().endswith("where") or text.strip().startswith("|"):
            break
    return "\n".join(shown)


def _roots(project: Path, commit: str) -> list[tuple[Path, str, str]]:
    session = _SESSION.get()
    key = str(project)
    if session is not None and key in session.roots:
        return session.roots[key]
    roots = [(project, commit, "")] + _package_roots(project)
    if session is not None:
        session.roots[key] = roots
    return roots


def _module_file(roots: list[tuple[Path, str, str]], module: str) -> tuple[Path, str, str] | None:
    """The pinned root that holds module `A.B.C` as `A/B/C.lean`; its own package is tried first."""
    path = module.replace(".", "/") + ".lean"
    head = module.split(".")[0].casefold()
    for root, pin, package in sorted(roots, key=lambda item: item[2].casefold() != head):
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
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_'.]*", needle):
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
        result = subprocess.run(["git", "grep", "-n", "-I", "-i", "-E", "-e", pattern, pin, "--", "*.lean"],
                                cwd=root, text=True, errors="replace", capture_output=True, check=False)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip() or "Pinned source search failed")
        hits = []
        for raw in result.stdout.splitlines():
            parts = raw[len(pin) + 1:].split(":", 2)
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


def _resolve_declaration_source(name: str, symbol: str, module: str | None = None,
                                span: tuple[int, int] | None = None) -> dict:
    """Find one declaration's pinned file and lines, excluding scratch copies.

    `module` and `span` come from the kickoff index and resolve the declaration exactly with no
    search; otherwise only declaration lines mentioning the name are searched. An exact qualified
    match wins; several distinct qualified matches raise AmbiguousDeclaration.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9'.]*", symbol):
        raise ValueError("Invalid declaration name")
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
            raise ValueError(f"{symbol} is defined in {module}, which is not in the pinned project or its dependency roots")
        files = [located]
    else:
        hits = _declaration_hits(roots, [symbol])
        files = []
        for index, pin, path, _, text in hits:
            declared = _DECLARATION_PATTERN.match(text)
            if declared and leaf.casefold() in declared.group(1).casefold() and (roots[index][0], pin, path) not in files:
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
        if span is not None and 1 <= span[0] <= span[1] <= len(lines) and leaf in "\n".join(lines[span[0] - 1:span[1]]):
            return {"root": root, "pin": pin, "path": path, "line": span[0], "end": span[1],
                    "qualified": symbol, "file_lines": len(lines)}
        for index, (line_number, qualified) in enumerate(starts):
            if qualified == symbol or qualified.endswith("." + symbol):
                start = _declaration_start(lines, line_number)
                found.setdefault(qualified, {"root": root, "pin": pin, "path": path, "line": start,
                                             "end": _declaration_end(lines, starts, index),
                                             "qualified": qualified, "file_lines": len(lines)})
    if symbol in found:
        return found[symbol]
    if len(found) > 1:
        raise AmbiguousDeclaration(symbol, sorted(found))
    if found:
        return next(iter(found.values()))
    raise ValueError(f"Declaration not found in pinned project: {symbol}")


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
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9'.]*", symbol):
        raise ValueError("Invalid declaration name")
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
        return {"symbol": symbol, "handle": f"decl:{qualified}", "name": qualified, "found": True,
                "pin": located["pin"], "path": located["path"], "line": located["line"],
                "end_line": located["end"], "file_lines": located["file_lines"],
                "source_text": "\n".join(lines[located["line"] - 1:located["end"]])}
    entry = _indexed_entry(name, symbol)
    if entry is not None and module not in (None, "this file"):
        # Indexed, but no pinned source root holds its module (for example the Lean toolchain).
        return {"symbol": symbol, "found": True, "name": symbol, "kind": entry.get("kind"),
                "module": module, "signature": entry.get("sig")}
    return {"symbol": symbol, "found": False,
            "hint": "No pinned source declaration matched this name."}


def _declaration_in_lean(name: str, symbol: str) -> dict:
    """Resolve a name the way the theorem's own file does (namespaces, opens, imported libraries)."""
    from arena.engine import candidate_file, run_lean

    row = problem(name)
    version, commit = measure_version(row)
    built = candidate_file(row, row["src"], version, commit)
    inserted = (Path(__file__).with_name("lean") / "declaration.lean").read_text() + f"arena_decl {symbol}\n\n"
    text = built["text"][:built["head"]] + inserted + built["text"][built["head"]:]
    ran = run_lean(row, built["path"], text)
    if ran is None:
        raise ValueError("Lean timed out while resolving the name")
    records = [json.loads(raw) for raw in re.findall(r"^ARENA_DECL (\{.*\})$", ran[1], re.M)]
    found = [item for item in records if item.get("found")]
    if not found:
        return {"symbol": symbol, "found": False,
                "hint": "No declaration of that name is visible where the theorem is stated; try the full name or a prefix."}
    best = found[0]
    return {"symbol": symbol, "found": True, "name": best["name"], "kind": best["kind"], "module": best["module"],
            "source": f"{best['module']}" + (f":{best['line']}" if best.get("line") else ""),
            "signature": best["signature"],
            **({"alternatives": [item["name"] for item in found[1:]]} if len(found) > 1 else {})}


def packet(name: str) -> str:
    """Kickoff packet: task, exchange rates, source-derived context. Built once per row and cached."""
    from arena.context import render_packet

    return render_packet(name)


def _append(directory: Path, event: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "ledger.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        data = (json.dumps({"ts": time.time(), **event}, ensure_ascii=False,
                           separators=(",", ":")) + "\n").encode()
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


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

    The model's own work (evaluate, probe, profile, polish) shares the `model`
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


def init(name: str, run_id: str, extra: str = "") -> dict:
    directory = run_dir(run_id)
    if directory.exists():
        raise ValueError(f"Run ID already exists: {directory}")
    row = problem(name)
    version, commit = versions(row)[0]
    project = workspace(row, version, commit)
    directory.mkdir(parents=True)
    text = packet(name) + ("\nAdditional instructions:\n" + extra + "\n" if extra else "")
    (directory / "packet.txt").write_text(text)
    shadow = directory / "scratch" / "project"
    shutil.copytree(project, shadow, ignore=shutil.ignore_patterns(".git", ".lake"))
    (shadow / ".lake").symlink_to(project / ".lake", target_is_directory=True)
    _append(directory, {"kind": "init", "theorem": name, "version": version, "commit": commit,
                        "versions": versions(row),
                        "packet_sha256": hashlib.sha256(text.encode()).hexdigest()})
    reference_id = hashlib.sha256((name + "\0" + row["src"]).encode()).hexdigest()
    _snapshot(directory, reference_id, row["src"])
    _append(directory, {"kind": "candidate", "candidate_id": reference_id, "parents": [],
                        "hypothesis": "Pinned original reference proof", "origin": "reference",
                        "source_versions": versions(row),
                        "evaluator_sha256": hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest()})
    materialize(name, run_id, row["src"])
    _append(directory, {"kind": "current", "candidate_id": reference_id})
    return {"packet": str(directory / "packet.txt"), "shadow": str(shadow),
            "candidate_path": str(shadow / source_path(row))}


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
    raise ValueError(f"Unknown candidate {reference}; candidates are #1-#{len(candidates)}")


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
    raise ValueError(f"Unknown probe {reference}; probes are p1-p{len(_probe_numbers(history))}")


IDEA_STATUSES = ("active", "parked", "succeeded", "abandoned")


def _region(text: str) -> list[int] | str:
    """Proof lines such as "12-30", "lines 12–30", "L12..L30" or "line 7"; anything else is kept as text."""
    numbers = [int(n) for n in re.findall(r"\d+", text)][:2]
    if not numbers:
        return text.strip()[:120]
    return [min(numbers), max(numbers)]


def record_idea(run_id: str, title: str | None = None, hypothesis: str = "", region: str | None = None,
                expected_effect: dict | None = None, idea_id: str | None = None,
                status: str | None = None, reason: str = "") -> dict:
    """Create or update a model-owned idea. The harness never authors or schedules ideas."""
    directory = run_dir(run_id)
    history = events(directory)
    if not history or not history[0].get("theorem"):
        raise ValueError("Run is uninitialized")
    if status is not None and status not in IDEA_STATUSES:
        raise ValueError(f"status must be one of {', '.join(IDEA_STATUSES)}")
    if status in ("parked", "abandoned", "succeeded") and not reason.strip():
        raise ValueError(f"Give a one-line reason when marking an idea {status}")
    effect = {str(k): str(v)[:80] for k, v in (expected_effect or {}).items()
              if k in ("tokens", "heartbeats", "compat")}
    span = _region(region) if region and region.strip() else None
    known = {item["id"]: item for item in history if item.get("kind") == "idea"}
    if idea_id:
        idea_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", idea_id.strip())[:40] or None
    if idea_id and idea_id not in known and not (title and title.strip()):
        raise ValueError(f"Unknown idea {idea_id}; give a title to create it "
                         f"(recorded ideas: {', '.join(known) or 'none yet'})")
    if idea_id and idea_id in known:
        update = {"kind": "idea_update", "id": idea_id}
        if title: update["title"] = title.strip()[:120]
        if hypothesis: update["hypothesis"] = hypothesis.strip()[:600]
        if span: update["region"] = span
        if effect: update["expected_effect"] = effect
        if status: update["status"] = status
        if reason.strip(): update["reason"] = reason.strip()[:300]
        _append(directory, update)
        return {"ok": True, **{k: v for k, v in update.items() if k != "kind"}}
    if not title or not title.strip():
        raise ValueError("A new idea needs a title")
    # Models often name their own ideas; keep that name so later updates by it work.
    identifier = idea_id or next(f"i{n}" for n in range(len(known) + 1, len(known) + 1000) if f"i{n}" not in known)
    item = {"kind": "idea", "id": identifier, "title": title.strip()[:120],
            "hypothesis": hypothesis.strip()[:600], "region": span, "expected_effect": effect,
            "status": status or "active", "reason": reason.strip()[:300]}
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
            rows[item["candidate_id"]] = {"id": item["candidate_id"], "n": len(rows) + 1,
                "idea_id": item.get("idea_id"), "origin": item.get("origin", "model"),
                "parents": item.get("parents", []), "evaluations": []}
        elif item.get("kind") == "evaluation" and item["candidate_id"] in rows:
            result = item["result"]
            rows[item["candidate_id"]]["evaluations"].append({
                "mode": item["mode"], "status": _evaluation_status(result, item["mode"], total),
                "result": result, "score": _metric_score(result.get("metrics"))})
    for row in rows.values():
        full = [e for e in row["evaluations"] if e["status"] == "full"]
        primary = [e for e in row["evaluations"] if e["status"] == "primary"]
        chosen = (max(full, key=lambda e: e["score"] or -1) if full else
                  max(primary, key=lambda e: e["score"] or -1) if primary else
                  (row["evaluations"][-1] if row["evaluations"] else None))
        row["status"] = chosen["status"] if chosen else "unevaluated"
        result = chosen["result"] if chosen else {}
        row.update(tokens=result.get("tokens"), heartbeats=result.get("heartbeat"),
                   score=chosen["score"] if chosen else None,
                   verified=bool(full), metrics=result.get("metrics"), evaluated=chosen is not None)
    return list(rows.values())


def _brief(row: dict | None) -> dict | None:
    if not row:
        return None
    return {"candidate": f"#{row['n']}", "tokens": row["tokens"], "heartbeats": row["heartbeats"],
            ("proxy" if row["verified"] else "estimated_proxy"): row["score"], "status": row["status"]}


def _best(rows: list[dict], exclude: str | None = None) -> dict | None:
    pool = [r for r in rows if r["id"] != exclude and r["score"] is not None
            and r["status"] in ("full", "primary") and r["origin"] != "reference"]
    return max(pool, key=lambda r: (r["verified"], r["score"]), default=None)


def _delta(current: dict, other: dict | None) -> dict | None:
    if not other or other.get("tokens") is None or other.get("heartbeats") is None:
        return None
    out = {"tokens": current["tokens"] - other["tokens"],
           "heartbeats": current["heartbeats"] - other["heartbeats"]}
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
    return (f"The last {window} candidates (#{recent[0]['n']}-#{recent[-1]['n']}) all descend from "
            f"#{by_id[root]['n']} and none improved on its score" + (f" of {base}." if base is not None else "."))


def _model_view(result: dict) -> dict:
    """Compact, non-duplicated payload for the model; the ledger keeps the full result."""
    view = {key: result[key] for key in ("ok", "mode", "candidate", "probe", "tokens", "heartbeat",
            "idea_id", "cached", "candidate_path", "start_line", "end_line", "error", "notes",
            "full_check", "advisory", "scored", "contains_sorry", "goals") if result.get(key) not in (None, [], "")}
    metrics = result.get("metrics")
    if metrics and metrics.get("axes"):
        view["metrics"] = {key: metrics[key] for key in ("proxy", "estimated_proxy", "assumes_full_compat",
                                                         "deltas") if key in metrics}
        view["metrics"]["axes"] = {axis: {k: v for k, v in info.items() if k != "reference"}
                                   for axis, info in metrics["axes"].items()}
    elif metrics is not None and not metrics.get("compiled"):
        view["metrics"] = {"compiled": False}
    compat = {}
    for version, info in (result.get("compat") or {}).items():
        item = {"passed": bool(info.get("passed"))}
        for key in ("heartbeats", "diagnostics", "full_diagnostics_ref", "error"):
            if info.get(key) not in (None, [], ""):
                item[key] = info[key]
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
    return {version: info for version, info in ((fast or {}).get("result", {}).get("compat") or {}).items()
            if info.get("passed")}


def record_evaluation(name: str, run_id: str, proof: str, mode: str,
                      parents: list[str] | None = None, hypothesis: str = "",
                      origin: str = "model", merge: dict | None = None,
                      materialize_live: bool = True, idea_id: str | None = None,
                      lane: str = "model", trigger: str = "model", precomputed: dict | None = None) -> dict:
    """Record a candidate and its evaluation. `precomputed` is a result the caller already
    compiled for this exact proof and mode; `trigger` says whether the model or the
    harness asked for it."""
    if mode not in ("fast", "full"):
        raise ValueError("mode must be fast or full")
    directory = run_dir(run_id)
    row = problem(name)
    # Forbidden constructs and statement edits are rejected before anything is recorded,
    # so `sorry` drafts can never become candidates.
    validate_proof(row, proof)
    candidate_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    notes: list[str] = []
    with _candidate_lock(directory, candidate_id):
        history = events(directory)
        if not history or history[0].get("theorem") != name:
            raise ValueError("Run is uninitialized or theorem differs")
        if history[0].get("versions") and history[0]["versions"] != [list(pair) for pair in versions(row)]:
            raise ValueError("Pinned source versions changed since run initialization")
        known = set(_candidate_ids(history))
        explicit: list[str] = []
        for reference in parents or []:
            try:
                resolved = resolve_candidate_ref(history, reference)
            except ValueError as error:
                notes.append(f"parent {reference} ignored: {error}")
                continue
            if resolved != candidate_id and resolved not in explicit:
                explicit.append(resolved)
        lineage = explicit or ([_current(history)] if candidate_id not in known and _current(history) else [])
        lineage = [parent for parent in lineage if parent != candidate_id]
        if candidate_id in known and idea_id is None:
            idea_id = next(item.get("idea_id") for item in history
                           if item.get("kind") == "candidate" and item["candidate_id"] == candidate_id)
        if idea_id and idea_id not in {item["id"] for item in history if item.get("kind") == "idea"}:
            notes.append(f"idea_id {idea_id} is not a recorded idea; kept as a label")
        _snapshot(directory, candidate_id, proof)
        if candidate_id not in known:
            _append(directory, {"kind": "candidate", "candidate_id": candidate_id,
                                "parents": lineage, "hypothesis": hypothesis,
                                "origin": origin, "merge": merge, "idea_id": idea_id,
                                "source_versions": versions(row),
                                "evaluator_sha256": _evaluator_sha()})
        elif explicit and not any(item.get("kind") == "derivation"
                                  and item.get("candidate_id") == candidate_id
                                  and item.get("parents") == explicit for item in history):
            original = next(item for item in history if item.get("kind") == "candidate"
                            and item["candidate_id"] == candidate_id)
            if original.get("parents", []) != explicit:
                _append(directory, {"kind": "derivation", "candidate_id": candidate_id,
                                    "parents": explicit, "origin": origin, "merge": merge})
        key = _evaluation_key(candidate_id, mode, row)
        prior = next((item for item in reversed(history) if item.get("kind") == "evaluation" and item["key"] == key), None)
        if prior:
            result = json.loads(json.dumps(prior["result"]))
        elif precomputed is not None:
            result = precomputed
        else:
            try:
                with lean_lock(directory, lane):
                    result = evaluate(name, proof, mode, known=_compiled_versions(history, candidate_id, row)
                                      if mode == "full" else None)
            except (ValueError, FileNotFoundError) as error:
                result = {"ok": False, "name": name, "mode": mode, "error": str(error),
                          "compat": {}, "tokens": None, "heartbeat": None, "local_proxy": None}
        if not prior:
            _externalize_output(directory, candidate_id, result)
            _append(directory, {"kind": "evaluation", "candidate_id": candidate_id, "key": key,
                                "mode": mode, "trigger": trigger, "result": result})
    location = materialize(name, run_id, proof) if materialize_live and result.get("tokens") is not None else {}
    if location:
        _append(directory, {"kind": "current", "candidate_id": candidate_id})
    history = events(directory)
    rows = _summaries(history)
    me = next((r for r in rows if r["id"] == candidate_id), None)
    result.setdefault("metrics", None)
    if me and result["metrics"] and result["metrics"].get("axes"):
        deltas = result["metrics"].setdefault("deltas", {})
        current = {"tokens": result["tokens"], "heartbeats": result["heartbeat"],
                   "score": _metric_score(result["metrics"])}
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
    return {**result, "candidate_id": candidate_id, "candidate": _label(history, candidate_id),
            "node_number": _candidate_ids(history).index(candidate_id) + 1,
            "idea_id": idea_id, "cached": prior is not None, "notes": notes,
            "best_so_far": best_line, "advisory": _advisory(rows), **location}


def evaluate_request(name: str, run_id: str, proof: str | None = None, mode: str = "fast",
                     parents: list[str] | None = None, hypothesis: str = "", idea_id: str | None = None,
                     candidate_ref: str | None = None, from_probe: str | None = None) -> dict:
    """Entry for the model: evaluate a proof, an existing `#N`, or a probe by ID."""
    if proof is not None and not proof.strip():
        proof = None
    candidate_ref = candidate_ref or None
    from_probe = from_probe or None
    if sum(value is not None for value in (proof, candidate_ref, from_probe)) != 1:
        raise ValueError("Pass exactly one of proof, candidate, or from_probe")
    directory = run_dir(run_id)
    history = events(directory)
    if candidate_ref:
        candidate_id = resolve_candidate_ref(history, candidate_ref)
        proof = (directory / "proofs" / f"{candidate_id}.lean").read_text()
    elif from_probe:
        proof_id = resolve_probe_ref(history, from_probe)
        source = next(item for item in reversed(history)
                      if item.get("kind") == "probe" and item["proof_id"] == proof_id)
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
        idea_id = idea_id or source.get("idea_id")
        parents = parents or ([source["parent"]] if source.get("parent") else None)
    if not proof:
        raise ValueError("Supply proof, candidate (#N) or from_probe (pN)")
    try:
        result = record_evaluation(name, run_id, proof, mode, parents, hypothesis, idea_id=idea_id)
    except ValueError as error:
        if str(error) in ("FORBIDDEN: sorry", "FORBIDDEN: admit"):
            raise ValueError(f"{error}; use arena_probe to inspect a draft with holes") from None
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
    return f"queued: the other {total - 1} version(s) are checked in the background"


def probe(name: str, run_id: str, proof: str, idea_id: str | None = None, parent: str | None = None) -> dict:
    """Compile a draft (sorry allowed) in the shadow project without creating a candidate."""
    proof = normalize_draft(name, proof)
    directory = run_dir(run_id)
    history = events(directory)
    row = problem(name)
    notes: list[str] = []
    parent_id = None
    if parent:
        try:
            parent_id = resolve_candidate_ref(history, parent)
        except ValueError as error:
            notes.append(f"parent {parent} ignored: {error}")
    parent_id = parent_id or _current(history)
    proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    if proof_id in set(_candidate_ids(history)):
        return evaluate_request(name, run_id, proof, idea_id=idea_id, parents=[parent] if parent else None)
    earlier = next((item for item in reversed(history)
                    if item.get("kind") == "probe" and item["proof_id"] == proof_id), None)
    if earlier:
        result = earlier["result"]
    else:
        validate_proof(row, proof, allow_sorry=True)
        complete = not _has_hole(row, proof)
        try:
            with lean_lock(directory):
                # A complete draft is compiled exactly as a fast evaluation would be,
                # so if it passes it becomes a candidate without another compile.
                result = evaluate(name, proof, "fast" if complete else "probe")
        except (ValueError, FileNotFoundError) as error:
            result = {"ok": False, "mode": "probe", "error": str(error), "compat": {}}
        if complete and next(iter((result.get("compat") or {}).values()), {}).get("passed"):
            recorded = record_evaluation(name, run_id, proof, "fast", [parent] if parent else None,
                                         idea_id=idea_id, precomputed=result)
            view = _model_view({**recorded, "full_check": _full_check_status(events(directory), recorded["candidate_id"])})
            view.setdefault("notes", []).append(f"complete draft compiled, recorded as candidate {recorded['candidate']}")
            return view
        result = {**result, "mode": "probe", "scored": False}
        _externalize_output(directory, proof_id, result)
        _snapshot(directory, proof_id, proof)
        _append(directory, {"kind": "probe", "proof_id": proof_id, "idea_id": idea_id,
                            "parent": parent_id, "result": result})
    location = materialize(name, run_id, proof) if result.get("tokens") is not None else {}
    label = _probe_numbers(events(directory))[proof_id]
    return _model_view({**result, "probe": label, "idea_id": idea_id or (earlier or {}).get("idea_id"),
                        "cached": earlier is not None, "notes": notes, **location})


def normalize_draft(name: str, draft: str) -> str:
    """Add the exact benchmark declaration to a proof body without altering complete proofs."""
    if not isinstance(draft, str) or not draft.strip():
        raise ValueError("Draft must be nonempty proof text")
    statement = problem(name)["statement"]
    body = draft.lstrip()
    if body.startswith(statement):
        return body
    if body.startswith(":="):
        return statement + " " + body
    if re.match(r"by\b", body):
        return statement + " := " + body
    raise ValueError("Draft must be a complete theorem or a proof body beginning with `by` or `:=`")


def probe_batch(name: str, run_id: str, drafts: list[str], idea_id: str | None = None,
                parent: str | None = None) -> dict:
    """Probe one to four drafts in order, keeping their parent fixed across promotions."""
    if not isinstance(drafts, list) or not 1 <= len(drafts) <= 4:
        raise ValueError("Pass between one and four drafts")
    history = events(run_dir(run_id))
    fixed_parent = resolve_candidate_ref(history, parent) if parent else _current(history)
    outcomes = []
    for index, draft in enumerate(drafts, 1):
        try:
            outcome = probe(name, run_id, draft, idea_id, fixed_parent)
        except (OSError, ValueError, RuntimeError) as error:
            outcome = {"ok": False, "mode": "probe", "error": " ".join(str(error).split())[:400]}
        outcomes.append({"index": index, **outcome})
    return {"ok": True, "drafts": outcomes}


def candidate(name: str, run_id: str, reference: str) -> dict:
    """Restore a candidate (`#N`) or a probe (`pN`) into the shadow project."""
    directory = run_dir(run_id)
    history = events(directory)
    if re.fullmatch(r"p[0-9]+", reference.strip().lower()):
        proof_id = resolve_probe_ref(history, reference)
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
        entry = next(item for item in reversed(history)
                     if item.get("kind") == "probe" and item["proof_id"] == proof_id)
        return {"ok": True, "probe": reference.strip().lower(), "proof": proof,
                "last_result": _model_view({**entry["result"], "probe": reference}),
                **materialize(name, run_id, proof)}
    candidate_id = resolve_candidate_ref(history, reference)
    proof_path = directory / "proofs" / f"{candidate_id}.lean"
    if not proof_path.exists():
        raise ValueError("Unknown candidate")
    proof = proof_path.read_text()
    location = materialize(name, run_id, proof)
    _append(directory, {"kind": "current", "candidate_id": candidate_id})
    row = next((r for r in _summaries(events(directory)) if r["id"] == candidate_id), None)
    return {"ok": True, "candidate": _label(history, candidate_id), "proof": proof,
            "idea_id": row and row["idea_id"],
            "evaluations": [{"mode": e["mode"], "status": e["status"], "tokens": e["result"].get("tokens"),
                             "heartbeats": e["result"].get("heartbeat"), "score": e["score"]}
                            for e in (row["evaluations"] if row else [])], **location}


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
                raise ValueError("No candidate to profile; give candidate (#N) or probe (pN)")
            label = _label(history, proof_id)
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
    proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    cached = next((item for item in reversed(history)
                   if item.get("kind") == "profile" and item["proof_id"] == proof_id), None)
    if cached:
        return {**cached["result"], "target": label, "cached": True}
    measured = next((e["result"].get("heartbeat") for row in _summaries(history) if row["id"] == proof_id
                     for e in row["evaluations"] if e["result"].get("heartbeat") is not None), None)
    with lean_lock(directory):
        result = profile(name, proof, measured)
        result["statement_floor_hb"] = heartbeat_floor(name)["heartbeats"]
    _append(directory, {"kind": "profile", "proof_id": proof_id, "result": result})
    return {**result, "target": label, "cached": False}


def polish_request(name: str, run_id: str, reference: str | None = None, **limits) -> dict:
    """Try mechanical variants of a candidate. Passing, improving variants are stored as probes
    (`pN`) so the model can promote one with `arena_evaluate from_probe`; nothing becomes a node."""
    directory = run_dir(run_id)
    history = events(directory)
    candidate_id = resolve_candidate_ref(history, reference) if reference else _current(history)
    if candidate_id is None:
        raise ValueError("No candidate to polish; give candidate (#N)")
    proof = (directory / "proofs" / f"{candidate_id}.lean").read_text()
    measured = next((e["result"].get("heartbeat") for row in _summaries(history) if row["id"] == candidate_id
                     for e in row["evaluations"] if e["result"].get("heartbeat") is not None), None)
    with lean_lock(directory):
        outcome = polish(name, proof, measured, **limits)
    version = versions(problem(name))[0][0]
    shown = []
    for variant in outcome["variants"]:
        proof_id = hashlib.sha256((name + "\0" + variant["proof"]).encode()).hexdigest()
        if proof_id not in _probe_numbers(events(directory)):
            _snapshot(directory, proof_id, variant["proof"])
            _append(directory, {"kind": "probe", "proof_id": proof_id, "idea_id": None, "parent": candidate_id,
                                "result": {"ok": True, "mode": "probe", "scored": False, "tokens": variant["tokens"],
                                           "heartbeat": variant["heartbeats"], "polish": variant["edit"],
                                           "compat": {version: {"passed": True, "heartbeats": variant["heartbeats"]}}}})
        shown.append({"probe": _probe_numbers(events(directory))[proof_id], "edit": variant["edit"],
                      "tokens": variant["tokens"], "heartbeats": variant["heartbeats"],
                      "estimated_proxy": variant["estimated_proxy"], "delta": variant["delta"]})
    return {"ok": True, "candidate": _label(history, candidate_id), "base": outcome["base"],
            "tried": outcome["tried"], "passing": outcome["passing"], "improving": outcome["improving"],
            "complete": outcome["complete"], "seconds": outcome["seconds"], "variants": shown,
            "next": "Promote a variant with arena_evaluate from_probe; nothing was recorded as a candidate."}


def set_decision(run_id: str, candidate_id: str, decision: str, reason: str) -> dict:
    if decision not in ("pursue", "park") or not reason.strip():
        raise ValueError("Decision must be pursue or park with a reason")
    directory = run_dir(run_id)
    candidate_id = resolve_candidate_ref(events(directory), candidate_id)
    record = {"kind": "decision", "candidate_id": candidate_id,
              "decision": decision, "reason": reason.strip()}
    _append(directory, record)
    return record


def graph_state(run_id: str) -> dict:
    directory = run_dir(run_id)
    history = events(directory)
    if not history:
        return {"run_id": run_id, "nodes": [], "evaluations": 0, "merge_checks": [],
                "milestones": [], "frontier": []}
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
            ideas.append({key: event.get(key) for key in ("id", "title", "hypothesis", "region",
                                                          "expected_effect", "status", "reason")})
        elif kind == "idea_update":
            target = next((i for i in ideas if i["id"] == event["id"]), None)
            if target:
                target.update({k: v for k, v in event.items() if k not in ("kind", "id", "ts")})
        elif kind == "probe":
            probes.append({"proof_id": event["proof_id"], "idea_id": event.get("idea_id"),
                           "parent": event.get("parent"), "result": event["result"], "ts": event.get("ts")})
        elif kind == "candidate":
            identifier = event["candidate_id"]
            nodes[identifier] = {"id": identifier, "index": len(order) + 1,
                                 "parents": event.get("parents", []),
                                 "derivations": [event], "origin": event.get("origin", "model"),
                                 "hypothesis": event.get("hypothesis", ""),
                                 "idea_id": event.get("idea_id"),
                                 "merge": event.get("merge"), "evaluations": [],
                                 "source_versions": event.get("source_versions", []),
                                 "evaluator_sha256": event.get("evaluator_sha256"),
                                 "proof": (directory / "proofs" / f"{identifier}.lean").read_text(),
                                 "children": [], "decision": "pursue"}
            order.append(identifier)
        elif kind == "derivation" and event["candidate_id"] in nodes:
            nodes[event["candidate_id"]]["derivations"].append(event)
        elif kind == "evaluation" and event["candidate_id"] in nodes:
            index = len(timeline) + 1
            nodes[event["candidate_id"]]["evaluations"].append(
                {"number": index, "mode": event["mode"], "result": event["result"]})
            result = event["result"]
            timeline.append({"number": index, "candidate_id": event["candidate_id"],
                             "mode": event["mode"], "tokens": result.get("tokens"),
                             "heartbeat": result.get("heartbeat"),
                             "local_proxy": result.get("local_proxy"), "ts": event.get("ts")})
        elif kind == "merge_check":
            checks.append(event)
        elif kind == "decision" and event.get("candidate_id") in nodes:
            nodes[event["candidate_id"]]["decision"] = event["decision"]
    best_proxy = float("-inf")
    milestones = []
    for row in timeline:
        node = nodes[row["candidate_id"]]
        evaluation = next(e for e in node["evaluations"] if e["number"] == row["number"])
        result = evaluation["result"]
        compat = result.get("compat", {})
        row["status"] = "full" if evaluation["mode"] == "full" and len(compat) == total_versions and all(
            version.get("passed") for version in compat.values()) else (
            "primary" if next(iter(compat.values()), {}).get("passed") else "fail")
        if row["status"] == "full" and row["local_proxy"] is not None and row["local_proxy"] > best_proxy:
            best_proxy = row["local_proxy"]
            milestones.append(row.copy())
    fingerprints: dict[str, set[str]] = {}
    for identifier in order:
        node = nodes[identifier]
        for parent in node["parents"]:
            if parent in nodes:
                nodes[parent]["children"].append(identifier)
        full = [e for e in node["evaluations"] if next(
            (row["status"] for row in timeline if row["number"] == e["number"]), "fail") == "full"]
        primary = [e for e in node["evaluations"] if next(
            (row["status"] for row in timeline if row["number"] == e["number"]), "fail") == "primary"]
        selected = max(full, key=lambda e: e["result"].get("local_proxy") or -1) if full else (
            min(primary, key=lambda e: e["result"].get("tokens") or 10**9) if primary else
            (node["evaluations"][-1] if node["evaluations"] else None))
        result = selected["result"] if selected else {}
        node["status"] = "full" if full else "primary" if primary else "fail" if selected else "unevaluated"
        node["tokens"] = result.get("tokens")
        node["heartbeat"] = result.get("heartbeat")
        node["local_proxy"] = result.get("local_proxy") if full else None
        parent_attempts = [nodes[p].get("attempts_since_gain", 0) for p in node["parents"] if p in nodes]
        node["attempts_since_gain"] = 0 if node["status"] == "full" and any(
            m["candidate_id"] == identifier for m in milestones) else 1 + (min(parent_attempts) if parent_attempts else 0)
        first_parent = nodes.get(node["parents"][0]) if node["parents"] else None
        fingerprint = edit_fingerprint(first_parent["proof"], node["proof"]) if first_parent else {node["proof"]}
        node["novelty"] = 1.0 - max((len(fingerprint & earlier) / len(fingerprint | earlier)
                                     for earlier in fingerprints.values() if fingerprint | earlier), default=0.0)
        fingerprints[identifier] = fingerprint
        node["merge_partners"] = 0
    checked_pairs = {tuple(sorted(check["parents"])) for check in checks}
    open_nodes = [node for node in nodes.values() if node["status"] in ("full", "primary")
                  and node["decision"] != "park"]
    ancestry = {node["id"]: node["parents"] for node in nodes.values()}
    reference = next((node for node in nodes.values() if node["origin"] == "reference"), None)
    for index, left in enumerate(open_nodes):
        for right in open_nodes[index + 1:]:
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
    return {"run_id": run_id, "theorem": theorem, "nodes": rows, "ledger_events": len(history), "evaluations": len(timeline),
            "timeline": timeline, "merge_checks": checks, "milestones": milestones,
            "frontier": ranked, "ideas": idea_rows, "probes": probes}


def merge_once(run_id: str, graph: dict | None = None) -> dict | None:
    """Process one unchecked good pair; repeated calls exhaust the queue."""
    graph = graph if graph is not None else graph_state(run_id)
    if not graph["nodes"]:
        return None
    directory = run_dir(run_id)
    nodes = {node["id"]: node for node in graph["nodes"]}
    good = [node for node in graph["nodes"] if node["status"] in ("full", "primary")
            and node["decision"] != "park"]
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
                merged = merge_text(nodes[base["base"]]["proof"], nodes[pair[0]]["proof"],
                                    nodes[pair[1]]["proof"])
                outcome["edits"] = {"left": merged["left_edits"], "right": merged["right_edits"]}
                if merged["text"] is None:
                    outcome["reason"] = merged["reason"]
                else:
                    recorded = record_evaluation(graph["theorem"], run_id, merged["text"], "fast",
                                                 pair, "Deterministic combination of disjoint edits",
                                                 origin="auto_merge", merge={"base": base["base"],
                                                                               "base_inferred_from_reference": inferred,
                                                                               "edits": outcome["edits"]},
                                                 materialize_live=False)
                    outcome["candidate_id"] = recorded["candidate_id"]
                    outcome["node_number"] = recorded["node_number"]
                    outcome["fast_passed"] = any(v.get("passed") for v in recorded.get("compat", {}).values())
                    if outcome["fast_passed"]:
                        full = record_evaluation(graph["theorem"], run_id, merged["text"], "full",
                                                 pair, "Deterministic combination of disjoint edits",
                                                 origin="auto_merge", merge={"base": base["base"],
                                                                               "base_inferred_from_reference": inferred,
                                                                               "edits": outcome["edits"]},
                                                 materialize_live=False)
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
        return f"#{number} full check could not run: {str(result.get('error') or 'unknown error')[:160]}"
    failing = [version for version, info in compat.items() if not info.get("passed")]
    if not failing and len(compat) == total:
        proxy = (result.get("metrics") or {}).get("proxy", result.get("local_proxy"))
        return f"#{number} passes all {total} versions: proxy {proxy}"
    first = compat[failing[0]]
    reason = (first.get("error_headlines") or [first.get("error") or "compile failed"])[0]
    return f"#{number} fails {', '.join(failing)} ({len(compat) - len(failing)}/{total} pass): {str(reason)[:160]}"


def _autocheck_jobs(rows: list[dict]) -> list[dict]:
    """Candidates that compile on the primary version but were never checked on every version,
    most promising first."""
    jobs = [r for r in rows if r["origin"] != "reference" and r["status"] == "primary"
            and not any(e["mode"] == "full" for e in r["evaluations"])]
    return sorted(jobs, key=lambda r: (r["score"] if r["score"] is not None else float("-inf"), r["n"]), reverse=True)


def autocheck(name: str, run_id: str, max_seconds: float | None = None) -> dict:
    """Drain the full-check queue in the background lane. Only one checker runs per run;
    the queue is derived from the ledger, so a killed checker loses nothing."""
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
            history = events(directory)
            jobs = _autocheck_jobs(_summaries(history))
            if not jobs:
                break
            job = jobs[0]
            try:
                proof = (directory / "proofs" / f"{job['id']}.lean").read_text()
                record_evaluation(name, run_id, proof, "full", materialize_live=False,
                                  lane="background", trigger="auto")
            except Exception as error:  # record the failure so the queue moves on
                _append(directory, {"kind": "evaluation", "candidate_id": job["id"], "key": f"auto-error-{job['id']}",
                                    "mode": "full", "trigger": "auto",
                                    "result": {"ok": False, "mode": "full", "error": str(error)[:300], "compat": {}}})
            checked.append(f"#{job['n']}")
            write_state(run_id)
    return {"ok": True, "checked": checked,
            "remaining": [f"#{r['n']}" for r in _autocheck_jobs(_summaries(events(directory)))]}


def state(run_id: str) -> dict:
    """Everything the model should know without asking: the best verified candidate, a
    better unverified one if any, what is being checked, and the harness's check results."""
    history = events(run_dir(run_id))
    if not history:
        raise ValueError("Run is uninitialized")
    rows = _summaries(history)
    total = len(history[0].get("versions") or [1])
    numbers = {r["id"]: r["n"] for r in rows}
    verified = _best([r for r in rows if r["verified"]])
    unverified = _best([r for r in rows if not r["verified"]])
    leading = unverified if unverified and (not verified or (unverified["score"] or 0) > (verified["score"] or 0)) else None
    updates = [{"seq": seq, "text": _check_text(numbers[item["candidate_id"]], item["result"], total)}
               for seq, item in enumerate(history)
               if item.get("kind") == "evaluation" and item.get("trigger") == "auto" and item["candidate_id"] in numbers]
    return {"ok": True, "seq": len(history), "versions": total, "best": _brief(verified),
            "leading_unverified": _brief(leading), "checking": [f"#{r['n']}" for r in _autocheck_jobs(rows)],
            "updates": updates[-10:]}


def write_state(run_id: str) -> None:
    """Publish `state` atomically for the Pi extension, which reads it on every tool result."""
    directory = run_dir(run_id)
    target = directory / "state.json"
    temporary = target.with_name(f"state.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state(run_id), ensure_ascii=False))
    temporary.replace(target)


def submission(run_id: str) -> dict:
    """The run's answer: the best candidate that passes every version. Written by the harness so
    nothing depends on the model remembering to submit."""
    directory = run_dir(run_id)
    history = events(directory)
    rows = _summaries(history)
    best = _best([r for r in rows if r["verified"]])
    if best is None:
        answer = {"ok": True, "candidate": None,
                  "reason": "no model candidate passed every version; the original proof stands"}
    else:
        proof = (directory / "proofs" / f"{best['id']}.lean").read_text()
        (directory / "submission.lean").write_text(proof)
        answer = {"ok": True, "candidate": f"#{best['n']}", "candidate_id": best["id"],
                  "tokens": best["tokens"], "heartbeats": best["heartbeats"], "proxy": best["score"],
                  "proof_file": "submission.lean"}
    (directory / "submission.json").write_text(json.dumps(answer, indent=2) + "\n")
    return answer


def frontier(run_id: str) -> dict:
    """Compact status: best candidates, the model's ideas with their attempts, recent failures."""
    history = events(run_dir(run_id))
    if not history:
        raise ValueError("Run is uninitialized")
    rows = _summaries(history)
    ideas: dict[str, dict] = {}
    for item in history:
        if item.get("kind") == "idea":
            ideas[item["id"]] = {"id": item["id"], "title": item["title"], "status": item["status"],
                                 "reason": item.get("reason") or None}
        elif item.get("kind") == "idea_update" and item["id"] in ideas:
            ideas[item["id"]].update({k: item[k] for k in ("title", "status", "reason") if k in item})
    probe_numbers = _probe_numbers(history)
    failures: list[dict] = []
    for idea in ideas.values():
        mine = [r for r in rows if r["idea_id"] == idea["id"] and r["origin"] == "model"]
        drafts = [item for item in history if item.get("kind") == "probe" and item.get("idea_id") == idea["id"]]
        idea["attempts"] = len(mine)
        idea["probes"] = len({d["proof_id"] for d in drafts})
        idea["best"] = _brief(_best(mine))
        failed = [r for r in mine if r["status"] == "fail" and r["evaluations"]]
        last = failed[-1] if failed else None
        idea["last_failure"] = (f"#{last['n']}: " + _failure_text(last["evaluations"][-1]["result"])) if last else None
    for row in rows:
        if row["status"] == "fail" and row["evaluations"]:
            failures.append({"ref": f"#{row['n']}", "idea_id": row["idea_id"],
                             "error": _failure_text(row["evaluations"][-1]["result"])})
    for item in history:
        if item.get("kind") == "probe" and _probe_failed(item["result"]):
            failures.append({"ref": probe_numbers[item["proof_id"]], "idea_id": item.get("idea_id"),
                             "error": _failure_text(item["result"])})
    top = sorted((r for r in rows if r["status"] in ("full", "primary") and r["origin"] != "reference"),
                 key=lambda r: (r["verified"], r["score"] or -1), reverse=True)[:5]
    evaluations = sum(len(r["evaluations"]) for r in rows)
    return {"best": _brief(_best(rows)), "top": [_brief(r) | {"idea_id": r["idea_id"]} for r in top],
            "ideas": list(ideas.values()), "recent_failures": failures[-3:],
            "candidates": len(rows), "evaluations": evaluations,
            "probes": len(probe_numbers), "advisory": _advisory(rows)}


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
