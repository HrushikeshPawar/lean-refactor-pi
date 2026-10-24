"""Source-grounded, persistent state for one Arena proof-search run."""

from __future__ import annotations

import fcntl
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

from arena import goalstate, lean_health, lean_session, routes, text
from arena import text as agent_text
from arena.engine import (
    ROOT,
    actor_request_class,
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
    archive,
    changed_lines,
    common_base,
    edit_fingerprint,
    effort_table,
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
from arena.prices import changed_steps, fmt_hb, fmt_signed, rates, snippet_tokens, step_table
from arena.prices import price_row as build_price_row
from arena.profile import profile
from arena.run_control import cached_jsonl_rows, committed_operation_ids
from arena.salvage import fill_cost, fill_text
from arena.salvage import holes as find_holes
from arena.salvage import salvage as salvage_proof
from arena.traces import call_context


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


_SESSION: ContextVar[_Session | None] = ContextVar("source_session", default=None)
_NAMED_PARENT_UNSET = object()
_BATCH_FOCUS: ContextVar[tuple[bool, str | None]] = ContextVar("arena_batch_focus", default=(False, None))
_BATCH_NEWLY_FILED: ContextVar[set[str] | None] = ContextVar("arena_batch_newly_filed", default=None)
_OPERATION_RECEIPTS: ContextVar[list[dict] | None] = ContextVar("arena_operation_receipts", default=None)
_SALVAGE_DIRECTORY: ContextVar[Path | None] = ContextVar("arena_salvage_directory", default=None)
_SUBMISSION_ADMISSIONS: ContextVar[dict | None] = ContextVar("arena_submission_admissions", default=None)
_SELECT_COMPILED: ContextVar[bool] = ContextVar("arena_select_compiled", default=False)


@contextmanager
def compile_authorization():
    """An agent compile selects the exact submitted proof in its admission."""
    token = _SELECT_COMPILED.set(True)
    try:
        yield
    finally:
        _SELECT_COMPILED.reset(token)


def _submission_scope(function):
    """Keep exact admission receipts within one tool/background invocation."""

    @wraps(function)
    def invoke(*args, **kwargs):
        if _SUBMISSION_ADMISSIONS.get() is not None:
            return function(*args, **kwargs)
        token = _SUBMISSION_ADMISSIONS.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _SUBMISSION_ADMISSIONS.reset(token)

    return invoke


def _submission_key(directory: Path, proof_id: str, proof: str, inputs) -> str:
    from arena.run_control import actor_ids

    identity = actor_ids(directory.name)
    return json.dumps(
        [
            str(directory),
            proof_id,
            hashlib.sha256(proof.encode()).hexdigest(),
            inputs,
            {key: identity.get(key) for key in ("actor_id", "session_id", "job_id", "activation_id")},
        ],
        sort_keys=True,
    )


def _submission_attempt(directory: Path, proof_id: str, proof: str, inputs) -> dict | None:
    return (_SUBMISSION_ADMISSIONS.get() or {}).get(_submission_key(directory, proof_id, proof, inputs))


def _published_events(directory: Path) -> list[dict]:
    from arena.run_control import published_history

    return published_history(directory, events(directory))


def _submit_proof(directory: Path, proof_id: str, proof: str, inputs, *, evaluation=None, candidate=None) -> dict:
    from arena.run_control import SubmissionRefused, actor_ids, submit_candidate

    attempt = _submission_attempt(directory, proof_id, proof, inputs)
    if attempt is None:
        identity = actor_ids(directory.name)
        attempt = {
            "operation_id": uuid.uuid4().hex,
            "run_id": directory.name,
            "actor_id": identity["actor_id"],
            "session_id": identity["session_id"],
            **{key: identity[key] for key in ("job_id", "activation_id", "generation") if identity.get(key)},
            "proof_id": proof_id,
            "proof_sha256": hashlib.sha256(proof.encode()).hexdigest(),
            "authorization": "candidate",
            "inputs": inputs,
            **({"evaluation": evaluation} if evaluation is not None else {}),
            **({"candidate": candidate} if candidate is not None else {}),
        }
        if _SELECT_COMPILED.get():
            attempt["ledger_events"] = [{"kind": "proof_selection", "proof_id": proof_id, "candidate_id": proof_id}]
    decision = submit_candidate(directory, attempt)
    if not decision["ok"]:
        raise SubmissionRefused(decision.get("operation_id") or "")
    admissions = _SUBMISSION_ADMISSIONS.get()
    if admissions is not None:
        admissions[_submission_key(directory, proof_id, proof, inputs)] = attempt
    return attempt


def _append_submitted(directory: Path, attempt: dict, event: dict) -> None:
    """Publish an outcome only under the receipt that admitted its exact input."""
    from arena.run_control import SubmissionRefused, _apply_locked, _submit_locked, control_lock

    arguments = {"submission_id": attempt["operation_id"], "event": event}
    operation_id = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()
    with control_lock(directory):
        if not _submit_locked(directory, attempt)["ok"]:
            raise SubmissionRefused(attempt["operation_id"])

        def publish(ctx):
            ctx.append_ledger(
                {
                    **event,
                    "submission_id": attempt["operation_id"],
                    **({"generation": attempt["generation"]} if attempt.get("generation") else {}),
                }
            )
            return ctx.evidence

        receipt = _apply_locked(
            directory,
            {
                "operation_id": operation_id,
                "kind": "submission_outcome",
                "arguments": arguments,
                **{
                    key: attempt[key]
                    for key in ("run_id", "actor_id", "session_id", "job_id", "activation_id")
                    if key in attempt
                },
            },
            publish,
        )
    receipts = _OPERATION_RECEIPTS.get()
    if receipts is not None:
        receipts.append(receipt)


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


def source_range(name: str, path: str, first: int | None = None, last: int | None = None) -> dict:
    """Read pinned source; `next_first` continues a range cut at the limit.

    Without `first`, a `decl:` handle starts at its declaration and a path at the top of the file.
    Without `last`, a `decl:` handle stops where its declaration ends (see `declaration_end`).
    """
    # Lines are 1-based; some models send 0 to mean "not given".
    first, last = (first or None), (last or None)
    with _session():
        return _source_range(name, path, first, last)


# A column-0 line starting with one of these ends the declaration before it.
_TOP_LEVEL = re.compile(
    r"(?:/--|/-!|/-|@\[|--|#|end\b|namespace\b|section\b|open\b|variable\b|universe\b|set_option\b|"
    r"(?:(?:private|protected|noncomputable|unsafe|partial|nonrec)\s+)*"
    r"(?:theorem|lemma|def|abbrev|instance|structure|class|inductive|axiom|opaque|example|macro|syntax|"
    r"notation|infix|infixl|infixr|prefix|postfix|elab|local|scoped|attribute|deriving|export|mutual)\b)"
)


def declaration_end(lines: list[str], first: int) -> int:
    """The last line (1-based) of the declaration starting at `first`: the line before the next top-level
    command, without the blank lines that separate them."""
    end = first
    for number in range(first + 1, len(lines) + 1):
        line = lines[number - 1]
        if line and not line[0].isspace() and _TOP_LEVEL.match(line):
            break
        if line.strip():
            end = number
    return end


def _source_range(name: str, path: str, first: int | None, last: int | None) -> dict:
    row = problem(name)
    version, commit = measure_version(row)
    project = workspace(row, version, commit)
    to_declaration_end = path.startswith("decl:") and last is None
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
    if to_declaration_end:
        wanted = declaration_end(lines, first)
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
    """Read one pinned Lean file and index its declaration starts for source handles."""
    try:
        lines = _git_source(root, pin, path).splitlines()
    except subprocess.CalledProcessError:
        return None
    return lines, _source_declarations(lines)


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


def packet(name: str, model: str | None = None, golf: dict | None = None, worker: str | None = None) -> str:
    """Kickoff packet: task, exchange rates, source-derived context. The model is the orchestrating one."""
    from arena.context import render_packet

    return render_packet(name, model=model, golf=golf, worker=worker)


def _append(directory: Path, event: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    # The event's own keys win. A tool call id already on the row is not replaced by the environment.
    context = {key: value for key, value in call_context().items() if key not in event}
    fd = os.open(directory / "ledger.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        row = {"ts": time.time(), **context, **event}
        data = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        start = os.lseek(fd, 0, os.SEEK_END)
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return {
        "byte_start": start,
        "byte_end": start + len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "record": "ledger.jsonl",
    }


# Set by `arena run` to show a concise human line for a phase; the event itself only goes to the ledger.
RUNTIME_SINK: Callable[[Path, dict], None] | None = None


def _runtime_event(directory: Path, event: dict) -> None:
    """Persist an operator-facing lifecycle event; never prints raw JSON."""
    _append(directory, event)
    sink = RUNTIME_SINK
    if sink is not None:
        try:
            sink(directory, event)
        except Exception:  # a display problem must not break the run
            pass


def _evaluate(
    name: str,
    proof: str,
    mode: str,
    known: dict | None = None,
    lane: str = "model",
    request_class: str | None = None,
) -> dict:
    """`engine.evaluate`, sending background-lane work (full checks, cold verification) to the Lean session's
    background lane when the engine supports lanes, so it never takes a model worker."""
    kwargs = {}
    if lane != "model" and "lane" in inspect.signature(evaluate).parameters:
        kwargs["lane"] = lane
    if request_class is not None and "request_class" in inspect.signature(evaluate).parameters:
        kwargs["request_class"] = request_class
    return evaluate(name, proof, mode, known=known, **kwargs)


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
    return cached_jsonl_rows(file, dicts_only=False, lock_shared=True)


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


def init(name: str, run_id: str, extra: str = "", seed: Path | None = None, model: str | None = None) -> dict:
    """Start a run. With `seed`, the graph of that ended run replaces the reference-only start."""
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
    text = packet(name, model) + ("\nAdditional instructions:\n" + extra + "\n" if extra else "")
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
    if seed is not None:
        from arena.seed import carry_over

        carry_over(name, run_id, seed)
        return {
            "packet": str(directory / "packet.txt"),
            "shadow": str(shadow),
            "candidate_path": str(shadow / source_path(row)),
        }
    _append(
        directory,
        {
            "kind": "candidate",
            "candidate_id": reference_id,
            "parents": [],
            "hypothesis": "Pinned original reference proof",  # log: internal record # not-model-facing
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
    if not result.get("compat"):
        return result
    compat = {}
    for version, item in result["compat"].items():
        item = dict(item)  # a reused result's versions can be ledger rows shared with other readers
        raw = item.pop("raw_output", None)
        if raw:
            path = directory / "diagnostics" / f"{key[:16]}-{result.get('mode', 'eval')}-{version}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw + "\n")
            item["full_diagnostics_ref"] = str(path.relative_to(directory))
        compat[version] = item
    result["compat"] = compat
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


def _compact_ids(ids: list[str]) -> str:
    """`n2, n3, n4, n5, n9` as `n2–n5, n9`; ids that are not plain nK stay as they are."""
    parts: list[tuple[int, int] | str] = []
    for ref in ids:
        number = int(ref[1:]) if re.fullmatch(r"n[0-9]+", ref) else None
        if number is None:
            parts.append(ref)
        elif parts and isinstance(parts[-1], tuple) and parts[-1][1] == number - 1:
            parts[-1] = (parts[-1][0], number)
        else:
            parts.append((number, number))
    return ", ".join(
        part if isinstance(part, str) else f"n{part[0]}" if part[0] == part[1] else f"n{part[0]}–n{part[1]}"
        for part in parts
    )


def _update_id(history: list[dict], proof_id: str) -> str:
    """The graph id (nK) that model-facing updates use, falling back to the stored label."""
    try:
        return _graph_node_id(history, proof_id)
    except KeyError:
        return node_label(history, proof_id)


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
    raise ValueError(text.render("messages/errors.node_reference_invalid", reference=reference))


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
    raise ValueError(text.render("messages/errors.node_reference_invalid", reference=reference))


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
        raise ValueError(text.render("messages/errors.node_reference_invalid", reference=reference.strip()))
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


def worker_anchor_proof(run_id: str, history: list[dict]) -> str | None:
    """The proof id of the anchor node of the job this process works for; None for any other actor."""
    job_id = os.environ.get("ARENA_JOB_ID")
    if not job_id:
        return None
    from arena.orchestration import jobs

    snapshot = next((job for job in jobs(run_dir(run_id), [job_id])["jobs"] if job.get("job_id") == job_id), None)
    node = ((snapshot or {}).get("anchor") or {}).get("node")
    try:
        return resolve_node_ref(history, node) if node else None
    except (ValueError, KeyError):
        return None


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
    """Resolve a named parent. Graph ids, candidate numbers and probe ids stay a named relation."""
    if not reference or not isinstance(reference, str):
        return None
    try:
        return resolve_node_ref(history, reference)
    except ValueError:
        return None


def _proof_reader(directory: Path) -> Callable[[str], str | None]:
    """Read a stored proof by id, or None when the file is missing."""

    def read(ident: str) -> str | None:
        path = directory / "proofs" / f"{ident}.lean"
        return path.read_text() if path.is_file() else None

    return read


def _construction_payload(edge_type: str, sources: list, operation: dict | None, named_parent, exact: bool) -> dict:
    return {
        "type": edge_type,
        "from": list(sources),
        "operation": operation,
        "named_parent": named_parent,
        "exact": exact,
    }


def _construction_relation(
    edge: dict,
    operation: dict | None,
    named_parent,
    *,
    alternate: bool,
) -> dict | None:
    """Describe the submitted relation without changing its durable representation."""
    if alternate and operation is not None:
        edge_type = operation["type"]
        sources = list(operation.get("from") or [])
        operation_data = (
            {"hole": operation["hole"], "text": operation["text"],
             **({"experiment_id": operation["experiment_id"]} if operation.get("experiment_id") else {})}
            if edge_type == "filled_from"
            else {key: value for key, value in operation.items() if key != "type"}
        )
        exact = True
    elif alternate:
        # An unanchored repeat is still this actor's submitted attempt. Its text
        # does not prove that the caller repeated an earlier exact construction.
        return _construction_payload("root", [], None, named_parent, False)
    else:
        edge_type = edge.get("type")
        sources = list(edge.get("from") or [])
        operation_data = edge.get("operation")
        exact = bool(edge.get("exact"))
        named_parent = edge.get("named_parent")
    return _construction_payload(edge_type, sources, operation_data, named_parent, exact)


def _admit_graph_submission(
    directory: Path, proof_id: str, proof: str, operation: dict | None, *, duplicate: bool
) -> bool:
    """Authorize a graph attempt under the same stop boundary as candidate submission.

    The caller already holds the control lock. A candidate submitted with the same
    inputs stays admissible so its attempt can be recorded after that commit.
    """
    from arena.run_control import _submit_locked, actor_ids

    identity = actor_ids(directory.name)
    attempt = _submission_attempt(directory, proof_id, proof, operation)
    if attempt is None:
        attempt = {
            "operation_id": uuid.uuid4().hex,
            "run_id": directory.name,
            "actor_id": identity["actor_id"],
            "session_id": identity["session_id"],
            "proof_id": proof_id,
            "proof_sha256": hashlib.sha256(proof.encode()).hexdigest(),
            "authorization": "duplicate" if duplicate else "candidate",
            "inputs": operation,
        }
    decision = _submit_locked(directory, attempt)
    return bool(decision["ok"])


def _record_construction(
    directory: Path,
    proof_id: str,
    edge: dict,
    operation: dict | None,
    named_parent,
    *,
    alternate: bool,
) -> None:
    """Record an attempt. A different exact construction also records a derivation."""
    import uuid

    from arena.run_control import _apply_locked, actor_ids, construction_digest, input_roles, published_history

    payload = _construction_relation(edge, operation, named_parent, alternate=alternate)
    if payload is None:
        return
    edge_type = payload["type"]
    sources = payload["from"]
    operation_data = payload["operation"]
    digest = construction_digest(payload)
    if alternate:
        prior = {
            construction_digest(
                _construction_payload(
                    edge.get("type"),
                    edge.get("from") or [],
                    edge.get("operation"),
                    edge.get("named_parent"),
                    bool(edge.get("exact")),
                )
            )
        }
        for event in published_history(directory, events(directory)):
            if event.get("kind") == "derivation" and (event.get("proof_id") or event.get("candidate_id")) == proof_id:
                data = event.get("data") or {}
                if data.get("construction_digest"):
                    prior.add(data["construction_digest"])
        # Only an exact construction is lineage; an unanchored repeat is an attempt alone.
        fresh_derivation = payload["exact"] and digest not in prior
    else:
        fresh_derivation = False
    identity = actor_ids(directory.name)
    artifact = directory / "proofs" / f"{proof_id}.lean"
    artifact_ref = {
        "path": f"proofs/{proof_id}.lean",
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest() if artifact.is_file() else None,
    }
    if not artifact.is_file():
        artifact_ref["missing"] = True
    run_id = directory.name

    def mutate(ctx):
        data = {
            "relation": "exact" if payload["exact"] else edge_type,
            "operation": operation_data,
            "inputs": input_roles({"type": edge_type, "from": sources, **(operation_data or {})}),
            "named_parent": payload["named_parent"],
            "artifact": artifact_ref,
            "construction_digest": digest,
            "tool_call_id": identity.get("tool_call_id"),
            "missing": identity["missing"],
        }
        ctx.append_ledger(
            {
                "kind": "attempt",
                "proof_id": proof_id,
                "candidate_id": proof_id,
                "data": data,
                **({"generation": identity["generation"]} if identity.get("generation") else {}),
            }
        )
        if fresh_derivation:
            ctx.append_ledger(
                {
                    "kind": "derivation",
                    "proof_id": proof_id,
                    "candidate_id": proof_id,
                    "parents": sources,
                    "data": data,
                    **({"generation": identity["generation"]} if identity.get("generation") else {}),
                }
            )
        return ctx.evidence

    receipt = _apply_locked(
        directory,
        {
            "operation_id": uuid.uuid4().hex,
            "kind": "attempt",
            "arguments": payload,
            "run_id": run_id,
            "actor_id": identity["actor_id"],
            "session_id": identity["session_id"],
            **{key: identity[key] for key in ("job_id", "activation_id") if identity.get(key)},
        },
        mutate,
    )
    receipts = _OPERATION_RECEIPTS.get()
    if receipts is not None:
        receipts.append(receipt)


def _file_node(
    directory: Path,
    history: list[dict],
    proof_id: str,
    proof: str,
    named_parent: str | None = None,
    operation: dict | None = None,
    projection_out: list[Graph] | None = None,
) -> tuple[dict, bool]:
    """Append exactly one graph edge per proof id under the run's graph lock.

    The control lock is held outside the graph lock. A second construction appends
    an attempt and, when its inputs differ, a derivation. It does not rewrite the edge.
    """
    from arena.run_control import control_lock

    directory.mkdir(parents=True, exist_ok=True)
    with control_lock(directory), (directory / "graph.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        history = _published_events(directory)
        existing = next(
            (event for event in history if event.get("kind") == "edge" and event.get("proof_id") == proof_id), None
        )
        if existing:
            if _admit_graph_submission(directory, proof_id, proof, operation, duplicate=True):
                _record_construction(
                    directory,
                    proof_id,
                    existing,
                    operation,
                    named_parent,
                    alternate=True,
                )
            if projection_out is not None:
                projection_out.append(
                    Graph.from_history(
                        events(directory),
                        _proof_reader(directory),
                        committed_operations=committed_operation_ids(directory),
                    )
                )
            return existing, False
        read = _proof_reader(directory)
        graph = Graph.from_history(history, read, committed_operations=committed_operation_ids(directory))
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
                {"hole": operation["hole"], "text": operation["text"],
                 **({"experiment_id": operation["experiment_id"]} if operation.get("experiment_id") else {})}
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
        if not _admit_graph_submission(directory, proof_id, proof, operation, duplicate=False):
            return {**event, "refused": "run_stopped"}, False
        _append(directory, event)
        _record_construction(directory, proof_id, event, operation, named_parent, alternate=False)
        earlier: dict[str, list[dict]] = {}
        graph_nodes = {node.proof_id: node for node in graph.nodes}
        for node in graph.nodes:
            if node.route is not None:
                # Only closed proofs are members; drafts and sketches keep their route name but are never matched against.
                members = earlier.setdefault(node.route, [])
                if node.status == "closed":
                    members.append(node.signature)
        parent = sources[0] if sources else None
        parent_node = graph_nodes.get(parent)
        compile_result = routes.attempt_results(history).get(proof_id, (None, None))[1]
        if routes.is_draft(proof) or (compile_result is not None and not goalstate.closed(compile_result)):
            # Sketches, test drafts and proofs that did not compile never open a route or become members; they carry
            # their base's route.
            assignment = routes.attach(earlier, routes.signature(proof), parent_node.route if parent_node else None)
        else:
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
            projection_out.append(
                Graph.from_history(events(directory), read, committed_operations=committed_operation_ids(directory))
            )
        return event, True


def _settle_focus(
    directory: Path, proof_ids: list[str], graph: Graph | None = None, *, actor_local: bool = False
) -> Graph:
    history = events(directory)
    graph = graph or Graph.from_history(
        history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )
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
    if actor_local:
        from arena.reply import set_actor_focus

        set_actor_focus(directory.name, winner.proof_id)
    if winner.proof_id != graph.focus:
        _append(directory, {"kind": "focus", "proof_id": winner.proof_id, "reason": "batch_best"})
        graph.focus = winner.proof_id
    return graph


def _check_stall(directory: Path, graph: Graph, newly_filed: set[str]) -> None:
    raw_threshold = os.environ.get("ARENA_STALL_M", "8")
    try:
        threshold = int(raw_threshold)
    except ValueError as error:
        raise ValueError(text.render("messages/errors.stall_threshold")) from error
    mode = os.environ.get("ARENA_STALL_TARGET", "best_other_cell")
    if mode not in ("best_other_cell", "least_visited", "map_only"):
        raise ValueError(text.render("messages/errors.stall_target", mode=mode))
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


def _kickoff_within(sections: list[tuple[str, str]], limit: int) -> str:
    """The kickoff packet fitted to `limit` characters, shedding entries in the packet's own priority order."""
    from arena import context

    parts = []
    for title, content in sections:
        head = f"{title}\n"
        if title and content.startswith(head):
            lines = content[len(head) :].split("\n")
            if title == context.template("packet/sections.titles.goals").strip():
                # Restore the atomic per-step entries flattened by packet serialization.
                goal_pattern = re.escape(context.template("packet/sections.fixed.goal"))
                for field, pattern in (("step", r"s\d+"), ("line", r"\d+"), ("text", ".*")):
                    goal_pattern = goal_pattern.replace(re.escape("{" + field + "}"), pattern)
                coverage_prefix = context.template("packet/sections.fixed.goal_coverage").split("{")[0]
                entries: list[str] = []
                for line in lines:
                    if not entries or re.fullmatch(goal_pattern, line) or line.startswith(coverage_prefix):
                        entries.append(line)
                    else:
                        entries[-1] += "\n" + line
                lines = entries
            parts.append((title, lines))
        else:
            parts.append(("", content.split("\n")))
    fitted = context._fit_sections(parts, limit)
    return "\n\n".join((f"{title}\n" if title else "") + "\n".join(body) for title, body in fitted) + "\n"



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
                "origin": item.get("origin", "model"),
                "parents": item.get("parents", []),
                "job": item.get("job_id"),
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
    first, last, origin = recent[0]["n"], recent[-1]["n"], by_id[root]["n"]
    score_suffix = f" of {base}." if base is not None else "."
    return f"The last {window} candidates (#{first}-#{last}) all descend from #{origin} and none improved on its score{score_suffix}"  # log: operator state # not-model-facing


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
            "cached",
            "candidate_path",
            "start_line",
            "end_line",
            "error",
            "notes",
            "full_check",
            "advisory",
            "price_row",
            "scored",
            "contains_sorry",
            "goals",
        )
        if result.get(key) not in (None, [], "")
    }
    # `ok` says the tool ran; `compiled` says whether the draft compiled. On a failed compile the
    # heartbeat is only the work done before the error, not a cost of the draft.
    failed = any(not info.get("passed") for info in (result.get("compat") or {}).values())
    view["outcome"] = _verification_outcome(result)
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
        for key in ("heartbeats", "diagnostics", "full_diagnostics_ref", "error", "outcome", "cause",
                    "retryable", "exit_code", "timeout"):
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


def _verification_outcome(result: dict) -> str:
    """Separate an evaluated proof from checks that could not establish an outcome."""
    compat = result.get("compat") or {}
    if result.get("lean_unavailable") or result.get("timeout") or not compat:
        if result.get("outcome") == "proof_error":
            return "proof_error"
        return "inconclusive"
    if result.get("ok") is not False and all(info.get("passed") is True for info in compat.values()):
        return "passed"
    # A completed Lean failure is proof evidence; a timeout, signal, or absent
    # measurement is not. Another version's inconclusive check cannot erase it.
    if any(
        info.get("passed") is False
        and info.get("exit_code") == 1
        and not info.get("lean_unavailable")
        and not info.get("timeout")
        and info.get("outcome") != "inconclusive"
        and info.get("cause") not in {"context", "measurement", "resource_denial", "toolchain_unavailable", "worker_crash"}
        for info in compat.values()
    ):
        return "proof_error"
    return "inconclusive"


def _verification_owners(directory: Path, proof_id: str) -> list[dict]:
    """Join exact proof attempts to their durable worker assignment, never their parents."""
    from arena.run_control import published_history

    history = published_history(directory, events(directory))
    assignments = [item for item in history if item.get("type") == "delegation"]
    owners = {}
    for attempt in history:
        if attempt.get("kind") != "attempt" or (attempt.get("proof_id") or attempt.get("candidate_id")) != proof_id:
            continue
        for assignment in assignments:
            if (attempt.get("actor_id"), attempt.get("session_id")) != (
                assignment.get("worker_actor_id"), assignment.get("worker_session_id"),
            ):
                continue
            job_id = assignment["job_id"]
            owner = owners.setdefault(job_id, {
                "job_id": job_id, "actor_id": attempt["actor_id"], "session_id": attempt["session_id"],
                "run_id": assignment["run_id"], "proof_id": proof_id, "attempt_ids": [],
            })
            if attempt.get("event_id") and attempt["event_id"] not in owner["attempt_ids"]:
                owner["attempt_ids"].append(attempt["event_id"])
    return list(owners.values())


def _queue_full_check(directory: Path, run_id: str, proof_id: str) -> list[dict]:
    from arena import orchestration

    with _candidate_lock(directory, proof_id):
        key = _evaluation_key(proof_id, "full", problem(events(directory)[0]["theorem"]))
        rows = [item for item in orchestration._history(directory)
                if item.get("type") == "verification" and item.get("proof_id") == proof_id
                and item.get("evaluation_id") == key]
        latest = {}
        for item in rows:
            execution = item.get("check_id") or f"legacy:{item['job_id']}:{key}"
            latest[(item["job_id"], execution)] = {**item, "check_id": execution}
        pending = [item for item in latest.values() if item["state"] in {"queued", "running"}]
        check_id = pending[0]["check_id"] if pending else uuid.uuid4().hex
        checks = [{**owner, "check_id": check_id, "evaluation_id": key}
                  for owner in _verification_owners(directory, proof_id) if owner["run_id"] == run_id]
        for check in checks:
            if not any(item["job_id"] == check["job_id"] for item in pending):
                orchestration.note_verification(directory, **check, state="queued")
        return checks


@_submission_scope
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
    lane: str = "model",
    trigger: str = "model",
    precomputed: dict | None = None,
    operation: dict | None = None,
    named_parent: str | object | None = _NAMED_PARENT_UNSET,
    verification_checks: list[dict] | None = None,
) -> dict:
    """Record a candidate and its evaluation. `precomputed` is a result the caller already
    compiled for this exact proof and mode; `trigger` says whether the model or the
    harness asked for it."""
    if mode not in ("fast", "full"):
        raise ValueError(text.render("messages/errors.evaluation_mode"))
    directory = run_dir(run_id)
    if lane == "model" and trigger == "model":
        _refuse_if_tripped(directory)
    record_started = time.monotonic()
    row = problem(name)
    # Forbidden constructs and statement edits are rejected before anything is recorded,
    # so `sorry` drafts can never become candidates.
    validate_proof(row, proof)
    candidate_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    notes: list[str] = []
    lock_wait_started = time.monotonic()
    lean_lock_wait_seconds = 0.0
    with _candidate_lock(directory, candidate_id):
        lock_wait_seconds = round(time.monotonic() - lock_wait_started, 3)
        history = _published_events(directory)
        if not history or history[0].get("theorem") != name:
            raise ValueError(text.render("messages/errors.run_theorem_mismatch"))
        if history[0].get("versions") and history[0]["versions"] != [list(pair) for pair in versions(row)]:
            raise ValueError(text.render("messages/errors.source_versions_changed"))
        known = set(_candidate_ids(history))
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
        hypothesis_ref = hypothesis if isinstance(hypothesis, str) and hypothesis.startswith("hyp:") else None
        if hypothesis_ref:
            hypothesis = ""
        _snapshot(directory, candidate_id, proof)
        if candidate_id not in known:
            key = _evaluation_key(candidate_id, mode, row)
            candidate = {
                "kind": "candidate",
                "candidate_id": candidate_id,
                "parents": lineage,
                "hypothesis": hypothesis,
                "hypothesis_ref": hypothesis_ref,
                "origin": origin,
                "merge": merge,
                "source_versions": versions(row),
                "evaluator_sha256": _evaluator_sha(),
            }
            prior_admission = _submission_attempt(directory, candidate_id, proof, operation)
            attempt = _submit_proof(
                directory, candidate_id, proof, operation,
                evaluation={"mode": mode, "key": key, "state": "queued"}, candidate=candidate,
            )
            if prior_admission is not None and not any(
                event.get("kind") == "candidate" and event.get("candidate_id") == candidate_id
                for event in _published_events(directory)
            ):
                # A complete probe was admitted before its result was known. Its
                # successful outcome can publish the candidate under that receipt.
                _append_submitted(directory, attempt, candidate)
            history = _published_events(directory)
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
                from arena.run_control import actor_ids, submit_candidate

                identity = actor_ids(directory.name)
                submit_candidate(
                    directory,
                    {
                        "operation_id": uuid.uuid4().hex,
                        "run_id": run_id,
                        "actor_id": identity["actor_id"],
                        "session_id": identity["session_id"],
                        "proof_id": candidate_id,
                        "proof_sha256": hashlib.sha256(proof.encode()).hexdigest(),
                        "authorization": "duplicate",
                        "inputs": {"parents": explicit, "origin": origin},
                        "ledger_events": [{"kind": "derivation", "candidate_id": candidate_id,
                                           "parents": explicit, "origin": origin, "merge": merge}],
                    },
                )
        key = _evaluation_key(candidate_id, mode, row)
        if candidate_id in known and _SELECT_COMPILED.get():
            from arena.run_control import SubmissionRefused

            # Already-published candidates can finish verification even if this
            # fresh selection is refused; no new construction is authorized.
            with suppress(SubmissionRefused):
                _submit_proof(directory, candidate_id, proof, operation, evaluation={
                    "mode": mode, "key": key, "state": "queued",
                })
        prior = next(
            (item for item in reversed(history) if item.get("kind") == "evaluation" and item["key"] == key), None
        )
        if prior and _verification_outcome(prior["result"]) == "inconclusive":
            prior = None
        checks = list(verification_checks or [])
        if not prior and not checks and trigger != "auto":
            job_id = operation.get("job_id") if isinstance(operation, dict) else None
            job_id = job_id or os.environ.get("ARENA_JOB_ID")
            if job_id:
                checks = [{"job_id": job_id, "check_id": uuid.uuid4().hex, "evaluation_id": key,
                           "proof_id": candidate_id, "run_id": run_id,
                           "actor_id": os.environ.get("ARENA_ACTOR_ID") or "sol",
                           "session_id": os.environ.get("ARENA_SESSION_ID") or run_id}]
        if checks:
            from arena import orchestration

            for check in checks:
                orchestration.note_verification(directory, **check, state="running")
        try:
            if prior:
                result = json.loads(json.dumps(prior["result"]))
            elif precomputed is not None:
                result = precomputed
            else:
                try:
                    from arena.run_control import submission_barrier

                    submission_barrier("during_lean", directory)
                    lean_lock_started = time.monotonic()
                    with lean_lock(directory, lane):
                        lean_lock_wait_seconds = round(time.monotonic() - lean_lock_started, 3)
                        result = _evaluate(
                            name,
                            proof,
                            mode,
                            known=_compiled_versions(history, candidate_id, row) if mode == "full" else None,
                            lane=lane,
                            request_class=(
                                ("full_check" if mode == "full" else "opportunistic")
                                if origin in {"assembly", "golf"} or trigger == "golf"
                                # a harness-submitted check is promising; a worker's own tool call stays its own class
                                else "full_check"
                                if trigger == "auto"
                                else actor_request_class()
                            ),
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
                result.setdefault("harness_timing", {})
                result["harness_timing"].update(
                    {"candidate_lock_wait_seconds": lock_wait_seconds, "lean_lock_wait_seconds": lean_lock_wait_seconds}
                )
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
        except BaseException:
            for check in checks:
                orchestration.note_verification(directory, **check, state="inconclusive")
            raise
        for check in checks:
            orchestration.note_verification(directory, **check, state=_verification_outcome(result))
    if lane == "model" and trigger == "model" and not prior:
        _check_breaker(directory)
    location = materialize(name, run_id, proof) if materialize_live and result.get("tokens") is not None else {}
    if location:
        _append(directory, {"kind": "current", "candidate_id": candidate_id})
    filing_history = _published_events(directory)
    in_batch, _ = _BATCH_FOCUS.get()
    projection_out: list[Graph] = []
    _, newly_filed = _file_node(
        directory,
        filing_history,
        candidate_id,
        proof,
        _named_parent_id(
            filing_history,
            (parents or [None])[0] if named_parent is _NAMED_PARENT_UNSET else named_parent,
        ),
        operation,
        None if in_batch else projection_out,
    )
    if not in_batch:
        graph = _settle_focus(
            directory,
            [candidate_id],
            projection_out[0] if projection_out else None,
            actor_local=origin == "model" and trigger == "model",
        )
        _check_stall(directory, graph, {candidate_id} if newly_filed else set())
    history = _published_events(directory)
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
    reply = {
        **result,
        "candidate_id": candidate_id,
        "candidate": _label(history, candidate_id),
        "node_number": _candidate_ids(history).index(candidate_id) + 1,
        "cached": prior is not None,
        "notes": notes,
        "best_so_far": best_line,
        "advisory": _advisory(rows),
        **location,
    }
    if me and (result.get("metrics") or {}).get("axes") and not re.search(r"\bsorry\b", proof):
        projection = (
            projection_out[0]
            if projection_out
            else Graph.from_history(
                history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
            )
        )
        node = next((item for item in projection.nodes if item.proof_id == candidate_id), None)
        if node is not None and node.score is not None:
            parent_ids = (node.edge or {}).get("from") or []
            by_id = {item.proof_id: item for item in projection.nodes}
            parent_node = by_id.get(parent_ids[0]) if parent_ids else None
            scored = [item for item in projection.nodes if item.score is not None and item.proof_id != node.proof_id]
            best_node = max(scored, key=lambda item: item.score) if scored else None
            cached_profiles = _cached_profiles(name, history)
            old_profile = cached_profiles.get(parent_node.proof_id) if parent_node else None
            new_profile = cached_profiles.get(node.proof_id)
            old_hb = _step_heartbeats(parent_node, old_profile)
            new_hb = _step_heartbeats(node, new_profile)
            changes = changed_steps(parent_node.steps, node.steps, old_hb, new_hb) if parent_node else []
            row = build_price_row(
                node,
                parent_node,
                best_node,
                changed_lines(parent_node.proof_text, node.proof_text)
                if parent_node
                else len(node.proof_text.splitlines()),
                changes,
            )
            # The model sees graph ids (nK) everywhere else; stored labels (#k, pK) stay internal.
            row["label"] = _update_id(history, node.proof_id)
            row["parent_label"] = _update_id(history, parent_node.proof_id) if parent_node else None
            total_versions = len(versions(problem(name)))
            row["versions"] = _versions_text(node.versions, total_versions)
            reply["price_row"] = render_price_row(row, parent_node is None, parent_node is best_node)
    if not prior:
        _append(
            directory,
            {
                "kind": "evaluation_span",
                "candidate_id": candidate_id,
                "mode": mode,
                "seconds": round(time.monotonic() - record_started, 3),
                "materialized": bool(location),
                "filed": newly_filed,
            },
        )
    if (mode == "fast" and origin != "reference" and _verification_outcome(result) == "passed"
            and any(job["id"] == candidate_id for job in _autocheck_jobs(_summaries(events(directory))))):
        _queue_full_check(directory, run_id, candidate_id)
    return reply


def evaluate_request(
    name: str,
    run_id: str,
    proof: str,
    mode: str = "fast",
    parents: list[str] | None = None,
    hypothesis: str = "",
    operation: dict | None = None,
    named_parent: str | object | None = _NAMED_PARENT_UNSET,
) -> dict:
    """Evaluate one complete proof and return its scored view."""
    result = record_evaluation(
        name, run_id, proof, mode, parents, hypothesis, operation=operation, named_parent=named_parent
    )
    return _model_view({**result, "full_check": _full_check_status(events(run_dir(run_id)), result["candidate_id"])})


def _full_check_status(history: list[dict], candidate_id: str) -> str | None:
    """What the model needs to know about the other toolchains, without asking for it."""
    rows = {r["id"]: r for r in _summaries(history)}
    row = rows.get(candidate_id)
    if not row or row["status"] == "fail":
        return None
    total = len(history[0].get("versions") or [1])
    done = next((e for e in reversed(row["evaluations"]) if e["mode"] == "full"), None)
    if done:
        return _check_text(_update_id(history, candidate_id), done["result"], total)
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
    from arena.run_control import submission_barrier

    submission_barrier("during_lean", None)
    complete = not _has_hole(row, proof)
    try:
        return evaluate(name, proof, "fast" if complete else "probe", request_class=actor_request_class())
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
    history = _published_events(directory)
    row = problem(name)
    known = set(_candidate_ids(history)) | {item["proof_id"] for item in history if item.get("kind") == "probe"}
    pending: dict[str, str] = {}
    for draft in drafts:
        try:
            proof = normalize_draft(name, draft)
            validate_proof(row, proof, allow_sorry=True)
        except ValueError:
            continue
        proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
        if proof_id not in known:
            from arena.run_control import SubmissionRefused

            try:
                _snapshot(directory, proof_id, proof)
                check_mode = "probe" if _has_hole(row, proof) else "fast"
                _submit_proof(directory, proof_id, proof, None, evaluation={
                    "mode": check_mode, "key": _evaluation_key(proof_id, check_mode, row), "state": "queued",
                })
            except SubmissionRefused:
                continue
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


@_submission_scope
def probe(
    name: str,
    run_id: str,
    proof: str,
    parent: str | None = None,
    operation: dict | None = None,
    mode: str = "fast",
    note: str | None = None,
    named_parent: str | object | None = _NAMED_PARENT_UNSET,
) -> dict:
    """Compile a draft (sorry allowed) in the shadow project without creating a candidate."""
    proof = normalize_draft(name, proof)
    directory = run_dir(run_id)
    _refuse_if_tripped(directory)
    history = _published_events(directory)
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
        return evaluate_request(
            name,
            run_id,
            proof,
            mode,
            parents=[parent] if parent else None,
            operation=operation,
            named_parent=named_parent,
        )
    earlier = next(
        (item for item in reversed(history) if item.get("kind") == "probe" and item["proof_id"] == proof_id), None
    )
    newly_filed: set[str] = set()
    if earlier:
        result = earlier["result"]
    else:
        validate_proof(row, proof, allow_sorry=True)
        complete = not _has_hole(row, proof)
        _snapshot(directory, proof_id, proof)
        check_mode = "fast" if complete else "probe"
        attempt = _submit_proof(directory, proof_id, proof, operation, evaluation={
            "mode": check_mode, "key": _evaluation_key(proof_id, check_mode, row), "state": "queued",
        })
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
                hypothesis=note or "",
                precomputed=result if mode == "fast" else None,
                operation=operation,
                named_parent=named_parent,
            )
            view = _model_view(
                {**recorded, "full_check": _full_check_status(events(directory), recorded["candidate_id"])}
            )
            view.setdefault("notes", []).append(
                f"complete draft compiled, recorded as candidate {recorded['candidate']}"  # log: internal record # not-model-facing
            )
            return view
        result = {**result, "mode": "probe", "scored": False}
        _externalize_output(directory, proof_id, result)
        _snapshot(directory, proof_id, proof)
        _append_submitted(
            directory,
            attempt,
            {
                "kind": "probe",
                "proof_id": proof_id,
                "evaluation_id": _evaluation_key(proof_id, "probe", row),
                "parent": parent_id,
                "named_parent": None if named_parent is _NAMED_PARENT_UNSET else named_parent,
                "note": note,
                "result": result,
            },
        )
        filing_history = _published_events(directory)
        in_batch, _ = _BATCH_FOCUS.get()
        projection_out: list[Graph] = []
        _, new_node = _file_node(
            directory,
            filing_history,
            proof_id,
            proof,
            _named_parent_id(history, parent if named_parent is _NAMED_PARENT_UNSET else named_parent),
            operation,
            None if in_batch else projection_out,
        )
        if new_node:
            newly_filed.add(proof_id)
        _check_breaker(directory)
        # A draft (holes, errors or a failed compile) never opens a route, so it is not queued for extraction.
    if earlier:
        # A repeat leaves its own row, so the reply can say how often this text has been tried.
        _append(directory, {"kind": "repeat", "proof_id": proof_id})
        filing_history = _published_events(directory)
        in_batch, _ = _BATCH_FOCUS.get()
        projection_out = []
        _, new_node = _file_node(
            directory,
            filing_history,
            proof_id,
            proof,
            _named_parent_id(history, parent if named_parent is _NAMED_PARENT_UNSET else named_parent),
            operation,
            None if in_batch else projection_out,
        )
        if new_node:
            newly_filed.add(proof_id)
    in_batch, _ = _BATCH_FOCUS.get()
    if not in_batch:
        graph = _settle_focus(directory, [proof_id], projection_out[0] if projection_out else None, actor_local=True)
        _check_stall(directory, graph, newly_filed)
    location = materialize(name, run_id, proof) if result.get("tokens") is not None else {}
    label = _probe_numbers(events(directory))[proof_id]
    return _model_view(
        {
            **result,
            "probe": label,
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


@_submission_scope
def probe_batch(
    name: str,
    run_id: str,
    drafts: list[str],
    parent: str | None = None,
    note: str | None = None,
    named_parent: str | object | None = _NAMED_PARENT_UNSET,
) -> dict:
    """Probe one to four drafts in order, keeping their parent fixed across promotions."""
    if not isinstance(drafts, list) or not 1 <= len(drafts) <= MAX_DRAFTS:
        raise ValueError(text.render("messages/errors.draft_limit"))
    history = events(run_dir(run_id))
    from arena.reply import actor_focus_proof, set_actor_focus

    actor_focus = actor_focus_proof(run_id)
    if actor_focus is None and (anchored := worker_anchor_proof(run_id, history)):
        set_actor_focus(run_id, anchored)  # a worker files under its job's anchor, never the run's moving focus
        actor_focus = anchored
    fixed_parent = resolve_parent_ref(history, parent) if parent else actor_focus or _current(history)
    starting_focus = actor_focus or next(
        (item["proof_id"] for item in reversed(history) if item.get("kind") == "focus"), None
    )
    if actor_focus is None and starting_focus is not None:
        set_actor_focus(run_id, starting_focus)
    outcomes = []
    token = _PRECOMPILED.set(_compile_probes(name, run_dir(run_id), drafts) if len(drafts) > 1 else {})
    focus_token = _BATCH_FOCUS.set((True, starting_focus))
    newly_filed: set[str] = set()
    filed_token = _BATCH_NEWLY_FILED.set(newly_filed)
    try:
        for index, draft in enumerate(drafts, 1):
            try:
                outcome = probe(name, run_id, draft, fixed_parent, note=note, named_parent=named_parent)
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
    graph = _settle_focus(directory, filed, actor_local=True)
    _check_stall(directory, graph, newly_filed)
    return {"ok": True, "drafts": outcomes}


@_submission_scope
def compile_operation(
    name: str,
    run_id: str,
    operation: dict,
    mode: str = "fast",
    note: str | None = None,
    named_parent: str | object | None = _NAMED_PARENT_UNSET,
) -> dict:
    """Build, compile and file one operation-derived proof."""
    if mode not in ("fast", "full"):
        raise ValueError(text.render("messages/errors.evaluation_mode"))
    directory = run_dir(run_id)
    from arena.run_control import read_state, submission_barrier

    submission_barrier("before_construction", directory)
    if read_state(directory).get("stopped"):
        from arena.run_control import SubmissionRefused

        raise SubmissionRefused()
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
        projection = Graph.from_history(
            history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
        )
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

    if operation.get("experiment_id"):
        edge_operation["experiment_id"] = operation["experiment_id"]
    proof = normalize_draft(name, proof)
    receipts: list[dict] = []
    token = _OPERATION_RECEIPTS.set(receipts)
    failure = None
    result = {}
    try:
        result = probe(
            name,
            run_id,
            proof,
            operation=edge_operation,
            mode=mode,
            note=note,
            named_parent=named_parent,
        )
    except Exception as error:
        failure = error
    finally:
        _OPERATION_RECEIPTS.reset(token)
    proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    from arena.run_control import published_history

    history = published_history(directory, events(directory))
    event_ids = {ref["event_id"] for receipt in receipts for ref in receipt.get("evidence_refs", [])}
    attempt = next((event for event in history if event.get("kind") == "attempt"
                    and event.get("event_id") in event_ids and event.get("proof_id") == proof_id), None)
    key = _evaluation_key(proof_id, mode, problem(name))
    evaluation = next((event for event in reversed(history) if event.get("kind") == "evaluation"
                       and event.get("key") == key), None)
    if evaluation is None:
        evaluation = next((event for event in reversed(history) if event.get("kind") == "probe"
                           and event.get("proof_id") == proof_id), None)
    full_key = _evaluation_key(proof_id, "full", problem(name))
    full = next((event for event in reversed(history) if event.get("kind") == "evaluation"
                 and event.get("key") == full_key), None)
    construction = (attempt or {}).get("data") or {}
    derivation = next((event for event in history if event.get("kind") == "derivation"
                       and event.get("proof_id") == proof_id
                       and (event.get("data") or {}).get("construction_digest") == construction.get("construction_digest")), None)
    evidence = {
        **result,
        "node": _graph_node_id(history, proof_id) if attempt else None,
        "proof_id": proof_id,
        "complete": not _has_hole(problem(name), proof),
        "edge": {"type": edge_operation["type"], "from": edge_operation["from"],
                 "operation": construction.get("operation"),
                 "construction_digest": construction.get("construction_digest")},
        "attempt_id": (attempt or {}).get("event_id"),
        "derivation_id": (derivation or {}).get("event_id"),
        "construction_operation_id": (attempt or {}).get("operation_id"),
        "evaluation_id": (evaluation or {}).get("key") or (evaluation or {}).get("evaluation_id"),
        "evaluation_ref": None if evaluation is None else {
            "record": "ledger.jsonl",
            "row": next(index for index, event in enumerate(events(directory), 1) if event == evaluation),
        },
        "raw_result": (evaluation or {}).get("result") or {},
        "full_result": (full or {}).get("result"),
    }
    if failure is not None:
        failure.operation_evidence = evidence
        raise failure
    return evidence


def _cached_profiles(name: str, history: list[dict]) -> dict[str, dict]:
    del name
    return {
        event["proof_id"]: event["result"]
        for event in history
        if event.get("kind") == "profile" and isinstance(event.get("result"), dict)
    }


def _step_heartbeats(node: Node | None, profile_result: dict | None) -> dict[str, int] | None:
    if node is None or profile_result is None:
        return None
    return {
        step.id: entry["hb"]
        for step in node.steps
        for entry in (profile_result.get("entries") or [])
        if entry.get("depth") == 0 and entry.get("proof_line") == step.first_line and entry.get("hb") is not None
    }


def _versions_text(statuses: dict[str, bool], total: int) -> str:
    checked = len(statuses)
    passed = sum(bool(value) for value in statuses.values())
    if checked == total:
        return text.render("replies/price-row.versions_full", passed=passed, total=total)
    return text.render("replies/price-row.versions_pending", checked=checked, total=total)


def _versions_total(statuses: dict[str, bool], total: int) -> str:
    return f"{sum(bool(value) for value in statuses.values())}/{total}"


def _price_change_text(changes: list[dict]) -> str:
    values = []
    for change in changes:
        label = ",".join(change["ids"]) or "—"
        value = f"{label} ({change['old_tokens']}→{change['new_tokens']} tok"
        if "old_hb" in change:
            value += f", {fmt_hb(change['old_hb'])}→{fmt_hb(change['new_hb'])} hb"
        values.append(value + ")")
    return "; ".join(values)


def _comparison(vs_parent, vs_best, parent_label: str, parent_is_best: bool, with_names: bool = False) -> str:
    """The parenthesis after a value: its change against the parent and against the best node, only the known
    ones; nothing at all when neither is known."""
    parts = []
    if vs_parent is not None:
        delta = fmt_signed(vs_parent)
        parts.append(text.render("replies/price-row.vs_node", delta=delta, node=parent_label) if with_names else delta)
    if not parent_is_best and vs_best is not None:
        parts.append(text.render("replies/price-row.vs_best", delta=fmt_signed(vs_best)))
    return text.render("replies/price-row.parenthesis", parts=", ".join(parts)) if parts else ""


def render_price_row(row: dict, root: bool = False, parent_is_best: bool = False) -> str:
    if root:
        return text.render(
            "replies/price-row.row_root",
            label=row["label"],
            tokens=row["tokens"],
            hb=fmt_hb(row["hb"]),
            versions=row["versions"],
        )
    tokens_part = _comparison(
        row["tokens_vs_parent"], row["tokens_vs_best"], row["parent_label"], parent_is_best, with_names=True
    )
    hb_part = _comparison(row["hb_vs_parent"], row["hb_vs_best"], row["parent_label"], parent_is_best)
    score_part = "n/a" if row["score_vs_best"] is None else f"{row['score_vs_best']:+.1f} vs best"
    rendered = [
        text.render(
            "replies/price-row",
            label=row["label"],
            parent_label=row["parent_label"],
            lines=row["lines"],
            tokens=row["tokens"],
            tokens_part=tokens_part,
            hb=fmt_hb(row["hb"]),
            hb_part=hb_part,
            versions=row["versions"],
            score_part=score_part,
        )
    ]
    if row["changed"]:
        rendered.append(text.render("replies/price-row.changed", changes=_price_change_text(row["changed"])))
    return "\n".join(rendered)


def render_price_table(
    table: dict,
    proof: str = "",
    profile: dict | None = None,
    proof_id: str = "reference",
    node_label: str = "n1",
) -> str:
    """Structural overview. Totals are not a step row. pts_if_gone stays off this text."""
    from arena.evidence import cost_evidence, render_cost_overview

    total = table.get("total") or {}
    evidence = cost_evidence(
        proof,
        profile,
        proof_id=proof_id,
        total_tokens=total.get("tokens"),
        published_score=total.get("proxy"),
        versions=total.get("versions"),
        local_hb=total.get("heartbeats"),
        node_label=node_label,
    )
    return "\n".join(render_cost_overview(table, evidence))


def _reference_tokens(name: str, node: Node) -> int:
    """The packet's token count for the reference (proof body only); other unscored nodes count their text."""
    if node.origin == "reference":
        length = problem(name).get("proof_length")
        if isinstance(length, int):
            return length
    return snippet_tokens(node.proof_text)


def _table_for_node(name: str, node: Node, profiles: dict[str, dict], price_rates: dict, total_versions: int) -> dict:
    profile_result = profiles.get(node.proof_id)
    if profile_result is None and node.origin == "reference":
        from arena.context import reference_profile

        try:
            profile_result = reference_profile(name, cache_only=True)
        except (ValueError, OSError):
            profile_result = None
    table = step_table(
        node.proof_text,
        profile_result,
        price_rates,
        _reference_tokens(name, node) if node.origin == "reference" else (
            node.tokens if node.tokens is not None else _reference_tokens(name, node)
        ),
        node.heartbeats,
        _versions_total(node.versions, total_versions),
    )
    table["total"]["proxy"] = node.score
    return table


def _span(lines: list[str], entry: dict) -> str:
    """The source text a profile entry covers, from its start line and column to its end line and column."""
    from arena.evidence import source_span

    return source_span(lines, entry)


def cost_tree(name: str, run_id: str, reference: str, page: int = 1, page_size: int = 30) -> dict:
    """A node's measured cost tree: every profiled tactic and stated term in source order with its nesting depth,
    tokens of its source span, total and own heartbeats, and the points it would return if it cost nothing.
    Cached data only; never Lean."""
    directory = run_dir(run_id)
    history = events(directory)
    graph = Graph.from_history(
        history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )
    proof_id = resolve_node_ref(history, reference)
    node = next(node for node in graph.nodes if node.proof_id == proof_id)
    profile = _cached_profiles(name, history).get(proof_id)
    if profile is None and node.origin == "reference":
        from arena.context import reference_profile

        try:
            profile = reference_profile(name, cache_only=True) or None
        except (ValueError, OSError):
            profile = None
    from arena.scoring import reference as scoring_reference

    price_rates = rates(*scoring_reference(name), len(versions(problem(name))))
    lines = node.proof_text.splitlines()
    rows = []
    for entry in (profile or {}).get("entries") or []:
        span = _span(lines, entry)
        tokens = snippet_tokens(span) if span.strip() else 0
        heartbeats = int(entry.get("hb") or 0)
        rows.append(
            {
                "line": entry.get("proof_line"),
                "depth": int(entry.get("depth") or 0),
                "kind": entry.get("kind", "tactic"),
                "text": " ".join(span.split()),
                "tokens": tokens,
                "heartbeats": heartbeats,
                "own_heartbeats": entry.get("self_hb"),
                "points": round(
                    tokens * price_rates["points_per_token"] + heartbeats / 1000 * price_rates["points_per_1k_hb"], 2
                ),
            }
        )
    from arena.profile import cached_heartbeat_floor

    try:
        floor = cached_heartbeat_floor(name)
    except (ValueError, OSError, KeyError):
        floor = None
    from arena.evidence import cost_evidence, render_cost_detail

    node_label = _update_id(history, proof_id)
    evidence = cost_evidence(
        node.proof_text,
        profile,
        proof_id=proof_id,
        total_tokens=node.tokens,
        published_score=node.score,
        versions=None,
        local_hb=(profile or {}).get("measured_total") if profile else None,
        node_label=node_label,
        page=page,
        page_size=page_size,
    )
    return {
        "node": node_label,
        "profiled": profile is not None,
        "rows": rows,
        "measured": (profile or {}).get("measured_total"),
        "attributed": (profile or {}).get("profiled_total"),
        "unattributed": (profile or {}).get("unattributed"),
        "floor": floor,
        "evidence": evidence,
        "detail": render_cost_detail(evidence),
    }


def price_table(name: str, run_id: str, reference: str | None = None) -> dict:
    """Return prices from cached proof/profile data only; this action never starts Lean."""
    directory = run_dir(run_id)
    history = events(directory)
    graph = Graph.from_history(
        history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )
    scored = [node for node in graph.nodes if node.score is not None]
    if reference:
        proof_id = resolve_node_ref(history, reference)
        node = next(node for node in graph.nodes if node.proof_id == proof_id)
    else:
        if not scored:
            raise ValueError(text.render("messages/errors.node_reference_invalid", reference="best scored node"))
        node = max(scored, key=lambda item: item.score)
    from arena.scoring import reference as scoring_reference

    reference_tokens, reference_heartbeats = scoring_reference(name)
    total_versions = len(versions(problem(name)))
    price_rates = rates(reference_tokens, reference_heartbeats, total_versions)
    profiles = _cached_profiles(name, history)
    profiled = node.proof_id in profiles
    if node.origin == "reference" and not profiled:
        from arena.context import reference_profile

        try:
            reference_result = reference_profile(name, cache_only=True)
        except (ValueError, OSError):
            reference_result = {}
        if reference_result:
            profiles[node.proof_id] = reference_result
            profiled = True
    table = _table_for_node(name, node, profiles, price_rates, total_versions)
    return {
        **table,
        "text": render_price_table(
            table, node.proof_text, profiles.get(node.proof_id), node.proof_id, node.id
        ),
        "profiled": profiled,
    }


def map_view(run_id: str, focus: str | None = None) -> dict:
    """Return the hidden JSON map without rendering it into model-facing prose."""
    directory = run_dir(run_id)
    return map_view_from(events(directory), directory, focus)


def map_view_from(history: list[dict], directory: Path, focus: str | None = None) -> dict:
    """The map for `history`, reading stored proofs from `directory`. Cached data only, never Lean.
    `focus` (a node id) puts that node's steps and line costs where the run best's would be (an island's own best)."""
    graph = Graph.from_history(
        history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )
    from arena.scoring import reference as scoring_reference

    name = history[0]["theorem"]
    try:
        reference_tokens, reference_heartbeats = scoring_reference(name)
    except ValueError:
        return graph_map_view(graph)
    total_versions = len(history[0].get("versions") or [1])
    price_rates = rates(reference_tokens, reference_heartbeats, total_versions)
    profiles = _cached_profiles(name, history)
    tables = {node.proof_id: _table_for_node(name, node, profiles, price_rates, total_versions) for node in graph.nodes}
    chosen = next((node for node in graph.nodes if node.id == focus), None)
    view = graph_map_view(graph, effort_table(graph, tables, chosen), (reference_tokens, reference_heartbeats))
    scored = [node for node in graph.nodes if node.score is not None]
    if chosen is not None:
        view["focus"] = {"node": chosen.id}
    if scored:
        best = chosen or max(scored, key=lambda node: node.score)
        view["line_costs"] = {
            **_line_costs(best.proof_text, profiles.get(best.proof_id)),
            "repeated": repeated_text(best.proof_text, price_rates["points_per_token"]),
        }
    return view


def step_costs(directory: Path, proof_id: str) -> list[dict]:
    """A saved node's steps, costliest first: `{step, tokens, heartbeats, points}`. Cached data only, never Lean;
    heartbeats and points are None for a step with no profile."""
    history = events(directory)
    graph = Graph.from_history(
        history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )
    node = next((item for item in graph.nodes if item.proof_id == proof_id), None)
    if node is None:
        return []
    from arena.scoring import reference as scoring_reference

    name = history[0]["theorem"]
    total_versions = len(history[0].get("versions") or [1])
    try:
        price_rates = rates(*scoring_reference(name), total_versions)
    except ValueError:
        return []
    table = _table_for_node(name, node, _cached_profiles(name, history), price_rates, total_versions)
    rows = [{"step": row["id"], "tokens": row["tokens"], "heartbeats": row["incl_hb"], "points": row["pts_if_gone"]}
            for row in table["rows"]]
    return sorted(rows, key=lambda row: (-(row["points"] or 0), -(row["tokens"] or 0)))


# Rows in each of the best node's two line lists.
LINE_COSTS_SHOWN = 5


def _line_costs(proof: str, profile: dict | None) -> dict:
    """The best node's costliest lines in two lists: lines whose own tactic spent heartbeats, by those heartbeats,
    and lines that run no tactic (stated terms, continued arguments), by tokens, with the heartbeats spent
    elaborating a stated term measured on its line."""
    if not profile:
        return {}
    lines = proof.splitlines()
    tokens = profile.get("line_tokens") if profile.get("token_attribution_available") else None
    tokens = tokens if isinstance(tokens, dict) else {}
    spent: dict[int, int] = {}
    stated: dict[int, int] = {}
    for item in profile.get("entries") or []:
        line = item.get("proof_line")
        if isinstance(line, int) and item.get("self_hb") is not None:
            book = stated if item.get("kind") == "term" else spent
            book[line] = book.get(line, 0) + int(item["self_hb"])

    def count(line: int) -> int | None:
        return tokens.get(line, tokens.get(str(line)))

    def row(line: int, hb: dict[int, int]) -> dict:
        return {
            "line": line,
            "text": lines[line - 1].strip() if 0 < line <= len(lines) else "",
            "tokens": count(line),
            "heartbeats": hb.get(line),
        }

    tactic = sorted(spent, key=lambda line: -spent[line])[:LINE_COSTS_SHOWN]
    quiet = [line for line in range(1, len(lines) + 1) if line not in spent and isinstance(count(line), int)]
    quiet = sorted(quiet, key=lambda line: (-int(count(line)), -stated.get(line, 0)))[:LINE_COSTS_SHOWN]
    return {"tactic": [row(line, spent) for line in tactic], "quiet": [row(line, stated) for line in quiet]}


def _cold_view(directory: Path, history: list[dict], event: dict | None) -> dict | None:
    """Present a cold check only for the bytes and context currently being inspected."""
    if event is None:
        return None
    identity, _proof, error = _cold_input(
        directory, history, event.get("proof_id") or event["candidate_id"], event.get("recorded_heartbeats")
    )
    if error or any(event.get(key) != value for key, value in identity.items()) or (
        event.get("outcome") == "passed" and not _cold_passed(event)
    ):
        return {**event, "outcome": "inconclusive", "cause": "context", "confirmed": False, "retryable": True}
    outcome = event.get("outcome") or ("passed" if _cold_passed(event) else "inconclusive")
    return {**event, "outcome": outcome}


def graph_state(run_id: str) -> dict:
    directory = run_dir(run_id)
    from arena.run_control import published_history

    history = published_history(directory, events(directory))
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
    probes: list[dict] = []
    timeline: list[dict] = []
    for event in history:
        kind = event.get("kind")
        if kind == "probe":
            probes.append(
                {
                    "proof_id": event["proof_id"],
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
                "merge": event.get("merge"),
                "evaluations": [],
                "source_versions": event.get("source_versions", []),
                "evaluator_sha256": event.get("evaluator_sha256"),
                "proof": (directory / "proofs" / f"{identifier}.lean").read_text(),
                "children": [],
                "decision": "pursue",
                "route": None,
                "eligibility": proof_eligibility(history, identifier),
                "verification": "unevaluated",
                "cold": None,
                "hypothesis_ref": event.get("hypothesis_ref"),
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
        node["verification"] = row["status"]
        node["verification_outcome"] = _verification_outcome(result)
        row["outcome"] = node["verification_outcome"]
        node["cold"] = None
        if row["status"] == "full" and row["local_proxy"] is not None and row["local_proxy"] > best_proxy:
            best_proxy = row["local_proxy"]
            milestones.append(row.copy())
    for identifier, node in nodes.items():
        node["eligibility"] = proof_eligibility(history, identifier)
        cold = next(
            (
                event
                for event in reversed(history)
                if event.get("kind") == "cold_verification" and event.get("candidate_id") == identifier
            ),
            None,
        )
        cold = _cold_view(directory, history, cold)
        cold_outcome = None if cold is None else cold.get("outcome") or (
            "passed" if cold.get("confirmed") else _verification_outcome(cold)
        )
        node["cold"] = True if cold_outcome == "passed" else False if cold_outcome == "proof_error" else None
        node["cold_outcome"] = cold_outcome
        node["cold_cause"] = None if cold is None else cold.get("cause")
        node["cold_retryable"] = False if cold is None else bool(cold.get("retryable"))
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
    projection = Graph.from_history(
        history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )
    projected = {node.proof_id: node for node in projection.nodes}
    for node in rows:
        graph_node = projected.get(node["id"])
        node["node"] = graph_node.id if graph_node else None
        node["edge"] = graph_node.edge if graph_node else None
        node["attempts"] = graph_node.attempts if graph_node else []
        node["alternate_derivations"] = (
            [item for item in graph_node.derivations if item.get("source") == "derivation"] if graph_node else []
        )
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
        "probes": probes,
        "routes": (route_rows := route_table(history)),
        "route_progress": _route_progress(route_rows),
        "focus": projection.focus,
        "job_log": _served_jobs(history),
        "experiments": _served_experiments(history),
        "actors": _served_actors(history),
    }


_WAIT_STATUS = {"wait": "waiting", "wait_end": "wait_ended"}


def _open_waits(history: list[dict]) -> set[str]:
    """Actors whose latest `wait` has no matching `wait_end`."""
    open_waits: dict[str, str] = {}
    for event in history:
        if event.get("kind") == "wait" and event.get("actor_id"):
            open_waits[event["wait_id"]] = event["actor_id"]
        elif event.get("kind") == "wait_end":
            open_waits.pop(event.get("wait_id"), None)
    return set(open_waits.values())


def _served_jobs(history: list[dict]) -> list[dict]:
    rows = []
    for event in history:
        source = _job_source(event)
        if source is None:
            continue
        rows.append(
            {
                "source": source,
                "job_id": event.get("job_id"),
                "status": event.get("status") or event.get("state") or _WAIT_STATUS.get(event.get("kind")),
                "actor_id": event.get("actor_id"),
                "session_id": event.get("session_id"),
                "candidate_id": event.get("candidate_id") or event.get("proof_id"),
                "queue": event.get("queue_depths"),
                "activation_id": event.get("activation_id"),
                "operation_id": event.get("operation_id"),
                "event_id": event.get("event_id"),
                "phase": event.get("phase"),
                "check": event.get("job") if source == "runtime" else None,
            }
        )
    return rows


def _job_source(event: dict) -> str | None:
    if event.get("type") in ("delegation", "assignment_state"):
        return "orchestration"
    if event.get("type") == "verification":
        return "check"
    if event.get("kind") == "job":
        return "runtime"
    if event.get("kind") in ("wait", "wait_end"):
        return "wait"
    return None


def _served_experiments(history: list[dict]) -> list[dict]:
    """One row per experiment: its accepted, raw and outcome rows joined by `experiment_id`."""
    found: dict[str, dict] = {}
    for event in history:
        if event.get("kind") != "scratch":
            continue
        key = event.get("experiment_id") or event.get("code_sha256") or ""
        row = found.setdefault(key, {"experiment_id": event.get("experiment_id")})
        row["phase"] = event.get("phase")
        for field in ("actor_id", "session_id", "tool_call_id", "job_id", "code_sha256", "elapsed_ms"):
            if event.get(field) is not None:
                row[field] = event[field]
        row["proof_id"] = event.get("proof_id") or event.get("candidate_id") or row.get("proof_id")
        at = (event.get("request") or {}).get("at")
        if at is not None:
            row["at"] = at
        if event.get("phase") == "outcome":
            row["outcome"] = event.get("outcome")
            for field in ("promotion", "validity", "compatibility", "cold"):
                row[field] = event.get(field)
            rendered = event.get("rendered")
            row["headline"] = rendered[0] if isinstance(rendered, list) and rendered else event.get("diagnostic")
        else:
            row.setdefault("outcome", event.get("outcome"))
    return list(found.values())


def _served_actors(history: list[dict]) -> list[dict]:
    sessions: dict[str, set[str]] = {}
    for event in history:
        actor = event.get("actor_id")
        session = event.get("session_id")
        if not actor:
            continue
        found = sessions.setdefault(actor, set())
        if session:
            found.add(session)
    waiting = _open_waits(history)
    rows = []
    for actor, found in sessions.items():
        ordered = sorted(found)
        status = "missing" if not ordered else "recorded" if len(ordered) == 1 else "ambiguous"
        rows.append(
            {
                "actor_id": actor,
                "session_id": ordered[0] if len(ordered) == 1 else None,
                "sessions": ordered,
                "session_status": status,
                "waiting": actor in waiting,
            }
        )
    return rows


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


def _hole_errors() -> tuple[str, ...]:
    return tuple(text.render("messages/errors.forbidden_construct", label=label) for label in ("sorry", "admit"))


def _has_hole(row: dict, proof: str) -> bool:
    try:
        validate_proof(row, proof)
    except ValueError as error:
        if str(error) in _hole_errors():
            return True
        raise
    return False


def _check_text(node: str, result: dict, total: int) -> str:
    compat = result.get("compat") or {}
    if result.get("ok") is False or not compat:
        return text.render(
            "replies/check.could_not_run", node=node, error=str(result.get("error") or "unknown error")[:160]
        )
    failing = [version for version, info in compat.items() if not info.get("passed")]
    if not failing and len(compat) == total:
        score = (result.get("metrics") or {}).get("proxy", result.get("local_proxy"))
        return text.render("replies/check.passed", node=node, total=total, score=score)
    first = compat[failing[0]]
    reason = (first.get("error_headlines") or [first.get("error") or "compile failed"])[0]
    return text.render(
        "replies/check.failed",
        node=node,
        failing=", ".join(failing),
        passed=len(compat) - len(failing),
        total=total,
        reason=str(reason)[:160],
    )


def _unchecked(rows: list[dict]) -> list[dict]:
    """Candidates that compile on the primary version but were never checked on every version."""
    return [
        r
        for r in rows
        if r["origin"] != "reference"
        and r["status"] == "primary"
        and not any(e["mode"] == "full" for e in r["evaluations"])
    ]


def _autocheck_jobs(rows: list[dict], closing: bool = False) -> list[dict]:
    """Unchecked candidates whose single-version score estimate can still beat or tie the best verified
    candidate (an unknown estimate is checked), most promising first. The skip applies to the closing
    drain too: a candidate the estimate rules out cannot become the submission."""
    jobs = _unchecked(rows)
    verified = [row for row in rows if row["verified"]]
    best_verified = _best(verified) if verified else None
    bar = best_verified["score"] if best_verified else None
    if bar is not None:
        jobs = [row for row in jobs if row["score"] is None or row["score"] >= bar]
    if not closing:
        chosen = {row["id"] for row in jobs}
        jobs += [row for row in _worker_records(rows) if row["id"] not in chosen]
    return sorted(jobs, key=lambda r: (r["score"] if r["score"] is not None else float("-inf"), r["n"]), reverse=True)


def _worker_records(rows: list[dict]) -> list[dict]:
    """Each worker job's unchecked record on each measure (fewest tokens, fewest heartbeats, top score) that beats
    the job's own best verified node on that measure: an island's best counts as closed only once every version
    compiles it, even when it does not beat the run best. Not in the closing drain: such a node cannot be the
    submission."""
    picked: dict[str, dict] = {}
    for job in {row["job"] for row in rows if row.get("job")}:
        mine = [row for row in rows if row.get("job") == job]
        unchecked = _unchecked(mine)
        verified = [row for row in mine if row["verified"]]
        for key, sign in (("tokens", 1), ("heartbeats", 1), ("score", -1)):
            pool = [row for row in unchecked if row[key] is not None]
            if not pool:
                continue
            record = min(pool, key=lambda row: (sign * row[key], row["n"]))
            held = [sign * row[key] for row in verified if row[key] is not None]
            if not held or sign * record[key] < min(held):
                picked[record["id"]] = record
    return list(picked.values())


def _submitted_full_jobs(directory: Path, history: list[dict], rows: list[dict], closing: bool) -> list[dict]:
    from arena.run_control import published_history

    latest = {}
    for event in published_history(directory, history):
        if event.get("type") == "verification" and event.get("proof_id"):
            execution = event.get("check_id") or f"legacy:{event['job_id']}:{event['evaluation_id']}"
            latest[(event["job_id"], execution)] = event
    pending = {event["proof_id"] for event in latest.values() if event["state"] == "queued"}
    # A saved candidate can precede any attributed check intent. Recovery uses
    # the existing full queue rather than inventing an author or an evaluation.
    evaluated_full = {event.get("candidate_id") for event in history
                      if event.get("kind") == "evaluation" and event.get("mode") == "full"}
    pending.update(event["candidate_id"] for event in history
                   if event.get("kind") == "job_queued" and event.get("job") == "full"
                   and event.get("phase") == "recovery" and event.get("candidate_id") not in evaluated_full)
    selected = _autocheck_jobs(rows, closing=closing)
    ids = {row["id"] for row in selected}
    return selected + [row for row in rows if row["id"] in pending and row["id"] not in ids]


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


def _profile_jobs(history: list[dict], graph: Graph) -> list[Node]:
    attempted = {event.get("proof_id") for event in history if event.get("kind") in {"profile", "profile_error"}}
    return [
        cell.node
        for cell in archive(graph)
        if cell.node.status == "closed" and cell.node.origin != "reference" and cell.node.proof_id not in attempted
    ]


def _mark_queued(directory: Path, history: list[dict], phase: str, kind: str, ids: list[str]) -> dict[str, dict]:
    queued = {
        (event.get("job"), event.get("candidate_id")): event for event in history if event.get("kind") == "job_queued"
    }
    result = {}
    for identifier in ids:
        event = queued.get((kind, identifier))
        if event is None:
            eligible = None
            source = "observed"
            if kind == "full":
                eligible = next(
                    (
                        row.get("ts")
                        for row in reversed(history)
                        if row.get("kind") == "evaluation"
                        and row.get("mode") == "fast"
                        and row.get("candidate_id") == identifier
                    ),
                    None,
                )
                if eligible is not None:
                    source = "fast_evaluation"
            event = {
                "ts": time.time(),
                "eligible_ts": eligible if isinstance(eligible, (int, float)) else time.time(),
                "eligibility_source": source,
            }
            _runtime_event(
                directory,
                {
                    "kind": "job_queued",
                    "job": kind,
                    "candidate_id": identifier,
                    "phase": phase,
                    "eligible_ts": event["eligible_ts"],
                    "eligibility_source": source,
                },
            )
        result[identifier] = event
    return result


def _queue_age(event: dict, now: float | None = None) -> float:
    return round(max(0, (time.time() if now is None else now) - event.get("eligible_ts", event["ts"])), 2)


def profile_in_call(name: str, run_id: str, node_refs: list[str]) -> None:
    """Profile closed nodes inside the model's own tool call, on the model lane: the background lane and the
    autocheck lock can be held for tens of seconds by other jobs, and the reply must not read "pending"."""
    directory = run_dir(run_id)
    history = events(directory)
    graph = Graph.from_history(
        history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )
    attempted = {event.get("proof_id") for event in history if event.get("kind") in {"profile", "profile_error"}}
    for ref in node_refs:
        try:
            proof_id = resolve_node_ref(history, ref)
        except (ValueError, KeyError):
            continue
        node = next((item for item in graph.nodes if item.proof_id == proof_id), None)
        if node is None or node.status != "closed" or proof_id in attempted:
            continue
        started = time.monotonic()
        try:
            result = profile(name, node.proof_text, node.heartbeats, lane="model")
            event = {"kind": "profile", "proof_id": proof_id, "result": result}
        except Exception as error:  # the background job does not retry a node that failed here
            event = {"kind": "profile_error", "proof_id": proof_id, "error": str(error)[:300]}
        _append(directory, {**event, "seconds": round(time.monotonic() - started, 2), "trigger": "in_call"})


def _run_profile_job(name: str, run_id: str, node: Node) -> None:
    directory = run_dir(run_id)
    started = time.monotonic()
    try:
        with lean_lock(directory, "background"):
            result = profile(name, node.proof_text, node.heartbeats, lane="background")
        _append(
            directory,
            {
                "kind": "profile",
                "proof_id": node.proof_id,
                "result": result,
                "seconds": round(time.monotonic() - started, 2),
            },
        )
    except Exception as error:  # any failure is terminal for this node; the loop keeps going
        _append(
            directory,
            {
                "kind": "profile_error",
                "proof_id": node.proof_id,
                "error": str(error)[:300],
                "seconds": round(time.monotonic() - started, 2),
            },
        )
    write_state(run_id)


def _salvage_jobs(history: list[dict], directory: Path, graph: Graph | None = None) -> list[Node]:
    """Broken, filed graph nodes with no terminal salvage event yet."""
    done = {
        item.get("proof_id") for item in history if item.get("kind") == "salvage" and item.get("status") != "deferred"
    }
    graph = graph or Graph.from_history(
        history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )
    # The pinned reference compiles by definition; it reads as broken only because it is never evaluated.
    return [
        node
        for node in graph.nodes
        if node.status == "broken" and node.edge and node.origin != "reference" and node.proof_id not in done
    ]


def _assembly_jobs(history: list[dict], directory: Path, graph: Graph | None = None) -> list[Node]:
    """Sketch nodes whose every hole has a closing fill and no assembly event."""
    done = {item.get("sketch") for item in history if item.get("kind") == "assembly"}
    graph = graph or Graph.from_history(
        history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )
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
        result = _evaluate(name, text_value, "probe", lane="background", request_class="opportunistic")
    compat = result.get("compat") or {}
    first = next(iter(compat.values()), {})
    diagnostics = first.get("diagnostics") or []
    clean = bool(first.get("passed")) and not any(item.get("severity") == "error" for item in diagnostics)
    lines = [
        item.get("proof_line") for item in diagnostics if item.get("severity") == "error" and item.get("proof_line")
    ]
    return {"clean": clean, "error_lines": lines, "unlocated": not clean and not lines, "result": result}


SALVAGE_SOFT_CAP_SECONDS = 60


@_submission_scope
def _run_salvage(name: str, run_id: str, node: Node, drain_deadline: float | None = None) -> dict:
    directory = run_dir(run_id)
    from arena.run_control import read_state, submission_barrier

    submission_barrier("before_construction", directory)
    if read_state(directory).get("stopped"):
        _append(directory, {
            "kind": "salvage", "proof_id": node.proof_id, "status": "run_stopped",
            "compiles": 0, "rounds": [], "kept": None, "sketch_id": None,
        })
        write_state(run_id)
        return {"status": "run_stopped", "compiles": 0, "rounds": [], "text": None, "result": None, "kept": None}
    started = time.monotonic()
    proof = node.proof_text
    history = _published_events(directory)
    prior = next(
        (
            item
            for item in reversed(history)
            if item.get("kind") == "salvage"
            and item.get("proof_id") == node.proof_id
            and item.get("status") == "deferred"
        ),
        None,
    )

    def should_yield() -> str | None:
        from arena.run_control import read_state

        if read_state(directory).get("stopped"):
            return "run_stopped"
        now = time.monotonic()
        if drain_deadline is not None and now >= drain_deadline:
            return "drain_budget_exhausted"
        if now - started >= SALVAGE_SOFT_CAP_SECONDS:
            return "salvage_soft_cap_exhausted"
        if _autocheck_jobs(_summaries(events(directory)), closing=False):
            return "full_check_arrived"
        return None

    submission_refused = False
    operation = {"type": "salvaged_from", "from": [node.proof_id]}

    def compile_salvage(candidate):
        nonlocal submission_refused
        from arena.run_control import SubmissionRefused

        proof_id = hashlib.sha256((name + "\0" + candidate).encode()).hexdigest()
        _snapshot(directory, proof_id, candidate)
        try:
            _submit_proof(directory, proof_id, candidate, operation, evaluation={
                "mode": "probe", "key": _evaluation_key(proof_id, "probe", problem(name)), "state": "queued",
            })
        except SubmissionRefused:
            submission_refused = True
            raise
        submission_barrier("during_lean", directory)
        return _salvage_compile(name, candidate)

    token = _SALVAGE_DIRECTORY.set(directory)
    try:
        outcome = salvage_proof(
            name,
            proof,
            compile_salvage,
            should_yield=should_yield,
            resume=(prior or {}).get("continuation"),
        )
    except (ValueError, FileNotFoundError):
        outcome = {"status": "unavailable", "compiles": 0, "rounds": [], "text": None, "result": None, "kept": None}
    finally:
        _SALVAGE_DIRECTORY.reset(token)
    if submission_refused or outcome.get("reason") == "run_stopped":
        outcome = {**outcome, "status": "run_stopped"}
    sketch_id = None
    if outcome["status"] == "salvaged":
        sketch_text = outcome["text"]
        sketch_id = hashlib.sha256((name + "\0" + sketch_text).encode()).hexdigest()
        _snapshot(directory, sketch_id, sketch_text)
        history = _published_events(directory)
        has_node = any(
            item.get("proof_id") == sketch_id and item.get("kind") in ("probe", "candidate") for item in history
        )
        if not has_node:
            result = dict(outcome["result"] or {})
            result["mode"] = "probe"
            result["scored"] = False
            result["salvaged"] = True
            from arena.run_control import SubmissionRefused

            try:
                attempt = _submit_proof(directory, sketch_id, sketch_text, operation, evaluation={
                    "mode": "probe", "key": _evaluation_key(sketch_id, "probe", problem(name)), "state": "queued",
                })
            except SubmissionRefused:
                outcome = {**outcome, "status": "run_stopped", "text": None}
                sketch_id = None
            else:
                _append_submitted(directory, attempt, {
                    "kind": "probe", "proof_id": sketch_id, "parent": node.proof_id, "result": result,
                })
        if sketch_id is not None:
            _file_node(
                directory,
                events(directory),
                sketch_id,
                sketch_text,
                operation=operation,
            )
    event = {
        "kind": "salvage",
        "proof_id": node.proof_id,
        "status": outcome["status"],
        "compiles": outcome["compiles"],
        "rounds": outcome["rounds"],
        "kept": outcome["kept"],
        "sketch_id": sketch_id,
        "seconds": round(time.monotonic() - started, 2),
    }
    if outcome["status"] == "deferred":
        event.update(reason=outcome["reason"], continuation=outcome["continuation"])
    _append(directory, event)
    write_state(run_id)
    return outcome


def _run_assembly(name: str, run_id: str, sketch: Node) -> None:
    directory = run_dir(run_id)
    from arena.run_control import read_state, submission_barrier

    submission_barrier("before_construction", directory)
    if read_state(directory).get("stopped"):
        _append(directory, {
            "kind": "assembly", "sketch": sketch.proof_id, "node": None, "fills": {},
            "alternatives": {}, "status": "run_stopped",
        })
        write_state(run_id)
        return
    started = time.monotonic()
    fills: dict[str, str] = {}
    alternatives: dict[str, list[str]] = {}
    chosen: list[tuple[dict, Node]] = []
    try:
        graph = Graph.from_history(
            events(directory), _proof_reader(directory), committed_operations=committed_operation_ids(directory)
        )
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
                "seconds": round(time.monotonic() - started, 2),
            },
        )
    except Exception as error:
        from arena.run_control import SubmissionRefused

        _append(
            directory,
            {
                "kind": "assembly",
                "sketch": sketch.proof_id,
                "node": None,
                "fills": fills,
                "alternatives": alternatives,
                "status": "run_stopped" if isinstance(error, SubmissionRefused) else "error",
                "error": str(error)[:300],
                "seconds": round(time.monotonic() - started, 2),
            },
        )
    write_state(run_id)


def _run_full_check(name: str, run_id: str, job: dict) -> str:
    directory = run_dir(run_id)
    from arena import orchestration
    from arena.recovery_proofs import _check_arguments, check_mode

    latest = {}
    for event in orchestration._history(directory):
        if event.get("type") == "verification" and event.get("proof_id") == job["id"]:
            identity = (event["job_id"], event.get("check_id") or f"legacy:{event['job_id']}:{event['evaluation_id']}")
            latest[identity] = event
    pending = [event for event in latest.values() if event["state"] == "queued"]
    mode = check_mode(job["id"], pending[0]["evaluation_id"], problem(name)) if pending else "full"
    if mode is None:
        raise ValueError("queued evaluation context changed")  # log: internal error # not-model-facing
    checks = [_check_arguments(event) for event in pending
              if event["evaluation_id"] == pending[0]["evaluation_id"]] if pending else _queue_full_check(
                  directory, run_id, job["id"],
              )
    try:
        proof = (directory / "proofs" / f"{job['id']}.lean").read_text()
        record_evaluation(name, run_id, proof, mode, materialize_live=False, lane="batch", trigger="auto",
                          verification_checks=checks)
    except Exception as error:  # record the failure so the queue moves on
        _append(
            directory,
            {
                "kind": "evaluation",
                "candidate_id": job["id"],
                "key": _evaluation_key(job["id"], mode, problem(name)),
                "mode": mode,
                "trigger": "auto",
                "result": {"ok": False, "mode": mode, "error": str(error)[:300], "compat": {}},
            },
        )
        from arena import orchestration

        for check in checks:
            orchestration.note_verification(directory, **check, state="inconclusive")
    write_state(run_id)
    return f"#{job['n']}"


def step_goals_in_call(name: str, run_id: str, proof_id: str) -> None:
    """Record one node's step goals inside the model's own read, on the model lane, when the background job has
    not reached it yet."""
    directory = run_dir(run_id)
    if any(
        event.get("kind") == "step_goals"
        and event.get("proof_id") == proof_id
        and ("goals" in event or "error" in event)
        for event in events(directory)
    ):
        return
    started = time.monotonic()
    try:
        from arena import step_goals

        goals = step_goals.step_goals(name, (directory / "proofs" / f"{proof_id}.lean").read_text(), lane="model")
        event = {"kind": "step_goals", "proof_id": proof_id, "goals": goals}
    except Exception as error:  # recorded so neither path retries it
        event = {"kind": "step_goals", "proof_id": proof_id, "error": str(error)[:300]}
    _append(directory, {**event, "seconds": round(time.monotonic() - started, 2), "trigger": "in_call"})


def _run_step_goals(name: str, run_id: str, proof_id: str) -> None:
    directory = run_dir(run_id)
    started = time.monotonic()
    try:
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
        from arena import step_goals

        with lean_lock(directory, "background"):
            goals = step_goals.step_goals(name, proof, lane="background")
        seconds = round(time.monotonic() - started, 2)
        _append(directory, {"kind": "step_goals", "proof_id": proof_id, "goals": goals, "seconds": seconds})
    except Exception as error:  # record the failure so this node does not block later jobs
        _append(
            directory,
            {
                "kind": "step_goals",
                "proof_id": proof_id,
                "error": str(error)[:300],
                "seconds": round(time.monotonic() - started, 2),
            },
        )
    write_state(run_id)


def _model_over(directory: Path, history: list[dict]) -> bool:
    """The run has stopped, or its model phase has ended (a resumed segment opens a new one)."""
    from arena.run_control import stopped

    last = next((e for e in reversed(history) if e.get("kind") == "phase" and e.get("phase") == "model"), None)
    return stopped(directory) or (last is not None and last.get("status") == "end")


def _autocheck_impl(
    name: str,
    run_id: str,
    max_seconds: float | None = None,
    closing: bool = False,
    kinds: tuple[str, ...] | None = None,
    phase_id: str = "",
) -> dict:
    """Drain salvage, assembly, full checks and step goals in the background lane.

    With ``closing`` (the model has stopped) it drains only full checks, then assemblies.
    ``kinds`` restricts the drain to those job kinds (in the usual order), e.g. ``("full",)``
    for the compile tool's short in-call wait, which must not spend it on salvage.
    Only one checker runs per run; all queues are derived from the ledger, so a
    killed checker loses nothing.
    """
    directory = run_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    drain_deadline = started + max_seconds if max_seconds is not None else None
    checked: list[str] = []
    capped_salvage: set[str] = set()
    phase = "closing_drain" if closing else "autocheck"
    with (directory / "autocheck.lock").open("a") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                # An in-call wait (kinds given) and the closing drain take their turn after the background job; the
                # background loop does not.
                if (kinds is None and not closing) or max_seconds is None or time.monotonic() - started >= max_seconds:
                    return {"ok": True, "checked": [], "running_elsewhere": True}
                time.sleep(0.2)
        phase_started = time.monotonic()
        _runtime_event(
            directory,
            {
                "kind": "phase",
                "phase": phase,
                "phase_id": phase_id,
                "status": "start",
                "lock_wait_seconds": round(phase_started - started, 2),
            },
        )
        while max_seconds is None or time.monotonic() - started < max_seconds:
            if lean_health.tripped(directory):
                break  # Lean is unhealthy: background checks pause with the model's work
            history = events(directory)
            if not closing and _model_over(directory, history):
                break  # the model has ended: the closing drain does the full checks, the rest only serves the model
            projection = Graph.from_history(
                history, _proof_reader(directory), committed_operations=committed_operation_ids(directory)
            )
            # Closing drain: the model has stopped, so only full checks (and assemblies, whose
            # results become new candidates) matter; salvage, step goals and profiles (which only
            # feed price tables) only serve the model.
            order = ("full", "assembly") if closing else ("full", "salvage", "assembly", "step_goals", "profiles")
            if kinds is not None:
                order = tuple(kind for kind in order if kind in kinds)
            jobs_by_kind = {
                "full": _submitted_full_jobs(directory, history, _summaries(history), closing=closing),
                "salvage": _salvage_jobs(history, directory, projection),
                "assembly": _assembly_jobs(history, directory, projection),
                "step_goals": _step_goal_jobs(history, directory) if not closing else [],
                "profiles": _profile_jobs(history, projection) if not closing else [],
            }
            queued_by_kind = {}
            eligible_kinds = ("full", "assembly") if closing else tuple(jobs_by_kind)
            for queued_kind in eligible_kinds:
                jobs_for_kind = jobs_by_kind[queued_kind]
                ids = [
                    item["id"]
                    if queued_kind == "full"
                    else item.proof_id
                    if queued_kind in ("salvage", "assembly", "profiles")
                    else item
                    for item in jobs_for_kind
                ]
                queued_by_kind[queued_kind] = _mark_queued(directory, history, phase, queued_kind, ids)
            queues = {key: len(value) for key, value in jobs_by_kind.items()}
            for kind in order:
                job = None
                jobs = jobs_by_kind[kind]
                if kind == "salvage" and jobs:
                    selected = next((item for item in jobs if item.proof_id not in capped_salvage), None)
                    if selected is not None:
                        job = (
                            selected.proof_id,
                            lambda selected=selected: _run_salvage(name, run_id, selected, drain_deadline),
                            queued_by_kind[kind][selected.proof_id],
                        )
                elif kind == "assembly" and jobs:
                    selected = jobs[0]
                    job = (
                        selected.proof_id,
                        lambda selected=selected: _run_assembly(name, run_id, selected),
                        queued_by_kind[kind][selected.proof_id],
                    )
                elif kind == "full" and jobs:
                    selected = jobs[0]
                    job = (
                        selected["id"],
                        lambda selected=selected: checked.append(_run_full_check(name, run_id, selected)),
                        queued_by_kind[kind][selected["id"]],
                    )
                elif kind == "step_goals" and jobs:
                    selected = jobs[0]
                    job = (
                        selected,
                        lambda selected=selected: _run_step_goals(name, run_id, selected),
                        queued_by_kind[kind][selected],
                    )
                elif kind == "profiles" and jobs:
                    selected = jobs[0]
                    job = (
                        selected.proof_id,
                        lambda selected=selected: _run_profile_job(name, run_id, selected),
                        queued_by_kind[kind][selected.proof_id],
                    )
                if job:
                    job_id, run_job, queued = job
                    created = next(
                        (
                            e.get("ts")
                            for e in history
                            if e.get("kind") == "candidate" and e.get("candidate_id") == job_id
                        ),
                        None,
                    )
                    job_id_event = f"{phase_id}:{kind}:{job_id}"
                    _runtime_event(
                        directory,
                        {
                            "kind": "job",
                            "phase": phase,
                            "phase_id": phase_id,
                            "job_id": job_id_event,
                            "job": kind,
                            "candidate_id": job_id,
                            "status": "start",
                            "queue_depths": queues,
                            "queue_age_s": _queue_age(queued),
                            "candidate_age_s": round(max(0, time.time() - created), 2) if created else None,
                        },
                    )
                    job_started = time.monotonic()
                    status = "end"
                    job_outcome = None
                    try:
                        job_outcome = run_job()
                    except Exception as error:
                        status = "error"
                        _runtime_event(
                            directory,
                            {
                                "kind": "job",
                                "phase": phase,
                                "phase_id": phase_id,
                                "job_id": job_id_event,
                                "job": kind,
                                "candidate_id": job_id,
                                "status": status,
                                "error": str(error)[:300],
                                "seconds": round(time.monotonic() - job_started, 2),
                            },
                        )
                        _runtime_event(
                            directory,
                            {
                                "kind": "phase",
                                "phase": phase,
                                "phase_id": phase_id,
                                "status": "error",
                                "error": str(error)[:300],
                                "seconds": round(time.monotonic() - phase_started, 2),
                            },
                        )
                        raise
                    else:
                        if kind == "salvage" and (job_outcome or {}).get("status") == "deferred":
                            status = "deferred"
                            if job_outcome.get("reason") != "full_check_arrived":
                                capped_salvage.add(job_id)
                        _runtime_event(
                            directory,
                            {
                                "kind": "job",
                                "phase": phase,
                                "phase_id": phase_id,
                                "job_id": job_id_event,
                                "job": kind,
                                "candidate_id": job_id,
                                "status": status,
                                "reason": (job_outcome or {}).get("reason"),
                                "seconds": round(time.monotonic() - job_started, 2),
                            },
                        )
                    break
            else:
                break
    rows = _summaries(events(directory))
    remaining = [f"#{r['n']}" for r in _autocheck_jobs(rows, closing=closing)]
    outcome = {"ok": True, "checked": checked, "remaining": remaining}
    _runtime_event(
        directory,
        {
            "kind": "phase",
            "phase": phase,
            "phase_id": phase_id,
            "status": "end",
            "seconds": round(time.monotonic() - phase_started, 2),
            "remaining": len(remaining),
        },
    )
    if closing:
        kept = set(remaining) | set(checked)
        outcome["skipped"] = [f"#{r['n']}" for r in _unchecked(rows) if f"#{r['n']}" not in kept]
        timed_out = bool(remaining) and max_seconds is not None and time.monotonic() - started >= max_seconds
        outcome["timed_out"] = timed_out
        _append(
            directory,
            {
                "kind": "closing_drain",
                "checked": len(checked),
                "skipped": outcome["skipped"],
                "unchecked_at_cap": remaining if timed_out else [],
                "timed_out": timed_out,
                "seconds": round(time.monotonic() - started, 2),
            },
        )
    return outcome


def autocheck(
    name: str,
    run_id: str,
    max_seconds: float | None = None,
    closing: bool = False,
    kinds: tuple[str, ...] | None = None,
) -> dict:
    directory = run_dir(run_id)
    phase = "closing_drain" if closing else "autocheck"
    phase_id = f"{phase}:{os.getpid()}:{time.monotonic_ns()}"
    try:
        return _autocheck_impl(name, run_id, max_seconds, closing, kinds, phase_id)
    except Exception as error:
        history = events(directory)
        started = any(
            e.get("kind") == "phase" and e.get("phase_id") == phase_id and e.get("status") == "start" for e in history
        )
        ended = any(
            e.get("kind") == "phase" and e.get("phase_id") == phase_id and e.get("status") in ("end", "error")
            for e in history
        )
        if started and not ended:
            _runtime_event(
                directory,
                {"kind": "phase", "phase": phase, "phase_id": phase_id, "status": "error", "error": str(error)[:300]},
            )
        raise


def _skeleton(history: list[dict], rows: list[dict], best: dict | None, run_id: str) -> dict:
    """Data for the continuation view: attempts since the best candidate, how many share its route, and the costliest
    step of the best node with its share of tokens or heartbeats, whichever is larger."""
    best_seq = max(
        (
            seq
            for seq, item in enumerate(history)
            if item.get("kind") == "evaluation" and best and item.get("candidate_id") == best["id"]
        ),
        default=-1,
    )
    attempts = {
        item["proof_id"] if item["kind"] == "probe" else item.get("candidate_id")
        for seq, item in enumerate(history)
        if seq > best_seq and item.get("kind") in ("probe", "candidate")
    }
    routes_by_id = {item["proof_id"]: item.get("route") for item in history if item.get("kind") == "route"}
    best_route = routes_by_id.get(best["id"]) if best else None
    same_route = sum(1 for attempt in attempts if best_route is not None and routes_by_id.get(attempt) == best_route)
    try:
        table = price_table(history[0]["theorem"], run_id)
    except ValueError:
        table = {"rows": [], "total": {}}
    total_tokens = table["total"].get("tokens") or 0
    total_hb = table["total"].get("heartbeats") or 0

    def share(row: dict) -> float:
        token_pct = 100 * row["tokens"] / total_tokens if total_tokens and row["tokens"] else 0.0
        hb_pct = 100 * row["self_hb"] / total_hb if total_hb and row.get("self_hb") else 0.0
        return max(token_pct, hb_pct)

    top = max(table["rows"], key=share, default=None)
    return {
        "attempts": len(attempts),
        "same_route": same_route,
        "top_step": top["id"] if top else None,
        "top_share_pct": round(share(top), 1) if top else None,
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
    updates: list[dict] = [
        {"seq": seq, "text": _check_text(_update_id(history, item["candidate_id"]), item["result"], total)}
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
    salvage_events: dict[str, list[tuple[int, dict]]] = {}
    for seq, item in enumerate(history):
        if item.get("kind") == "salvage" and item.get("status") == "salvaged" and item.get("sketch_id"):
            salvage_events.setdefault(item["sketch_id"], []).append((seq, item))
    for seq, item in enumerate(history):
        if item.get("kind") == "salvage" and item.get("status") == "salvaged" and item.get("sketch_id"):
            sketch_id = item["sketch_id"]
            if salvage_events[sketch_id][-1][0] != seq:
                continue  # one line per sketch, written when its last source draft arrives
            sketch_path = directory / "proofs" / f"{sketch_id}.lean"
            sketch_text = sketch_path.read_text() if sketch_path.is_file() else ""
            compile_result = (probes.get(sketch_id) or {}).get("result", {})
            hole_rows = find_holes(sketch_text, compile_result.get("goals") or [])
            sketch = _update_id(history, sketch_id)
            fill = (
                text.render(
                    "messages/salvage.fill_many" if len(hole_rows) > 1 else "messages/salvage.fill_one",
                    lines=", ".join(str(hole["line"]) for hole in hole_rows),
                    ids=", ".join(f"{sketch}.h{hole['index']}" for hole in hole_rows),
                )
                if hole_rows
                else text.render("messages/salvage.fill_none")
            )
            sources = list(
                dict.fromkeys(_update_id(history, entry["proof_id"]) for _, entry in salvage_events[sketch_id])
            )
            # `source` lets the delivery name the broken nodes only when the model has seen every id.
            updates.append(
                {
                    "seq": seq,
                    "text": text.render(
                        "messages/salvage.salvaged", sketch=sketch, sources=_compact_ids(sources), fill=fill
                    ),
                    "source": sources,
                    "quiet": True,  # bookkeeping for a draft that does not compile; stays in state, not in replies
                    "unseen_text": text.render("messages/salvage.salvaged_unseen", sketch=sketch, fill=fill),
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
                label = _update_id(history, fill_id)
                used.append(f"line {hole.get('line', '?')}: {label}")  # not-model-facing
                for alternate in (item.get("alternatives") or {}).get(hole_id, []):
                    operation = (fill_events.get(alternate) or {}).get("operation") or {}
                    cost = fill_cost(operation.get("text", ""))
                    alternatives.append(
                        f"line {hole.get('line', '?')}: {_update_id(history, alternate)} ({cost} tokens)"  # not-model-facing
                    )
            if item["status"] == "broken":
                notice = text.render("messages/assembly.assembly_failed", sketch=_update_id(history, sketch_id))
            else:
                row = next((row for row in rows if row["id"] == item.get("node")), {})
                notice = text.render(
                    "messages/assembly.assembled",
                    node=_update_id(history, item["node"]),
                    sketch=_update_id(history, sketch_id),
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
                    label=_update_id(history, proof_id),
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
        from arena.scoring import REFERENCE_SCORE, reference

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
                "proxy": REFERENCE_SCORE,
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
        "skeleton": _skeleton(history, rows, _best(rows), run_id),
    }


def write_state(run_id: str) -> None:
    """Publish `state` atomically for the Pi extension, which reads it on every tool result."""
    directory = run_dir(run_id)
    target = directory / "state.json"
    snapshot = state(run_id)
    # Tool calls and background checks publish concurrently: a slower writer holding an older snapshot must never
    # replace a newer one (v7-check4 Binius showed its best fall from 90.26 back to 89.89, then return).
    temporary = target.with_name(f"state.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(directory / "state.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            current = json.loads(target.read_text()).get("seq", -1)
        except (OSError, ValueError, AttributeError):
            current = -1
        if isinstance(current, int) and snapshot.get("seq", 0) < current:
            return
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False))
        temporary.replace(target)


COLD_TOLERANCE = 0.05  # same drift tolerance as arena certify
COLD_ATTEMPTS = 2  # one original check plus one infrastructure retry of that same proof


def _pin_cause(info: dict) -> str:
    """Only a completed Lean error condemns a proof; structured infrastructure wins."""
    if info.get("timeout") or info.get("cause") == "timeout":
        return "timeout"
    if info.get("cause") in ("toolchain_unavailable", "resource_denial", "worker_crash", "context", "measurement"):
        return info["cause"]
    if info.get("outcome") == "inconclusive":
        return info.get("cause") or "context"
    if info.get("lean_unavailable"):
        return "toolchain_unavailable"
    if info.get("outcome") == "proof_error" or info.get("cause") == "proof_error":
        return "proof_error"
    exit_code = info.get("exit_code")
    if exit_code == 1 and info.get("passed") is False:
        return "proof_error"
    if isinstance(exit_code, int) and exit_code not in (0, 1):
        return "worker_crash"
    blob = f"{info.get('error') or ''} {(info.get('lean') or {}).get('reason') or ''}".lower()
    if "timed out" in blob or "timeout" in blob:
        return "timeout"
    if "memory" in blob:
        return "resource_denial"
    return "context"


def _classify_cold(compat: dict, confirmed: bool, close: bool, error: str | None = None) -> dict:
    """Inconclusive checks neither certify nor invalidate a submitted proof."""
    if confirmed:
        return {"outcome": "passed", "cause": None, "retryable": False}
    if error:
        return {"outcome": "inconclusive", "cause": "context", "retryable": True}
    if compat and all(info.get("passed") is True for info in compat.values()) and not close:
        return {"outcome": "inconclusive", "cause": "measurement", "retryable": True}
    causes = [_pin_cause(info) for info in compat.values() if info.get("passed") is not True]
    if "proof_error" in causes:
        return {"outcome": "proof_error", "cause": "proof_error", "retryable": False}
    return {"outcome": "inconclusive", "cause": causes[0] if causes else "context", "retryable": True}


def _cold_events(history: list[dict], candidate_id: str) -> list[dict]:
    """Latest state of each attempt, retaining start and completion in the raw ledger."""
    attempts = {}
    for index, event in enumerate(history):
        if event.get("kind") != "cold_verification" or event.get("candidate_id") != candidate_id:
            continue
        key = (event["check_id"], event["attempt"]) if event.get("check_id") and event.get("attempt") else (index,)
        attempts.pop(key, None)
        attempts[key] = event
    return list(attempts.values())


def _cold_passed(event: dict | None) -> bool:
    """A positive event must explicitly establish every required pin."""
    if not event or event.get("outcome") != "passed" or not event.get("confirmed"):
        return False
    pins = [version for version, _commit in (event.get("context") or {}).get("pins", [])]
    passed = event.get("passed") or {}
    return bool(pins) and set(passed) == set(pins) and all(value is True for value in passed.values())


def _cold_input(
    directory: Path, history: list[dict], candidate_id: str, heartbeats: int | None
) -> tuple[dict, str | None, str | None]:
    """Identity covers the exact bytes, evaluator and immutable source/toolchain pins."""
    errors = []
    context = {"pins": history[0].get("versions") or [], "evaluator_sha256": None}
    try:
        context["evaluator_sha256"] = _evaluator_sha()
    except (OSError, ValueError) as error:
        errors.append(str(error))
    proof_bytes = None
    try:
        proof_bytes = (directory / "proofs" / f"{candidate_id}.lean").read_bytes()
        proof = proof_bytes.decode("utf-8")
        from arena.run_control import _control_rows

        committed = committed_operation_ids(directory)
        submitted_hashes = {
            event["proof_sha256"] for event in _control_rows(directory)
            if event.get("kind") == "candidate_submission" and event.get("proof_id") == candidate_id
            and event.get("operation_id") in committed and event.get("proof_sha256")
        }
        if submitted_hashes and submitted_hashes != {hashlib.sha256(proof_bytes).hexdigest()}:
            errors.append("saved proof bytes do not match the committed submission hash")  # log: internal error # not-model-facing
        elif not submitted_hashes and hashlib.sha256(
            (history[0]["theorem"] + "\0" + proof).encode()
        ).hexdigest() != candidate_id:
            errors.append("saved proof bytes do not match the submitted proof identity")  # log: internal error # not-model-facing
    except (OSError, UnicodeError) as error:
        proof = None
        errors.append(str(error))
    try:
        benchmark = problem(history[0]["theorem"])
        context["benchmark_sha256"] = hashlib.sha256(
            json.dumps(benchmark, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if json.loads(json.dumps(versions(benchmark))) != json.loads(json.dumps(context["pins"])):
            errors.append("saved toolchain pins do not match the current benchmark")  # log: internal error # not-model-facing
    except Exception as error:
        errors.append(str(error))
    identity = {
        "proof_id": candidate_id,
        "proof_sha256": hashlib.sha256(proof_bytes).hexdigest() if proof_bytes is not None else None,
        "mode": "cold",
        "context": context,
        "recorded_heartbeats": heartbeats,
    }
    identity["check_id"] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return identity, proof, "; ".join(errors) or None


def _matching_cold(history: list[dict], identity: dict) -> list[dict]:
    return [
        event
        for event in _cold_events(history, identity["proof_id"])
        if event.get("check_id") == identity["check_id"]
        and all(event.get(key) == value for key, value in identity.items())
    ]


def _certified_cold(directory: Path, history: list[dict], row: dict) -> dict | None:
    identity, _proof, error = _cold_input(directory, history, row["id"], row.get("heartbeats"))
    if error:
        return None
    matches = _matching_cold(history, identity)
    return matches[-1] if matches and _cold_passed(matches[-1]) else None


def cold_verify(run_id: str, row: dict) -> dict:
    """Independently check exact submitted bytes, with one bounded infrastructure retry."""
    directory = run_dir(run_id)
    # Counting attempts and running the check share this lock across threads/processes.
    with _candidate_lock(directory, row["id"]):
        history = _published_events(directory)
        identity, proof, context_error = _cold_input(directory, history, row["id"], row.get("heartbeats"))
        prior = _matching_cold(history, identity)
        done = prior[-1] if prior else None
        if done and done.get("state") == "running":
            # Acquiring the same candidate lock proves the previous checker is no longer
            # executing. Its durable start consumes one attempt even without a receipt.
            done = {key: value for key, value in done.items() if key != "ts"}
            done.update(
                state="finished",
                outcome="inconclusive",
                cause="worker_crash",
                confirmed=False,
                retryable=done["attempt"] < COLD_ATTEMPTS,
                error="cold check interrupted before completion",  # log: internal error # not-model-facing
                recovered=True,
            )
            _append(directory, done)
        if done and (_cold_passed(done) or done.get("outcome") == "proof_error"):
            return done
        if done and (len(prior) >= COLD_ATTEMPTS or not done.get("retryable", True)):
            return {**done, "retryable": False}
        event = {
            "kind": "cold_verification",
            "candidate_id": row["id"],
            **identity,
            "attempt": len(prior) + 1,
            "confirmed": False,
            "recorded_heartbeats": row.get("heartbeats"),
        }
        event["attempt_id"] = hashlib.sha256(f"{identity['check_id']}:{event['attempt']}".encode()).hexdigest()
        _append(
            directory, {**event, "state": "running", "outcome": "inconclusive", "cause": "context", "retryable": True}
        )
        phase_id = f"cold_verify:{os.getpid()}:{time.monotonic_ns()}"
        started = time.monotonic()
        _runtime_event(
            directory,
            {
                "kind": "phase",
                "phase": "cold_verify",
                "phase_id": phase_id,
                "status": "start",
                "candidate_id": row["id"],
            },
        )
        try:
            if context_error:
                event.update(_classify_cold({}, False, False, context_error), error=context_error)
            elif lean_health.tripped(directory):
                event.update(
                    outcome="inconclusive",
                    cause="resource_denial",
                    retryable=True,
                    error=text.render("messages/errors.cold_verification_paused"),
                    paused=True,
                )
            else:
                with lean_lock(directory, "background"), force_cold():
                    cold = _evaluate(
                        history[0]["theorem"], proof, "full", lane="background", request_class="full_check"
                    )
                compat = cold.get("compat") or {}
                passed = {
                    version: info.get("passed") is True and info.get("outcome", "passed") == "passed"
                    for version, info in compat.items()
                }
                recorded, measured = row.get("heartbeats"), cold.get("heartbeat")
                close = (
                    recorded is not None
                    and measured is not None
                    and abs(measured - recorded) <= COLD_TOLERANCE * max(recorded, 1)
                )
                required = {version for version, _commit in identity["context"]["pins"]}
                confirmed = bool(required) and set(passed) == required and all(passed.values()) and close
                event.update(
                    confirmed=confirmed,
                    passed=passed,
                    compat=compat,
                    cold_heartbeats=measured,
                    **_classify_cold(compat, confirmed, close),
                )
        except Exception as error:
            from arena.engine import ProofValidityError

            if isinstance(error, ProofValidityError):
                event.update(outcome="proof_error", cause="validity_error", retryable=False, error=str(error))
            else:
                event.update(_classify_cold({}, False, False, str(error)), error=str(error))
        if event.get("outcome") == "inconclusive" and event["attempt"] >= COLD_ATTEMPTS:
            event["retryable"] = False
        event["state"] = "finished"
        _append(directory, event)
        _runtime_event(
            directory,
            {
                "kind": "phase",
                "phase": "cold_verify",
                "phase_id": phase_id,
                "status": "error" if event.get("error") else "end",
                "candidate_id": row["id"],
                "seconds": round(time.monotonic() - started, 2),
                "confirmed": bool(event.get("confirmed")),
                "error": event.get("error"),
            },
        )
        return event

_HARNESS_ORIGINS = frozenset({"auto_merge", "assembly", "golf", "harness", "salvage"})


def proof_eligibility(history: list[dict], proof_id: str) -> str:
    """Agent compilation or an exact selection. An approved ancestor does not approve a child."""
    if any(
        event.get("kind") == "proof_selection" and (event.get("proof_id") or event.get("candidate_id")) == proof_id
        for event in history
    ):
        return "eligible"
    origin = next(
        (
            event.get("origin", "model")
            for event in history
            if event.get("kind") == "candidate" and event.get("candidate_id") == proof_id
        ),
        "model",
    )
    if origin in _HARNESS_ORIGINS:
        return "ineligible"
    return "eligible"


def select_proof(run_id: str, proof_id: str) -> dict:
    """An agent selects one exact proof. The selection does not extend to descendants."""
    from arena.run_control import actor_ids, submit_candidate

    directory = run_dir(run_id)
    identity = actor_ids(directory.name)
    proof_path = directory / "proofs" / f"{proof_id}.lean"
    proof_bytes = proof_path.read_bytes() if proof_path.is_file() else proof_id.encode()
    decision = submit_candidate(
        directory,
        {
            "operation_id": uuid.uuid4().hex,
            "run_id": run_id,
            "actor_id": identity["actor_id"],
            "session_id": identity["session_id"],
            "proof_id": proof_id,
            "proof_sha256": hashlib.sha256(proof_bytes).hexdigest(),
            "authorization": "exact_selection",
            "inputs": {"proof_id": proof_id},
            "ledger_events": [{"kind": "proof_selection", "proof_id": proof_id,
                               "candidate_id": proof_id, "actor_id": identity["actor_id"],
                               "session_id": identity["session_id"]}],
        },
    )
    if not decision["ok"]:
        return {
            "ok": False,
            "status": "run_stopped",
            "category": "run_stopped",
            "proof_id": proof_id,
            "eligibility": proof_eligibility(_published_events(directory), proof_id),
        }
    return {"ok": True, "proof_id": proof_id, "eligibility": "eligible", "actor_id": identity["actor_id"]}


def write_strategy(run_id: str, body: str) -> dict:
    """Sol replaces the shared strategic whiteboard. Workers cannot."""
    from arena.run_control import actor_ids

    directory = run_dir(run_id)
    identity = actor_ids(directory.name)
    if identity["actor_id"] != "sol":
        return {"ok": False, "category": "invalid_input", "reason": "strategy_owner"}
    _append(directory, {"kind": "strategy", "text": body, "actor_id": "sol", "session_id": identity["session_id"]})
    return {"ok": True, "text": body}


def write_observation(run_id: str, body: str, hypothesis_ref: str | None = None) -> dict:
    """Append an attributed observation. It does not replace strategy or another actor's notes."""
    from arena.run_control import actor_ids

    directory = run_dir(run_id)
    identity = actor_ids(directory.name)
    event = {
        "kind": "observation",
        "text": body,
        "actor_id": identity["actor_id"],
        "session_id": identity["session_id"],
        "hypothesis_ref": hypothesis_ref,
    }
    _append(directory, event)
    return {"ok": True, **event}


def current_strategy(history: list[dict]) -> str | None:
    texts = [
        event.get("text") for event in history if event.get("kind") == "strategy" and event.get("actor_id") == "sol"
    ]
    return texts[-1] if texts else None


def submission(run_id: str) -> dict:
    """The run's answer: the best candidate that passes every version. Written by the harness so
    nothing depends on the model remembering to submit.

    Every candidate requires independent all-pin cold certification. Infrastructure failures
    retain uncertainty and permit only an already-certified eligible fallback."""
    directory = run_dir(run_id)
    history = _published_events(directory)
    rows = _summaries(history)
    # Harness transformations need selection of this exact proof in addition to verification.
    pool = sorted(
        (
            r
            for r in rows
            if r["verified"]
            and r["score"] is not None
            and r["status"] == "full"
            and r["origin"] != "reference"
            and proof_eligibility(history, r["id"]) == "eligible"
        ),
        key=lambda r: (r["score"], -r["n"]),
        reverse=True,
    )
    best, rejected, cold, pending = None, [], None, []
    for index, row in enumerate(pool):
        certified = _certified_cold(directory, history, row)
        if certified:
            best, cold = row, certified
            break
        cold = cold_verify(run_id, row)
        while (
            cold.get("outcome") == "inconclusive"
            and cold.get("retryable")
            and isinstance(cold.get("attempt"), int)
            and cold["attempt"] < COLD_ATTEMPTS
        ):
            cold = cold_verify(run_id, row)
        if isinstance(cold.get("attempt"), int) and cold["attempt"] >= COLD_ATTEMPTS:
            cold = {**cold, "retryable": False}
        if _cold_passed(cold):
            best = row
            break
        if cold.get("outcome") == "inconclusive" or (
            cold.get("outcome") is None and not cold.get("confirmed") and cold.get("passed") is None
        ):
            # Certification is unavailable. Do not treat the proof as false, and do not
            # construct or freshly certify another candidate to take its place.
            pending.append(
                {
                    "candidate": f"#{row['n']}",
                    "candidate_id": row["id"],
                    "proof_id": cold.get("proof_id", row["id"]),
                    "mode": cold.get("mode", "cold"),
                    "outcome": "inconclusive",
                    "cause": cold.get("cause"),
                    "retryable": bool(cold.get("retryable")),
                    "attempt": cold.get("attempt"),
                    "passed": cold.get("passed"),
                    "error": cold.get("error"),
                }
            )
            for later in pool[index + 1 :]:
                prior = _certified_cold(directory, _published_events(directory), later)
                if prior:
                    best, cold = later, prior
                    break
            break
        rejected.append(
            {
                "candidate": f"#{row['n']}",
                "recorded_heartbeats": cold.get("recorded_heartbeats"),
                "cold_heartbeats": cold.get("cold_heartbeats"),
                "passed": cold.get("passed"),
                "error": cold.get("error"),
                "outcome": cold.get("outcome", "proof_error"),
            }
        )
    proof_bytes = None
    if best is not None:
        try:
            proof_bytes = (directory / "proofs" / f"{best['id']}.lean").read_bytes()
            if hashlib.sha256(proof_bytes).hexdigest() != cold["proof_sha256"]:
                raise ValueError("proof bytes changed after cold certification")  # log: internal error # not-model-facing
        except (OSError, ValueError) as error:
            pending.append({"candidate_id": best["id"], "outcome": "inconclusive",
                            "cause": "context", "retryable": False, "error": str(error)})
            best = None
    if best is None:
        answer = {
            "ok": True,
            "candidate": None,
            "reason": "no model candidate passed every version; the original proof stands",  # log: internal record # not-model-facing
        }
        answer["reason"] = "no certified submission exists"  # log: internal record # not-model-facing
        (directory / "submission.lean").unlink(missing_ok=True)
    else:
        (directory / "submission.lean").write_bytes(proof_bytes)
        answer = {
            "ok": True,
            "candidate": f"#{best['n']}",
            "candidate_id": best["id"],
            "tokens": best["tokens"],
            "heartbeats": best["heartbeats"],
            "proxy": best["score"],
            "proof_file": "submission.lean",
            "verified_by": "cold compile",  # log: internal record # not-model-facing
        }
        if cold and cold["confirmed"]:
            # The clean compile is the certified measurement; the session figure is kept for audit.
            answer["session_heartbeats"] = best["heartbeats"]
            answer["heartbeats"] = cold["cold_heartbeats"]
            # The score follows the certified measurement, not the session estimate it replaces.
            if cold.get("compat"):
                from arena.scoring import local_proxy

                answer["session_proxy"] = best["score"]
                answer["proxy"] = local_proxy(
                    history[0]["theorem"], best["tokens"], cold["cold_heartbeats"], cold["compat"]
                )
    if rejected:
        answer["rejected_on_cold"] = rejected
    if pending:
        answer["pending_checks"] = pending
    (directory / "submission.json").write_text(json.dumps(answer, indent=2) + "\n")
    return answer


def _route_progress(rows: list[dict]) -> dict:
    from arena.routes import progress

    return progress(rows)


def route_table(history: list[dict]) -> list[dict]:
    from arena.routes import route_table as table

    return table(history)


def frontier(run_id: str) -> dict:
    """Compact status: best candidates and recent failures."""
    history = events(run_dir(run_id))
    if not history:
        raise ValueError(text.render("messages/errors.run_uninitialized"))
    rows = _summaries(history)
    probe_numbers = _probe_numbers(history)
    failures: list[dict] = []
    failures.extend(
        {
            "ref": f"#{row['n']}",
            "error": _failure_text(row["evaluations"][-1]["result"]),
        }
        for row in rows
        if row["status"] == "fail" and row["evaluations"]
    )
    failures.extend(
        {
            "ref": probe_numbers[item["proof_id"]],
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
    return {
        "best": _brief(_best(rows)),
        "top": [_brief(r) for r in top],
        "recent_failures": failures[-3:],
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


# Repeated source spans: at least this many competition tokens, at most this many listed.
REPEAT_MIN_TOKENS = 6
REPEAT_SHOWN = 3
_REPEAT_WORDS = re.compile(r"[\w.'!?]+|[^\w\s]")
_REPEAT_START_WORDS = 4


def repeated_text(proof: str, points_per_token: float) -> list[dict]:
    """Source spans repeated in the proof body (after `:= by`), each with the tokens saved if it is shared once
    through a `have`: (count - 1) * tokens - (tokens + 4). Maximal spans only, positive savings only, and a span
    contained in a larger listed span is dropped."""
    from arena.profile import _mask_comments

    marker = proof.find(":= by")
    body = _mask_comments(proof[marker + len(":= by") :] if marker >= 0 else proof)
    found = list(_REPEAT_WORDS.finditer(body))
    words = [match.group() for match in found]
    total = len(words)
    level = [
        (_REPEAT_START_WORDS, positions)
        for key, positions in _group_starts(words, _REPEAT_START_WORDS).items()
        if len(positions) >= 2
    ]
    maximal: list[tuple[int, list[int]]] = []
    while level:
        grown = []
        for length, positions in level:
            children: dict[str, list[int]] = {}
            for p in positions:
                if p + length < total:
                    children.setdefault(words[p + length], []).append(p)
            if not any(len(kids) == len(positions) for kids in children.values()):
                maximal.append((length, positions))
            grown.extend((length + 1, kids) for kids in children.values() if len(kids) >= 2)
        level = grown
    items: dict[str, dict] = {}
    for length, positions in maximal:
        before = {words[p - 1] if p > 0 else None for p in positions}
        if len(before) == 1 and None not in before:
            continue  # every occurrence extends to the left as well; the longer span is listed instead
        trimmed = _balanced_span(body, found, words, positions, length)
        if trimmed is None:
            continue
        offset, length = trimmed
        occurrences = _non_overlapping([p + offset for p in positions], length)
        if len(occurrences) < 2:
            continue
        span = " ".join(body[found[occurrences[0]].start() : found[occurrences[0] + length - 1].end()].split())
        if span in items:
            continue
        tokens = snippet_tokens(span)
        if tokens < REPEAT_MIN_TOKENS or _repeat_saved(len(occurrences), tokens) <= 0:
            continue
        items[span] = {
            "text": span,
            "tokens": tokens,
            "ranges": [(found[p].start(), found[p + length - 1].end()) for p in occurrences],
        }
    # Greedy by savings; a span never overlaps one already chosen, in any occurrence (overlapping occurrences drop).
    chosen: list[dict] = []
    taken: list[tuple[int, int]] = []
    pool = list(items.values())
    while pool and len(chosen) < REPEAT_SHOWN:
        scored = []
        for item in pool:
            ranges = [r for r in item["ranges"] if not any(r[0] < end and start < r[1] for start, end in taken)]
            saved = _repeat_saved(len(ranges), item["tokens"]) if len(ranges) >= 2 else 0
            if saved > 0:
                scored.append((saved, item, ranges))
        if not scored:
            break
        saved, item, ranges = max(scored, key=lambda entry: (entry[0], -len(entry[1]["text"])))
        taken.extend(ranges)
        pool.remove(item)
        chosen.append(
            {
                "text": item["text"],
                "count": len(ranges),
                "tokens": item["tokens"],
                "saved_tokens": saved,
                "points": round(saved * points_per_token, 2),
            }
        )
    return sorted(chosen, key=lambda row: -row["saved_tokens"])


def _repeat_saved(count: int, tokens: int) -> int:
    """Tokens saved by sharing a span of `tokens` that occurs `count` times: one `have` costs tokens + 4."""
    return (count - 1) * tokens - (tokens + 4)


def _non_overlapping(positions: list[int], length: int) -> list[int]:
    kept: list[int] = []
    for p in positions:
        if not kept or p >= kept[-1] + length:
            kept.append(p)
    return kept


_OPENERS = {"(": ")", "[": "]", "{": "}", "⟨": "⟩"}
_CLOSERS = set(_OPENERS.values())


def _balanced_span(
    body: str, found: list, words: list[str], positions: list[int], length: int
) -> tuple[int, int] | None:
    """The longest part (offset, length in words) of a repeated word span that is bracket-balanced and starts and ends
    at a term boundary (whitespace or a bracket) in every occurrence."""

    def boundary(position: int, length_: int) -> bool:
        first, last = found[position].start(), found[position + length_ - 1].end()
        left = body[first - 1] if first > 0 else " "
        right = body[last] if last < len(body) else " "
        return (left.isspace() or left in _OPENERS) and (
            right.isspace() or right in _OPENERS or right in _CLOSERS or right in ",;"
        )

    def balanced(start: int, size: int) -> bool:
        stack: list[str] = []
        for word in words[positions[0] + start : positions[0] + start + size]:
            if word in _OPENERS:
                stack.append(_OPENERS[word])
            elif word in _CLOSERS and (not stack or stack.pop() != word):
                return False
        return not stack

    for size in range(length, 0, -1):
        for start in range(length - size + 1):
            if balanced(start, size) and all(boundary(p + start, size) for p in positions):
                return start, size
    return None


def _group_starts(words: list[str], length: int) -> dict[tuple[str, ...], list[int]]:
    groups: dict[tuple[str, ...], list[int]] = {}
    for index in range(len(words) - length + 1):
        groups.setdefault(tuple(words[index : index + length]), []).append(index)
    return groups
