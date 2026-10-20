"""Offline run-control journeys. No provider, Pi, or Lean process."""

import hashlib
import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import orchestration, pi_rpc, run_control
from arena.steps import split_steps

_PROOF = "theorem demo : True ∧ True := by\n  trivial\n  trivial\n"


def _seed_parent(directory: Path) -> None:
    (directory / "run-config.json").write_text(json.dumps({"theorem": "demo", "model": "gpt-6-sol"}))
    (directory / "proofs").mkdir(parents=True)
    (directory / "proofs" / "parent.lean").write_text(_PROOF)
    (directory / "ledger.jsonl").write_text(
        json.dumps({"kind": "candidate", "candidate_id": "parent", "origin": "model"}) + "\n"
    )


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
            _seed_parent(directory)
            child = _HeldChild()
            opened = {"count": 0, "receipt": False, "launch": None}

            def open_child(launch):
                opened["count"] += 1
                opened["launch"] = launch
                rows = (directory / "control.jsonl").read_text()
                opened["receipt"] = '"kind":"operation_receipt"' in rows
                return child

            anchor = {"node": "n1", "steps": [1, 2], "proof_hash": "not-the-file"}
            missing = orchestration.delegate(
                directory,
                operation_id="op-missing",
                run_id="run-1",
                actor_id="sol",
                session_id="sol-session",
                task="try the step",
                scope="step",
                anchor={"node": "missing", "steps": [1, 2]},
                open_child=open_child,
            )
            self.assertEqual(missing["category"], "invalid_input")
            self.assertEqual(opened["count"], 0)
            out_of_range = orchestration.delegate(
                directory,
                operation_id="op-range",
                run_id="run-1",
                actor_id="sol",
                session_id="sol-session",
                task="try the step",
                scope="step",
                anchor={"node": "n1", "steps": [1, 9]},
                open_child=open_child,
            )
            self.assertEqual(out_of_range["reason"], "steps")
            self.assertEqual(opened["count"], 0)
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
            parsed = split_steps(_PROOF)
            self.assertEqual(receipt["anchor"]["node"], "n1")
            self.assertEqual(receipt["anchor"]["proof_id"], "parent")
            self.assertEqual(receipt["anchor"]["steps"], [1, 2])
            self.assertEqual(receipt["anchor"]["proof_sha256"], hashlib.sha256(_PROOF.encode()).hexdigest())
            self.assertNotIn("not-the-file", json.dumps(receipt["anchor"]))
            self.assertEqual(receipt["anchor"]["source"]["first_line"], parsed[0].first_line)
            self.assertEqual(receipt["anchor"]["source"]["last_line"], parsed[1].last_line)
            self.assertEqual(receipt["anchor"]["step_hashes"], [parsed[0].hash, parsed[1].hash])
            launch = opened["launch"]
            self.assertEqual(launch["model"], "deepseek-v4.1-flash")
            self.assertEqual(launch["provider"], "opencode-go")
            self.assertEqual(launch["tools"], ["compile", "goal", "search", "read", "scratch"])
            self.assertEqual(launch["argv"][launch["argv"].index("--mode") + 1], "rpc")
            self.assertIn("--no-builtin-tools", launch["argv"])
            extension = Path(launch["argv"][launch["argv"].index("--extension") + 1])
            self.assertEqual(extension.name, "arena.ts")
            self.assertTrue(extension.is_file())
            self.assertIn("--no-extensions", launch["argv"])
            self.assertEqual(
                launch["argv"][launch["argv"].index("--tools") + 1],
                "compile,goal,search,read,scratch",
            )
            self.assertTrue(launch["session_dir"].endswith(receipt["session_id"]))
            self.assertEqual(launch["env"]["ARENA_RUN_ID"], "run-1")
            self.assertEqual(launch["env"]["ARENA_RUN_DIR"], str(directory))
            self.assertEqual(launch["env"]["ARENA_MODEL"], "deepseek-v4.1-flash")
            self.assertEqual(launch["env"]["ARENA_PI_MODEL_ID"], "deepseek-v4.1-flash")
            self.assertEqual(launch["env"]["ARENA_BUDGET_REQUIRED"], "1")
            self.assertEqual(launch["env"]["ARENA_AUTOCONTINUE"], "0")
            self.assertEqual(launch["env"]["ARENA_WORKER_THEOREM"], "demo")
            self.assertEqual(launch["env"]["ARENA_JOB_ID"], receipt["job_id"])
            self.assertEqual(launch["env"]["ARENA_ACTIVATION_ID"], receipt["activation_id"])
            self.assertNotEqual(launch["env"]["ARENA_ACTOR_ID"], "sol")
            self.assertEqual(launch["actor_id"], launch["env"]["ARENA_ACTOR_ID"])
            prompt = json.loads(child.written)
            self.assertNotIn("tools", prompt)
            self.assertIn(receipt["anchor"]["proof_sha256"], prompt["message"])
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
            self.assertEqual(view["jobs"][0]["anchor"]["proof_sha256"], receipt["anchor"]["proof_sha256"])
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
                _seed_parent(directory)
                child = _HeldChild()

                def immediate_write(
                    data, child=child, disposition=disposition, expected=expected,
                    settle_first=settle_first, directory=directory,
                ):
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
                    **call,
                    "anchor": {"node": "n1", "steps": [1, 2]},
                    "open_child": lambda _launch, child=child: child,
                })
                self.assertEqual(result["state"], expected)
                self.assertFalse(orchestration.awaits_settlement(directory, result["activation_id"]))
                retry = orchestration.delegate(directory, **{
                    **call,
                    "anchor": {"node": "n1", "steps": [1, 2]},
                    "open_child": lambda _launch: self.fail("respawn"),
                })
                self.assertEqual(retry["state"], expected)

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)

            def broken_child(_launch):
                raise OSError("cannot open child")

            result = orchestration.delegate(directory, **{
                **call,
                "operation_id": "op-broken",
                "anchor": {"node": "n1", "steps": [1, 2]},
                "open_child": broken_child,
            })
            self.assertEqual(result["state"], "failed")
            self.assertFalse(orchestration.awaits_settlement(directory, result["activation_id"]))

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            child = _HeldChild()
            flushed = []

            def partial_write(data):
                size = min(7, len(data))
                child.written.extend(data[:size])
                return size

            child.write = partial_write
            child.flush = lambda: flushed.append(True)
            result = orchestration.delegate(directory, **{
                **call,
                "operation_id": "op-partial",
                "anchor": {"node": "n1", "steps": [1, 2]},
                "open_child": lambda _launch: child,
            })
            self.assertTrue(json.loads(child.written)["message"].startswith("try the step\n"))
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

    def test_v8_early_result_followup(self):
        """A passing compile is visible before settlement, then the same session resumes."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            children = []

            def open_child(launch):
                child = _HeldChild()
                children.append((launch, child))
                return child

            call = {
                "operation_id": "op-fresh",
                "run_id": "run-1",
                "actor_id": "sol",
                "session_id": "sol-session",
                "task": "try the step",
                "scope": "step",
                "anchor": {"node": "n1", "steps": [1, 2]},
                "open_child": open_child,
            }
            fresh = orchestration.delegate(directory, **call)
            self.assertEqual(len(children), 1)
            busy = orchestration.delegate(
                directory,
                operation_id="op-busy",
                run_id="run-1",
                actor_id="sol",
                session_id="sol-session",
                task="keep going",
                job_id=fresh["job_id"],
                open_child=open_child,
            )
            self.assertEqual(busy["category"], "busy")
            self.assertEqual(len(children), 1)
            changed = orchestration.delegate(
                directory,
                operation_id="op-anchor",
                run_id="run-1",
                actor_id="sol",
                session_id="sol-session",
                task="replace the anchor",
                job_id=fresh["job_id"],
                scope="step",
                anchor={"node": "n1", "steps": [2, 2]},
                open_child=open_child,
            )
            self.assertEqual(changed["category"], "invalid_input")
            self.assertEqual(len(children), 1)

            command_id = orchestration.jobs(directory, [fresh["job_id"]])["jobs"][0]["command_id"]
            candidate = {
                "type": "tool_result",
                "name": "compile",
                "passed": True,
                "attempt_id": "attempt-1",
                "proof_id": "proof-1",
                "evaluation_id": "eval-1",
                "request_id": "req-1",
            }
            started = {
                "type": "response",
                "id": command_id,
                "success": True,
                "data": {"disposition": "started"},
            }
            child = children[0][1]
            child._chunks.put((json.dumps(started) + "\n" + json.dumps(candidate) + "\n").encode())

            def published():
                view = orchestration.jobs(directory, [fresh["job_id"]])["jobs"][0]
                if view["state"] == "active" and view["findings"]:
                    return view
                return None

            active = None
            for _ in range(20000):
                active = published()
                if active is not None:
                    break
            self.assertIsNotNone(active)
            finding = active["findings"][0]
            self.assertEqual(finding["activation_id"], fresh["activation_id"])
            self.assertEqual(finding["request_id"], "req-1")
            self.assertEqual(finding["attempt_id"], "attempt-1")
            self.assertEqual(finding["proof_id"], "proof-1")
            self.assertEqual(finding["evaluation_id"], "eval-1")
            delivered = orchestration.deliver(directory, "sol")
            self.assertEqual(delivered["results"][0]["proof_id"], "proof-1")
            self.assertFalse(delivered["results"][0]["resumed"])
            self.assertEqual(delivered["results"][0]["session_id"], fresh["session_id"])
            self.assertFalse(delivered["stopped"])

            child._chunks.put((json.dumps({"type": "agent_settled"}) + "\n").encode())
            child._chunks.put(None)
            orchestration.join_activation(fresh["activation_id"])
            released = orchestration.jobs(directory, [fresh["job_id"]])["jobs"][0]
            self.assertEqual(released["state"], "completed")
            self.assertEqual(released["session_id"], fresh["session_id"])
            self.assertEqual(released["findings"][0]["attempt_id"], "attempt-1")
            self.assertFalse(orchestration.awaits_settlement(directory, fresh["activation_id"]))
            self.assertFalse(run_control.read_state(directory)["stopped"])

            follow = orchestration.delegate(
                directory,
                operation_id="op-follow",
                run_id="run-1",
                actor_id="sol",
                session_id="sol-session",
                task="narrow the same step",
                job_id=fresh["job_id"],
                open_child=open_child,
            )
            self.assertTrue(follow["ok"])
            self.assertTrue(follow["resumed"])
            self.assertEqual(follow["job_id"], fresh["job_id"])
            self.assertEqual(follow["session_id"], fresh["session_id"])
            self.assertNotEqual(follow["activation_id"], fresh["activation_id"])
            self.assertEqual(follow["anchor"], fresh["anchor"])
            self.assertEqual(children[1][0]["session_dir"], children[0][0]["session_dir"])
            self.assertEqual(children[1][0]["env"]["ARENA_ACTIVATION_ID"], follow["activation_id"])
            self.assertEqual(children[1][0]["env"]["ARENA_SESSION_ID"], fresh["session_id"])
            resumed_view = orchestration.jobs(directory, [fresh["job_id"]])["jobs"][0]
            self.assertEqual(resumed_view["hypothesis"], "try the step")
            self.assertEqual(resumed_view["anchor"], fresh["anchor"])
            self.assertEqual(len(resumed_view["activations"]), 2)
            overlap = orchestration.delegate(
                directory,
                operation_id="op-overlap",
                run_id="run-1",
                actor_id="sol",
                session_id="sol-session",
                task="second prompt",
                job_id=fresh["job_id"],
                open_child=open_child,
            )
            self.assertEqual(overlap["category"], "busy")
            self.assertEqual(len(children), 2)

            follow_command = resumed_view["command_id"]
            later = {
                "type": "candidate",
                "passed": True,
                "attempt_id": "attempt-2",
                "proof_id": "proof-2",
                "evaluation_id": "eval-2",
                "request_id": "req-2",
            }
            follow_child = children[1][1]
            follow_child._chunks.put(
                (
                    json.dumps({
                        "type": "response",
                        "id": follow_command,
                        "success": True,
                        "data": {"disposition": "started"},
                    })
                    + "\n"
                    + json.dumps(later)
                    + "\n"
                ).encode()
            )
            resumed_finding = None
            for _ in range(20000):
                delivered = orchestration.deliver(directory, "sol")
                match = [item for item in delivered["results"] if item["attempt_id"] == "attempt-2"]
                if match and match[0]["resumed"]:
                    resumed_finding = match[0]
                    break
            self.assertIsNotNone(resumed_finding)
            self.assertEqual(resumed_finding["activation_id"], follow["activation_id"])
            self.assertEqual(resumed_finding["session_id"], fresh["session_id"])
            self.assertEqual(resumed_finding["request_id"], "req-2")
            follow_child._chunks.put((json.dumps({"type": "assignment_exhausted"}) + "\n").encode())
            follow_child._chunks.put(None)
            orchestration.join_activation(follow["activation_id"])
            exhausted = orchestration.jobs(directory, [fresh["job_id"]])["jobs"][0]
            self.assertEqual(exhausted["state"], "exhausted")
            self.assertEqual(exhausted["session_id"], fresh["session_id"])
            self.assertEqual(len(exhausted["findings"]), 2)
            self.assertFalse(run_control.read_state(directory)["stopped"])

            other = orchestration.delegate(
                directory,
                operation_id="op-other",
                run_id="run-1",
                actor_id="sol",
                session_id="sol-session",
                task="a different hypothesis",
                scope="proof",
                anchor={"node": "n1"},
                open_child=open_child,
            )
            self.assertNotEqual(other["job_id"], fresh["job_id"])
            self.assertNotEqual(other["session_id"], fresh["session_id"])
            self.assertNotEqual(children[2][0]["session_dir"], children[0][0]["session_dir"])
            both = orchestration.jobs(directory)
            sessions = {job["job_id"]: job["session_id"] for job in both["jobs"]}
            self.assertEqual(sessions[fresh["job_id"]], fresh["session_id"])
            self.assertEqual(sessions[other["job_id"]], other["session_id"])
            children[2][1]._chunks.put(None)
            orchestration.join_activation(other["activation_id"])
