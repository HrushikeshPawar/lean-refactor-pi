"""Offline run-control journeys. No provider, Pi, or Lean process."""

import contextlib
import hashlib
import importlib.util
import json
import queue
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import orchestration, pi_rpc, run_control, team_reply
from arena import reply as proof_reply
from arena.steps import split_steps
from tests.graph_support import FakeRunCase

_PROOF = "theorem demo : True ∧ True := by\n  trivial\n  trivial\n"


def setUpModule():
    # The fixture theorem "demo" is not a catalogued problem; its packet render has its own test in test_text.
    patcher = patch.object(orchestration, "_worker_packet", return_value="WORKER PACKET")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def _seed_parent(directory: Path) -> None:
    (directory / "run-config.json").write_text(json.dumps({"theorem": "demo", "model": "gpt-6-sol"}))
    (directory / "proofs").mkdir(parents=True)
    (directory / "proofs" / "parent.lean").write_text(_PROOF)
    (directory / "ledger.jsonl").write_text(
        json.dumps({"kind": "candidate", "candidate_id": "parent", "origin": "reference"}) + "\n"
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

    def test_v8_stop_submission_order(self):
        """A stop before submission leaves no candidate. A submission before the stop keeps its check."""
        from arena import campaign, tools
        from tests.test_tools_read_goal_search import ToolCase

        def stop(directory):
            if directory is None:
                return
            run_control._append_control(directory, {
                "schema_version": run_control.SCHEMA_VERSION,
                "kind": "run_stop",
                "event_id": "stop-barrier",
                "reason": "operator_interrupt",
            })

        def journey(barrier: str) -> dict:
            class _Holder(ToolCase):
                def runTest(self):
                    return None

            case = _Holder()
            case.setUp()
            try:
                parent = tools.compile_tool("T", "logic", {"drafts": ["by\n  sorry"]})["items"][0]["node"]
                before = [
                    row for row in campaign.events(case.directory) if row.get("kind") == "candidate"
                ]
                run_control.set_submission_barrier(barrier, stop)
                item = tools.scratch_tool("T", "logic", {
                    "replacement": "trivial", "at": {"node": parent, "steps": [1, 1]},
                })["items"][0]
                rows = campaign.events(case.directory)
                control = run_control._control_rows(case.directory)
                experiment = tools.experiments.retrieve("logic", item["experiment_id"])
                return {
                    "item": item, "before": before, "rows": rows, "control": control,
                    "experiment_code": experiment["code"],
                }
            finally:
                run_control.set_submission_barrier(barrier, None)
                case.doCleanups()

        stopped = journey("before_submission")
        self.assertEqual(stopped["item"]["promotion"]["state"], "not_promoted")
        self.assertEqual(stopped["item"]["promotion"]["reason"], "run_stopped")
        self.assertEqual(
            [row.get("candidate_id") for row in stopped["rows"] if row.get("kind") == "candidate"],
            [row.get("candidate_id") for row in stopped["before"]],
        )
        prior_ids = {row.get("candidate_id") for row in stopped["before"]}
        self.assertFalse(any(
            row.get("kind") == "evaluation_request" and row.get("proof_id") not in prior_ids
            for row in stopped["control"]
        ))
        self.assertTrue(stopped["experiment_code"])

        submitted = journey("after_submission")
        promotion = submitted["item"]["promotion"]
        self.assertTrue(promotion.get("attempt_id") or promotion.get("proof_id") or promotion.get("node"))
        new_ids = [
            row.get("candidate_id") for row in submitted["rows"] if row.get("kind") == "candidate"
        ]
        self.assertGreater(len(new_ids), len(submitted["before"]))
        requests = [
            row for row in submitted["control"]
            if row.get("kind") == "evaluation_request" and row.get("state") == "queued"
        ]
        self.assertTrue(requests)
        self.assertIn(requests[-1]["proof_id"], new_ids)


class _HeldChild:
    def __init__(self):
        self.order = []
        self.written = bytearray()
        self._chunks = queue.Queue()
        self.absent = False
        self.exit_on_eof = True

    def subscribe(self):
        self.order.append("subscribe")

    def write(self, data: bytes):
        if self.order != ["subscribe"]:
            raise RuntimeError("prompt before subscribe")
        self.order.append("write")
        self.written += data

    def read(self, _size: int) -> bytes:
        item = self._chunks.get()
        if item is None and self.exit_on_eof:
            self.absent = True
        return b"" if item is None else item

    def shutdown(self):
        self._chunks.put(None)

    def confirmed_absent(self):
        return self.absent

    def process_identity(self):
        return {"pid": id(self), "pgid": id(self), "start_id": f"fixture-{id(self)}"}


class AwaitTimeoutTests(unittest.TestCase):
    def test_await_returns_a_timeout_with_quiet_job_info_and_a_wait_end_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            child = _HeldChild()
            fresh = orchestration.delegate(
                directory, operation_id="timeout-worker", run_id="run-1", actor_id="sol",
                session_id="sol-session", task="try a route", scope="proof", anchor={"node": "n1"},
                open_child=lambda _launch: child,
            )
            try:
                with patch.dict("os.environ", {"ARENA_AWAIT_TIMEOUT_S": "0.3"}), \
                        patch.object(orchestration, "reconcile", return_value={"status": "running", "generation": "fixture"}):
                    started = time.monotonic()
                    reply = orchestration.await_results(directory, actor_id="sol")
                    elapsed = time.monotonic() - started
                self.assertGreaterEqual(elapsed, 0.25)
                self.assertLess(elapsed, 5)
                self.assertTrue(reply["ok"])
                self.assertEqual(reply["wake_reason"], "timeout")
                self.assertEqual(reply["events"], [])
                self.assertEqual([item["job_id"] for item in reply["quiet_jobs"]], [fresh["job_id"]])
                self.assertIn("No findings in 0 minutes", reply["message"])
                self.assertIn(fresh["job_id"], reply["message"])
                history = orchestration._history(directory)
                started_rows = [row for row in history if row.get("kind") == "wait"]
                ended = [row for row in history if row.get("kind") == "wait_end"]
                self.assertEqual([(row["wait_id"], row["wake_reason"]) for row in ended],
                                 [(started_rows[0]["wait_id"], "timeout")])
            finally:
                child._chunks.put(None)
                orchestration.join_activation(fresh["activation_id"], timeout=2)


class StreamDeltaTests(unittest.TestCase):
    def test_stream_deltas_never_take_the_control_lock(self):
        locks = []
        with patch.object(run_control, "control_lock", lambda _directory: locks.append(1) or contextlib.nullcontext()):
            orchestration._take(Path("."), {"activation_id": "a"}, "c", {"state": "active"},
                                [{"type": "message_update"}] * 500 + [{"type": "message_start"}])
        self.assertEqual(locks, [])


class V8OrphanSettlementTests(unittest.TestCase):
    def test_absent_worker_open_request_settles_unknown_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            child = _HeldChild()
            child.shutdown = lambda: None
            child.write = lambda data: child.written.extend(data)
            launches = []

            def open_child(launch):
                launches.append(launch)
                return child

            started = orchestration.delegate(
                directory, operation_id="op-orphan", run_id="run-1", actor_id="sol", session_id="sol-session",
                task="hang", scope="proof", anchor={"node": "n1"}, open_child=open_child,
            )
            session = launches[0]["env"]["ARENA_SESSION_ID"]
            attempt = {"request_id": "req-hung", "attempt_id": "att-hung", "run_id": "run-1",
                       "actor_id": launches[0]["env"]["ARENA_ACTOR_ID"], "session_id": session,
                       "job_id": started["job_id"], "generation": orchestration._control_generation(directory)}
            dispatched = run_control.begin_dispatch(directory, attempt, lambda: None)
            self.assertTrue(dispatched["admitted"], dispatched)
            self.assertTrue(orchestration._request_uncertain(directory, session))
            orchestration.cancel(directory, operation_id="op-cancel-orphan", run_id="run-1", actor_id="sol",
                                 session_id="sol-session", job_id=started["job_id"])
            child.exit_on_eof = False
            child.absent = True
            orchestration.observe_exit(directory, started["activation_id"])
            self.assertFalse(orchestration._request_uncertain(directory, session))
            settlements = [r for r in run_control._control_rows(directory) if r.get("kind") == "settlement"]
            self.assertEqual([(r["covered_request_ids"], r["state"]) for r in settlements], [(["req-hung"], "unknown")])
            delegation = next(d for d in orchestration._delegations(directory) if d["activation_id"] == started["activation_id"])
            orchestration._settle_orphans(directory, delegation)
            again = [r for r in run_control._control_rows(directory) if r.get("kind") == "settlement"]
            self.assertEqual(len(again), 1)


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
                    for _ in range(20000):
                        if orchestration.jobs(directory)["jobs"][0]["state"] == expected:
                            break
                    else:
                        self.fail("immediate response was not recorded")

                child.write = immediate_write
                result = orchestration.delegate(directory, **{
                    **call,
                    "anchor": {"node": "n1", "steps": [1, 2]},
                    "open_child": lambda _launch, child=child: child,
                })
                orchestration.join_activation(result["activation_id"])
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
            self.assertTrue(json.loads(child.written)["message"].startswith("WORKER PACKET\n"))
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

            def compile_event(index, launch):
                attempt_id, proof_id, evaluation_id = f"attempt-{index}", f"proof-{index}", f"eval-{index}"
                tool_call = f"compile-{index}"
                (directory / "proofs" / f"{proof_id}.lean").write_text(_PROOF)

                def record(writer):
                    writer.append_ledger({
                        "kind": "attempt", "event_id": attempt_id, "proof_id": proof_id,
                        "tool_call_id": tool_call, "request_id": f"req-{index}",
                    })
                    writer.append_ledger({
                        "kind": "evaluation", "candidate_id": proof_id, "key": evaluation_id, "mode": "fast",
                        "result": {"ok": True},
                    })

                run_control.apply_operation(directory, {
                    "operation_id": f"compile-op-{index}", "kind": "compile", "arguments": {"proof": proof_id},
                    "run_id": "run-1", "actor_id": launch["env"]["ARENA_ACTOR_ID"],
                    "session_id": launch["env"]["ARENA_SESSION_ID"],
                }, record)
                return {
                    "type": "tool_execution_end", "toolName": "compile", "toolCallId": tool_call, "isError": False,
                    "result": {"details": {"ok": True, "items": [{
                        "ok": True, "status": "closed", "attempts": [{"attempt_id": attempt_id}],
                    }]}},
                }

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
            self.assertTrue(busy["hint"])
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
            candidate = compile_event(1, children[0][0])
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

            report = {"type": "message_end", "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "hidden"}, {"type": "text", "text": "Held: step 2 closes by simp."}]}}
            child._chunks.put((json.dumps(report) + "\n" + json.dumps({"type": "agent_settled"}) + "\n").encode())
            child._chunks.put(None)
            orchestration.join_activation(fresh["activation_id"])
            released = orchestration.jobs(directory, [fresh["job_id"]])["jobs"][0]
            self.assertEqual(released["state"], "completed")
            with patch.object(orchestration, "reconcile", return_value={"status": "running", "generation": "fixture"}):
                settled = orchestration.await_results(directory, actor_id="sol")
            self.assertEqual([event["report"] for event in settled["events"] if event.get("report")],
                             ["Held: step 2 closes by simp."])
            shown = team_reply.render("await_results", settled, directory)
            self.assertIn("job1 completed.", shown)
            self.assertIn("job1 report: Held: step 2 closes by simp.", shown)
            self.assertNotIn(fresh["job_id"], shown)
            self.assertIn("job1", team_reply.render("delegate", fresh, directory))
            self.assertEqual(orchestration.resolve_job(directory, "job1"), fresh["job_id"])
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
            retry = orchestration.delegate(
                directory, operation_id="op-follow", run_id="run-1", actor_id="sol", session_id="sol-session",
                task="narrow the same step", job_id=fresh["job_id"], open_child=open_child,
            )
            self.assertTrue(retry["ok"])
            self.assertTrue(retry["reused"])
            self.assertEqual(retry["activation_id"], follow["activation_id"])
            self.assertEqual(len(children), 2)
            conflicting = orchestration.delegate(
                directory, operation_id="op-follow", run_id="run-1", actor_id="sol", session_id="sol-session",
                task="changed retry", job_id=fresh["job_id"], open_child=open_child,
            )
            self.assertEqual(conflicting["category"], "operation_conflict")
            unauthorized = orchestration.delegate(
                directory, operation_id="op-takeover", run_id="run-1", actor_id="another-worker", session_id="other",
                task="take over", job_id=fresh["job_id"], open_child=open_child,
            )
            self.assertEqual(unauthorized["category"], "invalid_input")
            self.assertEqual(unauthorized["reason"], "ownership")
            self.assertEqual(follow["job_id"], fresh["job_id"])
            self.assertEqual(follow["session_id"], fresh["session_id"])
            self.assertNotEqual(follow["activation_id"], fresh["activation_id"])
            self.assertEqual(follow["anchor"], fresh["anchor"])
            self.assertEqual(children[1][0]["session_dir"], children[0][0]["session_dir"])
            self.assertTrue(json.loads(children[0][1].written)["message"].startswith("WORKER PACKET"))
            follow_message = json.loads(children[1][1].written)["message"]
            self.assertNotIn("WORKER PACKET", follow_message)
            self.assertTrue(follow_message.startswith("narrow the same step"))
            self.assertEqual(children[1][0]["env"]["ARENA_ACTIVATION_ID"], follow["activation_id"])
            self.assertEqual(children[1][0]["env"]["ARENA_SESSION_ID"], fresh["session_id"])
            resumed_view = orchestration.jobs(directory, [fresh["job_id"]])["jobs"][0]
            self.assertTrue(resumed_view["resumed"])
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
            later = compile_event(2, children[1][0])
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

            # Replaying a fresh receipt while its follow-up is terminal must
            # still describe the original completed activation.
            replay = orchestration.delegate(directory, **call)
            self.assertEqual(replay["activation_id"], fresh["activation_id"])
            self.assertEqual(replay["state"], "completed")
            self.assertFalse(replay["resumed"])

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

    def test_v8_cancel_releases_after_exit(self):
        """Two live workers hold the slots. Cancel keeps its slot until that child exits."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            children = []

            class _Owned(_HeldChild):
                def __init__(self):
                    super().__init__()
                    self.shutdowns = 0

                def write(self, data: bytes):
                    if not self.order:
                        raise RuntimeError("prompt before subscribe")
                    if "write" not in self.order:
                        self.order.append("write")
                    self.written += data

                def shutdown(self):
                    self.shutdowns += 1

            def open_child(launch):
                child = _Owned()
                children.append((launch, child))
                return child

            def delegate(operation_id, task):
                return orchestration.delegate(
                    directory,
                    operation_id=operation_id,
                    run_id="run-1",
                    actor_id="sol",
                    session_id="sol-session",
                    task=task,
                    scope="proof",
                    anchor={"node": "n1"},
                    open_child=open_child,
                )

            first = delegate("op-a", "hypothesis a")
            second = delegate("op-b", "hypothesis b")
            third = delegate("op-c", "hypothesis c")
            self.assertEqual(len(children), 2)
            self.assertEqual(first["state"], "launching")
            self.assertEqual(second["state"], "launching")
            self.assertEqual(third["state"], "queued")
            view = orchestration.jobs(directory)
            by_job = {job["job_id"]: job for job in view["jobs"]}
            self.assertEqual(by_job[third["job_id"]]["state"], "queued")
            self.assertEqual(
                [job["job_id"] for job in view["jobs"] if job["state"] == "queued"],
                [third["job_id"]],
            )
            self.assertTrue(by_job[first["job_id"]]["occupies_slot"])
            self.assertFalse(by_job[third["job_id"]]["occupies_slot"])

            command_id = by_job[first["job_id"]]["command_id"]
            attempt_id, proof_id, evaluation_id = "attempt-late", "proof-late", "eval-late"
            tool_call = "compile-late"
            (directory / "proofs" / f"{proof_id}.lean").write_text(_PROOF)
            launch = children[0][0]

            def record(writer):
                writer.append_ledger({
                    "kind": "attempt", "event_id": attempt_id, "proof_id": proof_id,
                    "tool_call_id": tool_call, "request_id": "req-late",
                })
                writer.append_ledger({
                    "kind": "evaluation", "candidate_id": proof_id, "key": evaluation_id, "mode": "fast",
                    "result": {"ok": True},
                })

            run_control.apply_operation(directory, {
                "operation_id": "compile-late", "kind": "compile", "arguments": {"proof": proof_id},
                "run_id": "run-1", "actor_id": launch["env"]["ARENA_ACTOR_ID"],
                "session_id": launch["env"]["ARENA_SESSION_ID"],
            }, record)
            child = children[0][1]
            receipt = orchestration.cancel(
                directory,
                operation_id="op-cancel",
                run_id="run-1",
                actor_id="sol",
                session_id="sol-session",
                job_id=first["job_id"],
            )
            self.assertTrue(receipt["ok"])
            self.assertEqual(receipt["state"], "cancelling")
            self.assertEqual(child.shutdowns, 1)
            commands = [json.loads(line) for line in bytes(child.written).splitlines()]
            self.assertEqual([row["type"] for row in commands[-2:]], ["clear_queue", "abort"])
            self.assertNotEqual(commands[-2]["id"], commands[-1]["id"])
            self.assertNotEqual(commands[-1]["id"], command_id)
            again = orchestration.cancel(
                directory,
                operation_id="op-cancel-again",
                run_id="run-1",
                actor_id="sol",
                session_id="sol-session",
                job_id=first["job_id"],
            )
            self.assertTrue(again["reused"])
            self.assertEqual(again["operation_id"], "op-cancel")
            self.assertEqual(again["evidence_refs"], receipt["evidence_refs"])
            self.assertEqual(child.shutdowns, 1)
            self.assertEqual(len(children), 2)
            child._chunks.put(b"".join(
                (json.dumps(row) + "\n").encode()
                for row in (
                    {"type": "response", "id": command_id, "command": "abort", "success": True},
                    {
                        "type": "tool_execution_end", "toolName": "compile", "toolCallId": tool_call,
                        "isError": False,
                        "result": {"details": {"ok": True, "items": [{
                            "ok": True, "status": "closed", "attempts": [{"attempt_id": attempt_id}],
                        }]}},
                    },
                    {"type": "agent_settled"},
                )
            ))

            def still_held():
                current = orchestration.jobs(directory)
                jobs = {job["job_id"]: job for job in current["jobs"]}
                held = jobs[first["job_id"]]
                if held["state"] == "cancelling" and held["findings"] and len(children) == 2:
                    return held
                return None

            held = None
            for _ in range(20000):
                held = still_held()
                if held is not None:
                    break
            self.assertIsNotNone(held)
            self.assertTrue(held["occupies_slot"])
            self.assertEqual(held["findings"][0]["attempt_id"], attempt_id)
            self.assertEqual(held["activation_id"], first["activation_id"])
            self.assertEqual(orchestration.jobs(directory)["jobs"][2]["state"], "queued")

            child.exit_on_eof = False
            child._chunks.put(None)
            orchestration.join_activation(first["activation_id"])
            pipe_closed = {job["job_id"]: job for job in orchestration.jobs(directory)["jobs"]}
            self.assertEqual(pipe_closed[first["job_id"]]["state"], "cancelling")
            self.assertTrue(pipe_closed[first["job_id"]]["occupies_slot"])
            self.assertEqual(pipe_closed[third["job_id"]]["state"], "queued")
            self.assertEqual(len(children), 2)
            child.absent = True
            orchestration.observe_exit(directory, first["activation_id"])

            def admitted():
                if len(children) != 3:
                    return None
                current = {job["job_id"]: job for job in orchestration.jobs(directory)["jobs"]}
                if current[first["job_id"]]["state"] != "cancelled":
                    return None
                if current[third["job_id"]]["state"] != "launching":
                    return None
                return current

            admitted_view = None
            for _ in range(20000):
                admitted_view = admitted()
                if admitted_view is not None:
                    break
            self.assertIsNotNone(admitted_view)
            self.assertEqual(len(children), 3)
            self.assertEqual(children[2][0]["env"]["ARENA_JOB_ID"], third["job_id"])
            self.assertFalse(admitted_view[first["job_id"]]["occupies_slot"])
            self.assertTrue(admitted_view[second["job_id"]]["occupies_slot"])
            self.assertTrue(admitted_view[third["job_id"]]["occupies_slot"])
            self.assertEqual(admitted_view[first["job_id"]]["findings"][0]["proof_id"], proof_id)
            self.assertEqual(admitted_view[first["job_id"]]["activation_id"], first["activation_id"])
            self.assertEqual(len(admitted_view[first["job_id"]]["activations"]), 1)

            resumed = orchestration.delegate(
                directory, operation_id="op-resume-cancelled", run_id="run-1", actor_id="sol",
                session_id="sol-session", job_id=first["job_id"], task="continue hypothesis a", open_child=open_child,
            )
            self.assertEqual(resumed["state"], "queued")
            new_cancel = orchestration.cancel(
                directory, operation_id="op-cancel-new", run_id="run-1", actor_id="sol",
                session_id="sol-session", job_id=first["job_id"],
            )
            self.assertEqual(new_cancel["state"], "cancelled")
            self.assertEqual(new_cancel["activation_id"], resumed["activation_id"])
            self.assertEqual(new_cancel["operation_id"], "op-cancel-new")
            replay = orchestration.cancel(
                directory, operation_id="op-cancel", run_id="run-1", actor_id="sol",
                session_id="sol-session", job_id=first["job_id"],
            )
            self.assertEqual(replay["activation_id"], first["activation_id"])
            self.assertEqual(len(children), 3)

            fourth = delegate("op-d", "hypothesis d")
            self.assertEqual(fourth["state"], "queued")
            second_child = children[1][1]
            second_child.exit_on_eof = False
            second_command = admitted_view[second["job_id"]]["command_id"]
            second_child._chunks.put(b"".join((json.dumps(row) + "\n").encode() for row in (
                {"type": "response", "id": second_command, "success": True, "data": {"disposition": "started"}},
                {"type": "agent_settled"},
            )))
            second_child._chunks.put(None)
            orchestration.join_activation(second["activation_id"])
            completed = {job["job_id"]: job for job in orchestration.jobs(directory)["jobs"]}
            self.assertEqual(completed[second["job_id"]]["state"], "completed")
            self.assertTrue(completed[second["job_id"]]["occupies_slot"])
            self.assertEqual(completed[fourth["job_id"]]["state"], "queued")
            self.assertEqual(len(children), 3)
            second_child.absent = True
            orchestration.observe_exit(directory, second["activation_id"])
            self.assertEqual(len(children), 4)
            self.assertEqual(children[3][0]["env"]["ARENA_JOB_ID"], fourth["job_id"])
            orchestration.observe_exit(directory, second["activation_id"])
            self.assertEqual(len(children), 4)
            children[2][1]._chunks.put(None)
            children[3][1]._chunks.put(None)
            orchestration.join_activation(admitted_view[third["job_id"]]["activation_id"])
            orchestration.join_activation(fourth["activation_id"])

    def test_v8_wait_registration_and_no_work(self):
        """A retained finding is delivered once to each actor. A finished producer yields no_pending_work."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            children = []

            def open_child(launch):
                child = _HeldChild()
                children.append((launch, child))
                return child

            fresh = orchestration.delegate(
                directory,
                operation_id="op-wait",
                run_id="run-1",
                actor_id="sol",
                session_id="sol-session",
                task="try the step",
                scope="step",
                anchor={"node": "n1", "steps": [1, 2]},
                open_child=open_child,
            )
            launch = children[0][0]
            attempt_id, proof_id, evaluation_id = "attempt-wait", "proof-wait", "eval-wait"
            tool_call = "compile-wait"
            (directory / "proofs" / f"{proof_id}.lean").write_text(_PROOF)

            def record(writer):
                writer.append_ledger({
                    "kind": "attempt", "event_id": attempt_id, "proof_id": proof_id,
                    "tool_call_id": tool_call, "request_id": "req-wait",
                })
                writer.append_ledger({
                    "kind": "evaluation", "candidate_id": proof_id, "key": evaluation_id, "mode": "fast",
                    "result": {"ok": True},
                })

            run_control.apply_operation(directory, {
                "operation_id": "compile-op-wait", "kind": "compile", "arguments": {"proof": proof_id},
                "run_id": "run-1", "actor_id": launch["env"]["ARENA_ACTOR_ID"],
                "session_id": launch["env"]["ARENA_SESSION_ID"],
            }, record)
            child = children[0][1]
            command_id = orchestration.jobs(directory, [fresh["job_id"]])["jobs"][0]["command_id"]
            child._chunks.put((
                json.dumps({
                    "type": "response", "id": command_id, "success": True,
                    "data": {"disposition": "started"},
                }) + "\n" + json.dumps({
                    "type": "tool_execution_end", "toolName": "compile", "toolCallId": tool_call,
                    "isError": False, "result": {"details": {"ok": True, "items": [{
                        "ok": True, "status": "closed", "attempts": [{"attempt_id": attempt_id}],
                    }]}},
                }) + "\n"
            ).encode())
            finding_id = None
            for _ in range(20000):
                match = [
                    item for item in orchestration.deliver(directory, "sol")["results"]
                    if item["attempt_id"] == attempt_id
                ]
                if match:
                    finding_id = match[0]["event_id"]
                    break
            self.assertIsNotNone(finding_id)
            before = (directory / "control.jsonl").read_text()

            def await_actor(actor_id, cursor=None):
                return orchestration.await_results(
                    directory, actor_id=actor_id, cursor=cursor, job_ids=[fresh["job_id"]],
                )

            with patch.object(run_control, "watch_directory", return_value=contextlib.nullcontext(SimpleNamespace(available=False))):
                sol = await_actor("sol")
            first_cursor = sol["next_cursor"]
            other = await_actor("planner")
            self.assertEqual(sol["wake_reason"], "result")
            self.assertEqual([event["event_id"] for event in sol["events"]], [finding_id])
            self.assertEqual(sol["events"][0]["request_id"], "req-wait")
            self.assertEqual([event["event_id"] for event in other["events"]], [finding_id])
            self.assertNotEqual(sol["next_cursor"], other["next_cursor"])
            with patch.object(run_control, "watch_directory", return_value=contextlib.nullcontext(SimpleNamespace(available=False))):
                unavailable = await_actor("sol", sol["next_cursor"])
            self.assertFalse(unavailable["ok"])
            self.assertEqual(unavailable["category"], "notification_unavailable")
            self.assertTrue(unavailable["retryable"])
            self.assertEqual(len(orchestration.jobs(directory)["jobs"]), 1)
            self.assertNotIn("dispatch_started", (directory / "control.jsonl").read_text())
            self.assertEqual(
                (directory / "control.jsonl").read_text().count('"kind":"settlement"'),
                before.count('"kind":"settlement"'),
            )

            with patch("arena.campaign.run_dir", return_value=directory):
                proof_reply._load("run-1")

            # A new compile finishes exactly after the waiter registers.
            attempt_id, proof_id, evaluation_id = "attempt-registration", "proof-registration", "eval-registration"
            tool_call = "compile-registration"
            (directory / "proofs" / f"{proof_id}.lean").write_text(_PROOF)
            run_control.apply_operation(directory, {
                "operation_id": "compile-op-registration", "kind": "compile", "arguments": {"proof": proof_id},
                "run_id": "run-1", "actor_id": launch["env"]["ARENA_ACTOR_ID"],
                "session_id": launch["env"]["ARENA_SESSION_ID"],
            }, record)
            registered = threading.Event()
            replies = []
            real_wait = orchestration._interest.wait

            def on_wait(*args):
                registered.set()
                return real_wait(*args)

            with patch.object(orchestration._interest, "wait", side_effect=on_wait):
                waiter = threading.Thread(target=lambda: replies.append(await_actor("sol", sol["next_cursor"])), daemon=True)
                waiter.start()
                try:
                    self.assertTrue(registered.wait(1))
                    # Immediate returns above wrote nothing; this blocked wait is durable and shows as waiting.
                    from arena.campaign import _served_actors
                    history = orchestration._history(directory)
                    started = [row for row in history if row.get("kind") == "wait"]
                    self.assertEqual(len(started), 1)
                    self.assertEqual((started[0]["actor_id"], started[0]["job_ids"], started[0]["cursor"]),
                                     ("sol", [fresh["job_id"]], sol["next_cursor"]))
                    self.assertFalse([row for row in history if row.get("kind") == "wait_end"])
                    self.assertTrue(next(row for row in _served_actors(history) if row["actor_id"] == "sol")["waiting"])
                    child._chunks.put((json.dumps({
                        "type": "tool_execution_end", "toolName": "compile", "toolCallId": tool_call,
                        "isError": False, "result": {"details": {"ok": True, "items": [{
                            "ok": True, "status": "closed", "attempts": [{"attempt_id": attempt_id}],
                        }]}},
                    }) + "\n").encode())
                    waiter.join(1)
                    self.assertFalse(waiter.is_alive())
                    self.assertEqual(replies[0]["wake_reason"], "result")
                    self.assertEqual(replies[0]["events"][0]["attempt_id"], attempt_id)
                    sol = replies[0]
                    history = orchestration._history(directory)
                    ended = [row for row in history if row.get("kind") == "wait_end"]
                    self.assertEqual([(row["wait_id"], row["wake_reason"]) for row in ended],
                                     [(started[0]["wait_id"], "result")])
                    self.assertFalse(next(row for row in _served_actors(history) if row["actor_id"] == "sol")["waiting"])
                finally:
                    if waiter.is_alive():
                        child._chunks.put(None)
                        orchestration._wake()
                        waiter.join(1)

            child._chunks.put((json.dumps({"type": "assignment_exhausted"}) + "\n").encode())
            child._chunks.put(None)
            orchestration.join_activation(fresh["activation_id"])
            finished = await_actor("sol", sol["next_cursor"])
            if finished["wake_reason"] != "no_pending_work":
                self.assertEqual(finished["wake_reason"], "settled")
                self.assertNotIn(finding_id, [event["event_id"] for event in finished["events"]])
                finished = await_actor("sol", finished["next_cursor"])
            self.assertEqual(finished["wake_reason"], "no_pending_work")
            self.assertEqual(finished["events"], [])
            with patch.object(run_control, "watch_directory", return_value=contextlib.nullcontext(SimpleNamespace(available=False))):
                self.assertEqual(await_actor("sol")["wake_reason"], "no_pending_work")
            self.assertEqual(len(orchestration.jobs(directory)["jobs"]), 1)
            self.assertFalse(run_control.read_state(directory)["stopped"])
            self.assertNotIn("dispatch_started", (directory / "control.jsonl").read_text())
            protocol_path = Path(__file__).parents[1] / "arena" / "cli" / "protocol.py"
            spec = importlib.util.spec_from_file_location("await_protocol", protocol_path)
            await_protocol = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(await_protocol)
            from arena.coordinator import Coordinator

            with patch.object(orchestration, "reconcile", return_value={"status": "running", "generation": "fixture"}), Coordinator(directory), patch.object(await_protocol, "run_dir", return_value=directory):
                continued = await_protocol.run(SimpleNamespace(
                    action="await_results", theorem="demo", run_id="run-1", request_file=None,
                    max_seconds=None, spent_usd=None, cap_usd=None,
                ))
            self.assertEqual(continued["wake_reason"], "no_pending_work")
            self.assertNotEqual(continued.get("state"), "finished")
            self.assertEqual(len(orchestration.jobs(directory)["jobs"]), 1)

            orchestration.note_verification(
                directory, job_id=fresh["job_id"], evaluation_id="check-wait", state="running",
                run_id="run-1", actor_id="sol", session_id="sol-session",
            )
            check_registered = threading.Event()
            check_replies = []
            check_waiter = threading.Thread(
                target=lambda: check_replies.append(await_actor("sol", finished["next_cursor"])),
                daemon=True,
            )
            def on_check_wait(*args):
                check_registered.set()
                return real_wait(*args)

            with patch.object(orchestration._interest, "wait", side_effect=on_check_wait):
                check_waiter.start()
                self.assertTrue(check_registered.wait(2))
            subprocess.run(
                [
                    "uv", "run", "--no-sync", "python", "-c",
                    "import sys\nfrom pathlib import Path\nfrom arena import orchestration\n"
                    "orchestration.note_verification(Path(sys.argv[1]), job_id=sys.argv[2], "
                    "evaluation_id=sys.argv[3], state='passed', run_id='run-1', actor_id='sol', "
                    "session_id='sol-session')\n",
                    str(directory), fresh["job_id"], "check-wait",
                ],
                check=True,
            )
            check_waiter.join(15)
            self.assertFalse(check_waiter.is_alive())
            self.assertEqual(check_replies[0]["wake_reason"], "result")
            self.assertEqual(check_replies[0]["events"][0]["evaluation_id"], "check-wait")
            self.assertEqual(await_actor("sol", check_replies[0]["next_cursor"])["wake_reason"], "no_pending_work")

            def start_job(operation_id):
                return orchestration.delegate(
                    directory, operation_id=operation_id, run_id="run-1", actor_id="sol", session_id="sol-session",
                    task="another hypothesis", scope="proof", anchor={"node": "n1"}, open_child=open_child,
                )

            second = start_job("op-wait-second")
            second_child = children[-1][1]
            second_child.exit_on_eof = False
            second_child._chunks.put(None)
            orchestration.join_activation(second["activation_id"])
            failed = orchestration.await_results(directory, actor_id="sol", job_ids=[second["job_id"]])
            self.assertEqual(failed["wake_reason"], "failed")
            second_child.absent = True
            orchestration.observe_exit(directory, second["activation_id"])
            older = orchestration.await_results(
                directory, actor_id="sol", cursor=first_cursor, job_ids=[second["job_id"]],
            )
            self.assertEqual(older["wake_reason"], "failed")
            self.assertEqual(await_actor("sol")["wake_reason"], "no_pending_work")

            def ordinary_reply(writer):
                writer.append_ledger({
                    "kind": "delivered_reply", "data": {"cursor": 1, "seqs": [1], "event_ids": ["proof-context"]},
                })

            run_control.apply_operation(directory, {
                "operation_id": "ordinary-proof-reply", "kind": "delivered_reply", "arguments": {"seqs": [1]},
                "run_id": "run-1", "actor_id": "sol", "session_id": "sol-session",
            }, ordinary_reply)
            with patch("arena.campaign.run_dir", return_value=directory):
                self.assertEqual(proof_reply._load("run-1")["actors"]["sol"]["delivered_seq"], 1)
            self.assertEqual(await_actor("sol")["wake_reason"], "no_pending_work")

            stopped_job = start_job("op-wait-stop")
            _request(directory, "stop-fixture-request", "sol", stopped_job["job_id"])
            run_control.settle_usage(directory, {
                "settlement_id": "stop-fixture-settlement", "run_id": "run-1", "actor_id": "sol",
                "session_id": "sol-session", "job_id": stopped_job["job_id"],
                "covered_request_ids": ["stop-fixture-request"], "state": "known", "amount": "2.50",
                "usage": {"cost": {"total": 2.5}},
            })
            stopped = orchestration.await_results(directory, actor_id="sol")
            self.assertEqual(stopped["wake_reason"], "run_stopped")
            repeated = orchestration.await_results(directory, actor_id="sol", cursor=stopped["next_cursor"])
            self.assertEqual(repeated["wake_reason"], "run_stopped")
            self.assertTrue(repeated["evidence_refs"])
            children[-1][1]._chunks.put(None)
            orchestration.join_activation(stopped_job["activation_id"])
            self.assertNotIn("dispatch_started", (directory / "control.jsonl").read_text())


class _OwnedChild:
    """Injected process identity. No live process and no pipe the coordinator can reattach."""

    def __init__(self, identity: dict):
        self.identity = identity
        self.order = []
        self.written = bytearray()
        self._chunks = queue.Queue()

    def process_identity(self):
        return dict(self.identity)

    def subscribe(self):
        self.order.append("subscribe")

    def write(self, data: bytes):
        self.order.append("write")
        self.written += data

    def read(self, _size: int) -> bytes:
        item = self._chunks.get()
        return b"" if item is None else item


class V8RecoverySmokeTests(unittest.TestCase):
    def test_unknown_settlement_ends_request_uncertainty(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            _request(directory, "req-u", "sol", "job-1")
            run_control._append_control(directory, {
                "schema_version": run_control.SCHEMA_VERSION, "kind": "dispatch_intent", "event_id": "e1",
                "attempt_id": "att-u", "request_id": "req-u", "run_id": "run-1", "actor_id": "sol",
                "session_id": "sol-session", "status": "dispatch_uncertain", "sent": "uncertain",
            })
            self.assertTrue(orchestration._request_uncertain(directory, "sol-session"))
            run_control.settle_usage(directory, {
                "settlement_id": "unknown:req-u", "run_id": "run-1", "actor_id": "sol",
                "session_id": "sol-session", "covered_request_ids": ["req-u"],
                "state": "unknown", "irreconcilable": True,
            })
            self.assertEqual(run_control.read_state(directory)["unknown_requests"], ["req-u"])
            self.assertFalse(orchestration._request_uncertain(directory, "sol-session"))
            self.assertFalse(orchestration._request_uncertain(directory))

    def test_v8_owned_child_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ambiguous = Path(tmp)
            _seed_parent(ambiguous)

            def lost_spawn(_launch):
                raise KeyboardInterrupt("child may have spawned before receipt")

            with self.assertRaises(KeyboardInterrupt):
                orchestration.delegate(
                    ambiguous, operation_id="ambiguous", run_id="run-1", actor_id="sol",
                    session_id="sol-session", task="unacknowledged spawn", scope="proof",
                    anchor={"node": "n1"}, open_child=lost_spawn,
                )
            retained = orchestration.reconcile(
                ambiguous, inspect=lambda _pid: {"alive": False, "group_alive": False},
                signal=lambda _pgid: self.fail("unknown child must not be signalled"),
                open_child=lambda _launch: self.fail("ambiguous spawn must not be replaced"),
            )
            self.assertEqual(retained["status"], "recovering")
            self.assertEqual(retained["replacements"], 0)

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            launches = []
            crash_before_spawn = {"armed": True}

            def open_child(launch):
                ledger = (directory / "ledger.jsonl").read_text()
                self.assertIn('"phase":"intent"', ledger)
                self.assertIn(launch["session_dir"], ledger)
                if crash_before_spawn["armed"]:
                    crash_before_spawn["armed"] = False
                    error = KeyboardInterrupt("adapter proved no child was spawned")
                    error.not_spawned = True
                    raise error
                self.assertIn('"phase":"intent"', ledger)
                child = _OwnedChild({
                    "pid": 4100 + len(launches),
                    "pgid": 5100 + len(launches),
                    "start_id": f"start-{len(launches)}",
                    "run_id": "run-1",
                })

                def write(data: bytes):
                    ledger_now = (directory / "ledger.jsonl").read_text()
                    self.assertLess(
                        ledger_now.index(f'"pid":{child.identity["pid"]}'),
                        len(ledger_now),
                    )
                    self.assertIn('"phase":"spawned"', ledger_now)
                    self.assertEqual(orchestration._run_status(directory), "running")
                    self.assertEqual(launch["env"]["ARENA_GENERATION"], orchestration._control_generation(directory))
                    _OwnedChild.write(child, data)

                child.write = write
                launches.append((launch, child))
                return child

            anchor = {"node": "n1", "steps": [1, 2]}
            with self.assertRaises(KeyboardInterrupt):
                orchestration.delegate(
                    directory, operation_id="op-a", run_id="run-1", actor_id="sol",
                    session_id="sol-session", task="hypothesis a", scope="step", anchor=anchor,
                    open_child=open_child,
                )
            self.assertEqual(launches, [])
            self.assertIn('"phase":"intent"', (directory / "ledger.jsonl").read_text())
            orchestration._owned.clear()
            orchestration._openers.clear()
            orchestration._live.clear()
            orchestration._readers.clear()
            orchestration._stop_sent.clear()

            probed = {}

            def inspect(pid: int):
                return probed.get(pid, {"alive": False, "group_alive": False})

            signalled = []

            def signal(pgid: int):
                signalled.append(pgid)

            recovered = orchestration.reconcile(directory, inspect=inspect, signal=signal, open_child=open_child)
            self.assertEqual(signalled, [])
            self.assertEqual(recovered["replacements"], 1)
            self.assertEqual(recovered["status"], "running")
            self.assertEqual(len(launches), 1)
            owned = launches[0][1]
            self.assertEqual(owned.order[0], "subscribe")
            self.assertIn(f'"pid":{owned.identity["pid"]}', (directory / "ledger.jsonl").read_text())
            self.assertIn(owned.identity["start_id"], (directory / "ledger.jsonl").read_text())
            rows = run_control._control_rows(directory)
            generation = next(row["generation"] for row in reversed(rows) if row.get("kind") == "run_generation")

            second = orchestration.delegate(
                directory, operation_id="op-b", run_id="run-1", actor_id="sol",
                session_id="sol-session", task="hypothesis b", scope="proof",
                anchor={"node": "n1"}, open_child=open_child,
            )
            self.assertTrue(second["ok"])
            self.assertEqual(len(launches), 2)
            first_id = launches[0][1].identity
            second_id = launches[1][1].identity
            self.assertIn('"phase":"spawned"', (directory / "ledger.jsonl").read_text())
            # Prompt bytes exist only after the spawned ownership line for that child.
            self.assertTrue(launches[1][1].written)

            view = orchestration.jobs(directory)
            activation_a = view["jobs"][0]["activation_id"]
            activation_b = second["activation_id"]
            worker_b = launches[1][0]["env"]["ARENA_ACTOR_ID"]
            session_b = launches[1][0]["env"]["ARENA_SESSION_ID"]
            uncertain = run_control.begin_dispatch(
                directory,
                {
                    "request_id": "req-b",
                    "attempt_id": "attempt-b",
                    "run_id": "run-1",
                    "actor_id": worker_b,
                    "session_id": session_b,
                    "job_id": second["job_id"],
                    "generation": generation,
                },
                lambda: None,
            )
            self.assertEqual(uncertain["sent"], "uncertain")

            cancelled = orchestration.cancel(
                directory, operation_id="op-cancel-a", run_id="run-1", actor_id="sol",
                session_id="sol-session", job_id=view["jobs"][0]["job_id"],
            )
            self.assertEqual(cancelled["state"], "cancelling")

            for bucket in (
                orchestration._owned, orchestration._openers, orchestration._live, orchestration._readers,
            ):
                bucket.clear()
            orchestration._stop_sent.clear()

            probed[first_id["pid"]] = {
                "alive": True, "group_alive": False, "start_id": "reused-pid", "run_id": "other-run",
            }
            probed[second_id["pid"]] = {
                "alive": True, "group_alive": True, "start_id": second_id["start_id"], "run_id": "run-1",
            }
            held = orchestration.reconcile(directory, inspect=inspect, signal=signal, open_child=open_child)
            self.assertNotIn(first_id["pid"], signalled)
            self.assertNotIn(first_id["pgid"], signalled)
            self.assertEqual(signalled, [second_id["pgid"]])
            self.assertEqual(held["replacements"], 0)
            self.assertEqual(len(launches), 2)
            self.assertEqual(held["status"], "recovering")
            fenced = run_control.begin_dispatch(
                directory,
                {
                    "request_id": "req-during",
                    "attempt_id": "attempt-during",
                    "run_id": "run-1",
                    "actor_id": "sol",
                    "session_id": "sol-session",
                    "generation": "old-generation",
                },
                lambda: (_ for _ in ()).throw(AssertionError("transport")),
            )
            self.assertFalse(fenced["admitted"])
            self.assertEqual(fenced["reason"], "recovering")

            unknown = orchestration.note_worker_event(
                directory,
                activation_id=activation_a,
                generation="stale-generation",
                evidence={"attempt_id": "late-attempt", "proof_id": "late-proof", "evaluation_id": "late-eval"},
            )
            self.assertFalse(unknown["evidence"])

            def record_late(writer):
                writer.append_ledger({"kind": "attempt", "event_id": "late-attempt", "proof_id": "late-proof",
                                      "generation": generation})
                writer.append_ledger({
                    "kind": "evaluation", "candidate_id": "late-proof", "key": "late-eval",
                    "result": {"ok": True, "compat": {"v1": {"passed": True}}},
                })

            run_control.apply_operation(directory, {
                "operation_id": "late-compile", "kind": "compile", "arguments": {"proof": "late-proof"},
                "run_id": "run-1", "actor_id": launches[0][0]["env"]["ARENA_ACTOR_ID"],
                "session_id": launches[0][0]["env"]["ARENA_SESSION_ID"],
                "activation_id": activation_a,
            }, record_late)
            late = orchestration.note_worker_event(
                directory, activation_id=activation_a, generation=generation,
                evidence={"attempt_id": "late-attempt", "proof_id": "late-proof", "evaluation_id": "late-eval"},
            )
            self.assertTrue(late["evidence"])
            self.assertFalse(orchestration.note_worker_event(
                directory, activation_id=activation_a, generation="another-generation",
                evidence={"attempt_id": "late-attempt", "proof_id": "late-proof", "evaluation_id": "late-eval"},
            )["evidence"])
            self.assertFalse(late["state_changed"])
            after_late = orchestration.jobs(directory)
            cancelled_row = next(
                item for job in after_late["jobs"] for item in job["activations"] if item["activation_id"] == activation_a
            )
            other_row = next(
                item for job in after_late["jobs"] for item in job["activations"] if item["activation_id"] == activation_b
            )
            self.assertEqual(cancelled_row["state"], "cancelled")
            self.assertFalse(cancelled_row["occupies_slot"])
            self.assertTrue(other_row["occupies_slot"])
            self.assertTrue(any(item["attempt_id"] == "late-attempt" for job in after_late["jobs"] for item in job["findings"]))

            probed[second_id["pid"]] = {
                "alive": False, "group_alive": False, "start_id": second_id["start_id"], "run_id": "run-1",
            }
            finished = orchestration.reconcile(directory, inspect=inspect, signal=signal, open_child=open_child)
            self.assertEqual(signalled, [second_id["pgid"]])
            self.assertEqual(finished["replacements"], 1)
            self.assertEqual(len(launches), 3)
            self.assertEqual(finished["status"], "running")
            self.assertIn("req-b", run_control.read_state(directory)["unknown_requests"])
            self.assertFalse(orchestration._request_uncertain(directory, session_b))
            resumed = finished
            self.assertIsNone(run_control._fence_reason(
                run_control._control_rows(directory), {"generation": resumed["generation"]},
            ))
            before = orchestration.jobs(directory)
            stale = {"state": "active", "generation": generation, "transport": launches[1][1]}
            delegation_b = next(row for row in orchestration._delegations(directory)
                                if row["activation_id"] == activation_b)
            orchestration._take(directory, delegation_b, "old-command", stale, [{"type": "agent_settled"}])
            self.assertEqual(orchestration.jobs(directory)["jobs"], before["jobs"])
            with patch.dict(orchestration._owned, {activation_b: launches[1][1]}):
                orchestration._record_state(
                    directory, delegation_b, "failed", expected_transport=launches[1][1],
                    expected_generation=generation, reason="old-reader-eof",
                )
                self.assertEqual(orchestration.jobs(directory)["jobs"], before["jobs"])
            launches[1][1].confirmed_absent = lambda: True
            self.assertFalse(orchestration.observe_exit(directory, activation_b, expected_transport=launches[1][1]))

            with run_control.control_lock(directory):
                orchestration._append_state(directory, delegation_b, "completed", occupies_slot=True)
            terminal = orchestration.reconcile(directory, inspect=inspect, signal=signal, open_child=open_child)
            self.assertEqual(terminal["replacements"], 0)
            self.assertEqual(terminal["status"], "running")
            completed = orchestration._activation_view(directory, delegation_b)
            self.assertEqual(completed["state"], "completed")
            self.assertFalse(completed["occupies_slot"])

        with tempfile.TemporaryDirectory() as tmp:
            queued_run = Path(tmp)
            _seed_parent(queued_run)
            children = []

            def queued_child(_launch):
                child = _OwnedChild({"pid": 8000 + len(children), "pgid": 9000 + len(children),
                                     "start_id": f"queued-{len(children)}", "run_id": "run-1"})
                children.append(child)
                return child

            assignments = [orchestration.delegate(
                queued_run, operation_id=f"queued-{index}", run_id="run-1", actor_id="sol",
                session_id="sol-session", task=f"route {index}", scope="proof",
                anchor={"node": "n1"}, open_child=queued_child,
            ) for index in range(3)]
            self.assertEqual(assignments[-1]["state"], "queued")
            first = orchestration._delegations(queued_run)[0]
            with run_control.control_lock(queued_run):
                orchestration._append_state(queued_run, first, "completed", occupies_slot=True)
            for assignment in assignments:
                orchestration._openers.pop(assignment["activation_id"], None)
            queued_recovery = orchestration.reconcile(
                queued_run, inspect=lambda _pid: {"alive": False, "group_alive": False},
                signal=lambda _pgid: self.fail("absent group must not be signalled"), open_child=queued_child,
            )
            self.assertEqual(queued_recovery["status"], "running")
            self.assertEqual(len(children), 4)
            queued_job = orchestration.jobs(queued_run, [assignments[-1]["job_id"]])["jobs"][0]
            self.assertEqual(queued_job["state"], "launching")
            self.assertTrue(queued_job["occupies_slot"])

    def test_v8_receipt_replay_after_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            from arena import campaign

            theorem = {"name": "demo"}
            pins = [["v1", "pin1"], ["v2", "pin2"]]
            for seam in (patch.object(campaign, "problem", return_value=theorem),
                         patch.object(campaign, "versions", return_value=pins),
                         patch.object(campaign, "_evaluator_sha", return_value="evaluator"),
                         patch.object(campaign, "run_dir", return_value=directory)):
                seam.start()
                self.addCleanup(seam.stop)
            ledger = directory / "ledger.jsonl"
            ledger.write_text(json.dumps({"kind": "init", "theorem": "demo", "versions": pins}) + "\n" + ledger.read_text())

            def save_candidate(proof):
                candidate_id = hashlib.sha256(("demo\0" + proof).encode()).hexdigest()
                (directory / "proofs" / f"{candidate_id}.lean").write_text(proof)
                campaign._append(directory, {"kind": "candidate", "candidate_id": candidate_id,
                    "origin": "model", "source_versions": pins, "evaluator_sha256": "evaluator"})
                return candidate_id

            pending_candidate = save_candidate("by trivial")
            done_candidate = save_candidate("by exact True.intro")
            pending_key = campaign._evaluation_key(pending_candidate, "fast", theorem)
            done_key = campaign._evaluation_key(done_candidate, "full", theorem)
            identity = {"run_id": "run-1", "actor_id": "sol", "session_id": "sol-session", "job_id": "job-1"}
            generation = "gen-settled"

            def start(request_id: str):
                return run_control.begin_dispatch(
                    directory,
                    {**identity, "request_id": request_id, "attempt_id": f"attempt-{request_id}", "generation": generation},
                    lambda: None,
                )

            for request_id in ("req-settled", "req-journal", "req-session", "req-group-a", "req-group-b", "req-lost"):
                started = start(request_id)
                self.assertEqual(started["sent"], "uncertain")
            run_control.settle_usage(directory, {
                **identity, "settlement_id": "charge-settled", "covered_request_ids": ["req-settled"],
                "state": "known", "amount": "0.10", "usage": {"cost": {"total": "0.10"}},
            })
            with run_control.control_lock(directory):
                run_control._append_control(directory, {
                    "schema_version": run_control.SCHEMA_VERSION, "kind": "run_state",
                    "event_id": "recovering-fence", "status": "recovering",
                })
            unsent = start("req-unsent")
            self.assertEqual(unsent["sent"], "unsent")
            with run_control.control_lock(directory):
                run_control._append_control(directory, {
                    "schema_version": run_control.SCHEMA_VERSION, "kind": "run_stop",
                    "event_id": "stop-operator", "reason": "operator_interrupt",
                })
                run_control._append_control(directory, {
                    "schema_version": run_control.SCHEMA_VERSION, "kind": "track_deadline",
                    "event_id": "deadline-origin", "origin": "2026-10-01T00:00:00Z",
                })

            def record_attempt(writer):
                writer.append_ledger({
                    "kind": "attempt", "candidate_id": pending_candidate, "proof_id": pending_candidate,
                    "evaluation_id": pending_key,
                })

            run_control.apply_operation(directory, {
                "operation_id": "attempt-pending", "kind": "attempt", "arguments": {"candidate_id": pending_candidate},
                **identity,
            }, record_attempt)

            orchestration.note_verification(directory, **identity, check_id="pending-check",
                evaluation_id=pending_key, proof_id=pending_candidate, state="running")
            orchestration.note_verification(directory, **identity, check_id="done-check",
                evaluation_id=done_key, proof_id=done_candidate, state="running")

            def record_result(writer):
                writer.append_ledger({
                    "kind": "evaluation", "candidate_id": done_candidate, "key": done_key,
                    "mode": "full", "result": {"ok": True, "compat": {"v1": {"passed": True}, "v2": {"passed": True}}},
                })

            recorded = run_control.apply_operation(directory, {
                "operation_id": "result-done", "kind": "evaluation", "arguments": {"candidate_id": done_candidate},
                **identity,
            }, record_result)
            done_event = recorded["evidence_refs"][0]["event_id"]
            sends = []
            (directory / "cost-journal.jsonl").write_text(
                "\n".join(json.dumps(row) for row in (
                    {"covered_request_ids": ["req-journal"], "usage": {"cost": {"total": "0.20"}}, "amount": "0.20", **identity},
                    {"covered_request_ids": ["req-group-a", "req-group-b"], "usage": {"cost": {"total": "0.05"}}, "amount": "0.05", **identity},
                    {"covered_request_ids": ["req-lost"], "estimate": True, "amount": "9.99", "usage": {"cost": {"total": "9.99"}}},
                )) + "\n"
            )
            (directory / "session-evidence.jsonl").write_text(json.dumps({
                "request_id": "req-session", "phase": "response", "usage": {"cost": {"total": "0.04"}},
                "amount": "0.04", **identity,
            }) + "\n")

            def restart():
                return orchestration.reconcile(
                    directory,
                    inspect=lambda _pid: {"alive": False, "group_alive": False},
                    signal=lambda _pgid: None,
                    open_child=lambda _launch: None,
                )

            first = restart()["receipts"]
            second = restart()["receipts"]
            self.assertEqual(first["total"], "0.39")
            self.assertEqual(second["total"], "0.39")
            self.assertEqual(second["stop_reason"], "operator_interrupt")
            self.assertEqual(second["deadline_origin"], "2026-10-01T00:00:00Z")
            self.assertEqual(second["accounting"], "unknown")
            self.assertIn("req-lost", second["unknown_requests"])
            self.assertTrue(second["accounting_failures"])
            self.assertEqual(second["evaluations"], [pending_key])
            self.assertTrue(second["delivery_ids"])
            self.assertTrue(any(row.get("event_id") == done_event for row in orchestration._history(directory)))
            self.assertEqual(orchestration._delivery_rows(directory, "sol"), [])
            self.assertEqual(first["delivery_ids"], second["delivery_ids"])
            self.assertEqual(
                sum(1 for row in orchestration._history(directory) if row.get("key") == done_key),
                1,
            )
            self.assertEqual(
                sum(
                    1 for row in orchestration._history(directory)
                    if row.get("type") == "verification" and row.get("evaluation_id") == pending_key
                    and row.get("state") == "queued"
                ),
                1,
            )
            replay = run_control.begin_dispatch(
                directory,
                {**identity, "request_id": "req-lost", "attempt_id": "attempt-req-lost", "generation": generation},
                lambda: sends.append("sent"),
            )
            self.assertEqual(sends, [])
            self.assertFalse(replay["admitted"])
            blocked = run_control.prepare_request(directory, {
                **identity, "request_id": "req-replacement", "lineage_of": "req-lost",
            })
            self.assertFalse(blocked["ok"])
            prepared = run_control.prepare_request(directory, {
                **identity, "request_id": "req-replacement", "lineage_of": "req-unsent",
            })
            self.assertTrue(prepared["ok"])
            self.assertEqual(prepared["lineage_of"], "req-unsent")
            again = run_control.settle_usage(directory, {
                **identity, "settlement_id": "charge-settled", "covered_request_ids": ["req-settled"],
                "state": "known", "amount": "0.10", "usage": {"cost": {"total": "0.10"}},
            })
            self.assertTrue(again["reused"])
            self.assertEqual(run_control.read_state(directory)["total"], "0.39")
            grouped = [
                row for row in run_control._control_rows(directory)
                if row.get("kind") == "settlement" and row.get("covered_request_ids") == ["req-group-a", "req-group-b"]
            ]
            self.assertEqual(len(grouped), 1)
            self.assertEqual(run_control.read_state(directory)["stop_reason"], "operator_interrupt")


class TeamReplyAwaitTests(unittest.TestCase):
    def render(self, events, jobs=(), nodes=None):
        from types import SimpleNamespace

        found = {key: SimpleNamespace(id=key, score=score) for key, score in (nodes or {}).items()}
        with patch.object(orchestration, "job_labels", return_value={"j2": "job2"}), \
                patch.object(orchestration, "proof_nodes", return_value={f"p-{k}": v for k, v in found.items()}):
            return team_reply.render("await_results", {"events": events, "jobs": list(jobs)}, Path("."))

    def test_one_line_per_node_per_job_and_cancel_summary(self):
        check = {"type": "verification", "job_id": "j2", "node": "n49", "score": 70.12, "state": "passed"}
        shown = self.render([check, {**check}, {"type": "worker_finding", "job_id": "j2", "node": "n49", "score": 70.12}])
        self.assertEqual(shown.count("n49"), 1)
        self.assertIn("job2 saved n49 score 70.12 (check passed)", shown)
        self.assertEqual(self.render([check, {**check}]).count("n49"), 1)
        cancelled = {"type": "settled", "job_id": "j2", "state": "cancelled", "report": "mid-thought text"}
        jobs = [{"job_id": "j2", "findings": [{"proof_id": "p-n3"}, {"proof_id": "p-n49"}]}]
        shown = self.render([cancelled], jobs, {"n3": 60.0, "n49": 70.12})
        self.assertIn("saved 2 nodes, best n49 score 70.12", shown)
        self.assertNotIn("mid-thought", shown)
        self.assertIn("saved no nodes", self.render([cancelled]))


class V8VerificationSmokeTests(FakeRunCase):
    def test_v8_verification_outcomes(self):
        from arena import campaign, orchestration

        proof = "theorem t : True := by\n  exact True.intro"
        outcome = {"ok": True, "compat": {"v1": {"passed": False, "exit_code": 1}}, "tokens": 4}
        with patch.dict("os.environ", {"ARENA_JOB_ID": "job-check"}), patch.object(
            campaign, "_evaluate", return_value=outcome,
        ):
            campaign.record_evaluation("T", "logic", proof, "full", materialize_live=False)
        history = campaign.events(self.directory)
        completed = next(row for row in history if row.get("type") == "verification" and row["state"] != "running")
        self.assertEqual(completed["state"], "proof_error")
        evidence = next(row for row in history if row.get("kind") == "evaluation" and row["key"] == completed["evaluation_id"])
        self.assertLess(history.index(evidence), history.index(completed))

        with patch.dict("os.environ", {"ARENA_JOB_ID": "job-auto"}), patch.object(
            campaign, "_evaluate", return_value=outcome,
        ):
            campaign.record_evaluation("T", "logic", proof + " ", "full", materialize_live=False, trigger="auto")
        self.assertFalse([row for row in campaign.events(self.directory) if row.get("type") == "verification" and row.get("job_id") == "job-auto"])

        other = "theorem t : True := by\n  exact (True.intro)"
        with patch.dict("os.environ", {"ARENA_JOB_ID": "job-transport"}), patch.object(
            campaign, "_evaluate", side_effect=RuntimeError("transport lost"),
        ), self.assertRaisesRegex(RuntimeError, "transport lost"):
            campaign.record_evaluation("T", "logic", other, "full", materialize_live=False)
        states = [row["state"] for row in campaign.events(self.directory)
                  if row.get("type") == "verification" and row.get("job_id") == "job-transport"]
        self.assertEqual(states, ["running", "inconclusive"])
        self.assertFalse(orchestration._open_checks(self.directory, ["job-transport"]))


class _IdleServer:
    def alive(self):
        return True

    def doc(self, uri):
        from arena import lean_session

        return lean_session._Doc(uri)

    def close_doc(self, _slot):
        return None

    def stop(self):
        return None

    def check(self, *_args, **_kwargs):
        raise AssertionError("memory denial must not start a Lean check")


class V8AdmissionSmokeTests(unittest.TestCase):
    def test_v8_request_class_dispatch(self):
        from arena import lean_session

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            project = directory / "proj"
            project.mkdir()
            session = lean_session.Session(
                directory / "service",
                budget=lean_session.WorkerBudget(directory / "tokens", 1),
                mem_fn=lambda: (64.0, None),
            )
            self.addCleanup(session.shutdown)
            key = {"code": lean_session.code_sha()}
            entry = lean_session._Entry(project.resolve(), key, _IdleServer())
            session.entries[str(project.resolve())] = entry
            holder = session._acquire(entry, 5, "model", "import Shared\n", "opportunistic")
            order = []

            def queued(request_class):
                slot = session._acquire(entry, 5, "model", "import Shared\n", request_class)
                with entry.condition:
                    order.append((request_class, slot.queue_reason))
                    entry.condition.notify_all()
                session._release(entry, slot)

            classes = ("ds_experiment", "full_check", "sol_foreground", "opportunistic")
            threads = [threading.Thread(target=queued, args=(name,)) for name in classes]
            for thread in threads:
                thread.start()
            with entry.condition:
                while len(entry.waiters) < len(classes):
                    entry.condition.wait()
            session._release(entry, holder)
            with entry.condition:
                while len(order) < len(classes):
                    entry.condition.wait()
            for thread in threads:
                thread.join(5)
            self.assertEqual(
                [name for name, _reason in order],
                ["sol_foreground", "full_check", "ds_experiment", "opportunistic"],
            )
            # Before the Sol waiter registers, full_check can be first in line with no free worker.
            self.assertIn(order[1][1], ("queued behind sol_foreground", "queued: no free worker"))
            self.assertTrue(all(not thread.is_alive() for thread in threads))

            busy = entry.slots[0]
            with entry.condition:
                busy.busy = True
                busy.request_class = "ds_experiment"
            session.budget = lean_session.WorkerBudget(directory / "tokens-two", 2)
            admitted = []

            def second(request_class):
                slot = session._acquire(entry, 5, "model", "import Shared\n", request_class)
                with entry.condition:
                    admitted.append(request_class)
                    entry.condition.notify_all()
                session._release(entry, slot)

            extra = [threading.Thread(target=second, args=(name,)) for name in ("ds_experiment", "sol_foreground")]
            for thread in extra:
                thread.start()
            with entry.condition:
                while admitted != ["sol_foreground"]:
                    entry.condition.wait()
                self.assertEqual(
                    [waiter.queue_reason for waiter in entry.waiters],
                    ["queued: one DeepSeek Lean compilation is in flight"],
                )
                busy.busy = False
                entry.condition.notify_all()
            for thread in extra:
                thread.join(5)
            self.assertEqual(admitted, ["sol_foreground", "ds_experiment"])

            session.mem_fn = lambda: (1.0, None)
            entry.slots.clear()
            denied = session.check({
                "protocol": lean_session.PROTOCOL,
                "project": str(project),
                "fingerprint": key,
                "text": "theorem t : True := by\n  trivial\n",
                "display": "T.lean",
                "timeout": 1,
                "lane": "background",
                "request_class": "sol_foreground",
            })
            self.assertFalse(denied["ok"])
            self.assertIn("memory", denied["reason"])
            self.assertEqual(denied["outcome"], "inconclusive")
            self.assertEqual(denied["cause"], "resource")
            self.assertEqual(denied["admission"], "denied")
            self.assertEqual(lean_session.normalize_request_class("background"), "opportunistic")

    def test_v8_denied_request_is_inconclusive_and_never_runs_cold(self):
        from arena import engine, lean_session

        built = {"path": Path("/p"), "text": "t", "offset": 0, "head": 0, "start_line": 1, "end_line": 1}
        denied = {
            "ok": False,
            "reason": "no room for a Lean worker: memory (1.0 GB available)",
            "outcome": "inconclusive",
            "cause": "resource",
            "admission": "denied",
        }
        ok = {"ok": True, "returncode": 0, "output": ""}
        sent = []

        def request(payload, _wait):
            sent.append(payload)
            return ok if len(sent) == 3 else denied

        with (
            patch.object(lean_session, "configured", return_value=True),
            patch.object(lean_session, "request", request),
            patch.object(engine, "_session_request", return_value={}),
            patch.object(engine, "_run_cold") as cold,
            patch.object(engine, "candidate_file", return_value=built),
        ):
            result = engine.compile_version({}, "proof", "v", "c", request_class="ds_experiment")
            self.assertEqual(sent[0]["request_class"], "ds_experiment")
            self.assertEqual((result["outcome"], result["cause"], result["admission"]), ("inconclusive", "resource", "denied"))
            self.assertFalse(result["passed"])
            with self.assertRaises(engine.LeanInconclusive):
                engine.run_lean({}, Path("/p"), "t", request_class="opportunistic")
            cold.assert_not_called()
            engine.run_lean({}, Path("/p"), "t")
            self.assertEqual(sent[-1]["request_class"], "opportunistic")
            cold.assert_not_called()

