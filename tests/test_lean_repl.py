"""REPL process-pool behavior at the injected process seam."""

import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from arena import lean_repl, lean_session


class FakeRepl:
    instances: ClassVar[list] = []

    def __init__(self, project, toolchain):
        self.project, self.toolchain = project, toolchain
        self.pgid = len(self.instances) + 100
        self.running = False
        self.commands = []
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self):
        self.running = True

    def alive(self):
        return self.running

    def run(self, cmd, env=None, timeout=180):
        self.commands.append((cmd, env))
        if cmd == "timeout":
            self.running = False
            raise lean_repl.ReplError("REPL command timed out")
        return {"env": 1, "messages": []}

    def pickle(self, _env, path, _timeout=180):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"pickle")
        return {}

    def unpickle(self, _path, _timeout=180):
        return 1

    def stop(self):
        self.running, self.stopped = False, True


class ReplPoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "proj").mkdir()
        FakeRepl.instances = []
        self.cache = self.root / "cache"
        self.patch_repl_dir = patch.object(lean_repl, "repl_dir", lambda _toolchain: self.cache)
        self.patch_repl_dir.start()
        self.addCleanup(self.patch_repl_dir.stop)
        self.patch_pickle_dir = patch.object(lean_repl, "pickle_dir", lambda _toolchain: self.cache / "pickles")
        self.patch_pickle_dir.start()
        self.addCleanup(self.patch_pickle_dir.stop)
        self.pool = lean_repl.ReplPool(FakeRepl)
        self.project = self.root / "proj"

    def check(self, header, body="proof"):
        return self.pool.check(self.project, "v4.30.0", header, body, "A.lean", 1)

    def test_one_import_serves_multiple_bodies(self):
        self.check("import X\n", "first")
        self.check("import X\n", "second")
        self.assertEqual([command for command, _ in FakeRepl.instances[0].commands], ["import X\n", "first", "second"])

    def test_sixth_header_evicts_oldest_idle_process(self):
        for index in range(5):
            self.check(f"import H{index}\n")
        oldest = FakeRepl.instances[0]
        self.check("import H5\n")
        self.assertTrue(oldest.stopped)
        self.assertEqual(len(self.pool.items), 5)

    def test_sixth_header_does_not_evict_a_busy_process(self):
        for index in range(5):
            self.check(f"import H{index}\n")
        first = next(iter(self.pool.items.values()))
        first.busy = True
        self.check("import H5\n")
        self.assertFalse(getattr(first.process, "stopped", False))
        self.assertEqual(len(self.pool.items), 5)

    def test_a_slow_header_import_does_not_hold_up_a_check_of_another_header(self):
        import threading

        importing, release = threading.Event(), threading.Event()

        class SlowImport(FakeRepl):
            def run(self, cmd, env=None, timeout=180):
                if cmd == "import Slow\n":
                    importing.set()
                    release.wait(5)
                return super().run(cmd, env, timeout)

        pool = lean_repl.ReplPool(SlowImport)
        pool.check(self.project, "v4.30.0", "import Fast\n", "warm", "A.lean", 1)
        slow = threading.Thread(target=pool.check, args=(self.project, "v4.30.0", "import Slow\n", "b", "A.lean", 1))
        slow.start()
        self.assertTrue(importing.wait(5))
        done = threading.Event()
        threading.Thread(
            target=lambda: (pool.check(self.project, "v4.30.0", "import Fast\n", "c", "A.lean", 1), done.set())
        ).start()
        self.assertTrue(done.wait(2), "a check of a loaded header waited for another header's import")
        release.set()
        slow.join(5)

    def test_a_process_shared_by_two_checks_stays_busy_until_both_end(self):
        self.check("import X\n")
        (item,) = self.pool.items.values()
        item.busy += 1  # another check is still running on it
        self.check("import X\n", "second")
        self.assertEqual(item.busy, 1)
        for index in range(5):
            self.check(f"import H{index}\n")
        self.assertFalse(item.process.stopped, "the process in use was evicted")

    def test_over_limit_process_is_dropped_after_reply(self):
        pss = [5.0]
        pool = lean_repl.ReplPool(FakeRepl, pss_fn=lambda _pid: pss[0])
        pool.check(self.project, "v4.30.0", "import X\n", "one", "A.lean", 1)
        self.assertEqual(len(pool.items), 0)
        pool.check(self.project, "v4.30.0", "import X\n", "two", "A.lean", 1)
        self.assertEqual(len(FakeRepl.instances), 2)

    def test_timed_out_process_is_dropped_and_next_check_starts_fresh(self):
        with self.assertRaises(lean_repl.ReplError):
            self.check("import X\n", "timeout")
        self.assertTrue(FakeRepl.instances[0].stopped)
        self.check("import X\n", "again")
        self.assertEqual(len(FakeRepl.instances), 2)

    def test_pickle_that_changes_diagnostics_is_never_loaded_again(self):
        class MismatchedPickle(FakeRepl):
            unpickle_count = 0

            def run(self, cmd, env=None, timeout=180):
                self.commands.append((cmd, env))
                messages = [{"severity": "error", "data": "changed"}] if env == 2 else []
                return {"env": 1, "messages": messages}

            def unpickle(self, _path, _timeout=180):
                self.__class__.unpickle_count += 1
                return 2

        pool = lean_repl.ReplPool(MismatchedPickle)
        header = "import X\n"
        pool.check(self.project, "v4.30.0", header, "first", "A.lean", 1)
        pool.close_project(self.project)
        drafts = ("reference", "failing")
        pool.check(self.project, "v4.30.0", header, "second", "A.lean", 1, verification=drafts)
        bad = self.cache / "pickles" / f"{pool._hash(header)}.nopickle"
        self.assertTrue(bad.is_file())
        pool.close_project(self.project)
        pool.check(self.project, "v4.30.0", header, "third", "A.lean", 1, verification=drafts)
        self.assertEqual(MismatchedPickle.unpickle_count, 1)
        pool.close()

    def test_verified_pickle_is_reused_after_process_restart(self):
        class CountingPickle(FakeRepl):
            unpickle_count = 0

            def unpickle(self, _path, _timeout=180):
                self.__class__.unpickle_count += 1
                return 1

        pool = lean_repl.ReplPool(CountingPickle)
        header = "import X\n"
        drafts = ("reference", "failing")
        pool.check(self.project, "v4.30.0", header, "first", "A.lean", 1)
        pool.close_project(self.project)
        pool.check(self.project, "v4.30.0", header, "second", "A.lean", 1, verification=drafts)
        self.assertTrue((self.cache / "pickles" / f"{pool._hash(header)}.verified").is_file())
        pool.close_project(self.project)
        pool.check(self.project, "v4.30.0", header, "third", "A.lean", 1, verification=drafts)
        self.assertEqual(CountingPickle.unpickle_count, 3)
        self.assertNotIn((header, None), CountingPickle.instances[-1].commands)
        pool.close()

    def test_release_of_last_lease_and_hold_stops_project_repl(self):
        self.check("import X\n")
        name = str(self.project.resolve())
        with session_context(self.root) as session:
            session.leases["run"] = {"pid": 1, "primary": name, "others": []}
            session.repl = self.pool
            session.release("run")
        self.assertTrue(FakeRepl.instances[0].stopped)
        self.check("import X\n")
        with session_context(self.root) as session:
            session.holds["owner"] = {"pid": 1, "projects": [name]}
            session.repl = self.pool
            session.unhold("owner")
        self.assertTrue(FakeRepl.instances[-1].stopped)

    def test_batch_timeout_falls_back_to_background_once(self):
        session = lean_session.Session(self.root / "service")
        self.addCleanup(session.shutdown)
        session.repl = lean_repl.ReplPool(FakeRepl)
        metadata = self.cache / "build.json"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text('{"ok": true}')
        request = {
            "protocol": lean_session.PROTOCOL,
            "project": str(self.project),
            "fingerprint": {"code": lean_session.code_sha()},
            "lane": "batch",
            "toolchain": "v4.30.0",
            "header_end": len("import X\n"),
            "text": "import X\ntimeout",
            "display": "A.lean",
        }
        with (
            patch.object(lean_repl, "REPL_ENABLED", True),
            patch.object(session, "check", return_value={"ok": True, "lane": "background"}) as fallback,
        ):
            reply = session._batch_check(request, self.project, 1)
        fallback.assert_called_once()
        self.assertEqual(reply["fallback"], "repl")
        self.assertEqual((reply["engine"], reply["lane"]), ("lsp", "background"))
        request["text"] = "import X\nproof"
        with patch.object(lean_repl, "REPL_ENABLED", True):
            reply = session._batch_check(request, self.project, 1)
        self.assertEqual((reply["engine"], reply["lane"]), ("repl", "batch"))
        self.assertEqual(len(FakeRepl.instances), 2)


class RenderReplTests(unittest.TestCase):
    def test_repl_messages_match_lsp_renderer(self):
        header = "import X\nopen Nat\n"
        messages = [
            {"severity": "error", "pos": {"line": 1, "column": 2}, "data": "unknown"},
            {"severity": "warning", "pos": {"line": 2, "column": 0}, "data": "unused"},
            {"severity": "info", "data": "info"},
        ]
        diagnostics = [
            {"severity": 1, "range": {"start": {"line": 2, "character": 2}}, "message": "unknown"},
            {"severity": 2, "range": {"start": {"line": 3, "character": 0}}, "message": "unused"},
            {"severity": 3, "range": {"start": {"line": 0, "character": 0}}, "message": "info"},
        ]
        self.assertEqual(
            lean_repl.render_repl(messages, header, "A.lean"),
            lean_session.render(diagnostics, header + "  x\nwarn\n", "A.lean"),
        )


def session_context(directory):
    session = lean_session.Session(directory)

    class Context:
        def __enter__(self):
            return session

        def __exit__(self, *_args):
            session.shutdown()

    return Context()
