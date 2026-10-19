import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from session import manager


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "sessions"

    def tearDown(self):
        self.temp.cleanup()

    def test_create_and_schema(self):
        from jsonschema import Draft202012Validator, FormatChecker
        a = manager.create(self.root, "us.zoom.xos")
        b = manager.create(self.root, "us.zoom.xos")
        self.assertNotEqual(a["session_id"], b["session_id"])
        uuid.UUID(a["session_id"])
        schema = json.loads((Path(__file__).resolve().parents[1] / "contracts/session.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(a)
        self.assertTrue((self.root / a["session_id"] / "audio").is_dir())
        self.assertEqual(a["processing"]["transcription"]["state"], "pending")

    def test_transitions_and_recovery(self):
        a = manager.create(self.root, "com.google.Chrome")
        sid = a["session_id"]
        with self.assertRaises(ValueError):
            manager.transition(self.root, sid, "completed")
        manager.transition(self.root, sid, "recording")
        self.assertEqual(len(manager.recovery_candidates(self.root)), 1)
        manager.transition(self.root, sid, "interrupted")
        self.assertEqual(manager.recovery_candidates(self.root), [])
        with self.assertRaises(ValueError):
            manager.transition(self.root, sid, "completed")

    def test_atomic_replace_failure_keeps_previous_manifest(self):
        a = manager.create(self.root, "us.zoom.xos")
        sid = a["session_id"]
        path = self.root / sid / "manifest.json"
        before = path.read_bytes()
        with patch("session.manager.os.replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                manager.transition(self.root, sid, "recording")
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(path.parent.glob(".manifest-*.tmp")))

    def test_invalid_uuid_and_empty_bundle(self):
        with self.assertRaises(ValueError):
            manager.create(self.root, " ")
        with self.assertRaises(ValueError):
            manager.load(self.root, "../outside")


if __name__ == "__main__":
    unittest.main()
