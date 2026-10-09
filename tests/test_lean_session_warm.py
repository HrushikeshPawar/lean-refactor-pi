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

FAKE = textwrap.dedent('''
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
        elif method == "textDocument/waitForDiagnostics":
            threading.Thread(target=waiter, args=(p["uri"], p["version"], m["id"]), daemon=True).start()
''')

HEADER = "import X\n-- IMPORT 1.0\n"


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
        self.sessions = []
        self.addCleanup(lambda: [s.shutdown() for s in self.sessions])

    def session(self, name="run", limit=6, **options):
        session = lean_session.Session(self.dir / name, budget=lean_session.WorkerBudget(self.dir / "tokens", limit),
                                       **options)
        self.sessions.append(session)
        return session

    def request(self, body="-- PROOF 0\n", header=HEADER, **extra):
        text = header + body
        return {"protocol": lean_session.PROTOCOL, "project": str(self.dir / "proj"),
                "fingerprint": {"code": lean_session.code_sha()}, "display": "A.lean", "text": text,
                "header_end": len(header), **extra}

    def events(self, method=None):
        try:
            rows = [json.loads(line) for line in FakeLean.log_path.read_text().splitlines()]
        except OSError:
            return []
        return [r for r in rows if method is None or r["method"] == method]


class HeaderFirstTests(Base):
    def test_the_header_open_is_not_charged_to_the_request_timeout(self):
        session = self.session()
        reply = session.check(self.request("-- PROOF 0.1\n", timeout=0.6))
        self.assertTrue(reply["ok"], reply)
        self.assertNotIn("timeout", reply)
        self.assertGreaterEqual(reply["header_seconds"], 1.0)
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
        self.assertGreaterEqual(slow["header_seconds"], 1.0)
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
        time.sleep(0.3)
        self.assertEqual(len(self.events("didClose")), 1)

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
    def test_warm_opens_n_workers_in_parallel_with_the_header_only(self):
        session = self.session()
        started = time.monotonic()
        reply = session.warm({**self.request(), "slots": 3, "timeout": 30})
        took = time.monotonic() - started
        self.assertEqual((reply["ok"], reply["workers"], reply["failed"]), (True, 3, []))
        self.assertEqual(len(reply["seconds"]), 3)
        self.assertLess(took, 2.5)  # three 1 s imports side by side
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

        with patch.dict(os.environ, {lean_session.ENV: "/x"}), patch.object(lean_session, "request", fake), \
                patch.object(engine, "_fingerprint", return_value={"code": "x"}):
            engine.run_lean({"name": "T", "file_path": "A.lean"}, Path("/p"), "abcdef", prefix_end=3, lane="background")
        self.assertEqual((sent["lane"], sent["header_end"], sent["timeout"]), ("background", 3, 180))
        self.assertEqual(engine.last_lean_run()["header_seconds"], 2.0)


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

    def test_an_idle_background_worker_is_closed_after_the_idle_limit(self):
        session = self.session(limit=8)
        self.background(session, self.other("v2"))
        entry = session.entries[str(self.dir / "v2")]
        with patch.object(lean_session, "BACKGROUND_IDLE_S", 0.3):
            session.reap_idle()
            self.assertEqual(len(entry.lane_slots("background")), 1)  # not idle long enough yet
            time.sleep(0.4)
            session.reap_idle()
        self.assertEqual(entry.lane_slots("background"), [])
        for _ in range(100):
            if self.events("didClose"):
                break
            time.sleep(0.02)
        self.assertEqual(len(self.events("didClose")), 1)
        again = self.background(session, str(self.dir / "v2"))
        self.assertTrue(again["ok"] and again["new_worker"])

    def test_warm_on_the_background_lane_opens_only_the_background_worker(self):
        session = self.session(limit=8)
        reply = session.warm({**self.request(), "project": self.other("v2"), "slots": 4, "timeout": 30,
                              "lane": "background"})
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
        thread = threading.Thread(target=lambda: outcome.update(first=self.background(session, project, "-- PROOF 1.5\n")))
        thread.start()
        time.sleep(0.4)
        started = time.monotonic()
        second = self.background(session, project)
        thread.join()
        self.assertTrue(outcome["first"]["ok"] and second["ok"], (outcome, second))
        self.assertGreater(time.monotonic() - started, 0.8)  # it queued behind the first instead of failing

    def test_background_never_evicts_a_model_worker_even_with_no_machine_room(self):
        first = self.session("a", limit=2)  # share 2: model 1, background 1
        self.assertEqual(first.warm({**self.request(), "slots": 4, "timeout": 30})["workers"], 1)
        other = self.other("v2")
        reply = self.background(first, other)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.events("didClose"), [])
        model = first.entries[str(self.dir / "proj")]
        self.assertEqual([s.text is not None for s in model.lane_slots("model")], [True])

    def test_background_is_guaranteed_even_when_model_workers_hold_every_machine_token(self):
        session = self.session(limit=2)
        self.assertEqual(session.warm({**self.request(), "slots": 4, "timeout": 30})["workers"], 1)
        hog = lean_session.WorkerBudget(self.dir / "tokens", 2)
        taken = [hog.acquire(), hog.acquire()]  # no model token left on the machine
        self.assertFalse(hog.available())
        reply = self.background(session, self.other("v2"))
        self.assertTrue(reply["ok"], reply)

    def test_model_requests_do_not_evict_for_background_but_may_for_another_model_request(self):
        session = self.session(limit=2)  # model 1
        self.assertEqual(session.warm({**self.request(), "slots": 1, "timeout": 30})["workers"], 1)
        reply = session.check({**self.request("-- PROOF 0\n", timeout=10), "project": self.other("v2")})
        self.assertTrue(reply["ok"], reply)  # a model request on another toolchain evicts the idle model worker
        self.assertEqual(len(self.events("didClose")), 1)
        self.assertEqual(len(session.entries[str(self.dir / "v2")].lane_slots("model")), 1)



class QueueTests(Base):
    def test_waiting_for_a_busy_worker_longer_than_the_check_timeout_still_succeeds(self):
        session = self.session(max_slots=1)
        outcome = {}
        thread = threading.Thread(target=lambda: outcome.update(
            first=session.check(self.request("-- PROOF 1.5\n", timeout=10))))
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
        for thread in [first] + threads:
            thread.join()
        self.assertEqual(order, ["a", "b", "c"])

    def test_run_lean_socket_timeout_covers_queue_open_and_check(self):
        seen = {}

        def fake(payload, timeout, path=None):
            seen["wait"] = timeout
            return {"ok": True, "returncode": 0, "output": ""}

        with patch.dict(os.environ, {lean_session.ENV: "/x"}), patch.object(lean_session, "request", fake), \
                patch.object(engine, "_fingerprint", return_value={"code": "x"}):
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
        raw = ":".join(["/w/proj/.lake/packages/mathlib/.lake/build/lib/lean", "/tc/lib/lean",
                        "/w/proj/.lake/build/lib/lean", "/tc/lib/lean"]) + "\n"
        command, calls = self.run_command(raw)
        self.assertEqual(calls, [["lake", "env", "printenv", "LEAN_PATH"]])
        expected = ":".join(["/w/proj/.lake/build/lib/lean", "/w/proj/.lake/packages/mathlib/.lake/build/lib/lean",
                             "/tc/lib/lean"])
        self.assertEqual(command, ["lake", "env", "env", f"LAKE={lean_session.NO_LAKE}", f"LEAN_PATH={expected}",
                                   "lean", "--server"])

    def test_the_path_is_computed_once_per_project(self):
        _, calls = self.run_command("/a:/w/proj/.lake/build/lib/lean\n")
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

    def test_two_sessions_split_the_machine_budget_evenly(self):
        first = self.session("a", limit=8)
        self.assertEqual(first.budget.share(), (8, 1))
        second = self.session("b", limit=8)
        self.assertEqual(first.budget.share(), (4, 2))
        a, b = self.warm(first, 9), self.warm(second, 9)
        self.assertEqual((a["allowed"], a["workers"], b["allowed"], b["workers"]), (3, 3, 3, 3))
        self.assertEqual(b["failed"], [])

    def test_three_sessions_get_a_third_and_a_share_is_never_below_two(self):
        sessions = [self.session(name, limit=8) for name in "abc"]
        self.assertEqual(sessions[0].budget.share(), (2, 3))  # 8 // 3
        self.assertEqual(self.warm(sessions[0], 9)["allowed"], 1)
        many = [self.session(f"m{i}", limit=8) for i in range(5)]
        self.assertEqual(many[0].budget.share(), (2, 8))  # 8 // 8 = 1, floored at 2

    def test_a_warm_op_gets_the_share_minus_the_background_reserve(self):
        solo = self.session("solo", limit=4)
        reply = self.warm(solo, 9)
        self.assertEqual((reply["allowed"], reply["workers"]), (3, 3))
        self.assertEqual(len(self.events("didOpen")), 3)

    def test_a_dying_session_frees_its_tokens_and_registration(self):
        first, second = self.session("a", limit=8), self.session("b", limit=8)
        self.assertEqual(self.warm(second, 9)["allowed"], 3)
        self.assertEqual(self.warm(first, 9)["workers"], 3)
        first.shutdown()
        self.assertEqual(second.budget.share(), (8, 1))
        self.assertEqual(self.warm(second, 9)["allowed"], 4)  # capped by MAX_SLOTS, not by the share
        self.assertEqual(lean_session.WorkerBudget(self.dir / "tokens", 8).live_sessions(), 1)

    def test_a_killed_process_drops_its_registration(self):
        import subprocess
        code = ("import sys; from pathlib import Path; from arena import lean_session as l; "
                "t = l.WorkerBudget(Path(sys.argv[1]), 8).register(); print('held' if t else 'no', flush=True); "
                "sys.stdin.read()")
        holder = subprocess.Popen([sys.executable, "-c", code, str(self.dir / "tokens")], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, cwd=lean_session.ROOT)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        mine = self.session("a", limit=8)
        self.assertEqual(mine.budget.share(), (4, 2))
        holder.kill()
        holder.wait()
        self.assertEqual(mine.budget.share(), (8, 1))

    def test_a_shrinking_share_keeps_warm_workers_but_opens_no_more(self):
        first = self.session("a", limit=8)
        self.assertEqual(self.warm(first, 4)["workers"], 4)
        second = self.session("b", limit=8)  # share drops to 4: model 3, first holds 4
        reply = self.warm(first, 4)
        self.assertEqual((reply["allowed"], reply["workers"]), (3, 4))
        self.assertEqual(self.events("didClose"), [])
        entry = next(iter(first.entries.values()))
        self.assertEqual(len(entry.lane_slots("model")), 4)

    def test_tokens_free_themselves_when_the_holder_exits(self):
        budget = lean_session.WorkerBudget(self.dir / "tok", 1)
        code = ("import sys; from pathlib import Path; from arena import lean_session as l; "
                "t = l.WorkerBudget(Path(sys.argv[1]), 1).acquire(); print('held' if t else 'no', flush=True); "
                "sys.stdin.read()")
        import subprocess
        holder = subprocess.Popen([sys.executable, "-c", code, str(self.dir / "tok")], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, cwd=lean_session.ROOT)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        self.assertFalse(budget.available())
        holder.kill()
        holder.wait()
        self.assertTrue(budget.available())


class ColdPathTests(unittest.TestCase):
    def test_the_projects_own_build_folder_comes_first(self):
        project = Path("/w/proj")
        path = ":".join(["/w/proj/.lake/packages/a/.lake/build/lib/lean", "/w/proj/.lake/packages/mathlib/.lake/build/lib/lean",
                         "/w/proj/.lake/build/lib/lean", "/tc/lib/lean"])
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

        with patch.dict(os.environ, {"ARENA_LEAN_TIMEOUT": "77"}), patch.object(engine, "candidate_file", return_value=built), \
                patch.object(engine, "run_lean", fake):
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
        with patch.object(engine, "_lean_command", return_value=("/tc/bin/lean", {"LEAN_PATH": "/x"})), \
                patch.object(engine.subprocess, "Popen", popen):
            engine._run_cold(row, Path("/p"), "t", 5)
        self.assertEqual(calls[0][0][0], "/tc/bin/lean")
        self.assertEqual(calls[0][1]["LEAN_PATH"], "/x")
        with patch.object(engine, "_lean_command", return_value=None), patch.object(engine.subprocess, "Popen", popen):
            engine._run_cold(row, Path("/p"), "t", 5)
        self.assertEqual(calls[1][0][:3], ["lake", "env", "lean"])


if __name__ == "__main__":
    unittest.main()
