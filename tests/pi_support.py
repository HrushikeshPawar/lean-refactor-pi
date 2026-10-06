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
                 run_id: str | None = None, timeout: int = 240):
        self.run_id = run_id or f"test-{uuid.uuid4().hex[:10]}"
        self.directory = run_dir(self.run_id)
        self.work = Path(tempfile.mkdtemp())
        self.script = self.work / "script.json"
        self.script.write_text(json.dumps(steps))
        self.log = self.work / "requests.jsonl"
        self.command = [sys.executable, "tools/run_pi_budgeted.py", "--model", "gpt-6-luna",
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

    def start(self, *extra: str) -> subprocess.Popen:
        """Launch without waiting, for tests that signal the runner."""
        self.process = subprocess.Popen([*self.command, *extra], cwd=ROOT, env=self.env, text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
