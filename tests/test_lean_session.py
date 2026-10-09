"""Persistent Lean session: equivalence with cold compiles, fallback, and process lifecycle."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from tests.slow import slow
from arena import campaign, engine, lean_session
from arena.engine import (ROOT, compile_version, force_cold, instrument_sorries, last_lean_run, problem,
                          versions)

CORE = "Core.InitsUpdatesComm"
PHYSLIB = "fundamental_theorem_of_variational_calculus'"
CORE_READY = (ROOT / "workspaces/strata-v4.29.1").is_dir()
PHYSLIB_READY = (ROOT / "workspaces/physlib-v4.32.0").is_dir()
TOLERANCE = 0.05  # tools/arena_certify.py default


def alive(pid: int) -> bool:
    """A process that is running (a zombie awaiting its parent does not count)."""
    return lean_session.running(pid)


def wait_until(check, seconds: float = 20.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.2)
    return check()


class RenderTests(unittest.TestCase):
    def test_information_is_bare_text_and_problems_carry_a_position(self):
        text = "a\nlemma x := by\n  simp\n"
        found = [
            {"severity": 3, "message": "ARENA_HEARTBEATS 7", "range": {"start": {"line": 0, "character": 0}}},
            {"severity": 1, "message": "unsolved goals\n⊢ False",
             "range": {"start": {"line": 2, "character": 2}}},
            {"severity": 2, "message": "unused variable", "range": {"start": {"line": 1, "character": 6}}},
        ]
        code, output = lean_session.render(found, text, "A/B.lean")
        self.assertEqual(code, 1)
        self.assertEqual(output.splitlines(), ["ARENA_HEARTBEATS 7", "A/B.lean:3:2: error: unsolved goals",
                                               "⊢ False", "A/B.lean:2:6: warning: unused variable"])
        self.assertEqual(lean_session.render(found[:1] + found[2:], text, "A/B.lean")[0], 0)

    def test_columns_count_code_points_not_utf16_units(self):
        # 𝓝 is outside the BMP: two UTF-16 units, one code point.
        text = "x 𝓝 y bad\n"
        found = [{"severity": 1, "message": "boom", "range": {"start": {"line": 0, "character": 7}}}]
        self.assertEqual(lean_session.render(found, text, "f.lean")[1], "f.lean:1:6: error: boom")

    def test_parsed_output_is_what_the_cold_path_parses(self):
        found = [{"severity": 1, "message": "Type mismatch\n  rfl", "range": {"start": {"line": 4, "character": 3}}},
                 {"severity": 3, "message": "ARENA_HEARTBEATS 9", "range": {"start": {"line": 0, "character": 0}}}]
        _, output = lean_session.render(found, "\n" * 4 + "abcdef\n", "f.lean")
        parsed = engine.parse_diagnostics(output)
        self.assertEqual([(d["severity"], d["line"], d["column"]) for d in parsed],
                         [("error", 5, 3), ("info", None, None)])


class FallbackTests(unittest.TestCase):
    """A session that cannot answer must never change an answer, only the path."""

    def setUp(self):
        self.row = {"name": "T", "file_path": "A/B.lean"}

    def run_lean(self, reply, **env):
        with patch.dict(os.environ, {lean_session.ENV: "/nonexistent.sock", **env}, clear=False), \
                patch.object(lean_session, "request", return_value=reply), \
                patch.object(engine, "_fingerprint", return_value={"code": "x"}), \
                patch.object(engine, "_run_cold", return_value=(0, "cold output")):
            return engine.run_lean(self.row, Path("/p"), "text"), last_lean_run()

    def test_unconfigured_runs_are_cold_without_a_reason(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(engine, "_run_cold", return_value=(0, "x")):
            os.environ.pop(lean_session.ENV, None)
            result = engine.run_lean(self.row, Path("/p"), "text")
        self.assertEqual(result, (0, "x"))
        self.assertEqual(last_lean_run()["path"], "cold")

    def test_unavailable_stale_or_crashed_sessions_fall_back_and_say_why(self):
        for reason in ("session unreachable: FileNotFoundError", "stale session: toolchain changed",
                       "Lean server crashed", "no room for a Lean worker: memory (2.0 GB available)"):
            result, info = self.run_lean({"ok": False, "reason": reason})
            self.assertEqual(result, (0, "cold output"))
            self.assertEqual((info["path"], info["reason"]), ("cold-fallback", reason))

    def test_a_session_timeout_is_a_timeout(self):
        result, info = self.run_lean({"ok": True, "timeout": True})
        self.assertIsNone(result)
        self.assertEqual(info["path"], "session")

    def test_force_cold_ignores_a_configured_session(self):
        with patch.dict(os.environ, {lean_session.ENV: "/nonexistent.sock"}), \
                patch.object(lean_session, "request", side_effect=AssertionError("asked the session")), \
                patch.object(engine, "_run_cold", return_value=(0, "cold")):
            with force_cold():
                self.assertEqual(engine.run_lean(self.row, Path("/p"), "text"), (0, "cold"))
        self.assertEqual(last_lean_run()["path"], "cold")

    def test_model_view_reports_the_path_only_when_it_is_not_plain_cold(self):
        compat = {"v1": {"passed": True, "lean": {"path": "session"}},
                  "v2": {"passed": True, "lean": {"path": "cold-fallback", "reason": "stale session: wrapper changed"}},
                  "v3": {"passed": True, "lean": {"path": "cold"}}}
        view = campaign._model_view({"ok": True, "compat": compat})["compat"]
        self.assertEqual(view["v1"]["lean"], "session")
        self.assertEqual(view["v2"]["lean"], "cold (session unavailable: stale session: wrapper changed)")
        self.assertNotIn("lean", view["v3"])


    def test_model_view_labels_a_failed_draft_heartbeat_and_marks_it_not_compiled(self):
        failed = {"ok": True, "heartbeat": 6834, "tokens": 42,
                  "compat": {"v1": {"passed": False, "heartbeats": 6834}}}
        view = campaign._model_view(failed)
        self.assertIs(view["compiled"], False)
        self.assertTrue(view["ok"])
        self.assertEqual(view["heartbeat_to_failure"], 6834)
        self.assertNotIn("heartbeat", view)
        self.assertEqual(view["compat"]["v1"], {"passed": False, "heartbeats_to_failure": 6834})
        good = campaign._model_view({"ok": True, "heartbeat": 10,
                                     "compat": {"v1": {"passed": True, "heartbeats": 10}}})
        self.assertEqual(good["heartbeat"], 10)
        self.assertEqual(good["compat"]["v1"]["heartbeats"], 10)
        self.assertNotIn("compiled", good)


@slow
class DaemonTests(unittest.TestCase):
    """The per-run daemon, without any Lean."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="arena-session-"))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)

    def test_start_serve_and_stop_removes_every_trace(self):
        process = lean_session.start_daemon(self.directory)
        path = str(lean_session.socket_path(self.directory))
        status = lean_session.request({"op": "status"}, 5, path)
        self.assertTrue(status["ok"])
        self.assertEqual(status["servers"], [])
        self.assertEqual(status["code"], lean_session.code_sha())
        lean_session.stop_daemon(self.directory, process)
        self.assertIsNotNone(process.poll())
        self.assertFalse(Path(path).exists())
        self.assertFalse((self.directory / lean_session.INFO_NAME).exists())
        self.assertEqual(lean_session.request({"op": "status"}, 2, path)["ok"], False)

    def test_a_long_run_directory_gets_a_short_socket_and_the_pointer_says_where(self):
        deep = self.directory / ("x" * 90)
        process = lean_session.start_daemon(deep)
        try:
            path = lean_session.socket_path(deep)
            self.assertLessEqual(len(str(path)), lean_session.SOCKET_LIMIT)
            self.assertEqual(json.loads((deep / lean_session.INFO_NAME).read_text())["socket"], str(path))
            self.assertTrue(lean_session.request({"op": "status"}, 5, str(path))["ok"])
        finally:
            lean_session.stop_daemon(deep, process)

    def test_a_stale_evaluator_gets_a_stale_answer_not_a_compile(self):
        process = lean_session.start_daemon(self.directory)
        try:
            reply = lean_session.request({
                "op": "check", "protocol": lean_session.PROTOCOL, "project": str(self.directory),
                "fingerprint": {"code": "not-the-running-evaluator"}, "text": "x", "display": "f.lean",
                "timeout": 5}, 10, str(lean_session.socket_path(self.directory)))
            self.assertEqual((reply["ok"], reply["stale"]), (False, True))
            self.assertIn("evaluator changed", reply["reason"])
        finally:
            lean_session.stop_daemon(self.directory, process)

    def test_the_daemon_exits_when_its_runner_is_gone(self):
        parent = subprocess.Popen(["sleep", "300"])
        try:
            process = lean_session.start_daemon(self.directory, parent=parent.pid)
            parent.kill()
            parent.wait()
            self.assertTrue(wait_until(lambda: process.poll() is not None, 15), "daemon outlived its runner")
            self.assertFalse(lean_session.socket_path(self.directory).exists())
        finally:
            parent.kill()
            lean_session.stop_daemon(self.directory, None)

    def test_process_tree_and_memory_probes_see_children_in_other_groups(self):
        parent = subprocess.Popen(["sh", "-c", "setsid sleep 30 & wait"], start_new_session=True)
        try:
            self.assertTrue(wait_until(lambda: len(lean_session.process_tree(parent.pid)) >= 2, 5))
            self.assertGreater(lean_session.tree_pss_gb(parent.pid), 0)
            self.assertEqual(lean_session.process_tree(2**30), [])
            self.assertEqual(lean_session.tree_pss_gb(2**30), 0)
        finally:
            for pid in lean_session.process_tree(parent.pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            parent.wait()


@slow
class SubmissionColdVerificationTests(unittest.TestCase):
    """A candidate that only a session vouched for is re-verified cold before it is submitted."""

    def setUp(self):
        self.cold_calls = 0
        self.cold_heartbeats = 10
        self.cold_passes = True
        self.cold_only = False
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        patches = [patch.object(campaign, "ROOT", Path(self.temporary.name)),
                   patch.object(campaign, "problem", return_value={"name": "T"}),
                   patch.object(campaign, "validate_proof"),
                   patch.object(campaign, "versions", return_value=[("v1", "a"), ("v2", "b")]),
                   patch.object(campaign, "materialize", return_value={"candidate_path": "s.lean"}),
                   patch.object(campaign, "evaluate", side_effect=self.fake_eval)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.directory = campaign.run_dir("cold")
        campaign._append(self.directory, {"kind": "init", "theorem": "T", "versions": [["v1", "a"], ["v2", "b"]]})
        reference = campaign.record_evaluation("T", "cold", "theorem t := by\n  ref", "fast",
                                               origin="reference", materialize_live=False)
        campaign._append(self.directory, {"kind": "current", "candidate_id": reference["candidate_id"]})

    def fake_eval(self, _name, proof, mode, known=None):
        path = "cold" if engine._FORCE_COLD.get() or self.cold_only else "session"
        if path == "cold":
            self.cold_calls += 1
        heartbeats = self.cold_heartbeats if path == "cold" else 10
        passed = (self.cold_passes and not proof.endswith("  q")) or path == "session"
        compat = {version: {"passed": passed, "lean": {"path": path}} for version in ("v1", "v2")}
        tokens = len(proof)
        metrics = {"tokens": tokens, "heartbeats": heartbeats, "compiled": True,
                   "axes": {"tokens": {"value": tokens}}, "proxy": round(100 - tokens, 2) if mode == "full" else None,
                   "estimated_proxy": round(100 - tokens, 2)}
        return {"ok": True, "mode": mode, "tokens": tokens, "heartbeat": heartbeats, "compat": compat,
                "local_proxy": None, "metrics": metrics}

    def verified(self, text):
        campaign.evaluate_request("T", "cold", text, "full")

    def test_a_session_verified_candidate_is_confirmed_cold_once(self):
        self.verified("theorem t := by\n  a")
        self.cold_heartbeats = 10.3  # within tolerance, but distinguishable from the session's 10
        answer = campaign.submission("cold")
        self.assertEqual(answer["candidate"], "#2")
        self.assertEqual(answer["verified_by"], "cold compile")
        self.assertEqual(answer["heartbeats"], 10.3, "the clean compile is the reported measurement")
        self.assertEqual(answer["session_heartbeats"], 10)
        self.assertEqual(self.cold_calls, 1)
        campaign.submission("cold")
        self.assertEqual(self.cold_calls, 1, "the cold verification is recorded and not repeated")
        self.assertEqual([e["kind"] for e in campaign.events(self.directory)].count("cold_verification"), 1)

    def test_heartbeat_drift_beyond_tolerance_rejects_the_candidate(self):
        self.verified("theorem t := by\n  a")
        self.cold_heartbeats = 12
        answer = campaign.submission("cold")
        self.assertIsNone(answer["candidate"])
        self.assertEqual(answer["rejected_on_cold"][0]["cold_heartbeats"], 12)

    def test_a_candidate_that_fails_cold_is_skipped_for_the_next_best(self):
        self.verified("theorem t := by\n  ab")
        self.verified("theorem t := by\n  q")  # the better one, but it only passes in the session
        answer = campaign.submission("cold")
        self.assertEqual(answer["candidate"], "#2")
        self.assertEqual([item["candidate"] for item in answer["rejected_on_cold"]], ["#3"])
        self.assertEqual(self.cold_calls, 2)

    def test_candidates_already_checked_cold_are_not_compiled_again(self):
        self.cold_only = True
        self.verified("theorem t := by\n  a")
        before = self.cold_calls
        self.assertEqual(campaign.submission("cold")["candidate"], "#2")
        self.assertEqual(self.cold_calls, before)
        self.assertEqual(campaign.submission("cold")["verified_by"], "cold compile (no session used)")


class SessionHarness:
    """Shared by the Lean-backed tests: one daemon per class, cold vs session compiles of one row."""

    name = CORE

    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix="arena-session-"))
        cls.process = lean_session.start_daemon(cls.directory)
        cls.socket = str(lean_session.socket_path(cls.directory))
        cls.row = problem(cls.name)
        cls.version, cls.commit = versions(cls.row)[0]
        cls.previous = os.environ.get(lean_session.ENV)
        os.environ[lean_session.ENV] = cls.socket

    @classmethod
    def tearDownClass(cls):
        if cls.previous is None:
            os.environ.pop(lean_session.ENV, None)
        else:
            os.environ[lean_session.ENV] = cls.previous
        lean_session.stop_daemon(cls.directory, cls.process)
        shutil.rmtree(cls.directory, ignore_errors=True)

    def both(self, proof: str, **options):
        """(session result, cold result) of the same candidate."""
        via_session = compile_version(self.row, proof, self.version, self.commit, **options)
        with force_cold():
            cold = compile_version(self.row, proof, self.version, self.commit, **options)
        self.assertEqual(via_session["lean"]["path"], "session", via_session["lean"])
        self.assertEqual(cold["lean"]["path"], "cold")
        return via_session, cold

    def assertSameResult(self, session: dict, cold: dict):
        for key in ("passed", "exit_code", "diagnostics", "diagnostic_counts", "outside_target", "goals",
                    "error_headlines"):
            self.assertEqual(session[key], cold[key], key)
        if cold.get("heartbeats") is not None:
            self.assertIsNotNone(session["heartbeats"])
            self.assertLessEqual(abs(session["heartbeats"] - cold["heartbeats"]),
                                 max(5, TOLERANCE * cold["heartbeats"]), (session["heartbeats"], cold["heartbeats"]))
        else:
            self.assertIsNone(session["heartbeats"])

        # The text the model never sees must agree too, apart from the measured heartbeat count.
        def strip(output: str) -> str:
            return "\n".join(line for line in output.splitlines() if not line.startswith("ARENA_HEARTBEATS"))
        self.assertEqual(strip(session["raw_output"]), strip(cold["raw_output"]))

    def drafts(self) -> dict[str, tuple[str, dict]]:
        statement = self.row["statement"]
        return {
            "compiling": (self.row["src"], {"measure": True}),
            "failing": (statement + " := by\n  intros\n  exact absurd rfl rfl", {"measure": True}),
            "holes": (statement + " := by\n  intros\n  sorry", {"probe": True}),
        }

    def test_session_equals_cold_for_a_compiling_a_failing_and_a_hole_draft(self):
        for label, (proof, options) in self.drafts().items():
            with self.subTest(label):
                session, cold = self.both(proof, **options)
                self.assertSameResult(session, cold)
                if label == "compiling":
                    self.assertTrue(cold["passed"] and cold["heartbeats"])
                elif label == "failing":
                    self.assertFalse(cold["passed"])
                    self.assertTrue(cold["diagnostics"])
                else:
                    self.assertTrue(cold["goals"], "the hole draft must show its goals")


@slow
@unittest.skipUnless(CORE_READY, "Strata fixture environment is not provisioned")
class CoreSessionTests(SessionHarness, unittest.TestCase):
    def test_only_the_changed_theorem_is_reelaborated(self):
        statement = self.row["statement"]
        compile_version(self.row, statement + " := by\n  intros\n  sorry", self.version, self.commit, probe=True)
        again = compile_version(self.row, statement + " := by\n  intros\n  constructor\n  sorry",
                                self.version, self.commit, probe=True)
        info = again["lean"]
        self.assertEqual(info["path"], "session")
        self.assertFalse(info["new_worker"])
        self.assertGreaterEqual(info["changed_from_line"], self.row["start_line"],
                                "nothing above the theorem may be re-elaborated")

    def test_the_server_reports_what_it_holds_and_memory_stays_bounded(self):
        compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        status = lean_session.request({"op": "status"}, 5, self.socket)
        self.assertEqual(len(status["servers"]), 1)
        server = status["servers"][0]
        self.assertGreaterEqual(server["workers"], 1)
        self.assertLess(server["gb"], 4.0)

    def test_concurrent_drafts_get_their_own_documents(self):
        from concurrent.futures import ThreadPoolExecutor

        statement = self.row["statement"]
        proofs = [statement + f" := by\n  intros\n  sorry\n  -- {n}" for n in range(3)]
        with ThreadPoolExecutor(3) as pool:
            results = list(pool.map(lambda p: compile_version(self.row, p, self.version, self.commit, probe=True), proofs))
        self.assertTrue(all(r["lean"]["path"] == "session" for r in results))
        self.assertTrue(all(r["goals"] for r in results))
        status = lean_session.request({"op": "status"}, 5, self.socket)
        self.assertGreaterEqual(status["servers"][0]["workers"], 2)

    @unittest.skipIf((lean_session._available_gb() or 0) < 12, "not enough free memory to grow the session")
    def test_remaining_documents_warm_up_in_the_background_so_a_batch_is_incremental(self):
        from concurrent.futures import ThreadPoolExecutor

        statement = self.row["statement"]
        compile_version(self.row, statement + " := by\n  sorry", self.version, self.commit, probe=True)

        def workers() -> int:
            return lean_session.request({"op": "status"}, 5, self.socket)["servers"][0]["workers"]

        self.assertTrue(wait_until(lambda: workers() >= lean_session.MAX_SLOTS, 120),
                        "the session did not open its remaining documents")
        proofs = [statement + f" := by\n  intros\n  sorry\n  -- batch {n}" for n in range(4)]
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda p: compile_version(self.row, p, self.version, self.commit, probe=True), proofs))
        self.assertFalse(any(r["lean"]["new_worker"] for r in results), [r["lean"] for r in results])

    def test_a_changed_pin_or_toolchain_is_stale_and_runs_cold(self):
        project = engine.workspace(self.row, self.version, self.commit)
        real = engine._fingerprint(str(project))
        changed = {**real, "toolchain": "leanprover/lean4:v0.0.0"}
        with patch.object(engine, "_fingerprint", return_value=changed):
            result = compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        self.assertEqual(result["lean"]["path"], "cold-fallback")
        self.assertIn("stale session: toolchain changed", result["lean"]["reason"])
        self.assertTrue(result["passed"], "the cold fallback still answers correctly")
        # The stale server was dropped; the next call with the right fingerprint starts a fresh one.
        again = compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        self.assertEqual(again["lean"]["path"], "session")
        self.assertTrue(again["lean"]["new_worker"])

    def test_a_changed_file_prefix_is_stale_and_runs_cold(self):
        built = engine.candidate_file(self.row, self.row["src"], self.version, self.commit)
        text, project = built["text"], built["path"]
        first = engine.run_lean(self.row, project, text, prefix_end=10)
        self.assertEqual(last_lean_run()["path"], "session")
        self.assertEqual(first[0], 0, first)
        engine.run_lean(self.row, project, text, prefix_end=11)
        info = last_lean_run()
        self.assertEqual(info["path"], "cold-fallback")
        self.assertIn("file prefix changed", info["reason"])
        engine.run_lean(self.row, project, text, prefix_end=10)
        self.assertEqual(last_lean_run()["path"], "session")

    def test_a_crashed_server_falls_back_then_recovers(self):
        compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        victims = [pid for server in lean_session.request({"op": "status"}, 5, self.socket)["servers"]
                   for pid in server["pids"]]
        for pid in victims:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.assertTrue(wait_until(lambda: not any(alive(pid) for pid in victims), 10))
        first = compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        self.assertTrue(first["passed"])
        self.assertIn(first["lean"]["path"], ("cold-fallback", "session"))
        second = compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        self.assertEqual(second["lean"]["path"], "session")
        self.assertTrue(second["passed"])

    def test_a_timeout_frees_the_worker(self):
        project = engine.workspace(self.row, self.version, self.commit)
        reply = lean_session.request({
            "op": "check", "protocol": lean_session.PROTOCOL, "project": str(project),
            "fingerprint": engine._fingerprint(str(project)), "display": "x.lean", "timeout": 0.01,
            "text": "import Strata\n" + "example : True := by\n  trivial\n"}, 30, self.socket)
        self.assertTrue(reply["ok"] and reply.get("timeout"), reply)
        ok = compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        self.assertTrue(ok["passed"])


@slow
@unittest.skipUnless(PHYSLIB_READY, "PhysLib fixture environment is not provisioned")
class PhysLibSessionTests(SessionHarness, unittest.TestCase):
    name = PHYSLIB
    project_dir = "workspaces/physlib-v4.32.0"

    def test_a_draft_after_warm_up_runs_in_the_session(self):
        statement = self.row["statement"]
        compile_version(self.row, statement + " := by\n  sorry", self.version, self.commit, probe=True)
        again = compile_version(self.row, statement + " := by\n  intro\n  sorry", self.version, self.commit, probe=True)
        self.assertEqual(again["lean"]["path"], "session")
        self.assertFalse(again["lean"]["new_worker"])
        self.assertLess(again["lean"]["seconds"], 120.0)  # generous: cold PhysLib is ~32 s per compile


@slow
class LifecycleTests(unittest.TestCase):
    """No Lean process outlives the run, however it ends."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="arena-session-"))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)

    def start_with_server(self, **options):
        process = lean_session.start_daemon(self.directory, **options)
        socket_ = str(lean_session.socket_path(self.directory))
        row = problem(CORE)
        version, commit = versions(row)[0]
        project = engine.workspace(row, version, commit)
        reply = lean_session.request({
            "op": "check", "protocol": lean_session.PROTOCOL, "project": str(project),
            "fingerprint": engine._fingerprint(str(project)), "display": "x.lean", "timeout": 120,
            "text": "example : True := by\n  trivial\n"}, 180, socket_)
        self.assertTrue(reply["ok"], reply)
        servers = lean_session.request({"op": "status"}, 5, socket_)["servers"]
        self.assertEqual(len(servers), 1)
        pids = servers[0]["pids"]
        self.assertGreaterEqual(len(pids), 2, "expected the server and a worker")
        info = self.directory / lean_session.INFO_NAME
        self.assertTrue(wait_until(lambda: set(pids) <= set(json.loads(info.read_text())["pids"]), 10),
                        "the daemon did not record its Lean processes")
        return process, pids

    @unittest.skipUnless(CORE_READY, "Strata fixture environment is not provisioned")
    def test_stopping_the_daemon_stops_the_server_and_its_workers(self):
        process, pids = self.start_with_server()
        self.assertTrue(all(alive(pid) for pid in pids))
        lean_session.stop_daemon(self.directory, process)
        self.assertTrue(wait_until(lambda: not any(alive(pid) for pid in pids), 10), "Lean processes survived the daemon")

    @unittest.skipUnless(CORE_READY, "Strata fixture environment is not provisioned")
    def test_a_killed_runner_takes_the_session_with_it(self):
        parent = subprocess.Popen(["sleep", "300"])
        try:
            process, pids = self.start_with_server(parent=parent.pid)
            parent.kill()
            parent.wait()
            self.assertTrue(wait_until(lambda: process.poll() is not None and not any(alive(pid) for pid in pids), 20),
                            "daemon or Lean outlived the killed runner")
        finally:
            parent.kill()
            lean_session.stop_daemon(self.directory, None)

    @unittest.skipUnless(CORE_READY, "Strata fixture environment is not provisioned")
    def test_a_killed_daemon_leaves_no_lean_behind_even_without_the_sweep(self):
        process, pids = self.start_with_server()
        process.kill()
        process.wait()
        self.assertTrue(wait_until(lambda: not any(alive(pid) for pid in pids), 30),
                        "Lean kept running after its owner died and nothing swept it")


@slow
@unittest.skipUnless(CORE_READY and shutil.which("pi"), "pi and the Strata fixture are required")
class RunnerSessionTests(unittest.TestCase):
    """The real runner, Pi and tool processes against a scripted provider."""

    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def probe(self):
        from tests.pi_support import FakeRun

        statement = problem(CORE)["statement"]
        call = {"tool_calls": [{"name": "arena_probe", "arguments": {
            "proof": statement + " := by\n  intros Hup Hinit\n  sorry"}}],
            "usage": {"input": 300, "output": 40, "cacheRead": 4000, "cacheWrite": 100}}
        return call, FakeRun

    def test_tool_calls_run_in_the_session_and_nothing_is_left_after_the_run(self):
        call, FakeRun = self.probe()
        run = FakeRun([call, {"text": "done"}], session=True, timeout=300)
        self.runs.append(run)
        run.run()
        self.assertEqual(run.result.returncode, 0, run.result.stderr[-1500:])
        probes = [e for e in run.jsonl("ledger.jsonl") if e.get("kind") == "probe"]
        self.assertEqual(len(probes), 1, run.stdout[-1000:])
        self.assertEqual(probes[0]["result"]["compat"]["v4.29.1"]["lean"]["path"], "session")
        self.assertIn("Lean session pid=", run.stdout)
        for leftover in ("lean-session.sock", "lean-session.json"):
            self.assertFalse((run.directory / leftover).exists(), leftover)

    def test_ctrl_c_shuts_pi_down_cleanly_and_leaves_no_lean_processes(self):
        call, FakeRun = self.probe()
        run = FakeRun([call, {"text": "slow", "delay_ms": 60000}], session=True, timeout=300)
        self.runs.append(run)
        process = run.start(own_group=True)
        self.assertTrue(run.wait_for_requests(2, 180), "the probe never finished")
        info = json.loads((run.directory / lean_session.INFO_NAME).read_text())
        self.assertTrue(wait_until(lambda: len(json.loads((run.directory / lean_session.INFO_NAME).read_text())["pids"]) >= 2, 20))
        info = json.loads((run.directory / lean_session.INFO_NAME).read_text())
        os.killpg(process.pid, signal.SIGINT)
        _, stderr = process.communicate(timeout=120)
        self.assertEqual(process.returncode, 128 + signal.SIGINT, stderr)
        self.assertNotEqual(run.json("cost.json").get("written_by"), "runner_ledger_reconstruction", stderr)
        self.assertEqual(run.json("summary.json")["stop_reason"], "interrupted")
        self.assertTrue(wait_until(lambda: not any(alive(p) for p in info["pids"] + [info["pid"]]), 15),
                        "Lean or the session daemon survived Ctrl+C")

    def test_a_killed_runner_leaves_no_lean_processes(self):
        call, FakeRun = self.probe()
        run = FakeRun([call, {"text": "slow", "delay_ms": 60000}], session=True, timeout=300)
        self.runs.append(run)
        process = run.start(own_group=True)
        self.assertTrue(run.wait_for_requests(2, 180), "the probe never finished")
        self.assertTrue(wait_until(lambda: len(json.loads((run.directory / lean_session.INFO_NAME).read_text())["pids"]) >= 2, 20))
        info = json.loads((run.directory / lean_session.INFO_NAME).read_text())
        process.kill()  # a crash: no handler runs
        process.wait()
        subprocess.run(["pkill", "-9", "-f", run.run_id])  # Pi and its tools; the daemon has its own session
        self.assertTrue(wait_until(lambda: not any(alive(p) for p in info["pids"] + [info["pid"]]), 30),
                        "Lean or the session daemon survived a crashed runner")


if __name__ == "__main__":
    unittest.main()

class SessionLogTests(unittest.TestCase):
    """The daemon's decisions are logged, and a memory refusal leaves a marker background work yields to."""

    class FakeServer:
        def __init__(self):
            self.opened = 0
        def alive(self):
            return True
        def doc(self, uri):
            self.opened += 1
            return lean_session._Doc(uri)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.session = lean_session.Session(self.directory)
        self.entry = lean_session._Entry(self.directory / "proj", {}, self.FakeServer())
        self.session.entries[str(self.entry.project)] = self.entry

    def test_a_worker_open_and_a_memory_refusal_are_logged_and_marked(self):
        lines = []
        with patch.object(lean_session, "_log", lines.append):
            with patch.object(lean_session, "_available_gb", return_value=100.0):
                self.session._acquire(self.entry, 1)
            self.assertFalse(lean_session.memory_pressure(self.directory))
            other = lean_session._Entry(self.directory / "other", {}, self.FakeServer())
            self.session.entries[str(other.project)] = other
            with patch.object(lean_session, "_available_gb", return_value=4.0), \
                    self.assertRaises(lean_session.SessionError):
                self.session._acquire(other, 1)
        self.assertTrue(any(line.startswith("worker open proj") for line in lines), lines)
        self.assertTrue(any("no room for a Lean worker: memory (4.0 GB available)" in line for line in lines), lines)
        self.assertTrue(lean_session.memory_pressure(self.directory))
        self.assertFalse(lean_session.memory_pressure(self.directory, within=0))
        self.assertIn(lean_session.WAITING_NAME, lean_session.SESSION_FILES)

