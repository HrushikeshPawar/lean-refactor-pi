"""Final v8 end-to-end journeys (slow; set ARENA_SLOW_TESTS=1).

Layers, stated per journey so a green run is not over-read:
  * Journey 1 uses the REAL orchestration, run_control and coordinator state machines. Worker children are the
    INJECTED child transport (`_HeldChild`), not real Pi RPC processes: pi_support's scripted provider cannot be
    wired to orchestration-launched workers. Lean outcomes are injected ledger rows.
  * Journey 2 uses REAL pinned Lean through the real tool layer; only the resource denial is injected.
    Heavy work: one extraction, a handful of scratch/compile checks and one full/cold certification of the
    lightest fixture row, each with a finite timeout.
  * Journey 3 is offline: cached renders, registered schemas and fixture ledgers.
"""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import orchestration, run_control
from tests.slow import slow
from tests.test_orchestration import _PROOF, _HeldChild, _request, _seed_parent

def setUpModule():
    # The fixture theorem "demo" is not a catalogued problem; its packet render has its own test in test_text.
    patcher = patch.object(orchestration, "_worker_packet", return_value="WORKER PACKET")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


ROOT = Path(__file__).resolve().parents[1]
ELAN_HOME = os.environ.get("ELAN_HOME") or str(Path.home() / ".elan")


def _until(predicate, what: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def _json_lines(*rows: dict) -> bytes:
    return b"".join((json.dumps(row) + "\n").encode() for row in rows)


class V8E2ETests(unittest.TestCase):
    # ------------------------------------------------------------------ journey 1
    @slow
    @patch.object(orchestration, "_MODEL_SLOTS", 2)  # the queue lifecycle under test needs a pool smaller than three jobs
    def test_parallel_run_stop_and_resume(self):
        """Real orchestration/run_control/coordinator; INJECTED child transport and Lean (no real Pi child)."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            (directory / "run-config.json").write_text(
                json.dumps({"theorem": "demo", "model": "gpt-6-sol", "limit_usd": 0.30})
            )
            self.assertEqual(str(run_control.run_threshold(directory)), "0.3")
            children: list[tuple[dict, _HeldChild]] = []
            owned: dict[str, _HeldChild] = {}

            def open_child(launch):
                child = _HeldChild()
                children.append((launch, child))
                owned[launch["env"]["ARENA_ACTIVATION_ID"]] = child
                return child

            def delegate(operation_id, task, **extra):
                return orchestration.delegate(
                    directory, operation_id=operation_id, run_id="run-1", actor_id="sol",
                    session_id="sol-session", task=task, open_child=open_child,
                    **({"scope": "proof", "anchor": {"node": "n1"}} | extra),
                )

            def view():
                return {job["job_id"]: job for job in orchestration.jobs(directory)["jobs"]}

            def control_text():
                return (directory / "control.jsonl").read_text()

            def command_id(job_id):
                return view()[job_id]["command_id"]

            def started(job_id):
                return {"type": "response", "id": command_id(job_id), "success": True,
                        "data": {"disposition": "started"}}

            def publish_candidate(launch, tag):
                proof_id, attempt_id, tool_call = f"proof-{tag}", f"attempt-{tag}", f"compile-{tag}"
                (directory / "proofs" / f"{proof_id}.lean").write_text(_PROOF)

                def record(writer):
                    writer.append_ledger({"kind": "attempt", "event_id": attempt_id, "proof_id": proof_id,
                                          "tool_call_id": tool_call, "request_id": f"req-{tag}"})
                    writer.append_ledger({"kind": "evaluation", "candidate_id": proof_id, "key": f"eval-{tag}",
                                          "mode": "fast", "result": {"ok": True}})

                run_control.apply_operation(directory, {
                    "operation_id": f"compile-op-{tag}", "kind": "compile", "arguments": {"proof": proof_id},
                    "run_id": "run-1", "actor_id": launch["env"]["ARENA_ACTOR_ID"],
                    "session_id": launch["env"]["ARENA_SESSION_ID"],
                }, record)
                return {"type": "tool_execution_end", "toolName": "compile", "toolCallId": tool_call,
                        "isError": False, "result": {"details": {"ok": True, "items": [{
                            "ok": True, "status": "closed", "attempts": [{"attempt_id": attempt_id}]}]}}}

            def settle_child(activation_id, *, exit_clean=True):
                child = owned[activation_id]
                child._chunks.put(_json_lines({"type": "agent_settled"}))
                child._chunks.put(None)
                orchestration.join_activation(activation_id)

            # --- delegation receipts return before any held worker response; a third job queues (two slots)
            a = delegate("op-a", "hypothesis a")
            b = delegate("op-b", "hypothesis b")
            c = delegate("op-c", "hypothesis c")
            self.assertEqual((a["state"], b["state"], c["state"]), ("launching", "launching", "queued"),
                             "receipts must precede any worker response (held children never answered)")
            self.assertEqual(len(children), 2)
            self.assertNotEqual(a["session_id"], b["session_id"])
            self.assertEqual(view()[a["job_id"]]["findings"], [])

            # --- Sol blocks in await_results with no provider traffic; a passing candidate wakes it before settlement
            before_rows = control_text()
            owned[a["activation_id"]]._chunks.put(_json_lines(started(a["job_id"])))
            owned[b["activation_id"]]._chunks.put(_json_lines(started(b["job_id"])))
            _until(lambda: view()[a["job_id"]]["state"] == "active", "job a active")
            registered = threading.Event()
            real_wait = orchestration._interest.wait

            def on_wait(*args, **kwargs):
                registered.set()
                return real_wait(*args, **kwargs)

            replies: list[dict] = []
            with patch.object(orchestration._interest, "wait", side_effect=on_wait):
                waiter = threading.Thread(
                    target=lambda: replies.append(orchestration.await_results(directory, actor_id="sol",
                                                                              job_ids=[a["job_id"]])),
                    daemon=True)
                waiter.start()
                self.assertTrue(registered.wait(5), "await_results did not block")
                history = orchestration._history(directory)
                self.assertEqual([row["actor_id"] for row in history if row.get("kind") == "wait"], ["sol"])
                self.assertFalse([row for row in history if row.get("kind") == "wait_end"])
                from arena.campaign import _served_actors
                self.assertTrue(next(r for r in _served_actors(history) if r["actor_id"] == "sol")["waiting"])
                self.assertNotIn("dispatch_started", control_text())
                owned[a["activation_id"]]._chunks.put(_json_lines(publish_candidate(children[0][0], "a1")))
                waiter.join(10)
                self.assertFalse(waiter.is_alive())
            self.assertEqual(replies[0]["wake_reason"], "result")
            self.assertEqual(replies[0]["events"][0]["attempt_id"], "attempt-a1")
            self.assertEqual(view()[a["job_id"]]["state"], "active",
                             "the passing candidate must be visible before its assignment settles")
            ends = [row for row in orchestration._history(directory) if row.get("kind") == "wait_end"]
            self.assertEqual([row["wake_reason"] for row in ends], ["result"])
            self.assertEqual(control_text().count('"kind":"settlement"'), before_rows.count('"kind":"settlement"'))
            delivered = orchestration.deliver(directory, "sol")
            self.assertEqual([r["proof_id"] for r in delivered["results"]], ["proof-a1"])
            other = orchestration.await_results(directory, actor_id="planner", job_ids=[a["job_id"]])
            self.assertEqual([e["attempt_id"] for e in other["events"]], ["attempt-a1"],
                             "event cursors are per actor: planner still sees what sol consumed")

            # --- a and b settle; their exit frees slots and the queued job c activates
            settle_child(a["activation_id"])
            settle_child(b["activation_id"])
            cursor = None
            for _ in range(3):  # a settled producer may report "settled" once, then nothing can wake the waiter
                idle = orchestration.await_results(directory, actor_id="sol", cursor=cursor, job_ids=[b["job_id"]])
                if idle["wake_reason"] == "no_pending_work":
                    break
                cursor = idle["next_cursor"]
            self.assertEqual(idle["wake_reason"], "no_pending_work")
            self.assertEqual(idle["events"], [])
            self.assertNotIn("dispatch_started", control_text(), "await_results made no provider call")
            _until(lambda: len(children) == 3, "queued job c to activate after exits")
            self.assertEqual(children[2][0]["env"]["ARENA_JOB_ID"], c["job_id"])
            owned[c["activation_id"]]._chunks.put(_json_lines(started(c["job_id"])))
            _until(lambda: view()[c["job_id"]]["state"] == "active", "job c active")

            # --- same-hypothesis follow-up resumes the session; a distinct hypothesis gets a fresh one
            follow = delegate("op-follow", "narrow a", job_id=a["job_id"], scope=None, anchor=None)
            self.assertTrue(follow["resumed"])
            self.assertEqual(follow["session_id"], a["session_id"])
            self.assertEqual(children[3][0]["session_dir"], children[0][0]["session_dir"])
            fresh = delegate("op-fresh", "a different hypothesis d")
            self.assertEqual(fresh["state"], "queued", "two slots are held by c and the follow-up")
            self.assertNotEqual(fresh["session_id"], a["session_id"])
            self.assertEqual(len(children), 4)

            # --- cancel keeps the slot until actual exit, then the queued job activates
            cancel = orchestration.cancel(directory, operation_id="op-cancel-c", run_id="run-1", actor_id="sol",
                                          session_id="sol-session", job_id=c["job_id"])
            self.assertEqual(cancel["state"], "cancelling")
            c_child = owned[c["activation_id"]]
            c_child.exit_on_eof = False
            c_child._chunks.put(None)
            orchestration.join_activation(c["activation_id"])
            held = view()
            self.assertTrue(held[c["job_id"]]["occupies_slot"], "cancelling job keeps its slot until exit")
            self.assertEqual(held[fresh["job_id"]]["state"], "queued")
            self.assertEqual(len(children), 4)
            c_child.absent = True
            orchestration.observe_exit(directory, c["activation_id"])
            _until(lambda: len(children) == 5, "queued job to activate after the cancelled child exited")
            self.assertEqual(view()[c["job_id"]]["state"], "cancelled")
            self.assertEqual(children[4][0]["env"]["ARENA_JOB_ID"], fresh["job_id"])

            # --- shared spend: sol and workers reach one total; duplicates do not double-charge
            follow_worker = children[3][0]["env"]["ARENA_ACTOR_ID"]
            _request(directory, "sol-call", "sol", "sol-job")
            _request(directory, "worker-call", follow_worker, a["job_id"])
            _request(directory, "worker-unknown", follow_worker, a["job_id"])

            def settle(settlement_id, actor, session, requests, amount, *, state="known", job_id=None, **extra):
                body = {"settlement_id": settlement_id, "run_id": "run-1", "actor_id": actor, "session_id": session,
                        "covered_request_ids": requests, "state": state, "amount": amount,
                        "usage": {"cost": {"total": float(amount)}} if state == "known" else {}, **extra}
                if job_id:
                    body["job_id"] = job_id
                return run_control.settle_usage(directory, body)

            sol_spend = settle("s-sol", "sol", "sol-session", ["sol-call"], "0.10", job_id="sol-job")
            worker_spend = settle("s-worker", follow_worker, follow["session_id"], ["worker-call"], "0.10",
                                  job_id=a["job_id"])
            self.assertEqual((sol_spend["total"], worker_spend["total"]), ("0.10", "0.20"),
                             "sol and worker settlements reach one shared total")
            duplicate = settle("s-worker", follow_worker, follow["session_id"], ["worker-call"], "0.10",
                               job_id=a["job_id"])
            self.assertTrue(duplicate["reused"])
            self.assertEqual(duplicate["total"], "0.20", "a duplicate settlement must not double-charge")
            unknown = settle("s-unknown", follow_worker, follow["session_id"], ["worker-unknown"], "0",
                             state="unknown", job_id=a["job_id"])
            self.assertEqual(unknown["total"], "0.20")
            self.assertEqual(unknown["accounting"], "unknown")
            self.assertIn("worker-unknown", unknown["unknown_requests"])
            self.assertFalse(unknown["stopped"])

            # --- coordinator restart at a launch/settlement boundary: owned children are reconciled first
            d_launch, d_child = children[4]
            d_worker, d_session = d_launch["env"]["ARENA_ACTOR_ID"], d_launch["env"]["ARENA_SESSION_ID"]
            generation = next(row["generation"] for row in reversed(run_control._control_rows(directory))
                              if row.get("kind") == "run_generation")
            uncertain = run_control.begin_dispatch(directory, {
                "request_id": "req-d", "attempt_id": "attempt-d", "run_id": "run-1", "actor_id": d_worker,
                "session_id": d_session, "job_id": fresh["job_id"], "generation": generation}, lambda: None)
            self.assertEqual(uncertain["sent"], "uncertain")
            for bucket in (orchestration._owned, orchestration._openers, orchestration._live, orchestration._readers):
                bucket.clear()
            orchestration._stop_sent.clear()
            identity = d_child.process_identity()
            probes = {identity["pid"]: {"alive": True, "group_alive": True, "start_id": identity["start_id"],
                                        "run_id": "run-1"}}
            signalled: list[int] = []
            opened_before = len(children)
            held_view = orchestration.reconcile(
                directory, inspect=lambda pid: probes.get(pid, {"alive": False, "group_alive": False}),
                signal=signalled.append, open_child=open_child)
            self.assertEqual(signalled, [identity["pgid"]], "the owned old child is signalled")
            self.assertEqual(held_view["status"], "recovering")
            self.assertEqual(held_view["replacements"], 0)
            self.assertEqual(len(children), opened_before, "no replacement while the old child may be alive")
            fenced = run_control.begin_dispatch(directory, {
                "request_id": "req-fenced", "attempt_id": "attempt-fenced", "run_id": "run-1", "actor_id": "sol",
                "session_id": "sol-session", "generation": generation}, lambda: self.fail("transport during recovery"))
            self.assertFalse(fenced["admitted"])
            probes[identity["pid"]] = {"alive": False, "group_alive": False}
            gone = orchestration.reconcile(
                directory, inspect=lambda pid: probes.get(pid, {"alive": False, "group_alive": False}),
                signal=signalled.append, open_child=open_child)
            # The owner is confirmed dead, so recovery records req-d as unknown usage and resumes; req-d is not resent.
            self.assertEqual(gone["status"], "running", "a dead owner's uncertain request settles as unknown")
            self.assertIn("req-d", run_control._apply_coverage(run_control._control_rows(directory))["unknown"])
            self.assertFalse(any(row.get("request_id") == "req-d" and row.get("kind") == "dispatch"
                                 for row in run_control._control_rows(directory)[-50:]
                                 if row.get("attempt_id") != "attempt-d"), "req-d is not resent")
            resumed = gone
            self.assertGreaterEqual(resumed["replacements"], 1)
            self.assertEqual(len(children), opened_before + resumed["replacements"])

            # --- crossing the per-run limit (0.30) stops new dispatch
            _request(directory, "sol-call-2", "sol", "sol-job")
            crossing = settle("s-cross", "sol", "sol-session", ["sol-call-2"], "0.20", job_id="sol-job")
            self.assertGreaterEqual(float(crossing["total"]), 0.30)
            self.assertTrue(crossing["stop_transition"])
            self.assertEqual(crossing["stop_reason"], "spend_threshold")
            state = run_control.read_state(directory)
            self.assertEqual(state["stops"], ["spend_threshold"])
            self.assertEqual(float(json.loads((directory / "cost.json").read_text())["limit_usd"]), 0.30)
            refused = run_control.begin_dispatch(directory, {
                "request_id": "req-after", "attempt_id": "attempt-after", "run_id": "run-1", "actor_id": "sol",
                "session_id": "sol-session",
                "generation": next(r["generation"] for r in reversed(run_control._control_rows(directory))
                                   if r.get("kind") == "run_generation")},
                lambda: self.fail("a fetch began after the stop boundary"))
            self.assertFalse(refused["admitted"])
            self.assertEqual(refused["reason"], "run_stopped")
            count = len(children)
            late = delegate("op-after-stop", "after the stop")
            self.assertEqual(len(children), count, f"no new child after stop; delegate said {late}")
            self.assertEqual(orchestration.await_results(directory, actor_id="sol")["wake_reason"], "run_stopped")

            # --- shutdown: every child ends, nothing is left awaiting settlement
            for child in {id(c): c for _, c in children}.values():
                child._chunks.put(None)
            for activation_id in list(owned):
                orchestration.join_activation(activation_id, timeout=2)

    # ------------------------------------------------------------------ journey 2
    @slow
    def test_real_lean_promotion_and_cold(self):
        """REAL pinned Lean on the lightest benchmark row; only the resource denial is injected.

        Heavy work (declared up front): one cold context extraction (~100 s, library scan), one reference compile
        on both pins (~60 s), two anchored scratch promotions (~50 s) and one cold re-check on both pins (~40 s).
        Total about 5 minutes; a 840 s alarm bounds the whole journey and the engine bounds each Lean call.
        Not exercised: foreground/full-check/DS admission contention, Core and SKI pins (see report).
        """
        import signal
        import uuid

        from arena import campaign, context, engine, lean_session, tools
        from arena.steps import split_steps

        env = {"ELAN_HOME": ELAN_HOME, "PATH": f"{ELAN_HOME}/bin{os.pathsep}{os.environ.get('PATH', '')}"}
        with patch.dict(os.environ, env):
            if shutil.which("lake") is None:
                self.skipTest("lake is not installed")
            name = "putnam_1964_b2"  # standalone Putnam row, two pins, the smallest proof in the warmup set
            row = engine.problem(name)
            pins = [version for version, _commit in engine.versions(row)]
            self.assertEqual(pins, ["v4.25.0", "v4.26.0"])
            steps = split_steps(row["src"])
            last = len(steps)

            def alarm(_signum, _frame):
                raise TimeoutError("journey 2 exceeded its 840 s bound")

            previous = signal.signal(signal.SIGALRM, alarm)
            signal.setitimer(signal.ITIMER_REAL, 840)
            run_id = f"e2e-v8-{uuid.uuid4().hex[:8]}"
            directory = campaign.run_dir(run_id)
            cache = tempfile.TemporaryDirectory()
            self.addCleanup(cache.cleanup)
            try:
                # -- real context extraction, with a private cache so the extractor itself runs
                def private_cache(kind, name_, commit, salt):
                    return Path(cache.name) / f"{kind}-{name_}-{commit[:12]}.json"

                with patch.object(context, "_cache", private_cache):
                    extracted = context.lean_context(name)
                self.assertNotIn("error", extracted)
                self.assertTrue(extracted["complete"])
                self.assertEqual(extracted["failure"], [])
                self.assertTrue(extracted["goal"], "no goals extracted from the target proof")
                self.assertTrue(extracted["target"], "no target predicate records")
                self.assertEqual(
                    sorted(goal["proof_line"] for goal in extracted["goal"]),
                    [step.first_line for step in steps],
                    "goal coverage: one goal per top-level step of the target proof",
                )
                self.assertIn("Finset.card", json.dumps(extracted["goal"]))
                self.assertIn("Fintype", {item["name"] for item in extracted["source"]}, "statement definition missing")

                # -- real run: reference compile on every pin
                with patch.object(campaign, "packet", return_value="packet"):
                    campaign.init(name, run_id)
                candidate_file = directory / "scratch" / "project" / campaign.source_path(row)
                reference = tools.compile_tool(name, run_id, {"drafts": [row["src"]]})["items"][0]
                self.assertEqual(reference["verification"]["primary"], "passed")
                self.assertIn(f"versions {len(pins)}/{len(pins)}", reference["price"])

                # -- isolated scratch: a general check files no candidate and leaves the candidate file alone
                before = candidate_file.read_bytes()
                candidates = [e for e in campaign.events(directory) if e.get("kind") == "candidate"]
                scratch = tools.scratch_tool(name, run_id, {"code": "#check Fintype.card\nexample : 1 + 1 = 2 := rfl"})
                item = scratch["items"][0]
                self.assertEqual(item["outcome"], "success")
                self.assertEqual(item["promotion"]["state"], "not_promoted")
                self.assertEqual(item["promotion"]["reason"], "general_check")
                self.assertEqual(candidate_file.read_bytes(), before)
                self.assertEqual([e for e in campaign.events(directory) if e.get("kind") == "candidate"], candidates)
                self.assertEqual(tools.read_tool(name, run_id, {"experiment": item["experiment_id"]})["items"][0]["code"],
                                 item["code"])

                # -- anchored replacement promotes inside the same call
                anchor = {"node": reference["node"], "steps": [last, last]}
                good = tools.scratch_tool(name, run_id, {"replacement": "exact id h_card", "at": anchor})["items"][0]
                self.assertEqual(good["outcome"], "success")
                self.assertTrue(good["promotion"].get("node") and good["promotion"].get("evaluation_id"))
                self.assertEqual(good["promotion"]["verification"]["fast"], "passed")
                self.assertTrue(any(line.startswith("promoted ") for line in good["lines"]), good["lines"])
                self.assertEqual(len([e for e in campaign.events(directory) if e.get("kind") == "candidate"]),
                                 len(candidates) + 1)

                # -- a real invalid proof is a proof_error, never inconclusive
                bad = tools.scratch_tool(name, run_id, {"replacement": "exact h_no_empty", "at": anchor})["items"][0]
                self.assertEqual(bad["promotion"]["verification"]["fast"], "proof_error")
                self.assertNotEqual(bad["promotion"].get("reason"), "inconclusive")
                messages = json.dumps(bad["promotion"]["diagnostics"])
                self.assertIn("Type mismatch", messages)

                # -- an injected resource denial is inconclusive and carries no proof diagnostics
                denied = {"ok": False, "reason": "no room for a Lean worker: memory (1.0 GB available)",
                          "outcome": "inconclusive", "cause": "resource", "admission": "denied"}
                with patch.object(lean_session, "configured", return_value=True), patch.object(
                    lean_session, "request", lambda _payload, _wait: denied
                ):
                    refused = tools.scratch_tool(name, run_id, {"replacement": "exact (h_card)", "at": anchor})["items"][0]
                self.assertEqual(refused["outcome"], "inconclusive")
                self.assertEqual(refused["promotion"]["verification"]["fast"], "inconclusive")
                self.assertEqual(refused["promotion"]["reason"], "inconclusive")
                self.assertFalse(refused["promotion"]["diagnostics"].get(pins[0]))
                self.assertNotIn("proof_error", json.dumps(refused["promotion"]["verification"]))

                # -- primary / full / cold for the reference proof on every required pin
                full = campaign.evaluate_request(name, run_id, row["src"], "full")
                self.assertEqual(set(full["compat"]), set(pins))
                self.assertTrue(all(info["passed"] is True for info in full["compat"].values()))
                graph = campaign.graph_state(run_id)
                node = next(item for item in graph["nodes"] if item["id"] == reference["node"] or item["origin"] == "reference")
                self.assertEqual(node["status"], "full", "endpoint pins alone must not stand in for the full check")
                cold = campaign.cold_verify(run_id, {"id": node["id"], "heartbeats": node["heartbeat"]})
                self.assertEqual(cold["state"], "finished")
                self.assertEqual(set(cold["passed"]), set(pins), "cold must establish every required pin")
                self.assertTrue(all(cold["passed"].values()), cold)
                self.assertEqual(cold["outcome"], "passed", cold)
                self.assertTrue(cold["confirmed"])
                self.assertEqual({v for v, _ in cold["context"]["pins"]}, set(pins))
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous)
                shutil.rmtree(directory, ignore_errors=True)

    # ------------------------------------------------------------------ journey 3
    @slow
    def test_packet_reply_viewer_evidence(self):
        """Offline: cached packet renders, registered schemas, fixture ledgers. No Lean, no Pi, no provider."""
        import glob
        import hashlib
        import importlib
        import re

        from arena import campaign, context, reply, tool_schema, tools, viewer_data

        serve_cli = importlib.import_module("arena.cli.serve")  # `arena.cli.serve` attribute is shadowed by a function
        from arena.memory import memory, original_evidence

        docs = ROOT / "docs" / "packet-review-2026-10-18"
        manifest = json.loads((docs / "manifest.json").read_text())

        # -- the preserved baseline stays byte-identical to its recorded hash (it is evidence, not a golden file)
        for entry in manifest["packets"]:
            baseline = (docs / entry["task_packet"]).read_bytes()
            self.assertEqual(hashlib.sha256(baseline).hexdigest(), entry["task_sha256"], entry["task_packet"])
            self.assertIn(b"pts_if_gone", baseline, "the baseline is the pre-v8 render")

        # The Lean context script changed on 2026-10-21, so exact-key cache lookups for SKI and Fiberwise miss.
        # Cache-only still: fall back to the newest cached context of the same theorem and never start Lean.
        original = context.cached_context

        def newest_cached(name):
            found = original(name)
            if found:
                return found
            files = sorted(glob.glob(str(ROOT / "runs" / "cache" / "context" / f"{name}-*.json")), key=os.path.getmtime)
            return json.loads(Path(files[-1]).read_text()) if files else {}

        packets = {}
        with patch.object(context, "cached_context", newest_cached), patch.object(
            context, "lean_context", side_effect=AssertionError("cache-only render started Lean")
        ):
            for entry in manifest["packets"]:
                packets[entry["theorem"]] = context.render_packet(entry["theorem"], cache_only=True)
            rows = {name: context.problem(name) for name in packets}
            for name, rendered in packets.items():
                row = rows[name]
                with self.subTest(theorem=name):
                    self.assertIn(row["statement"].strip(), rendered, "exact theorem statement")
                    for _version, commit in context.versions(row):
                        self.assertNotIn(commit, rendered, "raw pin hash leaked into the packet")
                        self.assertNotIn(commit[:12], rendered)
                    self.assertIsNone(re.search(r"\b[0-9a-f]{40}\b", rendered), "a 40-hex hash is in the packet")
                    self.assertNotIn("pts_if_gone", rendered)
                    self.assertRegex(rendered, r"(?m)^Nested measured span under parent s\d+ lines \d+-\d+")
                    self.assertRegex(rendered, r"(?m)^Full detail: read\(node=\w+, view=tree\)")
                    self.assertNotEqual(rendered.encode(), (docs / next(
                        e["task_packet"] for e in manifest["packets"] if e["theorem"] == name)).read_bytes())

            # worker packet: same theorem packet, worker tool help (no management tools)
            worker_tools = tool_schema.render_tool_sections(tool_schema.registered_tools("worker"))
            worker_packet = "\n\n".join(body for _name, body in worker_tools) + "\n\n" + packets["Core.InitsUpdatesComm"]
            self.assertIn(rows["Core.InitsUpdatesComm"]["statement"].strip(), worker_packet)
            self.assertNotIn("pts_if_gone", worker_packet)
            for management in ("delegate", "await_results"):
                self.assertNotIn(f"\n{management}", worker_packet)

        # -- full-detail retrieval: the packet's pointer names a view the registered read schema really offers
        schemas = tool_schema.catalog()
        self.assertIn("tree", schemas["tools"]["read"]["properties"]["view"]["enum"])
        self.assertIn("source", schemas["tools"]["read"]["properties"]["view"]["enum"])
        self.assertIn("read(node=<original proof node>, view=source)", packets["Core.InitsUpdatesComm"])

        # -- five proof tools plus management tools, against the registered schema
        worker_names = [t["name"] for t in tool_schema.registered_tools("worker")]
        sol_names = [t["name"] for t in tool_schema.registered_tools("sol")]
        self.assertEqual(worker_names, ["compile", "goal", "search", "read", "scratch", "card", "ideas"])
        self.assertEqual(sol_names[:7], worker_names[:7])
        self.assertEqual(set(sol_names) - set(worker_names), {"delegate", "jobs", "await_results", "cancel"})

        def walk(properties, depth=0):
            for key, field in properties.items():
                yield key, field, depth
                yield from walk(field.get("properties") or {}, depth + 1)
                yield from walk((field.get("items") or {}).get("properties") or {}, depth + 1)

        for role in ("worker", "sol"):
            for section, body in tool_schema.render_tool_sections(tool_schema.registered_tools(role)):
                with self.subTest(role=role, tool=section):
                    schema = schemas["tools"][section]
                    self.assertEqual(body.count("```") % 2, 0, "malformed fence in help")
                    self.assertNotIn("None", body)
                    self.assertNotIn("{", body.replace("{{", ""), "unrendered placeholder")
                    for key, field, depth in walk(schema.get("properties") or {}):
                        line = next((ln for ln in body.splitlines() if ln.startswith("  " * depth + f"{key}: ")), None)
                        self.assertIsNotNone(line, f"help lacks {key} at depth {depth}")
                        self.assertIn("required" if field.get("required") else "optional", line)
                        for value in field.get("enum") or []:
                            self.assertIn(value, line)
                        if field.get("default") is not None:
                            self.assertIn(f"default {field['default']}", line)
                        if field.get("type") == "array" and "minItems" in field and "maxItems" in field:
                            self.assertIn(f"{field['minItems']}..{field['maxItems']}", line)
                    for exclusive in schema.get("exclusive") or []:
                        self.assertIn(exclusive, body)

        # -- two actors prove the same text: both attempts, the original bytes, no uncommitted rows
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            (directory / "proofs").mkdir()
            proof = "theorem t : True := by\n  trivial\n"
            (directory / "proofs" / "ref.lean").write_text("theorem t : True := by\n  sorry\n")
            (directory / "proofs" / "c2.lean").write_text(proof)

            def derivation(actor, session, event, operation, **extra):
                return {"kind": "derivation", "proof_id": "c2", "candidate_id": "c2", "actor_id": actor,
                        "session_id": session, "parents": ["ref"], "event_id": event, "operation_id": operation,
                        "data": {"relation": "exact", "operation": {"type": "edited_from"},
                                 "inputs": [{"role": "parent", "id": "ref"}], **extra}}

            def attempt(actor, session, event, operation, call):
                return {"kind": "attempt", "proof_id": "c2", "candidate_id": "c2", "actor_id": actor,
                        "session_id": session, "event_id": event, "operation_id": operation, "tool_call_id": call,
                        "data": {"relation": "exact"}}

            def write_rows(path, rows):
                path.write_text("".join(json.dumps(row) + "\n" for row in rows))

            write_rows(directory / "ledger.jsonl", [
                {"kind": "init", "theorem": "T", "ts": 0.1, "versions": ["v1"]},
                {"kind": "candidate", "ts": 1.0, "candidate_id": "ref", "origin": "reference", "parents": []},
                {"kind": "candidate", "ts": 1.5, "candidate_id": "ghost", "origin": "model", "parents": ["ref"],
                 "operation_id": "op-uncommitted"},
                {"kind": "candidate", "ts": 2.5, "candidate_id": "c2", "origin": "model", "parents": ["ref"],
                 "tool_call_id": "call-sol", "operation_id": "op-sol"},
                derivation("sol", "sol-session", "der-sol", "op-sol"),
                attempt("sol", "sol-session", "try-sol", "op-sol", "call-sol"),
                derivation("worker-a", "worker-session", "der-worker", "op-worker"),
                attempt("worker-a", "worker-session", "try-worker", "op-worker", "call-worker"),
                attempt("ghost", "ghost-session", "try-ghost", "op-uncommitted", "call-ghost"),
                {"kind": "wait", "wait_id": "w1", "actor_id": "sol", "session_id": "sol-session",
                 "job_ids": [], "cursor": None},
            ])
            write_rows(directory / "control.jsonl", [
                {"kind": "operation_receipt", "status": "committed", "operation_id": "op-sol"},
                {"kind": "operation_receipt", "status": "committed", "operation_id": "op-worker"},
            ])
            viewer_calls = [
                {"kind": "request", "id": "r1", "ts": 1000, "post_hook": {"messages": []}},
                {"kind": "tool_call", "id": "r1", "ts": 2000, "tool_call_id": "call-sol", "name": "compile", "args": {}},
                {"kind": "tool_result", "id": "r1", "ts": 4000, "tool_call_id": "call-sol", "name": "compile",
                 "trimmed": True, "text": "sol body\nfull untrimmed", "delivered_text": "sol body", "footer": "f"},
                {"kind": "response", "id": "r1", "ts": 4500, "content": [{"type": "text", "text": "ok"}]},
                {"kind": "request", "id": "r2", "ts": 5000, "post_hook": {"messages": []}},
                {"kind": "tool_call", "id": "r2", "ts": 6000, "tool_call_id": "call-worker", "name": "compile", "args": {}},
                {"kind": "tool_result", "id": "r2", "ts": 8000, "tool_call_id": "call-worker", "name": "compile",
                 "trimmed": False, "text": "worker body", "delivered_text": "worker body", "footer": "f"},
                {"kind": "response", "id": "r2", "ts": 8500, "content": [{"type": "text", "text": "ok"}]},
            ]
            write_rows(directory / "trace-journal.jsonl", viewer_calls)
            ledger_bytes = (directory / "ledger.jsonl").read_bytes()
            with patch("arena.campaign.run_dir", return_value=directory), patch(
                "arena.cli.serve.run_dir", return_value=directory
            ):
                waiting_payload = serve_cli.graph_payload("served")
                found = viewer_data.node_calls(directory, "n2")
                with (directory / "ledger.jsonl").open("a") as ledger:
                    ledger.write(json.dumps({"kind": "wait_end", "wait_id": "w1", "actor_id": "sol",
                                             "wake_reason": "result"}) + "\n")
                ended_payload = serve_cli.graph_payload("served")
            node = next(item for item in waiting_payload["nodes"] if item["id"] == "c2")
            self.assertEqual(sorted(a["actor_id"] for a in node["attempts"]), ["sol", "worker-a"])
            self.assertEqual(
                sorted(d["actor_id"] for d in node["alternate_derivations"]), ["sol", "worker-a"])
            self.assertEqual(sorted(a["actor_id"] for a in found["attempts"]), ["sol", "worker-a"])
            self.assertNotIn("ghost", json.dumps(waiting_payload["nodes"]))
            self.assertNotIn("ghost", json.dumps(found["attempts"]) + json.dumps(found["derivations"]))
            stored = {item["line"] for item in found["records"]}
            self.assertTrue(stored)
            self.assertTrue(all(line in ledger_bytes.decode() for line in stored), "records are original ledger bytes")
            self.assertFalse(any("ghost" in line for line in stored))
            self.assertEqual(found["artifact"]["bytes"], proof)
            self.assertEqual(
                [(item["tool_call_id"], item["call"]["delivered"]) for item in found["call_refs"]],
                [("call-sol", "sol body"), ("call-worker", "worker body")])
            self.assertEqual(found["call"]["untrimmed"], "sol body\nfull untrimmed",
                             "delivered and untrimmed stay distinct")
            # -- the served payload shows an intentionally waiting actor only while the wait is open
            self.assertTrue(next(a for a in waiting_payload["actors"] if a["actor_id"] == "sol")["waiting"])
            self.assertFalse(next(a for a in ended_payload["actors"] if a["actor_id"] == "sol")["waiting"])

        # -- compaction memory per actor: own focus only; references retrievable with read(ref=...)
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            (directory / "proofs").mkdir()
            (directory / "proofs" / "cd-alt.lean").write_text("alternate body\n")
            with patch.object(campaign, "run_dir", return_value=directory):
                campaign._append(directory, {"kind": "strategy", "actor_id": "sol", "text": "keep the second parent"})
                campaign._append(directory, {"kind": "derivation", "event_id": "der-main", "proof_id": "proof-main",
                                             "candidate_id": "proof-main", "parents": [],
                                             "data": {"relation": "exact", "artifact": "main-body"}})
                campaign._append(directory, {"kind": "derivation", "event_id": "der-alt", "operation_id": "op-alt",
                                             "proof_id": "proof-alt", "candidate_id": "proof-alt",
                                             "parents": ["proof-main"], "data": {"relation": "exact", "artifact": "x"}})
                campaign._append(directory, {"kind": "observation", "event_id": "obs-a", "actor_id": "worker-a",
                                             "text": "the first parent stays open"})
                (directory / "control.jsonl").write_text(
                    '{"kind":"operation_receipt","status":"committed","operation_id":"op-alt"}\n')
                reply.set_actor_focus("resume", "proof-main", actor="worker-a")
                reply.set_actor_focus("resume", "proof-b-only", actor="worker-b")
                sol_memory = memory("resume", actor="sol")
                memories = {actor: memory("resume", actor=actor) for actor in ("worker-a", "worker-b")}
                followed = tools.read_tool("T", "resume", {"ref": "op-alt"})
                evidence = original_evidence("resume", "der-main")
            self.assertIn("keep the second parent", sol_memory["text"])
            self.assertIn("worker-a proof-main", memories["worker-a"]["text"])
            self.assertNotIn("proof-b-only", memories["worker-a"]["text"])
            self.assertIn("proof-b-only", memories["worker-b"]["text"])
            self.assertNotIn("worker-a proof-main", memories["worker-b"]["text"])
            self.assertNotIn("worker-a proof-main", sol_memory["text"])
            self.assertNotIn("proof-b-only", sol_memory["text"])
            for ref in ("der-main", "der-alt"):
                self.assertIn(ref, sol_memory["text"], "the summary names the durable reference")
            self.assertTrue(followed["ok"])
            self.assertEqual(followed["items"][0]["record"]["event_id"], "der-alt")
            self.assertEqual(evidence["data"]["artifact"], "main-body")
