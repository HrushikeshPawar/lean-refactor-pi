"""Join an Arena trace journal to Langfuse, and keep the Pi plugin patch checkable.

Byte-for-byte equality belongs to the journal wire row and the fake provider's socket
body. Langfuse generation input is the post-hook object after the plugin's key redaction,
not those bytes: the plugin redacts key-like strings and the provider SDK adds stream
flags after the hook. The journal stores both payloads as deltas; `read_journal` restores them.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "packages/arena-pi/patches/langfuse-pi-observability-plugin-0.1.2-full-payload.patch"
PATCH_SHA256 = "c6cd7f65e03dde13f1b25a33a2ca1e8cc69b3b6511a9aa3d6fc0136b8a7625af"
PLUGIN_VERSION = "0.1.2"
INSTALLED_PLUGIN = Path.home() / ".pi/agent/npm/node_modules/@langfuse/pi-observability-plugin"
ORIG_PLUGIN = Path.home() / ".pi/agent/patches/pi-observability-plugin.orig-0.1.2"
REDACTION_MARK = "[redacted-langfuse-secret]"
_KEY_RE = __import__("re").compile(r"\b[sp]k-lf-[\w-]+\b")
_EXPAND = "assistant_text_meta,args_meta,output_meta,user_text_meta,arena_delta,summary_meta"
_FIELDS = "core,basic,io,usage,metadata,model"
_FORBIDDEN_KEYS = {"authorization", "x-api-key", "apikey", "api_key", "headers"}


def redact(value):
    """Same Langfuse-key redaction the patched plugin applies to a generation input."""
    if isinstance(value, str):
        return _KEY_RE.sub(REDACTION_MARK, value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_source(orig: Path, patch: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "plugin"
        shutil.copytree(orig, dest)
        proc = subprocess.run(["patch", "-p1", "--batch", "--forward", "-i", str(patch)],
                              cwd=dest, text=True, capture_output=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(detail or "plugin patch did not apply")
        return (dest / "src/index.ts").read_text()


def plugin_problems(installed: Path | None = None, orig: Path | None = None,
                    patch: Path | None = None) -> list[str]:
    """Empty when `installed` is exactly the vendored patch applied to the 0.1.2 backup."""
    installed = installed or INSTALLED_PLUGIN
    orig = orig or ORIG_PLUGIN
    patch = patch or PATCH_PATH
    problems = []
    if not patch.is_file():
        return [f"vendored plugin patch is missing: {patch}"]
    digest = _sha256(patch)
    if digest != PATCH_SHA256:
        problems.append(f"vendored plugin patch hash is {digest}, expected {PATCH_SHA256}")
    package = installed / "package.json"
    source = installed / "src/index.ts"
    if not package.is_file() or not source.is_file():
        return problems + [f"Langfuse plugin {PLUGIN_VERSION} is not installed at {installed}"]
    version = json.loads(package.read_text()).get("version")
    if version != PLUGIN_VERSION:
        problems.append(f"installed Langfuse plugin is {version}, expected {PLUGIN_VERSION}")
    if not (orig / "src/index.ts").is_file():
        return problems + [f"original plugin backup is missing: {orig}"]
    if problems:
        return problems
    expected = _expected_source(orig, patch)
    if source.read_text() != expected:
        problems.append("installed Langfuse plugin is not the patched 0.1.2 source")
    return problems


def apply_plugin(installed: Path | None = None, orig: Path | None = None,
                 patch: Path | None = None) -> str:
    """Rewrite an unpatched 0.1.2 install from the vendored patch. Leave a patched tree alone."""
    installed = installed or INSTALLED_PLUGIN
    orig = orig or ORIG_PLUGIN
    patch = patch or PATCH_PATH
    if _sha256(patch) != PATCH_SHA256:
        raise RuntimeError("refusing to apply a plugin patch whose hash does not match the ticket")
    expected = _expected_source(orig, patch)
    source = installed / "src/index.ts"
    current = source.read_text() if source.is_file() else None
    if current == expected:
        return "already patched"
    original = (orig / "src/index.ts").read_text()
    if current != original:
        raise RuntimeError(f"{source} is neither the original 0.1.2 plugin nor the vendored patch")
    source.write_text(expected)
    return "patched"


def langfuse_extension() -> Path:
    return INSTALLED_PLUGIN / "src/index.ts"


def langfuse_environment() -> dict[str, str]:
    """Keys from the local Langfuse config. Callers must not print or persist the result."""
    path = Path.home() / ".pi" / "agent" / "langfuse.json"
    try:
        config = json.loads(path.read_text())
        public = str(config["publicKey"])
        secret = str(config["secretKey"])
        host = str(config["baseUrl"]).rstrip("/")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Langfuse config at {path} is unusable ({type(error).__name__})") from None
    return {"LANGFUSE_PUBLIC_KEY": public, "LANGFUSE_SECRET_KEY": secret, "LANGFUSE_HOST": host,
            "LANGFUSE_BASE_URL": host, "PI_LANGFUSE_MAX_CHARS": "100000000", "LANGFUSE_TIMEOUT": "60"}


def list_observations(session_id: str, started: datetime) -> list[dict]:
    """Every observation for one Arena run, read back through Observations API v2."""
    env = langfuse_environment()
    token = base64.b64encode(f"{env['LANGFUSE_PUBLIC_KEY']}:{env['LANGFUSE_SECRET_KEY']}".encode()).decode()
    start = (started.astimezone(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict] = []
    cursor = None
    while True:
        query = {"sessionId": session_id, "fromStartTime": start, "toStartTime": end,
                 "fields": _FIELDS, "expandMetadata": _EXPAND, "limit": "1000"}
        if cursor:
            query["cursor"] = cursor
        url = f"{env['LANGFUSE_HOST']}/api/public/v2/observations?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Langfuse observations request failed with HTTP {error.code}") from None
        rows.extend(payload.get("data") or [])
        cursor = (payload.get("meta") or {}).get("cursor")
        if not cursor:
            return rows


def _parsed(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _truncated(value) -> bool:
    if isinstance(value, dict):
        if value.get("truncated") is True:
            return True
        return any(_truncated(item) for item in value.values())
    if isinstance(value, list):
        return any(_truncated(item) for item in value)
    if isinstance(value, str):
        compact = value.replace(" ", "")
        return '"truncated":true' in compact
    return False


def _credential_keys(value, path: str = "") -> list[str]:
    if isinstance(value, dict):
        found = []
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            if str(key).lower() in _FORBIDDEN_KEYS:
                found.append(here)
            else:
                found.extend(_credential_keys(item, here))
        return found
    if isinstance(value, list):
        found = []
        for index, item in enumerate(value):
            found.extend(_credential_keys(item, f"{path}[{index}]"))
        return found
    return []


def _output_text(observation: dict) -> str:
    raw = observation.get("output")
    if not isinstance(raw, str):
        return "" if raw is None else str(raw)
    parsed = _parsed(raw)
    if isinstance(parsed, dict):
        # A generation output is {role, content?, tool_calls?}; a tool-call-only turn has no content.
        return parsed["content"] if isinstance(parsed.get("content"), str) else ""
    # Tool output is a string. The v2 API returns I/O as a JSON string, so a pad of
    # P's comes back quoted; a value that is not JSON is already the text.
    if isinstance(parsed, str):
        return parsed
    return raw


def _output_tool_calls(observation: dict) -> list[tuple]:
    """(id, name) of each tool call in a generation output. The plugin records no arguments there."""
    parsed = _parsed(observation.get("output"))
    calls = parsed.get("tool_calls") if isinstance(parsed, dict) else None
    return [(call.get("id"), call.get("name")) for call in calls or [] if isinstance(call, dict)]


def _usage_count(details: dict | None, key: str) -> int:
    if not isinstance(details, dict) or details.get(key) is None:
        return 0
    return int(details[key])


class JournalError(ValueError):
    """A delta row that cannot be restored: its base is missing or the restored bytes fail their hash."""


def _restore(base: bytes | None, row: dict, middle: str, prefix_key: str, suffix_key: str) -> bytes:
    if base is None:
        raise JournalError(f"{row.get('kind')} {row.get('id')} is a delta with no earlier row to apply it to")
    suffix = row[suffix_key]
    return base[:row[prefix_key]] + middle.encode() + (base[len(base) - suffix:] if suffix else b"")


def expand_journal(rows: list[dict]) -> list[dict]:
    """Rows with their full `body` (wire) and `post_hook` (request) restored.

    The Pi extension stores both as a delta against the previous row of the same kind (journal.ts), with a
    keyframe first and every few rows. Rows without an encoding field are returned as they are, so older
    journals and hand-built rows pass through. The full-bytes sha256 on each row is checked.
    """
    out, wire, hook = [], None, None
    for row in rows:
        if row.get("kind") == "wire" and isinstance(row.get("body"), str):
            data = _restore(wire, row, row["body"], "prefix", "suffix") if row.get("encoding") == "delta" else row["body"].encode()
            if row.get("sha256") and hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise JournalError(f"wire body of {row.get('id')} does not match its sha256")
            wire = data
            row = {key: value for key, value in row.items() if key not in ("encoding", "prefix", "suffix")} | {"body": data.decode()}
        elif row.get("kind") == "request" and row.get("post_hook_encoding"):
            data = (_restore(hook, row, row["post_hook"], "post_hook_prefix", "post_hook_suffix")
                    if row["post_hook_encoding"] == "delta" else row["post_hook"].encode())
            if hashlib.sha256(data).hexdigest() != row.get("post_hook_sha256"):
                raise JournalError(f"post-hook payload of {row.get('id')} does not match its sha256")
            hook = data
            row = {key: value for key, value in row.items()
                   if not key.startswith("post_hook_")} | {"post_hook": json.loads(data)}
        out.append(row)
    return out


def read_journal(path: Path) -> list[dict]:
    """The whole trace journal with payloads restored; empty when there is none."""
    if not path.exists():
        return []
    return expand_journal([json.loads(line) for line in path.read_text().splitlines() if line])


def judge(journal: list[dict], observations: list[dict]) -> list[str]:
    """Problems that mean the Langfuse export is missing, clipped, or cannot join the journal.

    Generations pair with requests in time order. A retry resends the same payload, so a
    single generation must not satisfy two requests. Every request also needs its byte-exact
    wire row. The ledger's settled cost is authoritative; Pi prices from a catalog that
    `catalogPriceProblem` holds equal to the ledger, so Langfuse totalCost must match it,
    except where the ledger applied a conservative high price tier. Tool spans join their
    journal rows by tool call ID.
    """
    try:
        journal = expand_journal(journal)
    except JournalError as error:
        return [str(error)]
    problems = [f"truncated observation {item.get('id')}" for item in observations if _truncated(item)]
    for row in journal:
        problems.extend(f"credential field {field} on {row.get('kind')} {row.get('id')}"
                        for field in _credential_keys(row))
        if row.get("kind") == "wire" and isinstance(row.get("body"), str):
            try:
                problems.extend(f"credential field {field} in wire {row.get('id')}"
                                for field in _credential_keys(json.loads(row["body"])))
            except json.JSONDecodeError:
                problems.append(f"wire {row.get('id')} is not utf-8 json")

    requests = sorted((row for row in journal if row.get("kind") == "request"), key=lambda row: row.get("ts") or 0)
    wires: dict[str, list[int]] = {}
    for row in journal:
        if row.get("kind") == "wire":
            wires.setdefault(row.get("id"), []).append(row.get("retry_index"))
    for request in requests:
        indexes = wires.get(request.get("id"))
        if not indexes:
            problems.append(f"missing wire body for request {request.get('id')}")
        elif sorted(indexes) != list(range(len(indexes))):
            problems.append(f"wire retry indexes {indexes} are not 0..n for request {request.get('id')}")

    generations = sorted((row for row in observations
                          if row.get("type") == "GENERATION" and row.get("name") == "LLM Call"),
                         key=lambda row: row.get("startTime") or "")
    if len(generations) != len(requests):
        problems.append(f"unjoinable generations: {len(requests)} requests and {len(generations)} Langfuse generations")
    responses = {row.get("id"): row for row in journal if row.get("kind") == "response"}
    for request, generation in zip(requests, generations):
        if redact(request.get("post_hook")) != _parsed(generation.get("input")):
            problems.append(f"generation input does not match request {request.get('id')}")
        response = responses.get(request.get("id"))
        if response is None:
            problems.append(f"missing response for request {request.get('id')}")
            continue
        expected = response.get("text") or ""
        seen = _output_text(generation)
        if len(seen) < len(expected):
            problems.append(f"generation output shorter than journal for {request.get('id')}")
        elif seen != expected:
            problems.append(f"generation output does not match journal text for {request.get('id')}")
        calls = [(block.get("id"), block.get("name")) for block in response.get("content") or []
                 if isinstance(block, dict) and block.get("type") == "toolCall"]
        if calls != _output_tool_calls(generation):
            problems.append(f"generation tool calls do not match journal for {request.get('id')}")
        usage = response.get("usage")
        if not usage:
            continue
        settled = response.get("settled_usd")
        if settled is None:
            problems.append(f"settled cost missing for {request.get('id')}")
        details = generation.get("usageDetails") if isinstance(generation.get("usageDetails"), dict) else {}
        # Pi's output count includes reasoning. Langfuse splits that subset into its own bucket.
        seen = {"input": _usage_count(details, "input"),
                "output": _usage_count(details, "output") + _usage_count(details, "output_reasoning_tokens"),
                "cache_read_input_tokens": _usage_count(details, "cache_read_input_tokens"),
                "cache_creation_input_tokens": _usage_count(details, "cache_creation_input_tokens")}
        expected_usage = {"input": usage.get("input", 0), "output": usage.get("output", 0),
                          "cache_read_input_tokens": usage.get("cache_read", 0),
                          "cache_creation_input_tokens": usage.get("cache_write", 0)}
        if seen != expected_usage:
            problems.append(f"usage does not join attempt {request.get('id')}")
        total = generation.get("totalCost")
        if settled is not None and response.get("price_tier") != "high":
            if total is None or abs(float(total) - float(settled)) > 1e-6:
                problems.append(f"Langfuse cost {total} does not equal settled ${settled} for {request.get('id')}")

    calls = {row.get("tool_call_id"): row for row in journal if row.get("kind") == "tool_call"}
    tools = [row for row in journal if row.get("kind") == "tool_result"]
    spans = {}
    for row in observations:
        if row.get("type") == "TOOL":
            metadata = _parsed(row.get("metadata")) if row.get("metadata") is not None else {}
            spans[(metadata or {}).get("tool_id")] = row
    if len([key for key in spans if key is not None]) != len(tools):
        problems.append(f"unjoinable tools: {len(tools)} results and {len(spans)} Langfuse tool spans")
    for result in tools:
        span = spans.get(result.get("tool_call_id"))
        if span is None:
            problems.append(f"no Langfuse tool span for call {result.get('tool_call_id')}")
            continue
        if span.get("name") != f"Tool: {result.get('name')}":
            problems.append(f"tool span {span.get('name')} does not match {result.get('name')}")
            continue
        call = calls.get(result.get("tool_call_id"))
        if call is None:
            problems.append(f"missing tool_call row for {result.get('tool_call_id')}")
        elif redact(call.get("args")) != _parsed(span.get("input")):
            problems.append(f"tool span input does not match arguments for {result.get('tool_call_id')}")
        expected = result.get("text") or ""
        seen = _output_text(span)
        if len(seen) < len(expected):
            problems.append(f"tool output shorter than journal for {result.get('name')}")
        elif expected and seen != expected:
            problems.append(f"tool output does not match journal for {result.get('name')}")
    return problems


def preflight_problems(journal: list[dict], observations: list[dict]) -> list[str]:
    """Judge, and also fail a run that never invoked a tool.

    A text-only exchange has nothing to join, so `judge` accepts it. Preflight must
    read a tool span back from Langfuse.
    """
    problems = judge(journal, observations)
    if not any(row.get("type") == "TOOL" for row in observations):
        problems.append("missing tool span")
    return problems


def receipt_path() -> Path:
    override = os.environ.get("ARENA_PREFLIGHT_RECEIPT")
    if override:
        return Path(override)
    return ROOT / "runs" / "pi-budget" / "preflight.json"


def write_receipt(receipt: dict, path: Path | None = None) -> None:
    target = path or receipt_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(receipt, indent=2) + "\n").encode()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(target, 0o600)


def preflight_block(models: list[str]) -> str | None:
    """Why a paid matrix must not start, or None when the receipt covers every model."""
    path = receipt_path()
    if not path.is_file():
        return f"paid matrix needs a passing preflight receipt at {path}"
    try:
        receipt = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return f"preflight receipt is unreadable ({type(error).__name__})"
    if receipt.get("status") != "pass":
        return "preflight receipt did not pass"
    if receipt.get("patch_sha256") != PATCH_SHA256:
        return "preflight receipt patch hash does not match the vendored plugin patch"
    covered = receipt.get("models") or {}
    missing = [model for model in dict.fromkeys(models)
               if not (covered.get(model) or {}).get("trace_ids")]
    if missing:
        return f"preflight receipt has no passing trace for {', '.join(missing)}"
    problems = plugin_problems()
    if problems:
        return "; ".join(problems)
    return None
