"""Trace judge, plugin patch check, and the paid-matrix preflight gate."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from arena.engine import ROOT
from arena.traces import (
    ORIG_PLUGIN,
    PATCH_SHA256,
    judge,
    plugin_problems,
    preflight_block,
    preflight_problems,
    redact,
    write_receipt,
)
from tests.pi_support import LIVE_LANGFUSE, NAME


def _request(identifier: str, payload: dict, ts: int, retry_of: str | None = None) -> dict:
    return {"kind": "request", "id": identifier, "ts": ts, "model": "qwen3.8-flash",
            "retry_of": retry_of, "post_hook": payload}


def _wire(identifier: str, payload: dict, index: int = 0) -> dict:
    return {"kind": "wire", "id": identifier, "retry_index": index, "body": json.dumps(payload)}


def _generation(payload: dict, text: str, start: str, cost: float = 0.01,
                tool_calls: list[dict] | None = None) -> dict:
    output = {"role": "assistant", **({"content": text} if text else {}),
              **({"tool_calls": tool_calls} if tool_calls else {})}
    return {"type": "GENERATION", "name": "LLM Call", "id": f"obs-{start}", "traceId": "trace-1",
            "startTime": start, "sessionId": "run-1", "input": json.dumps(payload),
            "output": json.dumps(output),
            "usageDetails": {"input": 300, "output": 40, "cache_read_input_tokens": 4000,
                             "cache_creation_input_tokens": 100},
            "totalCost": cost,
            "metadata": {"assistant_text_meta": {"truncated": False, "orig_len": len(text)}}}


def _joined(payload: dict | None = None, text: str = "done") -> tuple[list[dict], list[dict]]:
    """One tool-call turn and one text turn, as the patched plugin exports them."""
    payload = payload or {"model": "qwen3.8-flash", "max_tokens": 2048, "messages": [{"role": "user", "content": "hi"}]}
    usage = {"input": 300, "output": 40, "cache_read": 4000, "cache_write": 100}
    call = {"type": "toolCall", "id": "c1", "name": "arena_skill_read", "arguments": {"page": 1}}
    journal = [
        _request("a", payload, 1), _wire("a", payload),
        {"kind": "response", "id": "a", "text": "", "content": [call], "stop_reason": "toolUse",
         "usage": dict(usage), "settled_usd": 0.01, "price_tier": "base", "pi_cost_usd": 0.01},
        {"kind": "tool_call", "id": "a", "tool_call_id": "c1", "name": "arena_skill_read", "args": {"page": 1}},
        {"kind": "tool_result", "id": "a", "tool_call_id": "c1", "name": "arena_skill_read", "text": "SKILL.md"},
        _request("b", payload, 2), _wire("b", payload),
        {"kind": "response", "id": "b", "text": text, "content": [{"type": "text", "text": text}],
         "stop_reason": "stop", "usage": dict(usage), "settled_usd": 0.01, "price_tier": "base", "pi_cost_usd": 0.01},
    ]
    observations = [
        _generation(payload, "", "2026-10-07T00:00:01Z", tool_calls=[{"id": "c1", "name": "arena_skill_read"}]),
        {"type": "TOOL", "name": "Tool: arena_skill_read", "id": "tool-1", "traceId": "trace-1",
         "startTime": "2026-10-07T00:00:02Z", "input": json.dumps({"page": 1}), "output": json.dumps("SKILL.md"),
         "metadata": {"tool_id": "c1", "tool_name": "arena_skill_read"}},
        _generation(payload, text, "2026-10-07T00:00:03Z"),
    ]
    return journal, observations


class JudgeTests(unittest.TestCase):
    def test_a_complete_trace_joins_and_key_redaction_matches_the_plugin(self):
        payload = {"model": "qwen3.8-flash", "messages": [{"role": "user", "content": "key pk-lf-abc secret"}]}
        journal, observations = _joined(payload, "answered")
        for item in observations:
            if item["type"] == "GENERATION":
                item["input"] = json.dumps(redact(payload))
        self.assertEqual(judge(journal, observations), [])
        self.assertEqual(redact({"nested": "sk-lf-xyz-1"}), {"nested": "[redacted-langfuse-secret]"})
        self.assertEqual(redact("offline-test"), "offline-test")

    def test_identical_retries_need_one_generation_each(self):
        payload = {"model": "qwen3.8-flash", "max_tokens": 16000}
        journal = [_request("a", payload, 1), _wire("a", payload),
                   {"kind": "response", "id": "a", "text": "", "stop_reason": "error", "settled_usd": None},
                   _request("b", payload, 2, retry_of="a"), _wire("b", payload),
                   {"kind": "response", "id": "b", "text": "ok",
                    "usage": {"input": 300, "output": 40, "cache_read": 4000, "cache_write": 100},
                    "settled_usd": 0.01, "price_tier": "base", "pi_cost_usd": 0.01}]
        one = [_generation(payload, "ok", "2026-10-07T00:00:02Z")]
        self.assertTrue(any("unjoinable" in item or "missing" in item for item in judge(journal, one)))
        both = [_generation(payload, "", "2026-10-07T00:00:01Z"),
                _generation(payload, "ok", "2026-10-07T00:00:02Z")]
        self.assertEqual(judge(journal, both), [])

    def test_a_request_without_its_wire_body_fails(self):
        journal, observations = _joined()
        journal = [row for row in journal if not (row["kind"] == "wire" and row["id"] == "a")]
        self.assertIn("missing wire body for request a", judge(journal, observations))
        journal, observations = _joined()
        journal.append({**_wire("a", {}), "retry_index": 2})
        self.assertTrue(any("retry indexes" in item for item in judge(journal, observations)))

    def test_a_tool_call_only_turn_is_still_compared(self):
        journal, observations = _joined()
        observations[0]["output"] = json.dumps({"role": "assistant", "tool_calls": [{"id": "c9", "name": "arena_skill_read"}]})
        self.assertTrue(any("tool calls do not match" in item for item in judge(journal, observations)))
        journal, observations = _joined()
        observations[0]["output"] = json.dumps({"role": "assistant", "content": "stray"})
        self.assertTrue(any("does not match journal text" in item for item in judge(journal, observations)))

    def test_tool_spans_join_by_call_id_and_compare_arguments(self):
        journal, observations = _joined()
        observations[1]["input"] = json.dumps({"page": 2})
        self.assertTrue(any("does not match arguments" in item for item in judge(journal, observations)))
        journal, observations = _joined()
        observations[1]["metadata"] = {"tool_id": "other"}
        self.assertTrue(any("no Langfuse tool span for call c1" in item for item in judge(journal, observations)))

    def test_langfuse_cost_must_equal_the_settled_ledger_cost(self):
        journal, observations = _joined()
        observations[2]["totalCost"] = 0.005
        self.assertTrue(any("does not equal settled" in item for item in judge(journal, observations)))
        journal[-1]["price_tier"] = "high"
        self.assertEqual(judge(journal, observations), [])

    def test_clipped_short_or_unpriced_observations_fail(self):
        journal, observations = _joined()
        observations[2]["metadata"] = {"assistant_text_meta": {"truncated": True, "orig_len": 50000, "kept_len": 20000}}
        self.assertTrue(any("truncated" in item for item in judge(journal, observations)))

        journal, observations = _joined(text="Z" * 50)
        observations[2]["output"] = json.dumps({"role": "assistant", "content": "Z" * 10})
        self.assertTrue(any("shorter" in item for item in judge(journal, observations)))

        journal, observations = _joined()
        observations = [item for item in observations if item["type"] != "TOOL"]
        self.assertTrue(any("tool" in item for item in judge(journal, observations)))

        journal, observations = _joined()
        journal[-1]["usage"]["output"] = 41
        observations[2]["usageDetails"] = {"input": 300, "output": 24, "output_reasoning_tokens": 17,
                                           "cache_read_input_tokens": 4000, "cache_creation_input_tokens": 100}
        self.assertEqual(judge(journal, observations), [])

    def test_a_text_only_preflight_is_missing_its_tool_span(self):
        journal, observations = _joined()
        journal = [row for row in journal if row["id"] != "a"]
        observations = [item for item in observations[2:]]
        self.assertEqual(judge(journal, observations), [])
        self.assertTrue(any("tool" in item for item in preflight_problems(journal, observations)))
        self.assertEqual(preflight_problems(*_joined()), [])


@unittest.skipUnless(ORIG_PLUGIN.joinpath("src/index.ts").is_file(),
                     "needs the original Langfuse plugin 0.1.2 backup under ~/.pi/agent/patches")
class PluginTests(unittest.TestCase):
    @unittest.skipUnless(LIVE_LANGFUSE, "set ARENA_LIVE_LANGFUSE=1 to check the installed plugin")
    def test_vendored_patch_reproduces_the_installed_plugin(self):
        self.assertEqual(plugin_problems(), [])

    def test_apply_repairs_an_unpatched_copy(self):
        from arena.traces import PATCH_PATH, apply_plugin

        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        installed = work / "installed"
        shutil.copytree(ORIG_PLUGIN, installed)
        self.assertTrue(plugin_problems(installed))
        self.assertEqual(apply_plugin(installed, ORIG_PLUGIN, PATCH_PATH), "patched")
        self.assertEqual(plugin_problems(installed, ORIG_PLUGIN, PATCH_PATH), [])
        self.assertEqual(apply_plugin(installed, ORIG_PLUGIN, PATCH_PATH), "already patched")


class ReceiptTests(unittest.TestCase):
    def test_receipt_is_owner_only_and_blocks_a_model_it_does_not_cover(self):
        path = Path(tempfile.mkdtemp()) / "preflight.json"
        self.addCleanup(shutil.rmtree, path.parent, True)
        write_receipt({"status": "pass", "patch_sha256": PATCH_SHA256,
                       "models": {"qwen3.8-flash": {"session_id": "s", "trace_ids": ["t"]}}}, path)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        previous = os.environ.get("ARENA_PREFLIGHT_RECEIPT")
        os.environ["ARENA_PREFLIGHT_RECEIPT"] = str(path)
        self.addCleanup(self._restore_receipt, previous)
        self.assertIsNone(preflight_block(["qwen3.8-flash"]))
        blocked = preflight_block(["qwen3.8-flash", "gpt-6-luna"])
        self.assertIn("gpt-6-luna", blocked or "")

    def _restore_receipt(self, previous: str | None) -> None:
        if previous is None:
            os.environ.pop("ARENA_PREFLIGHT_RECEIPT", None)
        else:
            os.environ["ARENA_PREFLIGHT_RECEIPT"] = previous


class MatrixGateTests(unittest.TestCase):
    def test_a_paid_matrix_refuses_without_a_passing_receipt(self):
        prefix = f"gate-{uuid.uuid4().hex[:8]}"
        missing = Path(tempfile.mkdtemp()) / "missing.json"
        self.addCleanup(shutil.rmtree, missing.parent, True)
        env = {**os.environ, "ARENA_PREFLIGHT_RECEIPT": str(missing)}
        proc = subprocess.run(
            [sys.executable, "tools/run_experiment_matrix.py", "--theorem", NAME, "--prefix", prefix,
             "--factor", "thinking", "--values", "low,high", "--cap", "0.1"],
            cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("preflight", proc.stderr.lower())
        self.assertFalse((ROOT / "runs" / "pi-budget" / f"{prefix}-matrix").exists())

    def test_a_dry_run_does_not_need_a_receipt(self):
        prefix = f"gate-{uuid.uuid4().hex[:8]}"
        missing = Path(tempfile.mkdtemp()) / "missing.json"
        self.addCleanup(shutil.rmtree, missing.parent, True)
        env = {**os.environ, "ARENA_PREFLIGHT_RECEIPT": str(missing)}
        proc = subprocess.run(
            [sys.executable, "tools/run_experiment_matrix.py", "--theorem", NAME, "--prefix", prefix,
             "--factor", "thinking", "--values", "low,high", "--dry-run"],
            cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(prefix, proc.stdout)
