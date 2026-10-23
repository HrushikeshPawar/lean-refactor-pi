import errno
import os
import select
import tempfile
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from arena import orchestration, run_control


class DirectoryWatchTests(TestCase):
    def test_lock_file_events_do_not_wake_the_waiter(self):
        def event(name):
            name = name + b"\0"
            return run_control._IN_EVENT.pack(1, run_control._IN_CLOSE_WRITE, 0, len(name)) + name

        watch = run_control.DirectoryWatch.__new__(run_control.DirectoryWatch)
        watch.available = True
        poller = Mock()
        poller.poll.side_effect = [[(10, select.POLLIN)], [(10, select.POLLIN)], [(11, select.POLLIN)]]
        with (
            patch.object(run_control.select, "poll", return_value=poller),
            patch.object(run_control.os, "read", side_effect=[event(b"control.lock"), event(b"ledger.jsonl")]),
            patch.object(run_control, "_notify_waiters") as notify,
        ):
            watch._read(10, 11)
        # One ledger notification and one terminal watch notification.
        self.assertEqual(notify.call_count, 2)

    def test_watch_failure_wakes_and_close_releases_resources(self):
        invalidated = run_control._IN_EVENT.pack(1, 0x00008000, 0, 0)
        for readiness, chunk in (
            ([(10, select.POLLIN)], invalidated),
            ([(10, select.POLLERR)], b""),
            ([(10, select.POLLIN)], OSError(errno.EIO, "read failed")),
            (OSError(errno.EIO, "poll failed"), b""),
        ):
            with self.subTest(readiness=readiness, chunk=chunk):
                watch = run_control.DirectoryWatch.__new__(run_control.DirectoryWatch)
                watch.available = True
                poller = Mock()
                if isinstance(readiness, Exception):
                    poller.poll.side_effect = readiness
                else:
                    poller.poll.return_value = readiness
                read = {"side_effect": chunk} if isinstance(chunk, Exception) else {"return_value": chunk}
                with (
                    patch.object(run_control.select, "poll", return_value=poller),
                    patch.object(run_control.os, "read", **read),
                    patch.object(run_control, "_notify_waiters") as notify,
                ):
                    watch._read(10, 11)
                self.assertFalse(watch.available)
                notify.assert_called_once_with()

        with tempfile.TemporaryDirectory() as tmp:
            with run_control.watch_directory(Path(tmp)) as watch:
                self.assertTrue(watch.available)
                descriptors = list(watch._fds)
                reader = watch._thread
            self.assertFalse(reader.is_alive())
            self.assertFalse(watch.available)
            self.assertEqual(watch._fds, [])
            watch.close()
            for fd in descriptors:
                with self.assertRaises(OSError):
                    os.fstat(fd)

    def test_cancellation_and_invalidation_release_a_blocked_wait(self):
        for cancelled in (True, False):
            with self.subTest(cancelled=cancelled), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                lease = SimpleNamespace(available=True)
                cancellation = threading.Event()
                registered = threading.Event()
                replies = []
                real_wait = orchestration._interest.wait

                def wait(*args, registered=registered, real_wait=real_wait, **kwargs):
                    registered.set()
                    return real_wait(*args, **kwargs)

                with (
                    patch.object(run_control, "watch_directory", return_value=nullcontext(lease)),
                    patch.object(orchestration, "_has_producer", return_value=True),
                    patch.object(orchestration._interest, "wait", side_effect=wait),
                ):
                    thread = threading.Thread(
                        target=lambda replies=replies, directory=directory, cancellation=cancellation:
                            replies.append(orchestration.await_results(
                                directory, actor_id="sol", cancel_event=cancellation,
                            )),
                    )
                    thread.start()
                    try:
                        self.assertTrue(registered.wait(1))
                        if cancelled:
                            cancellation.set()
                        else:
                            lease.available = False
                        orchestration.wake_waiters()
                        thread.join(1)
                        self.assertFalse(thread.is_alive())
                    finally:
                        cancellation.set()
                        orchestration.wake_waiters()
                        thread.join(1)
                expected = "cancelled" if cancelled else "notification_unavailable"
                self.assertEqual(replies[0]["category"], expected)
                self.assertTrue(replies[0]["retryable"])
                self.assertFalse((directory / "control.jsonl").exists())
