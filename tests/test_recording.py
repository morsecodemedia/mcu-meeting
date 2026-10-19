import hashlib
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

from session import manager
from session.recording import CaptureFailed, record


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "sessions"
        self.binary = Path(self.tmp.name) / "fake-capture"
        self.binary.write_text("#!/bin/sh\nexit 0\n")
        self.binary.chmod(0o700)

    def tearDown(self):
        self.tmp.cleanup()

    def test_success_and_checksum(self):
        def runner(argv, **kwargs):
            path = Path(argv[argv.index("--output") + 1])
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(b"\x01\x00" * 200)
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        data = record(self.root, "com.google.Chrome", self.binary, runner=runner)
        self.assertEqual(data["capture"]["state"], "completed")
        self.assertEqual(data["processing"]["transcription"]["state"], "pending")
        item = data["artifacts"][0]
        self.assertEqual(item["path"], "audio/application.wav")
        self.assertEqual(item["sha256"], hashlib.sha256((self.root / data["session_id"] / item["path"]).read_bytes()).hexdigest())
        from jsonschema import Draft202012Validator, FormatChecker
        import json
        schema = json.loads((Path(__file__).resolve().parents[1] / "contracts/session.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)

    def test_nonzero_exit_fails(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=7, stderr="test failure", stdout="")
        with self.assertRaises(CaptureFailed) as caught:
            record(self.root, "us.zoom.xos", self.binary, runner=runner)
        data = manager.load(self.root, caught.exception.session_id)
        self.assertEqual(data["capture"]["state"], "failed")
        self.assertEqual(data["artifacts"], [])

    def test_invalid_wav_fails(self):
        def runner(argv, **kwargs):
            Path(argv[-1]).write_bytes(b"not a wav")
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        with self.assertRaises(CaptureFailed) as caught:
            record(self.root, "us.zoom.xos", self.binary, runner=runner)
        self.assertEqual(manager.load(self.root, caught.exception.session_id)["capture"]["state"], "failed")

    def test_missing_binary_creates_no_session(self):
        with self.assertRaises(ValueError):
            record(self.root, "us.zoom.xos", self.root / "missing")
        self.assertFalse(self.root.exists())

    def test_interrupted_recording_is_not_completed(self):
        def runner(*args, **kwargs):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            record(self.root, "us.zoom.xos", self.binary, runner=runner)
        manifests = list(self.root.glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        import json
        self.assertEqual(json.loads(manifests[0].read_text())["capture"]["state"], "interrupted")
