import tempfile
import unittest
from pathlib import Path

from session import manager


class ProcessingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.session = manager.create(self.root, "com.example.test")
        self.sid = self.session["session_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def complete_capture(self):
        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

    def test_requires_completed_capture(self):
        with self.assertRaises(ValueError):
            manager.transition_processing(
                self.root, self.sid, "transcription", "running"
            )

    def test_successful_processing(self):
        self.complete_capture()

        running = manager.transition_processing(
            self.root, self.sid, "transcription", "running"
        )
        self.assertEqual(
            running["processing"]["transcription"]["attempts"], 1
        )

        completed = manager.transition_processing(
            self.root, self.sid, "transcription", "completed"
        )
        self.assertEqual(
            completed["processing"]["transcription"]["state"],
            "completed",
        )
        self.assertEqual(completed["capture"]["state"], "completed")

    def test_retryable_failure(self):
        self.complete_capture()

        manager.transition_processing(
            self.root, self.sid, "transcription", "running"
        )
        manager.transition_processing(
            self.root, self.sid, "transcription", "failed",
            retryable=True, error="synthetic failure",
        )
        retried = manager.transition_processing(
            self.root, self.sid, "transcription", "running"
        )

        self.assertEqual(
            retried["processing"]["transcription"]["attempts"], 2
        )
        self.assertIsNone(
            retried["processing"]["transcription"]["error"]
        )

    def test_nonretryable_failure(self):
        self.complete_capture()

        manager.transition_processing(
            self.root, self.sid, "transcription", "running"
        )
        manager.transition_processing(
            self.root, self.sid, "transcription", "failed",
            retryable=False,
        )

        with self.assertRaises(ValueError):
            manager.transition_processing(
                self.root, self.sid, "transcription", "running"
            )

    def test_recovery_is_read_only(self):
        self.complete_capture()
        manager.transition_processing(
            self.root, self.sid, "transcription", "running"
        )

        before = (self.root / self.sid / "manifest.json").read_bytes()
        candidates = manager.processing_recovery_candidates(self.root)
        after = (self.root / self.sid / "manifest.json").read_bytes()

        self.assertEqual(before, after)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["stage"], "transcription")


if __name__ == "__main__":
    unittest.main()
