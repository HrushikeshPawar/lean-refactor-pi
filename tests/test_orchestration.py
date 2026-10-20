"""Offline run-control journeys. No provider, Pi, or Lean process."""

import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import orchestration, pi_rpc, run_control


def _request(directory: Path, request_id: str, actor_id: str, job_id: str) -> None:
    run_control.prepare_request(
        directory,
        {
            "request_id": request_id,
            "run_id": "run-1",
            "actor_id": actor_id,
            "session_id": f"{actor_id}-session",
            "job_id": job_id,
        },
    )


class V8ControlSmokeTests(unittest.TestCase):
    def test_v8_shared_settlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            identity = {"request_id": "body-check", "run_id": "run-1", "actor_id": "sol", "session_id": "sol-session"}
            prepared = {**identity, "body": {"prompt": "first"}}
            run_control.prepare_request(directory, prepared)
            self.assertTrue(run_control.prepare_request(directory, prepared)["reused"])
            changed = run_control.prepare_request(directory, {**prepared, "body": {"prompt": "changed"}})
            self.assertEqual(changed["status"], "operation_conflict")
            _request(directory, "sol-call", "sol", "sol-job")
            _request(directory, "worker-a", "worker", "job-a")
            _request(directory, "worker-b", "worker", "job-a")
            _request(directory, "worker-missing", "worker", "job-b")
            _request(directory, "worker-zero", "worker", "job-b")
            _request(directory, "worker-cancelled", "worker", "job-c")

            # The worker finishes first. Its grouped compaction covers both of its calls once.
            first = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-worker",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-a",
                    "covered_request_ids": ["worker-b", "worker-a"],
                    "candidate_ids": ["proof-1", "proof-2"],
                    "state": "known",
                    "amount": "1.00",
                    "usage": {"cost": {"total": 1}},
                },
            )
            self.assertEqual(first["total"], "1.00")
            self.assertFalse(first["stopped"])
            self.assertEqual(first["by_actor"]["worker"], "1.00")
            self.assertEqual(first["by_job"]["job-a"], "1.00")

            crossing = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-sol",
                    "run_id": "run-1",
                    "actor_id": "sol",
                    "session_id": "sol-session",
                    "job_id": "sol-job",
                    "covered_request_ids": ["sol-call"],
                    "state": "known",
                    "amount": "1.50",
                    "usage": {"cost": {"total": 1.5}},
                },
            )
            self.assertEqual(crossing["total"], "2.50")
            self.assertTrue(crossing["stop_transition"])
            self.assertEqual(crossing["stop_reason"], "spend_threshold")

            replayed = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-sol",
                    "run_id": "run-1",
                    "actor_id": "sol",
                    "session_id": "sol-session",
                    "job_id": "sol-job",
                    "covered_request_ids": ["sol-call"],
                    "state": "known",
                    "amount": "1.50",
                    "usage": {"cost": {"total": 1.5}},
                },
            )
            self.assertTrue(replayed["reused"])
            self.assertEqual(replayed["total"], "2.50")
            self.assertFalse(replayed["stop_transition"])

            overlap = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-overlap",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-a",
                    "covered_request_ids": ["worker-a"],
                    "state": "known",
                    "amount": "1.00",
                    "usage": {},
                },
            )
            self.assertEqual(overlap["status"], "operation_conflict")

            missing = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-missing",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-b",
                    "covered_request_ids": ["worker-missing"],
                    "state": "unknown",
                    "amount": "0",
                    "usage": {},
                },
            )
            self.assertEqual(missing["total"], "2.50")
            self.assertEqual(missing["accounting"], "unknown")
            self.assertIn("worker-missing", missing["unknown_requests"])
            self.assertFalse(missing["stop_transition"])

            zero = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-zero",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-b",
                    "covered_request_ids": ["worker-zero"],
                    "state": "known",
                    "amount": "0",
                    "usage": {"cost": {"total": 0}},
                },
            )
            self.assertEqual(zero["total"], "2.50")
            self.assertEqual(zero["accounting"], "unknown")
            self.assertNotIn("worker-zero", zero["unknown_requests"])

            cancelled = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-cancelled",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-c",
                    "covered_request_ids": ["worker-cancelled"],
                    "state": "known",
                    "amount": "0.20",
                    "transport": "cancelled",
                    "usage": {"cost": {"total": 0.2}},
                },
            )
            self.assertEqual(cancelled["total"], "2.70")
            self.assertFalse(cancelled["stop_transition"])

            reconciliation = {
                "reconciles": "settle-missing",
                "run_id": "run-1",
                "actor_id": "worker",
                "session_id": "worker-session",
                "job_id": "job-b",
                "covered_request_ids": ["worker-missing"],
                "state": "known",
                "amount": "0.05",
            }
            incomplete = run_control.settle_usage(
                directory,
                {**reconciliation, "settlement_id": "recon-incomplete", "usage": {}},
            )
            self.assertEqual(incomplete["accounting"], "unknown")
            self.assertEqual(incomplete["total"], "2.70")
            reconciled = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "recon-missing",
                    "reconciles": "settle-missing",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-b",
                    "covered_request_ids": ["worker-missing"],
                    "state": "known",
                    "amount": "0.05",
                    "usage": {"cost": {"total": 0.05}},
                },
            )
            self.assertEqual(reconciled["total"], "2.75")
            self.assertEqual(reconciled["accounting"], "known")
            self.assertEqual(reconciled["unknown_requests"], [])
            self.assertEqual(reconciled["by_actor"]["sol"], "1.50")
            self.assertEqual(reconciled["by_actor"]["worker"], "1.25")

            state = run_control.read_state(directory)
            self.assertEqual(state["total"], "2.75")
            self.assertEqual(state["stops"], ["spend_threshold"])
            self.assertEqual(state["settlements"]["settle-missing"]["state"], "unknown")
            projection = json.loads((directory / "cost.json").read_text())
            self.assertEqual(projection["spent_usd"], "2.75")
            self.assertEqual(projection["projection_of"], "control.jsonl")
            self.assertNotEqual(projection.get("written_by"), "runner_ledger_reconstruction")

            recovery = directory / "recovery"
            _request(recovery, "crossing", "sol", "sol-job")
            crossing_charge = {
                "settlement_id": "crossing-charge",
                "run_id": "run-1",
                "actor_id": "sol",
                "session_id": "sol-session",
                "covered_request_ids": ["crossing"],
                "state": "known",
                "amount": "2.50",
                "usage": {"cost": {"total": "2.50"}},
            }
            append = run_control._append_control

            def interrupt_stop(path, event):
                if event["kind"] == "run_stop":
                    raise RuntimeError("stop append interrupted")
                return append(path, event)

            with (
                patch.object(run_control, "_append_control", side_effect=interrupt_stop),
                self.assertRaisesRegex(RuntimeError, "stop append interrupted"),
            ):
                run_control.settle_usage(recovery, crossing_charge)
            repaired = run_control.settle_usage(recovery, crossing_charge)
            self.assertTrue(repaired["reused"])
            self.assertTrue(repaired["stopped"])
            self.assertEqual(repaired["stops"], ["spend_threshold"])
            self.assertEqual(repaired["total"], "2.50")

            partial = directory / "partial"
            _request(partial, "partial-write", "sol", "sol-job")
            write = run_control.os.write
            with patch.object(
                run_control.os, "write", side_effect=lambda fd, data: write(fd, data[: max(1, len(data) // 2)])
            ):
                settled = run_control.settle_usage(
                    partial,
                    {
                        **crossing_charge,
                        "settlement_id": "partial-charge",
                        "covered_request_ids": ["partial-write"],
                        "amount": "0.01",
                        "usage": {"cost": {"total": "0.01"}},
                    },
                )
            self.assertEqual(settled["total"], "0.01")
            torn = b'{"kind":"settlement","incomplete":"\xc3'
            with (partial / "control.jsonl").open("ab") as ledger:
                ledger.write(torn)
            _request(partial, "after-torn", "sol", "sol-job")
            self.assertIn(torn + b"\n", (partial / "control.jsonl").read_bytes())
            self.assertIn("after-torn", run_control._prepared(run_control._control_rows(partial)))

            failed = directory / "unknown"
            _request(failed, "unknown-call", "worker", "job-a")
            unknown_charge = {
                "settlement_id": "unknown-charge",
                "run_id": "run-1",
                "actor_id": "worker",
                "session_id": "worker-session",
                "covered_request_ids": ["unknown-call"],
                "state": "unknown",
                "irreconcilable": True,
            }

            def interrupt_failure(path, event):
                if event["kind"] == "accounting_failure":
                    raise RuntimeError("failure append interrupted")
                return append(path, event)

            with (
                patch.object(run_control, "_append_control", side_effect=interrupt_failure),
                self.assertRaisesRegex(RuntimeError, "failure append interrupted"),
            ):
                run_control.settle_usage(failed, unknown_charge)
            self.assertTrue(run_control.settle_usage(failed, unknown_charge)["reused"])
            failure = run_control.read_state(failed)
            self.assertEqual(failure["accounting_failures"][0]["category"], "accounting_unknown")
            self.assertEqual(failure["total"], "0")
            self.assertEqual(failure["accounting"], "unknown")
            self.assertEqual(len(failure["accounting_failures"]), 1)


class _HeldChild:
    def __init__(self):
        self.order = []
        self.written = bytearray()
        self._chunks = queue.Queue()

    def subscribe(self):
        self.order.append("subscribe")

    def write(self, data: bytes):
        if self.order != ["subscribe"]:
            raise RuntimeError("prompt before subscribe")
        self.order.append("write")
        self.written += data

    def read(self, _size: int) -> bytes:
        item = self._chunks.get()
        return b"" if item is None else item


class V8WorkerSmokeTests(unittest.TestCase):
    def test_v8_one_worker_receipt(self):
        reader = pi_rpc.FrameReader()
        text = "line\u2028sep\u2029end"
        raw = (json.dumps({"type": "response", "data": {"text": text}}, ensure_ascii=False) + "\n").encode()
        split = raw.index("\u2028".encode()) + 1
        self.assertEqual(reader.feed(raw[:split]), [])
        self.assertEqual(reader.feed(raw[split:])[0]["data"]["text"], text)
        crlf = (json.dumps({"type": "agent_settled", "id": "session-event"}) + "\r\n").encode()
        self.assertEqual(reader.feed(crlf[:5]), [])
        self.assertEqual(reader.feed(crlf[5:]), [{"type": "agent_settled", "id": "session-event"}])

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            child = _HeldChild()
            opened = {"count": 0, "receipt": False}

            def open_child():
                opened["count"] += 1
                rows = (directory / "control.jsonl").read_text()
                opened["receipt"] = '"kind":"operation_receipt"' in rows
                return child

            anchor = {"node": "proof-node", "steps": [1, 2]}
            call = {
                "operation_id": "op-fresh",
                "run_id": "run-1",
                "actor_id": "sol",
                "session_id": "sol-session",
                "task": "try the step",
                "scope": "step",
                "anchor": anchor,
                "open_child": open_child,
            }
            receipt = orchestration.delegate(directory, **call)
            self.assertTrue(opened["receipt"])
            self.assertEqual(opened["count"], 1)
            self.assertEqual(child.order, ["subscribe", "write"])
            self.assertTrue(receipt["ok"])
            self.assertEqual(receipt["state"], "launching")
            self.assertEqual(receipt["anchor"], {"node": "proof-node", "steps": [1, 2]})
            self.assertEqual(receipt["tools"], ["compile", "goal", "search", "read", "scratch"])
            self.assertNotEqual(receipt["job_id"], receipt["activation_id"])
            self.assertTrue(orchestration.awaits_settlement(directory, receipt["activation_id"]))
            again = orchestration.delegate(directory, **call)
            self.assertEqual(opened["count"], 1)
            self.assertTrue(again["reused"])
            self.assertEqual(again["job_id"], receipt["job_id"])
            conflict = orchestration.delegate(directory, **{**call, "task": "other task"})
            self.assertEqual(conflict["category"], "operation_conflict")
            self.assertEqual(opened["count"], 1)
            anchor["steps"][0] = 9
            view = orchestration.jobs(directory, [receipt["job_id"]])
            self.assertEqual(view["jobs"][0]["anchor"]["steps"], [1, 2])
            self.assertNotEqual(view["jobs"][0]["command_id"], receipt["activation_id"])
            self.assertIn(view["jobs"][0]["command_id"].encode(), child.written)

            handled = {
                "type": "response",
                "id": view["jobs"][0]["command_id"],
                "command": "prompt",
                "success": True,
                "data": {"disposition": "handled"},
            }
            child._chunks.put((json.dumps(handled) + "\n").encode())
            child._chunks.put(None)
            orchestration.join_activation(receipt["activation_id"])
            settled = orchestration.jobs(directory, [receipt["job_id"]])["jobs"][0]
            self.assertEqual(settled["state"], "handled")
            self.assertFalse(orchestration.awaits_settlement(directory, receipt["activation_id"]))

        # A child may answer before write returns. Exercise both event orders,
        # including a rejected prompt that never has an agent_settled event.
        scenarios = (
            ("started", False, "completed"),
            ("queued", True, "completed"),
            ("handled", False, "handled"),
            ("rejected", False, "failed"),
        )
        for disposition, settle_first, expected in scenarios:
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                child = _HeldChild()

                def immediate_write(data):
                    child.written.extend(data)
                    command = json.loads(data)
                    response = {
                        "type": "response", "id": command["id"], "command": "prompt",
                        "success": disposition != "rejected",
                        "data": {"disposition": disposition},
                    }
                    records = [response]
                    if expected == "completed":
                        records.insert(0 if settle_first else 1, {"type": "agent_settled"})
                    records.append({
                        "type": "response", "id": command["id"], "success": True,
                        "data": {"disposition": "started"},
                    })
                    child._chunks.put(b"".join((json.dumps(row) + "\n").encode() for row in records))
                    child._chunks.put(b"invalid late stdout\n")
                    child._chunks.put(None)
                    activation = orchestration.jobs(directory)["jobs"][0]["activation_id"]
                    orchestration.join_activation(activation)

                child.write = immediate_write
                result = orchestration.delegate(directory, **{
                    **call, "anchor": {"node": "proof-node", "steps": [1, 2]}, "open_child": lambda: child,
                })
                self.assertEqual(result["state"], expected)
                self.assertFalse(orchestration.awaits_settlement(directory, result["activation_id"]))
                retry = orchestration.delegate(directory, **{
                    **call, "anchor": {"node": "proof-node", "steps": [1, 2]}, "open_child": lambda: self.fail("respawn"),
                })
                self.assertEqual(retry["state"], expected)

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)

            def broken_child():
                raise OSError("cannot open child")

            result = orchestration.delegate(directory, **{
                **call, "anchor": {"node": "proof-node", "steps": [1, 2]}, "open_child": broken_child,
            })
            self.assertEqual(result["state"], "failed")
            self.assertFalse(orchestration.awaits_settlement(directory, result["activation_id"]))

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            child = _HeldChild()
            flushed = []

            def partial_write(data):
                size = min(7, len(data))
                child.written.extend(data[:size])
                return size

            child.write = partial_write
            child.flush = lambda: flushed.append(True)
            result = orchestration.delegate(directory, **{
                **call, "anchor": {"node": "proof-node", "steps": [1, 2]}, "open_child": lambda: child,
            })
            self.assertEqual(json.loads(child.written)["message"], "try the step")
            self.assertEqual(flushed, [True])
            child._chunks.put(None)
            orchestration.join_activation(result["activation_id"])
            self.assertEqual(orchestration.jobs(directory)["jobs"][0]["state"], "failed")

            # Interrupted ledger writes are not published without their receipt.
            with (directory / "ledger.jsonl").open("a") as ledger:
                ledger.write(json.dumps({
                    "type": "delegation", "operation_id": "uncommitted", "job_id": "phantom",
                }) + "\n")
            self.assertEqual(len(orchestration.jobs(directory)["jobs"]), 1)
