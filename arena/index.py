"""Build and open per-row declaration indexes without query-time Lean."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import subprocess
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from arena import engine

LEAN_FILE = Path(__file__).with_name("lean") / "index.lean"
INDEX_TIMEOUT = 900
SCHEMA_VERSION = "declaration-index-v2"


def _log_build(path: Path, event: str, /, **fields: object) -> None:
    """Append one durable stage event beside the generated index."""
    log_path = path.with_suffix(".log.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(UTC).isoformat(), "event": event, **fields}
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _context(name: str, version: str | None = None) -> tuple[dict, str, str, str]:
    row = engine.problem(name)
    listed = engine.versions(row)
    if version is None:
        version, commit = engine.measure_version(row)
    else:
        match = next((pair for pair in listed if pair[0] == version), None)
        if match is None:
            raise ValueError(f"toolchain {version} is not listed for {name}")
        version, commit = match
    built = engine.candidate_file(row, row["src"], version, commit)
    index_source = LEAN_FILE.read_text()
    digest = hashlib.sha256((index_source + built["text"][: built["head"]] + SCHEMA_VERSION).encode()).hexdigest()[:12]
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    safe_version = re.sub(r"[^A-Za-z0-9_.-]", "_", version)
    path = engine.ROOT / "runs" / "cache" / "index" / f"{safe_name}-{safe_version}-{commit[:12]}-{digest}.sqlite"
    return row, version, commit, str(path)


def _path(name: str, version: str | None = None) -> Path:
    return Path(_context(name, version)[3])


def index_path(name: str, version: str | None = None) -> Path | None:
    """Return the cache path if present; this function never invokes Lean."""
    try:
        path = _path(name, version)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None
    return path if path.is_file() else None


def open_index(name: str, version: str | None = None) -> sqlite3.Connection:
    path = index_path(name, version)
    if path is None:
        row = engine.problem(name)
        selected = version or engine.measure_version(row)[0]
        raise ValueError(f"declaration index missing for {name} {selected}; run: arena index build {name}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _trigrams(value: str) -> set[str]:
    padded = f"  {value.casefold()}  "
    return {padded[index : index + 3] for index in range(len(padded) - 2)}


def _restore_current_file_lines(jsonl_path: Path, insertion_line: int, shift: int) -> None:
    """Map current-file ranges back across the wrapper inserted before the target declaration."""
    remapped = []
    for raw in jsonl_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(raw)
        if record.get("module") == "(this file)":
            for field in ("line", "end_line"):
                line = record.get(field)
                if line is not None and line >= insertion_line + shift:
                    record[field] = line - shift
        remapped.append(json.dumps(record, ensure_ascii=False))
    jsonl_path.write_text("\n".join(remapped) + "\n", encoding="utf-8")


def load_index(jsonl_path: Path, db_path: Path) -> int:
    """Load Lean JSONL into the same indexed SQLite schema used by production builds.

    Link tables hold integer ids only, keyed in their lookup direction: trigrams of each
    distinct folded last component (fuzzy name search) and declarations per constant (type search).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode = OFF;
            PRAGMA synchronous = OFF;
            CREATE TABLE components (
              id INTEGER PRIMARY KEY,
              folded_last TEXT NOT NULL UNIQUE,
              length INTEGER NOT NULL
            );
            CREATE TABLE declarations (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              folded_name TEXT NOT NULL,
              normalized_name TEXT NOT NULL,
              last_component TEXT NOT NULL,
              folded_last TEXT NOT NULL,
              component_id INTEGER NOT NULL REFERENCES components(id),
              kind TEXT NOT NULL,
              module TEXT NOT NULL,
              line INTEGER,
              end_line INTEGER,
              generated INTEGER NOT NULL,
              private INTEGER NOT NULL,
              type TEXT,
              head TEXT NOT NULL,
              consts TEXT NOT NULL
            );
            CREATE TABLE component_grams (
              gram TEXT NOT NULL,
              component_id INTEGER NOT NULL,
              PRIMARY KEY(gram, component_id)
            ) WITHOUT ROWID;
            CREATE TABLE constants (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, idf REAL NOT NULL);
            CREATE TABLE decl_consts (
              constant_id INTEGER NOT NULL,
              decl_id INTEGER NOT NULL,
              PRIMARY KEY(constant_id, decl_id)
            ) WITHOUT ROWID;
            """
        )
        components: dict[str, int] = {}
        documents: dict[str, set[int]] = {}
        count = 0
        with jsonl_path.open(encoding="utf-8") as source:
            for raw in source:
                record = json.loads(raw)
                name = str(record["name"])
                last = name.rsplit(".", 1)[-1]
                folded_last = last.casefold()
                normalized = unicodedata.normalize("NFKC", name).casefold()
                consts = list(dict.fromkeys(str(value) for value in record.get("consts", [])))
                component_id = components.get(folded_last)
                if component_id is None:
                    component_id = components[folded_last] = len(components) + 1
                    connection.execute(
                        "INSERT INTO components VALUES (?, ?, ?)", (component_id, folded_last, len(folded_last))
                    )
                    connection.executemany(
                        "INSERT INTO component_grams VALUES (?, ?)",
                        ((gram, component_id) for gram in _trigrams(folded_last)),
                    )
                decl_id = connection.execute(
                    "INSERT INTO declarations VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        name.casefold(),
                        normalized,
                        last,
                        folded_last,
                        component_id,
                        str(record["kind"]),
                        str(record["module"]),
                        record.get("line"),
                        record.get("end_line"),
                        int(bool(record.get("generated", False))),
                        int(bool(record.get("private", False))),
                        record.get("type"),
                        str(record.get("head", "")),
                        json.dumps(consts, ensure_ascii=False),
                    ),
                ).lastrowid
                assert decl_id is not None
                for constant in set(consts) | ({str(record["head"])} if record.get("head") else set()):
                    documents.setdefault(constant, set()).add(decl_id)
                count += 1
        total = max(count, 1)
        for constant_id, (constant, decl_ids) in enumerate(documents.items(), 1):
            connection.execute(
                "INSERT INTO constants VALUES (?, ?, ?)",
                (constant_id, constant, math.log((total + 1) / (len(decl_ids) + 0.5))),
            )
            connection.executemany(
                "INSERT INTO decl_consts VALUES (?, ?)", ((constant_id, decl_id) for decl_id in sorted(decl_ids))
            )
        connection.executescript(
            """
            CREATE INDEX declarations_folded_name ON declarations(folded_name);
            CREATE INDEX declarations_folded_last ON declarations(folded_last);
            CREATE INDEX declarations_component ON declarations(component_id);
            CREATE INDEX declarations_head ON declarations(head);
            CREATE INDEX declarations_last_component ON declarations(last_component);
            CREATE INDEX declarations_normalized_name ON declarations(normalized_name);
            CREATE INDEX components_length ON components(length);
            """
        )
        connection.commit()
        return count
    finally:
        connection.close()


def build_index(name: str, version: str | None = None) -> dict:
    """Build the selected row/toolchain index once; all later queries use only SQLite."""
    row, version, commit, raw_path = _context(name, version)
    path = Path(raw_path)
    if path.is_file():
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            declarations = connection.execute("SELECT count(*) FROM declarations").fetchone()[0]
        finally:
            connection.close()
        result = {
            "path": str(path),
            "declarations": declarations,
            "bytes": path.stat().st_size,
            "seconds": 0.0,
            "cached": True,
        }
        _log_build(path, "cache_hit", declarations=declarations, bytes=result["bytes"])
        return result

    started = time.monotonic()
    _log_build(path, "build_started", row=name, version=version, commit=commit)
    path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path = path.with_suffix(".jsonl")
    database_path = path.with_suffix(".sqlite.tmp")
    inserted = LEAN_FILE.read_text().replace("@@INDEX_PATH@@", json.dumps(str(jsonl_path)))
    built = engine.candidate_file(row, row["src"], version, commit)
    insertion_line = built["text"][: built["head"]].count("\n") + 1
    line_shift = inserted.count("\n") + 1
    source = built["text"]
    source = source[: built["head"]] + inserted + "\n" + source[built["head"] :]
    try:
        _log_build(path, "lean_started", timeout_seconds=INDEX_TIMEOUT)
        with engine.force_cold():
            ran = engine.run_lean(row, built["path"], source, timeout=INDEX_TIMEOUT, prefix_end=built["head"])
        if ran is None:
            raise RuntimeError(f"Lean declaration index timed out after {INDEX_TIMEOUT}s")
        returncode, output = ran
        _log_build(path, "lean_finished", returncode=returncode, output_tail=output[-2000:])
        if returncode:
            raise RuntimeError(output[-4000:] or f"Lean exited with status {returncode}")
        if not jsonl_path.is_file():
            raise RuntimeError("Lean completed without writing the declaration index")
        _log_build(path, "sqlite_load_started", jsonl_bytes=jsonl_path.stat().st_size)
        _restore_current_file_lines(jsonl_path, insertion_line, line_shift)
        declarations = load_index(jsonl_path, database_path)
        database_path.replace(path)
        _log_build(path, "sqlite_load_finished", declarations=declarations, bytes=path.stat().st_size)
    except Exception as error:
        _log_build(path, "build_failed", error=str(error), seconds=round(time.monotonic() - started, 3))
        database_path.unlink(missing_ok=True)
        raise
    finally:
        jsonl_path.unlink(missing_ok=True)
    result = {
        "path": str(path),
        "declarations": declarations,
        "bytes": path.stat().st_size,
        "seconds": round(time.monotonic() - started, 3),
        "cached": False,
    }
    _log_build(path, "build_finished", **result)
    return result
