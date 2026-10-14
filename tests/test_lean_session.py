"""Persistent Lean session: equivalence with cold compiles, fallback, and process lifecycle."""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign, engine, lean_session
from arena.engine import ROOT, compile_version, force_cold, last_lean_run, problem, versions
from tests.slow import slow

CORE = "Core.InitsUpdatesComm"
PHYSLIB = "fundamental_theorem_of_variational_calculus'"
CORE_READY = (ROOT / "workspaces/strata-v4.29.1").is_dir()
PHYSLIB_READY = (ROOT / "workspaces/physlib-v4.32.0").is_dir()
TOLERANCE = 0.05  # arena certify default


def alive(pid: int) -> bool:
    """A process that is running (a zombie awaiting its parent does not count)."""
    return lean_session.running(pid)


def status_of(path: str, timeout: float = 5) -> dict:
    """The service's status reply (a dict even when it cannot be reached)."""
    return lean_session.request({"op": "status"}, timeout, path) or {}


OPENS_IN_FLIGHT_S = 60.0  # background warm-ups still loading headers when a run ends (they load one at a time)


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
            {"severity": 1, "message": "unsolved goals\n⊢ False", "range": {"start": {"line": 2, "character": 2}}},
            {"severity": 2, "message": "unused variable", "range": {"start": {"line": 1, "character": 6}}},
        ]
        code, output = lean_session.render(found, text, "A/B.lean")
        self.assertEqual(code, 1)
        self.assertEqual(
            output.splitlines(),
            [
                "ARENA_HEARTBEATS 7",
                "A/B.lean:3:2: error: unsolved goals",
                "⊢ False",
                "A/B.lean:2:6: warning: unused variable",
            ],
        )
        self.assertEqual(lean_session.render(found[:1] + found[2:], text, "A/B.lean")[0], 0)

    def test_columns_count_code_points_not_utf16_units(self):
        # 𝓝 is outside the BMP: two UTF-16 units, one code point.
        text = "x 𝓝 y bad\n"
        found = [{"severity": 1, "message": "boom", "range": {"start": {"line": 0, "character": 7}}}]
        self.assertEqual(lean_session.render(found, text, "f.lean")[1], "f.lean:1:6: error: boom")

    def test_parsed_output_is_what_the_cold_path_parses(self):
        found = [
            {"severity": 1, "message": "Type mismatch\n  rfl", "range": {"start": {"line": 4, "character": 3}}},
            {"severity": 3, "message": "ARENA_HEARTBEATS 9", "range": {"start": {"line": 0, "character": 0}}},
        ]
        _, output = lean_session.render(found, "\n" * 4 + "abcdef\n", "f.lean")
        parsed = engine.parse_diagnostics(output)
        self.assertEqual(
            [(d["severity"], d["line"], d["column"]) for d in parsed], [("error", 5, 3), ("info", None, None)]
        )


class FallbackTests(unittest.TestCase):
    """A session that cannot answer must never change an answer, only the path."""

    def setUp(self):
        self.row = {"name": "T", "file_path": "A/B.lean"}

    def run_lean(self, reply, **env):
        with (
            patch.dict(os.environ, {lean_session.ENV: "/nonexistent.sock", **env}, clear=False),
            patch.object(lean_session, "request", return_value=reply),
            patch.object(engine, "_fingerprint", return_value={"code": "x"}),
            patch.object(engine, "_run_cold", return_value=(0, "cold output")),
        ):
            return engine.run_lean(self.row, Path("/p"), "text"), last_lean_run()

    def test_unconfigured_runs_are_cold_without_a_reason(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(engine, "_run_cold", return_value=(0, "x")):
            os.environ.pop(lean_session.ENV, None)
            result = engine.run_lean(self.row, Path("/p"), "text")
        self.assertEqual(result, (0, "x"))
        self.assertEqual(last_lean_run()["path"], "cold")

    def test_unavailable_stale_or_crashed_sessions_fall_back_and_say_why(self):
        for reason in (
            "session unreachable: FileNotFoundError",
            "stale session: toolchain changed",
            "Lean server crashed",
            "no room for a Lean worker: memory (2.0 GB available)",
        ):
            result, info = self.run_lean({"ok": False, "reason": reason})
            self.assertEqual(result, (0, "cold output"))
            self.assertEqual((info["path"], info["reason"]), ("cold-fallback", reason))

    def test_a_session_timeout_is_a_timeout(self):
        result, info = self.run_lean({"ok": True, "timeout": True})
        self.assertIsNone(result)
        self.assertEqual(info["path"], "session")

    def test_force_cold_ignores_a_configured_session(self):
        with (
            patch.dict(os.environ, {lean_session.ENV: "/nonexistent.sock"}),
            patch.object(lean_session, "request", side_effect=AssertionError("asked the session")),
            patch.object(engine, "_run_cold", return_value=(0, "cold")),
            force_cold(),
        ):
            self.assertEqual(engine.run_lean(self.row, Path("/p"), "text"), (0, "cold"))
        self.assertEqual(last_lean_run()["path"], "cold")

    def test_model_view_reports_the_path_only_when_it_is_not_plain_cold(self):
        compat = {
            "v1": {"passed": True, "lean": {"path": "session"}},
            "v2": {"passed": True, "lean": {"path": "cold-fallback", "reason": "stale session: wrapper changed"}},
            "v3": {"passed": True, "lean": {"path": "cold"}},
        }
        view = campaign._model_view({"ok": True, "compat": compat})["compat"]
        self.assertEqual(view["v1"]["lean"], "session")
        self.assertEqual(view["v2"]["lean"], "cold (session unavailable: stale session: wrapper changed)")
        self.assertNotIn("lean", view["v3"])

    def test_model_view_labels_a_failed_draft_heartbeat_and_marks_it_not_compiled(self):
        failed = {"ok": True, "heartbeat": 6834, "tokens": 42, "compat": {"v1": {"passed": False, "heartbeats": 6834}}}
        view = campaign._model_view(failed)
        self.assertIs(view["compiled"], False)
        self.assertTrue(view["ok"])
        self.assertEqual(view["heartbeat_to_failure"], 6834)
        self.assertNotIn("heartbeat", view)
        self.assertEqual(view["compat"]["v1"], {"passed": False, "heartbeats_to_failure": 6834})
        good = campaign._model_view({"ok": True, "heartbeat": 10, "compat": {"v1": {"passed": True, "heartbeats": 10}}})
        self.assertEqual(good["heartbeat"], 10)
        self.assertEqual(good["compat"]["v1"]["heartbeats"], 10)
        self.assertNotIn("compiled", good)


@slow
class DaemonTests(unittest.TestCase):
    """The shared service control path, without starting Lean."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="arena-session-"))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)

    def test_start_serve_and_stop_removes_every_trace(self):
        path = lean_session.ensure_service(self.directory)
        self.addCleanup(lean_session.stop_service, self.directory)
        status = lean_session.request({"op": "status"}, 5, path)
        self.assertTrue(status["ok"])
        self.assertEqual(status["servers"], [])
        self.assertEqual(status["code"], lean_session.code_sha())
        lean_session.stop_service(self.directory)
        self.assertFalse(Path(path).exists())
        self.assertFalse((self.directory / lean_session.INFO_NAME).exists())
        self.assertEqual(status_of(path, 2)["ok"], False)

    def test_an_overlong_service_socket_path_is_rejected(self):
        deep = self.directory / ("x" * 90)
        with self.assertRaises(lean_session.SessionError):
            lean_session.socket_path(deep)

    def test_a_stale_evaluator_gets_a_stale_answer_not_a_compile(self):
        path = lean_session.ensure_service(self.directory)
        self.addCleanup(lean_session.stop_service, self.directory)
        reply = lean_session.request(
            {
                "op": "check",
                "protocol": lean_session.PROTOCOL,
                "project": str(self.directory),
                "fingerprint": {"code": "not-the-running-evaluator"},
                "text": "x",
                "display": "f.lean",
                "timeout": 5,
            },
            10,
            path,
        )
        self.assertEqual((reply["ok"], reply["stale"]), (False, True))
        self.assertIn("evaluator changed", reply["reason"])

    def test_a_dead_lease_is_dropped_by_the_watch_loop(self):
        parent = subprocess.Popen(["sleep", "300"])
        path = lean_session.ensure_service(self.directory)
        self.addCleanup(lean_session.stop_service, self.directory)
        try:
            reply = lean_session.request(
                {
                    "op": "lease",
                    "protocol": lean_session.PROTOCOL,
                    "run_id": "gone",
                    "pid": parent.pid,
                    "primary": "/not-opened",
                    "others": [],
                },
                5,
                path,
            )
            self.assertTrue(reply["ok"], reply)
            parent.kill()
            parent.wait()
            self.assertTrue(wait_until(lambda: "gone" not in status_of(path, 2)["leases"], 5))
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.wait()

    def test_process_tree_and_memory_probes_see_children_in_other_groups(self):
        parent = subprocess.Popen(["sh", "-c", "setsid sleep 30 & wait"], start_new_session=True)
        try:
            self.assertTrue(wait_until(lambda: len(lean_session.process_tree(parent.pid)) >= 2, 5))
            self.assertGreater(lean_session.tree_pss_gb(parent.pid), 0)
            self.assertEqual(lean_session.process_tree(2**30), [])
            self.assertEqual(lean_session.tree_pss_gb(2**30), 0)
        finally:
            for pid in lean_session.process_tree(parent.pid):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
            parent.wait()

    def test_tree_pss_uses_injected_per_pid_measurements(self):
        with patch.object(lean_session, "process_tree", return_value=[101, 102, 103]):
            measured = lean_session.tree_pss_gb(100, lambda pid: {101: 0.4, 102: None, 103: 0.7}[pid])

        self.assertEqual(measured, 1.1)


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
        patches = [
            patch.object(campaign, "ROOT", Path(self.temporary.name)),
            patch.object(campaign, "problem", return_value={"name": "T"}),
            patch.object(campaign, "validate_proof"),
            patch.object(campaign, "versions", return_value=[("v1", "a"), ("v2", "b")]),
            patch.object(campaign, "materialize", return_value={"candidate_path": "s.lean"}),
            patch.object(campaign, "evaluate", side_effect=self.fake_eval),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.directory = campaign.run_dir("cold")
        campaign._append(self.directory, {"kind": "init", "theorem": "T", "versions": [["v1", "a"], ["v2", "b"]]})
        reference = campaign.record_evaluation(
            "T", "cold", "theorem t := by\n  ref", "fast", origin="reference", materialize_live=False
        )
        campaign._append(self.directory, {"kind": "current", "candidate_id": reference["candidate_id"]})

    def fake_eval(self, _name, proof, mode, known=None):
        path = "cold" if engine._FORCE_COLD.get() or self.cold_only else "session"
        if path == "cold":
            self.cold_calls += 1
        heartbeats = self.cold_heartbeats if path == "cold" else 10
        passed = (self.cold_passes and not proof.endswith("  q")) or path == "session"
        compat = {version: {"passed": passed, "lean": {"path": path}} for version in ("v1", "v2")}
        tokens = len(proof)
        metrics = {
            "tokens": tokens,
            "heartbeats": heartbeats,
            "compiled": True,
            "axes": {"tokens": {"value": tokens}},
            "proxy": round(100 - tokens, 2) if mode == "full" else None,
            "estimated_proxy": round(100 - tokens, 2),
        }
        return {
            "ok": True,
            "mode": mode,
            "tokens": tokens,
            "heartbeat": heartbeats,
            "compat": compat,
            "local_proxy": None,
            "metrics": metrics,
        }

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
    """Shared Lean-backed tests: one leased service per class, cold vs session compiles of one row."""

    name = CORE

    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix="arena-session-"))
        cls.previous_service_dir = os.environ.get(lean_session.SERVICE_DIR_ENV)
        os.environ[lean_session.SERVICE_DIR_ENV] = str(cls.directory)
        cls.socket = lean_session.ensure_service(cls.directory)
        cls.row = problem(cls.name)
        cls.version, cls.commit = versions(cls.row)[0]
        cls.run_id = f"test-{os.getpid()}-{cls.name}"
        primary = str(engine.workspace(cls.row, cls.version, cls.commit))
        others = [
            str(engine.workspace(cls.row, v, c)) for v, c in versions(cls.row) if (v, c) != (cls.version, cls.commit)
        ]
        reply = lean_session.request(
            {
                "op": "lease",
                "protocol": lean_session.PROTOCOL,
                "run_id": cls.run_id,
                "pid": os.getpid(),
                "primary": primary,
                "others": others,
            },
            5,
            cls.socket,
        )
        if not reply or not reply.get("ok"):
            raise RuntimeError(f"could not lease Lean service: {reply}")
        cls.previous = os.environ.get(lean_session.ENV)
        os.environ[lean_session.ENV] = cls.socket

    @classmethod
    def tearDownClass(cls):
        if cls.previous is None:
            os.environ.pop(lean_session.ENV, None)
        else:
            os.environ[lean_session.ENV] = cls.previous
        lean_session.request({"op": "release", "protocol": lean_session.PROTOCOL, "run_id": cls.run_id}, 5, cls.socket)
        lean_session.stop_service(cls.directory)
        if cls.previous_service_dir is None:
            os.environ.pop(lean_session.SERVICE_DIR_ENV, None)
        else:
            os.environ[lean_session.SERVICE_DIR_ENV] = cls.previous_service_dir
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
        for key in (
            "passed",
            "exit_code",
            "diagnostics",
            "diagnostic_counts",
            "outside_target",
            "goals",
            "error_headlines",
        ):
            self.assertEqual(session[key], cold[key], key)
        if cold.get("heartbeats") is not None:
            self.assertIsNotNone(session["heartbeats"])
            self.assertLessEqual(
                abs(session["heartbeats"] - cold["heartbeats"]),
                max(5, TOLERANCE * cold["heartbeats"]),
                (session["heartbeats"], cold["heartbeats"]),
            )
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
    def test_batch_repl_matches_background_lsp_for_core_and_cslib(self):
        from arena import lean_repl

        def available(toolchain: str) -> bool:
            metadata = lean_repl.repl_dir(toolchain) / "build.json"
            binary = lean_repl.repl_dir(toolchain) / ".lake/build/bin/repl"
            try:
                return binary.is_file() and bool(json.loads(metadata.read_text()).get("ok"))
            except (OSError, ValueError):
                return False

        if not available(self.version):
            self.skipTest(f"REPL is not built for Core toolchain {self.version}")
        directory = Path(tempfile.mkdtemp(prefix="arena-repl-seam-c-"))
        self.addCleanup(shutil.rmtree, directory, True)
        session = lean_session.Session(directory, budget=lean_session.WorkerBudget(directory / "tokens"))
        self.addCleanup(session.shutdown)
        rows = [(self.row, self.version, self.commit)]
        cslib = problem("Cslib.SKI.parallelReduction_diamond")
        cslib_version, cslib_commit = versions(cslib)[0]
        if available(cslib_version):
            rows.append((cslib, cslib_version, cslib_commit))

        for row, toolchain, commit in rows:
            project = engine.workspace(row, toolchain, commit)
            statement = row["statement"]
            drafts = (
                ("compiling", row["src"]),
                ("failing", statement + " := by\n  exact arena_repl_missing_name"),
                ("hole", engine.instrument_sorries(statement + " := by\n  sorry")),
            )
            for label, proof in drafts:
                with self.subTest(row=row["name"], draft=label):
                    built = engine.candidate_file(row, proof, toolchain, commit)
                    text = built["text"]
                    # The wrapper ends with the start of the theorem's command, so it belongs to the body: a REPL
                    # header must end on a command boundary (the LSP lane sees one file and does not care).
                    header_end = built["head"]
                    wrapped = text[: built["head"]] + engine.HEARTBEAT_WRAPPER + text[built["head"] :]
                    request = {
                        "protocol": lean_session.PROTOCOL,
                        "fingerprint": lean_session.fingerprint(project),
                        "project": str(project),
                        "display": engine.source_path(row),
                        "text": wrapped,
                        "header_end": header_end,
                        "timeout": 600,
                        "toolchain": toolchain,
                        "row": row["name"],
                        "measure": False,
                    }
                    lsp = session.check({**request, "lane": "background"})
                    with patch.object(lean_repl, "REPL_ENABLED", True):
                        repl = session.check({**request, "lane": "batch"})
                    self.assertEqual(repl["engine"], "repl")
                    self.assertEqual(repl["returncode"] == 0, lsp["returncode"] == 0)
                    lsp_shape = engine.structure_diagnostics(
                        lsp["output"], text, built["start_line"], built["end_line"], built["start_line"]
                    )
                    repl_shape = engine.structure_diagnostics(
                        repl["output"], text, built["start_line"], built["end_line"], built["start_line"]
                    )
                    for key in ("diagnostic_counts", "goals"):
                        self.assertEqual(repl_shape[key], lsp_shape[key], key)
                    lsp_heartbeats = lean_repl._heartbeat(lsp["output"])
                    repl_heartbeats = lean_repl._heartbeat(repl["output"])
                    if lsp_heartbeats is None or repl_heartbeats is None:
                        self.fail("the heartbeat wrapper did not report a count")
                    self.assertLessEqual(abs(repl_heartbeats - lsp_heartbeats), max(5, 0.05 * lsp_heartbeats))

    def test_sequential_leases_reuse_the_core_header(self):
        project = str(engine.workspace(self.row, self.version, self.commit))
        proof = self.row["statement"] + " := by\n  intros\n  sorry"
        first = compile_version(self.row, proof, self.version, self.commit, probe=True)
        self.assertEqual(first["lean"]["path"], "session")
        next_run = f"next-{self.run_id}"
        lean_session.request(
            {"op": "release", "protocol": lean_session.PROTOCOL, "run_id": self.run_id}, 5, self.socket
        )
        leased = lean_session.request(
            {
                "op": "lease",
                "protocol": lean_session.PROTOCOL,
                "run_id": next_run,
                "pid": os.getpid(),
                "primary": project,
                "others": [],
            },
            5,
            self.socket,
        )
        self.assertTrue(leased and leased.get("ok"), leased)
        with patch.dict(os.environ, {lean_session.RUN_ID_ENV: next_run}):
            second = compile_version(self.row, proof + "\n-- second run", self.version, self.commit, probe=True)
        self.assertFalse(second["lean"]["new_worker"])  # the released project stayed warm for the row's next run
        self.assertIsNone(second["lean"].get("header_seconds"))
        log = (self.directory / lean_session.LOG_NAME).read_text(errors="replace")
        self.assertNotIn(f"header open run={next_run}", log)
        lean_session.request({"op": "release", "protocol": lean_session.PROTOCOL, "run_id": next_run}, 5, self.socket)
        restored = lean_session.request(
            {
                "op": "lease",
                "protocol": lean_session.PROTOCOL,
                "run_id": self.run_id,
                "pid": os.getpid(),
                "primary": project,
                "others": [],
            },
            5,
            self.socket,
        )
        self.assertTrue(restored and restored.get("ok"), restored)

    def test_only_the_changed_theorem_is_reelaborated(self):
        statement = self.row["statement"]
        compile_version(self.row, statement + " := by\n  intros\n  sorry", self.version, self.commit, probe=True)
        again = compile_version(
            self.row, statement + " := by\n  intros\n  constructor\n  sorry", self.version, self.commit, probe=True
        )
        info = again["lean"]
        self.assertEqual(info["path"], "session")
        self.assertFalse(info["new_worker"])
        self.assertGreaterEqual(
            info["changed_from_line"], self.row["start_line"], "nothing above the theorem may be re-elaborated"
        )

    def test_the_server_reports_what_it_holds_and_memory_stays_bounded(self):
        compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        status = lean_session.request({"op": "status"}, 5, self.socket)
        self.assertEqual(len(status["servers"]), 1)
        server = status["servers"][0]
        self.assertGreaterEqual(len(server["workers"]), 1)
        self.assertLess(server["gb"], 4.0)

    def test_concurrent_drafts_get_their_own_documents(self):
        from concurrent.futures import ThreadPoolExecutor

        statement = self.row["statement"]
        proofs = [statement + f" := by\n  intros\n  sorry\n  -- {n}" for n in range(3)]
        with ThreadPoolExecutor(3) as pool:
            results = list(
                pool.map(lambda p: compile_version(self.row, p, self.version, self.commit, probe=True), proofs)
            )
        self.assertTrue(all(r["lean"]["path"] == "session" for r in results))
        self.assertTrue(all(r["goals"] for r in results))
        status = lean_session.request({"op": "status"}, 5, self.socket)
        self.assertGreaterEqual(len(status["servers"][0]["workers"]), 2)

    @unittest.skipIf((lean_session._available_gb() or 0) < 12, "not enough free memory to grow the session")
    def test_remaining_documents_warm_up_in_the_background_so_a_batch_is_incremental(self):
        from concurrent.futures import ThreadPoolExecutor

        statement = self.row["statement"]
        compile_version(self.row, statement + " := by\n  sorry", self.version, self.commit, probe=True)

        def workers() -> int:
            return len(status_of(self.socket, 5)["servers"][0]["workers"])

        self.assertTrue(
            wait_until(lambda: workers() >= lean_session.PRIMARY_MAX_WORKERS, 120),
            "the session did not open its remaining documents",
        )
        proofs = [statement + f" := by\n  intros\n  sorry\n  -- batch {n}" for n in range(4)]
        with ThreadPoolExecutor(4) as pool:
            results = list(
                pool.map(lambda p: compile_version(self.row, p, self.version, self.commit, probe=True), proofs)
            )
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
        victims = [pid for server in status_of(self.socket, 5)["servers"] for pid in server["pids"]]
        for pid in victims:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        self.assertTrue(wait_until(lambda: not any(alive(pid) for pid in victims), 10))
        first = compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        self.assertTrue(first["passed"])
        self.assertIn(first["lean"]["path"], ("cold-fallback", "session"))
        second = compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        self.assertEqual(second["lean"]["path"], "session")
        self.assertTrue(second["passed"])

    def test_a_timeout_frees_the_worker(self):
        project = engine.workspace(self.row, self.version, self.commit)
        reply = lean_session.request(
            {
                "op": "check",
                "protocol": lean_session.PROTOCOL,
                "project": str(project),
                "fingerprint": engine._fingerprint(str(project)),
                "display": "x.lean",
                "timeout": 0.01,
                "text": "import Strata\n" + "example : True := by\n  trivial\n",
            },
            30,
            self.socket,
        )
        self.assertTrue(reply["ok"] and reply.get("timeout"), reply)
        ok = compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        self.assertTrue(ok["passed"])

    def test_timeout_returns_partial_output_and_reuses_the_worker(self):
        from arena.cli.lean_load import make_proof

        proof = make_proof("slow", self.row, 1, 1.0)
        with patch.dict(os.environ, {"ARENA_LEAN_TIMEOUT": "1"}):
            timed_out = compile_version(self.row, proof, self.version, self.commit)
        self.assertFalse(timed_out["passed"])
        self.assertEqual(timed_out["lean"]["path"], "session")
        self.assertTrue(timed_out["lean"]["warm_kept"])
        self.assertIsInstance(timed_out["lean"]["partial_output"], str)
        quick = compile_version(self.row, self.row["src"], self.version, self.commit, measure=True)
        self.assertEqual(quick["lean"]["path"], "session")
        self.assertFalse(quick["lean"]["new_worker"])
        self.assertIsNone(quick["lean"].get("header_seconds"))

    def test_goals_are_available_at_a_hole_and_absent_after_a_complete_proof(self):
        proof = self.row["statement"] + " := by\n  sorry"
        built = engine.candidate_file(self.row, proof, self.version, self.commit)
        line = built["text"].splitlines().index("  sorry")
        reply = engine.lean_goals(self.row, built["path"], built["text"], built["head"], line, 2)
        self.assertTrue(reply and reply["ok"], reply)
        self.assertTrue(reply["goals"])
        complete = engine.candidate_file(self.row, self.row["src"], self.version, self.commit)
        reply = engine.lean_goals(
            self.row,
            complete["path"],
            complete["text"],
            complete["head"],
            len(complete["text"].splitlines()),
            0,
        )
        self.assertTrue(reply and reply["ok"], reply)
        self.assertEqual(reply["goals"], [])

    def test_try_runs_a_closing_snippet_and_a_snippet_that_leaves_a_goal(self):
        proof = self.row["statement"] + " := by\n  sorry"
        built = engine.candidate_file(self.row, proof, self.version, self.commit)
        line = built["text"].splitlines().index("  sorry")
        close = self.row["src"].split(":= by", 1)[1]
        reply = engine.lean_try(
            self.row,
            built["path"],
            built["text"],
            built["head"],
            {"line": line, "column": 2, "end_line": line, "end_column": 7},
            [close, "intro"],
        )
        self.assertTrue(reply and reply["ok"], reply)
        self.assertEqual(len(reply["results"]), 2)
        self.assertEqual(reply["results"][0]["returncode"], 0)
        self.assertIsNone(reply["results"][0]["goals_after"])
        self.assertTrue(reply["results"][1]["goals_after"])


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
        self.previous_service_dir = os.environ.get(lean_session.SERVICE_DIR_ENV)
        os.environ[lean_session.SERVICE_DIR_ENV] = str(self.directory)
        self.addCleanup(self.restore_service_dir)
        grace = patch.dict(os.environ, {"ARENA_LEAN_RELEASE_GRACE_S": "1"})  # the service inherits it
        grace.start()
        self.addCleanup(grace.stop)

    def restore_service_dir(self):
        lean_session.stop_service(self.directory)
        if self.previous_service_dir is None:
            os.environ.pop(lean_session.SERVICE_DIR_ENV, None)
        else:
            os.environ[lean_session.SERVICE_DIR_ENV] = self.previous_service_dir

    def start_with_server(self, **options):
        socket_ = lean_session.ensure_service(self.directory)
        row = problem(CORE)
        version, commit = versions(row)[0]
        project = engine.workspace(row, version, commit)
        run_id = f"lifecycle-{os.getpid()}-{time.monotonic_ns()}"
        pid = options.get("parent_pid", os.getpid())
        lease = lean_session.request(
            {
                "op": "lease",
                "protocol": lean_session.PROTOCOL,
                "run_id": run_id,
                "pid": pid,
                "primary": str(project),
                "others": [],
            },
            5,
            socket_,
        )
        self.assertTrue(lease and lease.get("ok"), lease)
        reply = lean_session.request(
            {
                "op": "check",
                "protocol": lean_session.PROTOCOL,
                "project": str(project),
                "fingerprint": engine._fingerprint(str(project)),
                "display": "x.lean",
                "timeout": 120,
                "text": "example : True := by\n  trivial\n",
            },
            180,
            socket_,
        )
        self.assertTrue(reply["ok"], reply)
        servers = status_of(socket_, 5)["servers"]
        self.assertEqual(len(servers), 1)
        pids = servers[0]["pids"]
        self.assertGreaterEqual(len(pids), 2, "expected the server and a worker")
        info = self.directory / lean_session.INFO_NAME
        self.assertTrue(
            wait_until(lambda: set(pids) <= set(json.loads(info.read_text())["pids"]), 10),
            "the daemon did not record its Lean processes",
        )
        return socket_, run_id, pid, pids

    @unittest.skipUnless(CORE_READY, "Strata fixture environment is not provisioned")
    def test_stopping_the_service_stops_its_lean_processes(self):
        _socket, _run_id, _pid, pids = self.start_with_server()
        self.assertTrue(all(alive(pid) for pid in pids))
        lean_session.stop_service(self.directory)
        self.assertTrue(
            wait_until(lambda: not any(alive(pid) for pid in pids), 10), "Lean processes survived the daemon"
        )
        self.assertFalse(lean_session.socket_path(self.directory).exists())

    @unittest.skipUnless(CORE_READY, "Strata fixture environment is not provisioned")
    def test_a_killed_runner_lease_is_dropped_and_its_project_is_closed(self):
        parent = subprocess.Popen(["sleep", "300"])
        try:
            socket_, run_id, _pid, pids = self.start_with_server(parent_pid=parent.pid)
            parent.kill()
            parent.wait()
            self.assertTrue(
                wait_until(
                    lambda: run_id not in status_of(socket_, 5)["leases"] and not any(alive(pid) for pid in pids),
                    20,
                ),
                "lease or project Lean processes survived the killed runner",
            )
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.wait()

    @unittest.skipUnless(CORE_READY, "Strata fixture environment is not provisioned")
    def test_a_killed_service_leaves_no_lean_behind_even_without_the_sweep(self):
        _socket, _run_id, _pid, pids = self.start_with_server()
        service = json.loads((self.directory / lean_session.INFO_NAME).read_text())["pid"]
        os.kill(service, signal.SIGKILL)
        self.assertTrue(
            wait_until(lambda: not any(alive(pid) for pid in pids), 30),
            "Lean kept running after the service died and nothing swept it",
        )


@slow
@unittest.skipUnless(CORE_READY and shutil.which("pi"), "pi and the Strata fixture are required")
class RunnerSessionTests(unittest.TestCase):
    """The real runner, Pi and tool processes against a scripted provider."""

    def setUp(self):
        self.runs = []
        self.service_directory = Path(tempfile.mkdtemp(prefix="arena-runner-service-"))
        self.previous_service_dir = os.environ.get(lean_session.SERVICE_DIR_ENV)
        os.environ[lean_session.SERVICE_DIR_ENV] = str(self.service_directory)
        grace = patch.dict(os.environ, {"ARENA_LEAN_RELEASE_GRACE_S": "1"})  # the service inherits it
        grace.start()
        self.addCleanup(grace.stop)

    def tearDown(self):
        for run in self.runs:
            run.cleanup()
        lean_session.stop_service(self.service_directory)
        if self.previous_service_dir is None:
            os.environ.pop(lean_session.SERVICE_DIR_ENV, None)
        else:
            os.environ[lean_session.SERVICE_DIR_ENV] = self.previous_service_dir
        shutil.rmtree(self.service_directory, ignore_errors=True)

    def probe(self):
        from tests.pi_support import FakeRun

        statement = problem(CORE)["statement"]
        call = {
            "tool_calls": [
                {"name": "compile", "arguments": {"drafts": [statement + " := by\n  intros Hup Hinit\n  sorry"]}}
            ],
            "usage": {"input": 300, "output": 40, "cacheRead": 4000, "cacheWrite": 100},
        }
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
        # The gate decides the primary toolchain itself (check_seconds, passed); only check_others sets "checked".
        primary = json.loads((run.directory / "lean-health.json").read_text())["versions"]["v4.29.1"]
        self.assertIsNotNone(primary.get("check_seconds"))
        self.assertTrue(primary["passed"])
        self.assertIn("Lean session pid=", run.stdout)
        for leftover in ("service.sock", "service.json"):
            self.assertFalse((run.directory / leftover).exists(), leftover)

    def test_ctrl_c_shuts_pi_down_cleanly_and_leaves_no_lean_processes(self):
        call, FakeRun = self.probe()
        run = FakeRun([call, {"text": "slow", "delay_ms": 60000}], session=True, timeout=300)
        self.runs.append(run)
        process = run.start(own_group=True)
        self.assertTrue(run.wait_for_requests(2, 180), "the probe never finished")
        info = json.loads((self.service_directory / lean_session.INFO_NAME).read_text())
        status = lean_session.request({"op": "status"}, 5, info["socket"])
        run_id = run.run_id
        self.assertIn(run_id, status["leases"])
        os.killpg(process.pid, signal.SIGINT)  # a terminal Ctrl+C reaches the whole group (the service has its own)
        _, stderr = process.communicate(timeout=120)
        self.assertEqual(process.returncode, 128 + signal.SIGINT, stderr)
        self.assertNotEqual(run.json("cost.json").get("written_by"), "runner_ledger_reconstruction", stderr)
        self.assertEqual(run.json("summary.json")["stop_reason"], "interrupted")
        self.assertTrue(wait_until(lambda: run_id not in status_of(info["socket"], 5)["leases"], 15))
        # The other toolchains warm in the background (header loads take turns machine-wide, about 12 s for the
        # last one), and a project closes only once its open has finished: allow that, not just the grace.
        self.assertTrue(
            wait_until(lambda: status_of(info["socket"], 5)["servers"] == [], OPENS_IN_FLIGHT_S),
            "the interrupted run's project outlived the release grace",
        )

    def test_a_killed_runner_leaves_no_lean_processes(self):
        call, FakeRun = self.probe()
        run = FakeRun([call, {"text": "slow", "delay_ms": 60000}], session=True, timeout=300)
        self.runs.append(run)
        process = run.start(own_group=True)
        self.assertTrue(run.wait_for_requests(2, 180), "the probe never finished")
        info = json.loads((self.service_directory / lean_session.INFO_NAME).read_text())
        self.assertIn(run.run_id, status_of(info["socket"], 5)["leases"])
        # The runner started the machine-wide service, which must outlive the run: kill the runner's other
        # descendants (Pi and its tools) by their recorded PIDs, then the runner itself.
        victims = set(lean_session.process_tree(process.pid)) - set(lean_session.process_tree(info["pid"]))
        victims -= {process.pid, info["pid"]}
        for pid in victims:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        process.kill()  # a crash: no handler runs
        process.wait()
        self.assertTrue(wait_until(lambda: not any(alive(pid) for pid in victims), 10), "Pi or a tool survived")
        self.assertTrue(
            wait_until(
                lambda: (
                    run.run_id not in status_of(info["socket"], 5)["leases"]
                    and not status_of(info["socket"], 5)["servers"]
                ),
                OPENS_IN_FLIGHT_S,  # as above: a background header load in flight finishes before its project closes
            ),
            "lease or project Lean processes survived a crashed runner",
        )


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
        self.environment = patch.dict(os.environ, {lean_session.SERVICE_DIR_ENV: str(self.directory)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.session = lean_session.Session(
            self.directory,
            budget=lean_session.WorkerBudget(self.directory / "tokens", 4),
        )
        self.entry = lean_session._Entry(self.directory / "proj", {}, self.FakeServer())
        self.session.entries[str(self.entry.project)] = self.entry

    def test_a_worker_open_and_a_memory_refusal_are_logged_and_marked(self):
        lines = []
        with patch.object(lean_session, "_log", lines.append):
            with patch.object(lean_session, "_available_gb", return_value=100.0):
                self.session._acquire(self.entry, 1)
            self.assertFalse(lean_session.memory_pressure())
            other = lean_session._Entry(self.directory / "other", {}, self.FakeServer())
            self.session.entries[str(other.project)] = other
            with (
                patch.object(lean_session, "_available_gb", return_value=4.0),
                self.assertRaises(lean_session.SessionError),
            ):
                self.session._acquire(other, 1)
        self.assertTrue(any(line.startswith("worker open proj") for line in lines), lines)
        self.assertTrue(any("no room for a Lean worker: memory (4.0 GB available)" in line for line in lines), lines)
        self.assertTrue(lean_session.memory_pressure())
        self.assertFalse(lean_session.memory_pressure(within=0))
        self.assertIn(lean_session.WAITING_NAME, lean_session.SESSION_FILES)


class OrphanExitTests(unittest.TestCase):
    """A service whose socket or directory is deleted exits at once (no Lean: the service has no projects)."""

    def serve(self) -> tuple[Path, threading.Thread]:
        directory = Path(tempfile.mkdtemp(prefix="arena-orphan-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        lines: list[str] = []
        for patcher in (patch.object(lean_session.signal, "signal"), patch.object(lean_session, "_log", lines.append)):
            patcher.start()
            self.addCleanup(patcher.stop)
        thread = threading.Thread(target=lean_session.serve, args=(directory,), daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not (directory / lean_session.SOCKET_NAME).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue((directory / lean_session.SOCKET_NAME).exists())
        return directory, thread

    def test_the_service_exits_when_its_directory_is_deleted(self):
        directory, thread = self.serve()
        shutil.rmtree(directory)
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_the_service_exits_when_its_socket_is_replaced(self):
        directory, thread = self.serve()
        newer = directory / "newer"
        newer.write_text("a newer service's socket")  # created while the old one exists: a distinct inode
        os.replace(newer, directory / lean_session.SOCKET_NAME)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertTrue((directory / lean_session.SOCKET_NAME).exists())  # never removes another service's socket
