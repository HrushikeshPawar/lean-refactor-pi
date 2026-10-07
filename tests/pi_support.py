"""Seam B helpers: run the real budgeted runner and Pi against the scripted offline provider."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from arena.campaign import run_dir
from arena.engine import ROOT

NAME = "Core.InitsUpdatesComm"
FAKE = ROOT / "tests/fake_opencode.ts"
PI_AVAILABLE = shutil.which("pi") is not None and (ROOT / "workspaces/strata-v4.29.1").is_dir()


class FakeRun:
    """One scripted run. `steps` are provider responses; see tests/fake_opencode.ts."""

    def __init__(self, steps: list[dict], *extra: str, cap: str = "0.1", env: dict | None = None,
                 run_id: str | None = None, timeout: int = 240, model: str = "gpt-6-luna"):
        self.run_id = run_id or f"test-{uuid.uuid4().hex[:10]}"
        self.directory = run_dir(self.run_id)
        self.work = Path(tempfile.mkdtemp())
        self.script = self.work / "script.json"
        self.script.write_text(json.dumps(steps))
        self.log = self.work / "requests.jsonl"
        self.command = [sys.executable, "tools/run_pi_budgeted.py", "--model", model,
                        "--theorem", NAME, "--run-id", self.run_id, "--hard-cap-usd", cap,
                        "--no-mcp", "--test-extension", str(FAKE), *extra]
        self.env = {**os.environ, "ARENA_FAKE_SCRIPT": str(self.script), "ARENA_FAKE_LOG": str(self.log),
                    **(env or {})}
        self.timeout = timeout
        self.result: subprocess.CompletedProcess | None = None

    def run(self, *extra: str) -> "FakeRun":
        self.result = subprocess.run([*self.command, *extra], cwd=ROOT, env=self.env, text=True,
                                     capture_output=True, timeout=self.timeout)
        return self

    def start(self, *extra: str, own_group: bool = False) -> subprocess.Popen:
        """Launch without waiting, for tests that signal the runner.

        `own_group` puts the runner in a fresh process group, like a terminal
        foreground job, so a test can deliver Ctrl+C to the whole group.
        """
        self.process = subprocess.Popen([*self.command, *extra], cwd=ROOT, env=self.env, text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=own_group)
        return self.process

    def wait_for_requests(self, count: int, timeout: float = 60.0) -> bool:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.requests) >= count:
                return True
            time.sleep(0.2)
        return False

    def cleanup(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    @property
    def requests(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines() if line]

    def json(self, name: str):
        return json.loads((self.directory / name).read_text())

    def jsonl(self, name: str) -> list[dict]:
        path = self.directory / name
        return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []

    @property
    def stdout(self) -> str:
        return self.result.stdout if self.result else ""


def message_text(message: dict) -> str:
    """Plain text of a transcript message: content blocks plus any system sections."""
    content = message.get("content", "")
    if isinstance(content, list):
        content = "\n".join(block.get("text") or json.dumps(block, ensure_ascii=False)
                            for block in content if isinstance(block, dict))
    sections = message.get("sections") or {}
    return "\n".join([str(content)] + [str(value) for value in sections.values()])


class AnthropicWire:
    """A local Anthropic Messages endpoint for Pi's real client.

    It enforces the request rules the real API rejects with HTTP 400 (the class of bug that
    stopped the first Qwen v5 run), records every payload, and streams scripted replies:
    each reply is {"text": str} or {"tool": name, "input": dict}. After the script it says "done".
    """

    def __init__(self, replies: list[dict], fail_first: int = 0):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.replies = list(replies)
        self.fail_first = fail_first
        self.payloads: list[dict] = []
        self.raw_bodies: list[bytes] = []
        self.rejections: list[str] = []
        wire = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                wire.raw_bodies.append(raw)
                body = json.loads(raw)
                wire.payloads.append(body)
                if wire.fail_first:
                    wire.fail_first -= 1
                    data = json.dumps({"type": "error", "error": {"type": "api_error",
                                                                 "message": "internal server error 500"}})
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data.encode())
                    return
                problem = wire.invalid(body)
                if problem:
                    wire.rejections.append(problem)
                    data = json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": problem}})
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(data.encode())
                    return
                reply = wire.replies.pop(0) if wire.replies else {"text": "done"}
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for event in wire.events(body, reply):
                    self.wfile.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def invalid(body: dict) -> str | None:
        limit = body.get("max_tokens")
        if not isinstance(limit, int) or limit < 1:
            return "max_tokens: field required"
        thinking = body.get("thinking") or {}
        if thinking.get("type") == "enabled":
            budget = thinking.get("budget_tokens")
            if not isinstance(budget, int) or budget < 1024:
                return "thinking.budget_tokens: must be at least 1024"
            if budget >= limit:
                return "`max_tokens` must be greater than `thinking.budget_tokens`"
        return None

    @staticmethod
    def events(body: dict, reply: dict) -> list[dict]:
        usage = {"input_tokens": 300, "output_tokens": 1, "cache_read_input_tokens": 4000,
                 "cache_creation_input_tokens": 100}
        events = [{"type": "message_start", "message": {"id": "msg_offline", "type": "message", "role": "assistant",
                   "model": body.get("model"), "content": [], "stop_reason": None, "stop_sequence": None,
                   "usage": usage}}]
        index = 0
        if reply.get("redacted"):
            events += [{"type": "content_block_start", "index": index, "content_block": {
                           "type": "redacted_thinking", "data": reply["redacted"]}},
                       {"type": "content_block_stop", "index": index}]
            index += 1
        if "tool" in reply:
            events += [{"type": "content_block_start", "index": index, "content_block": {
                           "type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:12]}", "name": reply["tool"], "input": {}}},
                       {"type": "content_block_delta", "index": index,
                        "delta": {"type": "input_json_delta", "partial_json": json.dumps(reply["input"])}}]
            stop = "tool_use"
        else:
            events += [{"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
                       {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": reply["text"]}}]
            stop = "end_turn"
        return events + [{"type": "content_block_stop", "index": index},
                         {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                          "usage": {"output_tokens": 40}},
                         {"type": "message_stop"}]

    def close(self) -> None:
        self.server.shutdown()
