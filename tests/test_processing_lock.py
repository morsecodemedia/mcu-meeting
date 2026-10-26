import multiprocessing
import tempfile
import unittest
from pathlib import Path

from session import manager


def contender(root, sid, queue):
    try:
        with manager.processing_lock(Path(root), sid):
            queue.put("acquired")
    except manager.ProcessingLockBusy:
        queue.put("busy")


def manifest_contender(root, sid, queue):
    try:
        with manager.manifest_lock(Path(root), sid):
            queue.put("acquired")
    except manager.ManifestLockBusy:
        queue.put("busy")


class ProcessingLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sid = manager.create(
            self.root, "com.example.lock-test"
        )["session_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_lock_contention(self):
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()

        with manager.processing_lock(self.root, self.sid):
            process = ctx.Process(
                target=contender,
                args=(str(self.root), self.sid, queue),
            )
            process.start()
            process.join(timeout=10)

            self.assertEqual(process.exitcode, 0)
            self.assertEqual(queue.get(timeout=2), "busy")

    def test_lock_released(self):
        with manager.processing_lock(self.root, self.sid):
            pass

        with manager.processing_lock(self.root, self.sid):
            pass

    def test_transition_allowed_under_coordinator_lock(self):
        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

        with manager.processing_lock(self.root, self.sid):
            result = manager.transition_processing(
                self.root, self.sid, "transcription", "running"
            )

        self.assertEqual(
            result["processing"]["transcription"]["state"],
            "running",
        )

    def test_manifest_lock_contention(self):
        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

        with manager.manifest_lock(self.root, self.sid):
            with self.assertRaises(manager.ManifestLockBusy):
                manager.transition_processing(
                    self.root, self.sid, "transcription", "running"
                )

        self.assertEqual(
            manager.load(self.root, self.sid)["processing"]
            ["transcription"]["state"],
            "pending",
        )

    def test_both_lock_files_are_distinct(self):
        with manager.processing_lock(self.root, self.sid):
            with manager.manifest_lock(self.root, self.sid):
                self.assertTrue(
                    (self.root / self.sid / ".processing.lock").exists()
                )
                self.assertTrue(
                    (self.root / self.sid / ".manifest.lock").exists()
                )


    def test_cross_process_manifest_contention(self):
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()

        with manager.manifest_lock(self.root, self.sid):
            process = ctx.Process(
                target=manifest_contender,
                args=(str(self.root), self.sid, queue),
            )
            process.start()
            process.join(timeout=10)

            self.assertEqual(process.exitcode, 0)
            self.assertEqual(queue.get(timeout=2), "busy")


if __name__ == "__main__":
    unittest.main()
