"""Lean session: header-first open, warm timeouts, warm op, lanes, machine budget. Uses a fake language server."""

import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import engine, lean_session

FAKE = textwrap.dedent("""
    import json, os, re, sys, threading, time
    LOG = os.environ["FAKE_LOG"]
    docs, done, lock = {}, set(), threading.Lock()
    out = sys.stdout.buffer
    def send(m):
        d = json.dumps(m).encode()
        with lock:
            out.write(b"Content-Length: %d\\r\\n\\r\\n" % len(d) + d); out.flush()
    def log(**k):
        with open(LOG, "a") as f: f.write(json.dumps(k) + "\\n")
    def delay(text, first):
        t = sum(float(x) for x in re.findall(r"-- PROOF ([0-9.]+)", text))
        if first: t += sum(float(x) for x in re.findall(r"-- IMPORT ([0-9.]+)", text))
        return t
    def finish(uri, version, wait):
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
              "params": {"uri": uri, "version": version, "diagnostics": [
                  {"severity": 3, "message": "partial", "range": {"start": {"line": 2, "character": 0}}}]}})
        send({"jsonrpc": "2.0", "method": "$/lean/fileProgress",
              "params": {"textDocument": {"uri": uri}, "processing": [
                  {"range": {"start": {"line": 3}}}]}})
        time.sleep(wait)
        if docs.get(uri, (0,))[0] == version:
            send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                  "params": {"uri": uri, "version": version, "diagnostics": [
                      {"severity": 3, "message": "ok v%d" % version, "range": {"start": {"line": 0, "character": 0}}}]}})
            done.add((uri, version))
    def waiter(uri, version, ident):
        while (uri, version) not in done and docs.get(uri, (0,))[0] == version: time.sleep(0.01)
        send({"jsonrpc": "2.0", "id": ident, "result": {}})
    def read():
        while True:
            n = None
            while True:
                h = sys.stdin.buffer.readline()
                if not h: return
                h = h.strip()
                if not h: break
                if h.lower().startswith(b"content-length:"): n = int(h.split(b":")[1])
            yield json.loads(sys.stdin.buffer.read(n))
    for m in read():
        method, p = m.get("method"), m.get("params", {})
        if method == "initialize": send({"jsonrpc": "2.0", "id": m["id"], "result": {"capabilities": {}}})
        elif method in ("textDocument/didOpen", "textDocument/didChange"):
            td = p["textDocument"]
            opened = method.endswith("didOpen")
            text = td["text"] if opened else p["contentChanges"][0]["text"]
            docs[td["uri"]] = (td["version"], text)
            log(method=method.split("/")[1], uri=td["uri"], version=td["version"], size=len(text))
            threading.Thread(target=finish, args=(td["uri"], td["version"], delay(text, opened)), daemon=True).start()
        elif method == "textDocument/didClose":
            docs.pop(p["textDocument"]["uri"], None); log(method="didClose", uri=p["textDocument"]["uri"])
        elif method in ("$/lean/plainGoal", "$/lean/plainTermGoal"):
            log(method="goal_position", position=p["position"], uri=p["textDocument"]["uri"])
            uri = p["textDocument"]["uri"]
            text = docs[uri][1]
            if method == "$/lean/plainGoal":
                result = {"goals": ["h : True\\n⊢ True"] if "sorry" in text else [], "rendered": "h : True\\n⊢ True" if "sorry" in text else None}
            else:
                result = {"goal": "⊢ True" if "sorry" in text else None}
            send({"jsonrpc": "2.0", "id": m["id"], "result": result})
        elif method == "textDocument/waitForDiagnostics":
            threading.Thread(target=waiter, args=(p["uri"], p["version"], m["id"]), daemon=True).start()
""")

HEADER = "import X\n-- IMPORT 0.3\n"


class FakeLean(lean_session.LeanServer):
    script = None
    log_path = None

    def command(self):
        return [sys.executable, str(self.script)]

    def start(self, timeout=30):
        with patch.dict(os.environ, {"FAKE_LOG": str(self.log_path)}):
            super().start(timeout)


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        (self.dir / "proj").mkdir()
        (self.dir / "fake.py").write_text(FAKE)
        FakeLean.script, FakeLean.log_path = self.dir / "fake.py", self.dir / "fake.log"
        patcher = patch.object(lean_session, "LeanServer", FakeLean)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(lean_session, "_available_gb", return_value=100.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Nothing a test does may reach the machine-wide service directory: a memory marker left there holds back
        # every real run's route extraction for two minutes (and every later test that extracts routes).
        patcher = patch.dict(os.environ, {lean_session.SERVICE_DIR_ENV: str(self.dir / "machine")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sessions = []
        self.addCleanup(lambda: [s.shutdown() for s in self.sessions])

    def session(self, name="run", limit=6, **options):
        max_slots = options.pop("max_slots", None)
        if max_slots is not None:
            patcher = patch.object(lean_session, "PRIMARY_MAX_WORKERS", max_slots)
            patcher.start()
            self.addCleanup(patcher.stop)
        session = lean_session.Session(self.dir / name, budget=lean_session.WorkerBudget(self.dir / "tokens", limit))
        self.sessions.append(session)
        return session

    def request(self, body="-- PROOF 0\n", header=HEADER, **extra):
        text = header + body
        return {
            "protocol": lean_session.PROTOCOL,
            "project": str(self.dir / "proj"),
            "fingerprint": {"code": lean_session.code_sha()},
            "display": "A.lean",
            "text": text,
            "header_end": len(header),
            **extra,
        }

    def events(self, method=None):
        try:
            rows = [json.loads(line) for line in FakeLean.log_path.read_text().splitlines()]
        except OSError:
            return []
        return [r for r in rows if method is None or r["method"] == method]

    def settled(self, method, expected, within=3.0):
        """The fake logs asynchronously: the count of `method` events once it reaches `expected` (or the deadline)."""
        deadline = time.monotonic() + within
        while len(self.events(method)) < expected and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)  # and nothing more arrives
        return len(self.events(method))


class HeaderFirstTests(Base):
    def test_the_header_open_is_not_charged_to_the_request_timeout(self):
        session = self.session()
        reply = session.check(self.request("-- PROOF 0.1\n", timeout=0.6))
        self.assertTrue(reply["ok"], reply)
        self.assertNotIn("timeout", reply)
        self.assertGreaterEqual(reply["header_seconds"], 0.3)
        self.assertLess(reply["seconds"], 0.6)
        self.assertEqual([e["method"] for e in self.events()], ["didOpen", "didChange"])
        self.assertEqual(self.events("didOpen")[0]["size"], len(HEADER))

    def test_without_a_header_end_the_whole_text_is_opened_at_once(self):
        reply = self.session().check({**self.request("-- PROOF 0.1\n", timeout=5), "header_end": None})
        self.assertTrue(reply["ok"], reply)
        self.assertIsNone(reply["header_seconds"])
        # a successful check may start background pre-warming of other slots: look at the checked document only
        opened = self.events("didOpen")[0]["uri"]
        self.assertEqual([e["method"] for e in self.events() if e.get("uri") == opened], ["didOpen"])


class WarmTimeoutTests(Base):
    def test_a_timeout_keeps_the_worker_warm_and_the_next_check_does_not_reopen(self):
        session = self.session()
        slow = session.check(self.request("-- PROOF 30\n", timeout=0.4))
        self.assertEqual((slow["ok"], slow["timeout"], slow["warm_kept"]), (True, True, True))
        self.assertGreaterEqual(slow["header_seconds"], 0.3)
        started = time.monotonic()
        fast = session.check(self.request("-- PROOF 0.05\n", timeout=5))
        self.assertTrue(fast["ok"] and not fast.get("timeout"), fast)
        self.assertLess(time.monotonic() - started, 0.9)  # no second 1 s import
        self.assertIsNone(fast["header_seconds"])
        self.assertFalse(fast["new_worker"])
        self.assertEqual(len(self.events("didOpen")), 1)
        self.assertEqual(self.events("didClose"), [])
        # the answer belongs to the newest version: the cancelled one's diagnostics were not reused
        first = self.events("didOpen")[0]["uri"]
        versions = [e["version"] for e in self.events() if e.get("uri") == first]
        self.assertEqual(versions, sorted(versions))
        self.assertIn(f"ok v{versions[-1]}", fast["output"])

    def test_a_timeout_without_a_known_header_closes_the_document(self):
        session = self.session()
        reply = session.check({**self.request("-- PROOF 30\n", timeout=0.4), "header_end": None})
        self.assertEqual((reply["ok"], reply["timeout"], reply["warm_kept"]), (True, True, False))
        self.assertEqual(self.settled("didOpen", 1), 1)
        self.assertEqual(self.settled("didClose", 1), 1)

    def test_a_changed_header_reopens_the_document(self):
        server = lean_session.LeanServer(self.dir / "proj", self.dir / "s.log")
        server.start()
        self.addCleanup(server.stop)
        doc = server.doc("file:///x.lean")
        server.check(doc, "a\n-- PROOF 0\n", 5, 2)
        server.check(doc, "b\n-- PROOF 0\n", 5, 2)
        time.sleep(0.3)
        self.assertEqual(len(self.events("didClose")), 1)
        self.assertEqual(len(self.events("didOpen")), 2)  # reopened for the new header


class WarmOpTests(Base):
    def test_warm_opens_n_workers_one_after_another_with_the_header_only(self):
        session = self.session()
        started = time.monotonic()
        reply = session.warm({**self.request(), "slots": 3, "timeout": 30})
        took = time.monotonic() - started
        self.assertEqual((reply["ok"], reply["workers"], reply["failed"]), (True, 3, []))
        self.assertEqual(len(reply["seconds"]), 3)
        self.assertGreaterEqual(took, 0.9)  # three 0.3 s imports, one at a time (WorkerBudget.opening)
        self.assertEqual([e["size"] for e in self.events("didOpen")], [len(HEADER)] * 3)
        followup = session.check(self.request("-- PROOF 0\n", timeout=5))
        self.assertTrue(followup["ok"] and not followup["new_worker"], followup)
        self.assertEqual(len(self.events("didOpen")), 3)

    def test_warm_is_bounded_by_the_slot_limit_and_reports_a_refusal(self):
        reply = self.session(max_slots=2).warm({**self.request(), "slots": 9, "timeout": 30})
        self.assertEqual(reply["workers"], 2)
        refused = self.session("other", limit=0).warm({**self.request(), "slots": 2, "timeout": 30})
        self.assertEqual(refused["workers"], 0)
        self.assertIn("machine workers", refused["failed"][0])

    def test_warm_session_without_a_session_is_none(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(lean_session.ENV, None)
            self.assertIsNone(engine.warm_session({}, "v", "c", 2))

    def test_goal_and_try_wrappers_send_the_session_operations(self):
        sent = []

        def fake(payload, timeout, path=None):
            sent.append((payload, timeout))
            return {"ok": True}

        row = {"name": "T", "file_path": "A.lean"}
        with (
            patch.dict(os.environ, {lean_session.ENV: "/x"}),
            patch.object(lean_session, "request", fake),
            patch.object(engine, "_fingerprint", return_value={"code": "x"}),
        ):
            engine.lean_goals(row, Path("/p"), "abcdef", 3, 1, 2, timeout=12)
            engine.lean_try(row, Path("/p"), "abcdef", 3, {"line": 1}, ["x"], timeout=13)
        self.assertEqual([request[0]["op"] for request in sent], ["goal", "try"])
        self.assertEqual(sent[0][0]["position"], {"line": 1, "column": 2})
        self.assertEqual(sent[1][0]["snippets"], ["x"])


class LaneTests(Base):
    def test_background_has_one_slot_of_its_own_and_model_slots_are_untouched(self):
        session = self.session(max_slots=1)
        outcome = {}

        def model():
            outcome["model"] = session.check(self.request("-- PROOF 1.5\n", timeout=10))

        thread = threading.Thread(target=model)
        thread.start()
        time.sleep(0.3)  # the model request holds the only model slot
        started = time.monotonic()
        background = session.check(self.request("-- PROOF 0.05\n", timeout=10, lane="background"))
        self.assertTrue(background["ok"], background)
        self.assertEqual(background["lane"], "background")
        self.assertTrue(thread.is_alive() or time.monotonic() - started < 5)
        thread.join()
        self.assertTrue(outcome["model"]["ok"])
        entry = next(iter(session.entries.values()))
        self.assertEqual([len(entry.lane_slots("model")), len(entry.lane_slots("background"))], [1, 1])
        # a second background request reuses the one background slot; a model request never takes it
        session.check(self.request("-- PROOF 0.01\n", timeout=10, lane="background"))
        session.check(self.request("-- PROOF 0.02\n", timeout=10))
        self.assertEqual([len(entry.lane_slots("model")), len(entry.lane_slots("background"))], [1, 1])
        self.assertEqual(len(self.events("didOpen")), 2)

    def test_a_background_timeout_keeps_its_slot_warm(self):
        session = self.session()
        reply = session.check(self.request("-- PROOF 30\n", timeout=0.4, lane="background"))
        self.assertTrue(reply["timeout"] and reply["warm_kept"])
        again = session.check(self.request("-- PROOF 0\n", timeout=5, lane="background"))
        self.assertTrue(again["ok"] and not again["new_worker"])
        self.assertEqual(len(self.events("didOpen")), 1)

    def test_run_lean_forwards_the_lane_and_the_header(self):
        sent = {}

        def fake(payload, timeout, path=None):
            sent.update(payload)
            return {"ok": True, "returncode": 0, "output": "", "header_seconds": 2.0, "warm_kept": False}

        with (
            patch.dict(os.environ, {lean_session.ENV: "/x"}),
            patch.object(lean_session, "request", fake),
            patch.object(engine, "_fingerprint", return_value={"code": "x"}),
        ):
            engine.run_lean({"name": "T", "file_path": "A.lean"}, Path("/p"), "abcdef", prefix_end=3, lane="background")
        self.assertEqual((sent["lane"], sent["header_end"], sent["timeout"]), ("background", 3, 180))
        self.assertEqual(engine.last_lean_run()["header_seconds"], 2.0)

    def test_timeout_returns_partial_diagnostics_and_progress_but_keeps_worker(self):
        session = self.session()
        reply = session.check(self.request("-- PROOF 30\n", timeout=0.4))
        self.assertTrue(reply["timeout"] and reply["warm_kept"])
        self.assertEqual(reply["partial"][0]["message"], "partial")
        self.assertEqual(reply["progress_line"], 3)
        self.assertIn("partial", reply["partial_output"])
        again = session.check(self.request("-- PROOF 0\n", timeout=5))
        self.assertTrue(again["ok"] and not again["new_worker"])

    def test_goal_maps_codepoint_column_to_utf16_and_returns_goal_forms(self):
        session = self.session()
        text = HEADER + "😀 sorry\n"
        request = {
            **self.request(),
            "text": text,
            "header_end": len(HEADER),
            "position": {"line": 2, "column": 1},
            "op": "goal",
        }
        reply = session.goal(request)
        self.assertEqual(reply["goals"], ["h : True\n⊢ True"])
        self.assertEqual(reply["term_goal"], "⊢ True")
        # The emoji takes two UTF-16 code units before the requested codepoint column.
        self.assertTrue(any(event["position"] == {"line": 2, "character": 2} for event in self.events("goal_position")))

    def test_goal_asks_the_worker_that_checked_the_text_and_sends_the_text_once(self):
        session = self.session()
        primary = str(self.dir / "proj")
        self.assertTrue(session.lease({"run_id": "run", "pid": os.getpid(), "primary": primary, "others": []})["ok"])
        session.warm({**self.request(), "run_id": "run", "slots": lean_session.PRIMARY_MIN_WORKERS, "timeout": 30})
        text = HEADER + "theorem t : True := by\n  sorry\n"
        reply = session.goal({**self.request(), "text": text, "position": {"line": 3, "column": 2}, "op": "goal"})
        self.assertEqual(reply["goals"], ["h : True\n⊢ True"])
        self.settled("didOpen", lean_session.PRIMARY_MAX_WORKERS)  # the first model check grows the primary
        sent = [e["uri"] for e in self.events() if e["method"] in ("didOpen", "didChange") and e["size"] == len(text)]
        asked = {e["uri"] for e in self.events("goal_position")}
        self.assertEqual(len(sent), 1)
        self.assertEqual(asked, set(sent))

    def test_try_runs_ordered_snippets_and_continues_after_a_timeout(self):
        session = self.session()
        request = {
            **self.request("sorry\n"),
            "hole": {"line": 2, "column": 0, "end_line": 2, "end_column": 6},
            "snippets": ["-- PROOF 1.0\n", "exact True\n"],
            "timeout": 0.4,
        }
        reply = session.try_snippets(request)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(len(reply["results"]), 2)
        self.assertTrue(reply["results"][0]["timeout"])
        self.assertIn("returncode", reply["results"][1])
        refused = session.try_snippets({**request, "snippets": ["x"] * 9})
        self.assertFalse(refused["ok"])


class BackgroundWorkerTests(Base):
    def other(self, name):
        (self.dir / name).mkdir(exist_ok=True)
        return str(self.dir / name)

    def background(self, session, project, body="-- PROOF 0.02\n", **extra):
        return session.check({**self.request(body, timeout=10, lane="background"), "project": project, **extra})

    def test_each_toolchain_keeps_its_own_background_worker_across_alternating_requests(self):
        session = self.session(limit=8)
        self.assertEqual(session.warm({**self.request(), "slots": 2, "timeout": 30})["workers"], 2)
        v2, v3 = self.other("v2"), self.other("v3")
        for i in range(3):
            for project in (v2, v3):
                reply = self.background(session, project, f"-- PROOF 0.0{i + 1}\n")
                self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.events("didClose"), [])
        opened = [e["uri"] for e in self.events("didOpen")]
        self.assertEqual(len(opened), 4)  # 2 model + one background document per toolchain, never reopened
        for name in ("v2", "v3"):
            entry = session.entries[str(self.dir / name)]
            self.assertEqual(len(entry.lane_slots("background")), 1)
            self.assertEqual(len(entry.lane_slots("model")), 0)
        self.assertEqual(len(session.entries[str(self.dir / "proj")].lane_slots("model")), 2)

    def test_an_adhoc_project_stays_open_until_its_idle_limit(self):
        session = self.session(limit=8)
        self.background(session, self.other("v2"))
        entry = session.entries[str(self.dir / "v2")]
        entry.used = time.monotonic() - 5
        session.reap_idle()  # the watch loop runs every second: an idle ad hoc project must outlive many ticks
        self.assertIn(str(self.dir / "v2"), session.entries)
        with patch.object(lean_session, "ADHOC_IDLE_S", 3):
            session.reap_idle()
        self.assertNotIn(str(self.dir / "v2"), session.entries)
        self.assertEqual(self.settled("didClose", 1), 1)

    def test_warm_on_the_background_lane_opens_only_the_background_worker(self):
        session = self.session(limit=8)
        reply = session.warm(
            {**self.request(), "project": self.other("v2"), "slots": 4, "timeout": 30, "lane": "background"}
        )
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["workers"], 1)
        entry = session.entries[str(self.dir / "v2")]
        self.assertEqual([len(entry.lane_slots("background")), len(entry.lane_slots("model"))], [1, 0])
        check = self.background(session, str(self.dir / "v2"))
        self.assertTrue(check["ok"] and not check["new_worker"])
        self.assertEqual([e["size"] for e in self.events("didOpen")], [len(HEADER)])  # header only, opened once

    def test_a_background_request_waits_for_its_toolchains_busy_background_worker(self):
        session = self.session(limit=8)
        outcome = {}
        project = self.other("v2")
        thread = threading.Thread(
            target=lambda: outcome.update(first=self.background(session, project, "-- PROOF 1.5\n"))
        )
        thread.start()
        time.sleep(0.4)
        started = time.monotonic()
        second = self.background(session, project)
        thread.join()
        self.assertTrue(outcome["first"]["ok"] and second["ok"], (outcome, second))
        self.assertGreater(time.monotonic() - started, 0.8)  # it queued behind the first instead of failing

    def test_background_never_evicts_a_model_worker_even_with_no_machine_room(self):
        first = self.session("a", limit=1)
        self.assertEqual(first.warm({**self.request(), "slots": 4, "timeout": 30})["workers"], 1)
        other = self.other("v2")
        reply = self.background(first, other)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.events("didClose"), [])
        model = first.entries[str(self.dir / "proj")]
        self.assertEqual([s.text is not None for s in model.lane_slots("model")], [True])

    def test_cross_version_warmup_with_no_memory_never_closes_primary_workers(self):
        session = self.session(limit=8)
        primary = str(self.dir / "proj")
        self.assertTrue(session.lease({"run_id": "run", "pid": os.getpid(), "primary": primary, "others": []})["ok"])
        self.assertEqual(
            session.warm({**self.request(), "run_id": "run", "slots": lean_session.PRIMARY_MIN_WORKERS})["workers"],
            2,
        )
        with patch.object(lean_session, "_available_gb", return_value=5.0):
            for name in ("v2", "v3", "v4"):
                self.assertEqual(
                    session.warm({**self.request(), "project": self.other(name), "lane": "background", "slots": 1})[
                        "workers"
                    ],
                    0,
                )
        self.assertEqual(self.events("didClose"), [])
        self.assertEqual(len(session.entries[primary].lane_slots("model")), 2)
        # The refusals mark this session's own directory, not the machine-wide one.
        self.assertTrue((self.dir / "run" / lean_session.WAITING_NAME).exists())
        self.assertFalse((self.dir / "machine" / lean_session.WAITING_NAME).exists())

    def test_background_is_guaranteed_even_when_model_workers_hold_every_machine_token(self):
        session = self.session(limit=2)
        self.assertEqual(session.warm({**self.request(), "slots": 4, "timeout": 30})["workers"], 2)
        hog = lean_session.WorkerBudget(self.dir / "tokens", 2)
        _held = [hog.acquire(), hog.acquire()]  # held (not garbage-collected) so no model token is left
        self.assertFalse(hog.available())
        reply = self.background(session, self.other("v2"))
        self.assertTrue(reply["ok"], reply)

    def test_another_projects_idle_background_worker_is_the_only_eviction_target(self):
        session = self.session(limit=1)
        v2, v3 = self.other("v2"), self.other("v3")
        self.assertTrue(self.background(session, v2)["ok"])
        hog = lean_session.WorkerBudget(self.dir / "tokens", 1)
        _held = [hog.acquire(background=True) for _ in range(lean_session.BACKGROUND_TOKENS - 1)]
        self.assertTrue(self.background(session, v3)["ok"])
        self.assertEqual(len(self.events("didClose")), 1)
        self.assertEqual(len(session.entries[v2].lane_slots("background")), 0)
        self.assertEqual(len(session.entries[v3].lane_slots("background")), 1)

    def test_model_request_is_refused_instead_of_evicting_a_running_runs_primary_worker(self):
        session = self.session(limit=1)
        primary = self.request()["project"]
        self.assertTrue(session.lease({"run_id": "run", "pid": os.getpid(), "primary": primary, "others": []})["ok"])
        self.assertEqual(session.warm({**self.request(), "slots": 1})["workers"], 1)
        reply = session.check({**self.request(), "project": self.other("v2")})
        self.assertFalse(reply["ok"])
        self.assertEqual(self.events("didClose"), [])

    def test_an_idle_pre_warmed_worker_no_run_uses_is_evicted_for_a_starting_run(self):
        # v7-check2: workers pre-warmed for a later row filled the machine cap and a starting row was refused.
        session = self.session(limit=1)
        self.assertEqual(session.warm({**self.request(), "slots": 1})["workers"], 1)
        reply = session.check({**self.request(), "project": self.other("v2")})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(len(self.events("didClose")), 1)


class AsyncWarmAndPssTests(Base):
    def test_nonblocking_warm_returns_before_header_open_finishes(self):
        session = self.session()
        started = time.monotonic()
        reply = session.warm({**self.request(), "slots": 1, "wait": False})
        self.assertEqual(reply, {"ok": True, "started": True})
        self.assertLess(time.monotonic() - started, 0.25)
        self.assertEqual(self.settled("didOpen", 1), 1)

    def test_a_failed_warm_up_nobody_waits_for_is_logged(self):
        session = self.session()
        logged = []
        with patch.object(lean_session, "_log", logged.append):
            stale = {**self.request(), "fingerprint": {"code": "old"}, "slots": 1, "wait": False}
            self.assertEqual(session.warm(stale), {"ok": True, "started": True})
            deadline = time.monotonic() + 3
            while not logged and time.monotonic() < deadline:
                time.sleep(0.02)
        self.assertTrue(any(line.startswith("background warm-up proj failed: stale") for line in logged), logged)

    def test_status_names_each_workers_lane_by_the_document_it_serves_not_by_pid_order(self):
        documents = {}
        session = lean_session.Session(
            self.dir / "lanes",
            budget=lean_session.WorkerBudget(self.dir / "tokens", 4),
            mem_fn=lambda: (8.5, None),
            pss_fn=lambda _: {10: 1.0, 20: 2.0, 30: 0.5},
            external_fn=lambda _: {},
            document_fn=lambda pid: documents.get(pid),
        )
        self.sessions.append(session)
        with patch.object(lean_session, "process_tree", return_value=[]):
            session.warm({**self.request(), "slots": 1})
            session.warm({**self.request(), "slots": 1, "lane": "background"})
            slots = {slot.lane: slot.uri for entry in session.entries.values() for slot in entry.slots}
            # The background document's worker has the lower pid: pid order says nothing about which is which.
            documents.update({10: slots["background"], 20: slots["model"]})
            workers = session.status()["servers"][0]["workers"]
        self.assertEqual(
            [(worker["pid"], worker["lane"]) for worker in workers], [(10, "background"), (20, "model"), (30, None)]
        )

    def test_status_and_log_include_injected_worker_and_external_memory_and_rotate(self):
        session = lean_session.Session(
            self.dir / "pss",
            budget=lean_session.WorkerBudget(self.dir / "tokens", 4),
            mem_fn=lambda: (8.5, 1.25),
            pss_fn=lambda _: {456: 1.5},
            external_fn=lambda _: {789: 0.75},
            document_fn=lambda _: next(iter(session.entries.values())).slots[0].uri,
        )
        self.sessions.append(session)
        with patch.object(lean_session, "process_tree", return_value=[]):
            session.warm({**self.request(), "slots": 1})
            status = session.status()
            self.assertEqual(status["servers"][0]["workers"], [{"pid": 456, "gb": 1.5, "lane": "model"}])
            self.assertEqual(
                (status["mem_available_gb"], status["swap_used_gb"], status["external_lean_gb"]), (8.5, 1.25, 0.75)
            )
            session.last_pss_log = 0
            session.log_pss()
            line = json.loads((self.dir / "pss" / "pss.jsonl").read_text())
            self.assertEqual((line["external_lean_gb"], line["servers"][0]["workers"][0]["gb"]), (0.75, 1.5))
            with patch.object(lean_session, "PSS_LOG_MAX_BYTES", 1):
                session.last_pss_log = 0
                session.log_pss()
            self.assertTrue((self.dir / "pss" / "pss.jsonl.1").exists())


class QueueTests(Base):
    def test_waiting_for_a_busy_worker_longer_than_the_check_timeout_still_succeeds(self):
        session = self.session(max_slots=1)
        outcome = {}
        thread = threading.Thread(
            target=lambda: outcome.update(first=session.check(self.request("-- PROOF 1.5\n", timeout=10)))
        )
        thread.start()
        time.sleep(0.3)
        started = time.monotonic()
        with patch.object(lean_session, "MODEL_QUEUE_TIMEOUT", 10):
            second = session.check(self.request("-- PROOF 0.05\n", timeout=0.6))
        thread.join()
        self.assertGreater(time.monotonic() - started, 0.6)  # it waited longer than its own check timeout
        self.assertTrue(second["ok"], second)
        self.assertNotIn("timeout", second)  # the check clock started only once it held the worker
        self.assertLess(second["seconds"], 0.6)

    def test_the_queue_has_its_own_limit(self):
        session = self.session(max_slots=1)
        thread = threading.Thread(target=lambda: session.check(self.request("-- PROOF 2\n", timeout=10)))
        thread.start()
        time.sleep(0.3)
        with patch.object(lean_session, "MODEL_QUEUE_TIMEOUT", 0.5):
            reply = session.check(self.request("-- PROOF 0\n", timeout=10))
        thread.join()
        self.assertFalse(reply["ok"])
        self.assertIn("busy for too long", reply["reason"])

    def test_waiters_are_served_in_arrival_order(self):
        session = self.session(max_slots=1)
        order = []
        first = threading.Thread(target=lambda: session.check(self.request("-- PROOF 1\n", timeout=10)))
        first.start()
        time.sleep(0.3)

        def waiter(name):
            session.check(self.request(f"-- PROOF 0.05\n-- {name}\n", timeout=10))
            order.append(name)

        threads = []
        for name in "abc":
            thread = threading.Thread(target=waiter, args=(name,))
            thread.start()
            threads.append(thread)
            time.sleep(0.1)
        for thread in [first, *threads]:
            thread.join()
        self.assertEqual(order, ["a", "b", "c"])

    def test_run_lean_socket_timeout_covers_queue_open_and_check(self):
        seen = {}

        def fake(payload, timeout, path=None):
            seen["wait"] = timeout
            return {"ok": True, "returncode": 0, "output": ""}

        with (
            patch.dict(os.environ, {lean_session.ENV: "/x"}),
            patch.object(lean_session, "request", fake),
            patch.object(engine, "_fingerprint", return_value={"code": "x"}),
        ):
            engine.run_lean({"name": "T", "file_path": "A.lean"}, Path("/p"), "abcdef", timeout=100, prefix_end=3)
        self.assertGreaterEqual(seen["wait"], lean_session.MODEL_QUEUE_TIMEOUT + lean_session.OPEN_TIMEOUT + 200 + 60)


class ServerCommandTests(unittest.TestCase):
    def setUp(self):
        lean_session.server_lean_path.cache_clear()
        self.addCleanup(lean_session.server_lean_path.cache_clear)

    def run_command(self, stdout, returncode=0, project="/w/proj"):
        done = type("Done", (), {"stdout": stdout, "returncode": returncode})()
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return done

        with patch.object(lean_session.subprocess, "run", run):
            server = lean_session.LeanServer(Path(project), Path("/nonexistent/log"))
            return server.command(), calls

    def test_the_server_gets_the_projects_own_build_folder_first(self):
        raw = (
            ":".join(
                [
                    "/w/proj/.lake/packages/mathlib/.lake/build/lib/lean",
                    "/tc/lib/lean",
                    "/w/proj/.lake/build/lib/lean",
                    "/tc/lib/lean",
                ]
            )
            + "\n"
        )
        command, calls = self.run_command(raw)
        self.assertEqual(calls, [["lake", "env", "printenv", "LEAN_PATH"]])
        expected = ":".join(
            ["/w/proj/.lake/build/lib/lean", "/w/proj/.lake/packages/mathlib/.lake/build/lib/lean", "/tc/lib/lean"]
        )
        self.assertEqual(
            command, ["lake", "env", "env", f"LAKE={lean_session.NO_LAKE}", f"LEAN_PATH={expected}", "lean", "--server"]
        )

    def test_the_path_is_computed_once_per_project(self):
        _, _calls = self.run_command("/a:/w/proj/.lake/build/lib/lean\n")
        server = lean_session.LeanServer(Path("/w/proj"), Path("/nonexistent/log"))
        with patch.object(lean_session.subprocess, "run", side_effect=AssertionError("recomputed")):
            self.assertIn("LEAN_PATH=/w/proj/.lake/build/lib/lean:/a", server.command())

    def test_a_failure_falls_back_to_the_plain_command(self):
        command, _ = self.run_command("", returncode=1)
        self.assertEqual(command, ["lake", "env", "env", f"LAKE={lean_session.NO_LAKE}", "lean", "--server"])
        lean_session.server_lean_path.cache_clear()
        with patch.object(lean_session.subprocess, "run", side_effect=OSError("no lake")):
            server = lean_session.LeanServer(Path("/w/proj"), Path("/nonexistent/log"))
            self.assertNotIn("lean_path", " ".join(server.command()).lower())


class MachineBudgetTests(Base):
    def warm(self, session, slots, project="proj"):
        reply = session.warm({**self.request(), "project": str(self.dir / project), "slots": slots, "timeout": 30})
        self.assertTrue(reply["ok"], reply)
        return reply

    def test_tokens_free_themselves_when_the_holder_exits(self):
        budget = lean_session.WorkerBudget(self.dir / "tok", 1)
        code = (
            "import sys; from pathlib import Path; from arena import lean_session as l; "
            "t = l.WorkerBudget(Path(sys.argv[1]), 1).acquire(); print('held' if t else 'no', flush=True); "
            "sys.stdin.read()"
        )
        import subprocess

        holder = subprocess.Popen(
            [sys.executable, "-c", code, str(self.dir / "tok")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            cwd=lean_session.ROOT,
        )
        self.assertEqual(holder.stdout.readline().strip(), "held")
        self.assertFalse(budget.available())
        holder.kill()
        holder.wait()
        self.assertTrue(budget.available())


class ServiceLeaseTests(Base):
    def reap(self, session, project, closed=True, within=5.0):
        """Tick like the service's watch loop until `project` is closed (or, with closed=False, for a while).
        A project closes only when no document is busy, and a check starts background pre-warming."""
        deadline = time.monotonic() + within
        while time.monotonic() < deadline:
            session.reap_idle()
            if closed and project not in session.entries:
                break
            time.sleep(0.05)
        return project not in session.entries

    def lease(self, session, run_id, primary, others=()):
        reply = session.lease({"run_id": run_id, "pid": os.getpid(), "primary": primary, "others": list(others)})
        self.assertTrue(reply["ok"], reply)

    def test_the_next_run_of_a_row_finds_its_workers_warm_and_they_close_after_the_grace(self):
        session = self.session()
        project = str(self.dir / "proj")
        self.lease(session, "first", project)
        self.assertTrue(session.check(self.request(run_id="first"))["ok"])
        opened = self.settled("didOpen", 1)
        self.assertEqual(session.release("first")["closing"], [project])
        session.reap_idle()
        self.assertIn(project, session.entries)  # inside the grace: still warm
        self.lease(session, "second", project)
        reply = session.check(self.request("-- PROOF 0.01\n", run_id="second"))
        self.assertTrue(reply["ok"], reply)
        self.assertFalse(reply["new_worker"])
        self.assertIsNone(reply["header_seconds"])
        self.assertEqual(self.settled("didOpen", opened), opened)  # no new document for the second run
        session.release("second")
        with patch.object(lean_session, "RELEASE_GRACE_S", 0):
            self.assertTrue(self.reap(session, project))
        self.assertEqual(self.settled("didClose", len(self.events("didOpen"))), len(self.events("didOpen")))

    def test_close_idle_closes_a_released_project_at_once_but_keeps_a_leased_one(self):
        """Between campaign runs nothing of a finished run may stay in memory, grace period or not."""
        session = self.session()
        project, other = str(self.dir / "proj"), str(self.dir / "v2")
        (self.dir / "v2").mkdir()
        self.lease(session, "done", project)
        self.lease(session, "live", other)
        self.assertTrue(session.check(self.request(run_id="done"))["ok"])
        self.assertTrue(session.check(self.request(run_id="live", project=other))["ok"])
        session.release("done")
        deadline = time.monotonic() + 5.0
        closed = []
        while time.monotonic() < deadline and project in session.entries:
            closed += session.close_idle()["closed"]
            time.sleep(0.05)
        self.assertNotIn(project, session.entries)
        self.assertIn(project, closed)
        self.assertIn(other, session.entries)

    def test_close_idle_stops_a_finished_runs_project_even_while_a_check_is_busy(self):
        """v7/22 handoff test: the run's last background check outlived it and kept strata open past the next row."""
        session = self.session()
        project = str(self.dir / "proj")
        self.lease(session, "done", project)
        self.assertTrue(session.check(self.request(run_id="done"))["ok"])
        session.release("done")
        entry = session.entries[project]
        for slot in entry.slots:
            slot.busy = True  # a check still running after its run exited
        self.assertIn(project, session.close_idle()["closed"])
        self.assertNotIn(project, session.entries)

    def test_a_project_another_lease_or_a_hold_names_stays_open(self):
        session = self.session()
        project, other = str(self.dir / "proj"), str(self.dir / "v2")
        (self.dir / "v2").mkdir()
        self.lease(session, "first", project)
        self.lease(session, "second", other, others=[project])
        self.assertTrue(session.check(self.request(run_id="first"))["ok"])
        session.release("first")
        with patch.object(lean_session, "RELEASE_GRACE_S", 0):
            self.assertFalse(self.reap(session, project, closed=False, within=0.5))  # in the second run's others
            self.assertTrue(session.hold({"owner": "queue", "pid": os.getpid(), "projects": [project]})["ok"])
            session.release("second")
            self.assertFalse(self.reap(session, project, closed=False, within=0.5))  # a queued row holds it
            session.unhold("queue")
            self.assertTrue(self.reap(session, project))

    def test_model_request_for_other_project_uses_background_while_a_hold_stays_model(self):
        session = self.session(limit=8)
        primary, other = str(self.dir / "proj"), str(self.dir / "v2")
        (self.dir / "v2").mkdir()
        self.lease(session, "run", primary, [other])
        request = {**self.request(), "project": other, "lane": "model", "run_id": "run"}
        reply = session.check(request)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["lane"], "background")
        entry = session.entries[other]
        self.assertEqual((len(entry.lane_slots("model")), len(entry.lane_slots("background"))), (0, 1))
        held = str(self.dir / "v3")
        (self.dir / "v3").mkdir()
        session.hold({"owner": "queued", "pid": os.getpid(), "projects": [held]})
        held_reply = session.check({**request, "project": held})
        self.assertEqual(held_reply["lane"], "model")

    def test_dead_pids_are_refused_and_their_leases_and_holds_dropped(self):
        session = self.session()
        project = str(self.dir / "proj")
        self.lease(session, "run", project)
        self.assertTrue(session.hold({"owner": "queue", "pid": os.getpid(), "projects": [project]})["ok"])
        self.assertTrue(session.check(self.request(run_id="run"))["ok"])
        with patch.object(session, "_pid_alive", return_value=False):
            self.assertFalse(session.lease({"run_id": "x", "pid": 1, "primary": project, "others": []})["ok"])
            self.assertFalse(session.hold({"owner": "y", "pid": 1, "projects": [project]})["ok"])
            session.reap_dead()
        self.assertEqual((session.leases, session.holds), ({}, {}))
        with patch.object(lean_session, "RELEASE_GRACE_S", 0):
            self.assertTrue(self.reap(session, project))  # a crashed runner's project closes like a released one

    def test_service_linger_starts_only_when_no_entries_leases_or_holds_remain(self):
        session = self.session()
        with patch.object(lean_session, "SERVICE_LINGER_S", 0.1):
            session.last_active = time.monotonic() - 1
            self.assertTrue(session.should_exit())
            session.leases["active"] = {"pid": os.getpid(), "primary": "p", "others": []}
            self.assertFalse(session.should_exit())
            session.leases.clear()


class EnsureServiceTests(unittest.TestCase):
    """Finding, reusing or replacing the machine-wide service, with injected status replies and process start."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.path = lean_session.socket_path(self.directory)
        patcher = patch.object(lean_session, "code_sha", return_value="current")
        patcher.start()
        self.addCleanup(patcher.stop)

    def status(self, code="current", **extra):
        return {"ok": True, "protocol": lean_session.PROTOCOL, "code": code, "leases": {}, "holds": {}, **extra}

    def ensure(self, probes, shutdown=None):
        replies = iter(probes)
        with (
            patch.object(lean_session, "_probe", side_effect=lambda *_: next(replies)),
            patch.object(lean_session, "request", side_effect=shutdown) as request,
            patch.object(lean_session.subprocess, "Popen") as start,
        ):
            return lean_session.ensure_service(self.directory, wait=0.5), start, request

    def test_a_service_with_current_code_is_reused(self):
        path, start, _ = self.ensure([self.status()])
        self.assertEqual(path, str(self.path))
        start.assert_not_called()

    def test_an_idle_service_with_old_code_is_stopped_and_replaced(self):
        path, start, request = self.ensure(
            [self.status("old"), "absent", "absent", self.status()], shutdown=lambda *_: {"ok": True}
        )
        self.assertEqual(path, str(self.path))
        self.assertEqual(request.call_args.args[0]["op"], "shutdown")
        start.assert_called_once()

    def test_old_code_with_live_runs_is_refused(self):
        with self.assertRaisesRegex(lean_session.SessionError, "older code with live runs"):
            self.ensure([self.status("old", leases={"r": {}})])

    def test_a_busy_service_is_never_mistaken_for_a_dead_one(self):
        self.path.touch()
        with self.assertRaisesRegex(lean_session.SessionError, "does not answer"):
            self.ensure(["busy"] * 50)
        self.assertTrue(self.path.exists())  # its socket was left alone and no second service was started

    def test_a_dead_socket_is_replaced(self):
        self.path.touch()
        path, start, _ = self.ensure(["absent", self.status()])
        self.assertEqual(path, str(self.path))
        start.assert_called_once()


class SharedDocumentTests(Base):
    def test_prefix_change_closes_only_documents_for_that_display(self):
        session = self.session()
        first_header, second_header = "import A\n", "import B\n"
        session.warm({**self.request(header=first_header, display="A.lean", prefix_sha="first"), "slots": 1})
        session.warm({**self.request(header=second_header, display="B.lean", prefix_sha="second"), "slots": 2})
        reply = session.check({**self.request(header=first_header, display="A.lean", prefix_sha="changed")})
        self.assertFalse(reply["ok"])
        entry = session.entries[str(self.dir / "proj")]
        self.assertEqual([slot.display for slot in entry.slots], ["B.lean"])
        self.assertEqual(self.settled("didClose", 1), 1)
        again = session.check({**self.request(header=first_header, display="A.lean", prefix_sha="first")})
        self.assertTrue(again["ok"], again)  # the pin was reset: going back is not a second change

    def test_runs_on_different_targets_in_one_file_do_not_disturb_each_other(self):
        session = self.session()
        for _ in range(2):
            for run, prefix in (("one", "first target"), ("two", "second target")):
                reply = session.check({**self.request(display="A.lean", prefix_sha=prefix), "run_id": run})
                self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.settled("didClose", 0, within=0.3), 0)

    def test_idle_document_with_matching_header_is_preferred(self):
        session = self.session()
        first_header, second_header = "import A\n", "import B\n"
        session.warm({**self.request(header=first_header, display="A.lean"), "slots": 1})
        session.warm({**self.request(header=second_header, display="B.lean"), "slots": 2})
        entry = session.entries[str(self.dir / "proj")]
        matching = next(slot for slot in entry.slots if slot.header == first_header)
        other = next(slot for slot in entry.slots if slot.header == second_header)
        matching.used, other.used = 1.0, 2.0
        reply = session.check(self.request(header=first_header, display="A.lean"))
        self.assertTrue(reply["ok"] and not reply["new_worker"], reply)
        self.assertIsNone(reply["header_seconds"])
        self.assertGreater(matching.used, other.used)


class OpeningGateTests(Base):
    def test_header_loads_take_turns_across_sessions(self):
        first, second = self.session("a", limit=8), self.session("b", limit=8)
        replies = []
        threads = [
            threading.Thread(target=lambda s=s: replies.append(s.check(self.request(timeout=5))))
            for s in (first, second)
        ]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(all(r["ok"] for r in replies), replies)
        self.assertGreaterEqual(time.monotonic() - started, 0.6)  # two 0.3 s imports, one after the other

    def test_a_header_load_waits_for_memory_and_then_gives_up(self):
        budget = lean_session.WorkerBudget(self.dir / "tokens", 8)
        with patch.object(lean_session, "_available_gb", return_value=lean_session.RESERVE_GB + 1.0):
            with self.assertRaisesRegex(lean_session.SessionError, "no memory"), budget.opening(2.0, 0.5):
                pass
            with budget.opening(0.5, 0.5) as waited:
                self.assertLess(waited, 0.5)

    def test_a_held_gate_blocks_another_holder_until_released(self):
        budget = lean_session.WorkerBudget(self.dir / "tokens", 8)
        with (
            budget.opening(0.0, 1.0),
            self.assertRaisesRegex(lean_session.SessionError, "still loading"),
            budget.opening(0.0, 0.3),
        ):
            pass
        with budget.opening(0.0, 0.5):
            pass


class ColdPathTests(unittest.TestCase):
    def test_the_projects_own_build_folder_comes_first(self):
        project = Path("/w/proj")
        path = ":".join(
            [
                "/w/proj/.lake/packages/a/.lake/build/lib/lean",
                "/w/proj/.lake/packages/mathlib/.lake/build/lib/lean",
                "/w/proj/.lake/build/lib/lean",
                "/tc/lib/lean",
            ]
        )
        got = engine.reorder_lean_path(path, project).split(":")
        self.assertEqual(got[0], "/w/proj/.lake/build/lib/lean")
        self.assertEqual(sorted(got), sorted(path.split(":")))
        self.assertEqual(got[1:], [p for p in path.split(":") if p != got[0]])
        self.assertEqual(engine.reorder_lean_path("/a:/b", project), "/a:/b")

    def test_arena_lean_timeout_is_used_and_named_in_the_error(self):
        built = {"path": Path("/p"), "text": "t", "offset": 0, "head": 0, "start_line": 1, "end_line": 1}
        seen = {}

        def fake(row, project, text, timeout=None, prefix_end=None, lane="model"):
            seen["timeout"] = timeout
            return None

        with (
            patch.dict(os.environ, {"ARENA_LEAN_TIMEOUT": "77"}),
            patch.object(engine, "candidate_file", return_value=built),
            patch.object(engine, "run_lean", fake),
        ):
            result = engine.compile_version({}, "proof", "v", "c")
        self.assertEqual(seen["timeout"], 77)
        self.assertEqual(result["error"], "Lean timed out after 77 seconds")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARENA_LEAN_TIMEOUT", None)
            self.assertEqual(engine.lean_timeout(), 180)

    def test_the_cold_path_runs_lean_directly_with_the_reordered_path_and_falls_back(self):
        calls = []

        class Proc:
            returncode = 0
            pid = 1

            def communicate(self, timeout=None):
                return "", ""

        def popen(command, **kwargs):
            calls.append((command, kwargs.get("env")))
            return Proc()

        row = {"name": "T", "file_path": "A.lean"}
        with (
            patch.object(engine, "_lean_command", return_value=("/tc/bin/lean", {"LEAN_PATH": "/x"})),
            patch.object(engine.subprocess, "Popen", popen),
        ):
            engine._run_cold(row, Path("/p"), "t", 5)
        self.assertEqual(calls[0][0][0], "/tc/bin/lean")
        self.assertEqual(calls[0][1]["LEAN_PATH"], "/x")
        with patch.object(engine, "_lean_command", return_value=None), patch.object(engine.subprocess, "Popen", popen):
            engine._run_cold(row, Path("/p"), "t", 5)
        self.assertEqual(calls[1][0][:3], ["lake", "env", "lean"])


if __name__ == "__main__":
    unittest.main()
