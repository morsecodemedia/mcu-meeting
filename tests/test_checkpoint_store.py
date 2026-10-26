import multiprocessing
import tempfile
import unittest
from pathlib import Path

from processing.checkpoint_store import checkpoint_store
from session import manager

FINGERPRINT = "a" * 64
CHUNK_ID = "application_audio:000000"


def contender(root, sid, queue):
    try:
        with checkpoint_store(Path(root), sid):
            queue.put("acquired")
    except manager.ProcessingLockBusy:
        queue.put("busy")


class CheckpointStoreTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sid = manager.create(
            self.root, "com.example.checkpoint-test"
        )["session_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def complete_capture(self):
        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

    def test_requires_completed_capture(self):
        with self.assertRaises(ValueError):
            with checkpoint_store(self.root, self.sid):
                pass

    def test_create_and_transition(self):
        self.complete_capture()

        with checkpoint_store(self.root, self.sid) as store:
            store.create(FINGERPRINT, CHUNK_ID)
            result = store.transition(
                FINGERPRINT, CHUNK_ID, "running"
            )
            self.assertEqual(result["attempts"], 1)

    def test_closed_store_rejects_operations(self):
        self.complete_capture()

        with checkpoint_store(self.root, self.sid) as store:
            store.create(FINGERPRINT, CHUNK_ID)

        with self.assertRaises(RuntimeError):
            store.load(FINGERPRINT, CHUNK_ID)

    def test_capture_state_unchanged(self):
        self.complete_capture()

        before = manager.load(self.root, self.sid)["capture"]

        with checkpoint_store(self.root, self.sid) as store:
            store.create(FINGERPRINT, CHUNK_ID)
            store.transition(FINGERPRINT, CHUNK_ID, "running")

        after = manager.load(self.root, self.sid)["capture"]
        self.assertEqual(before, after)

    def test_cross_process_contention(self):
        self.complete_capture()

        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()

        with checkpoint_store(self.root, self.sid):
            process = ctx.Process(
                target=contender,
                args=(str(self.root), self.sid, queue),
            )
            process.start()
            process.join(timeout=10)

            self.assertEqual(process.exitcode, 0)
            self.assertEqual(queue.get(timeout=2), "busy")

    def test_manifest_identity_mismatch(self):
        self.complete_capture()

        path = self.root / self.sid / "manifest.json"
        original = path.read_text()

        import json
        data = json.loads(original)
        data["session_id"] = "00000000-0000-4000-8000-000000000000"
        path.write_text(json.dumps(data))

        with self.assertRaises(ValueError):
            with checkpoint_store(self.root, self.sid):
                pass

    def test_session_directory_symlink_rejected(self):
        self.complete_capture()

        original = self.root / self.sid
        moved = self.root / "moved-session"
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)

        with self.assertRaises(ValueError):
            with checkpoint_store(self.root, self.sid):
                pass


if __name__ == "__main__":
    unittest.main()
