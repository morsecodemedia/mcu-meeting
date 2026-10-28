import hashlib
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from processing.batch_runner import execute_batch
from session import manager


class BatchRunnerTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sid = manager.create(
            self.root, "com.example.batch"
        )["session_id"]
        self.folder = self.root / self.sid
        self.model = self.root / "model.bin"
        self.model.write_bytes(b"synthetic-model")

        manifest = manager.load(self.root, self.sid)

        for source, filename, frames in (
            ("application_audio", "application.wav", 96000),
            ("microphone_audio", "microphone.wav", 144000),
        ):
            path = self.folder / "audio" / filename

            with wave.open(str(path), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(48000)
                stream.writeframes(b"\x00\x00" * frames)

            manifest["artifacts"].append({
                "kind": source,
                "path": f"audio/{filename}",
                "sha256": hashlib.sha256(
                    path.read_bytes()
                ).hexdigest(),
            })

        manager._write_atomic(
            self.folder / "manifest.json", manifest
        )
        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

    def tearDown(self):
        self.tmp.cleanup()

    def fake_execute(self, root, sid, chunk, model, **kwargs):
        return {
            "fingerprint": "a" * 64,
            "segments": 1,
        }

    def test_success(self):
        with patch(
            "processing.batch_runner.execute_chunk",
            side_effect=self.fake_execute,
        ):
            report = execute_batch(
                self.root, self.sid, self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

        self.assertEqual(report["state"], "completed")
        self.assertEqual(report["total_chunks"], 5)
        self.assertEqual(report["completed_chunks"], 5)

    def test_source_order(self):
        seen = []

        def capture(root, sid, chunk, model, **kwargs):
            seen.append(chunk["chunk_id"])
            return self.fake_execute(root, sid, chunk, model, **kwargs)

        with patch(
            "processing.batch_runner.execute_chunk",
            side_effect=capture,
        ):
            execute_batch(
                self.root, self.sid, self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

        self.assertEqual(seen, [
            "application_audio:000000",
            "application_audio:000001",
            "microphone_audio:000000",
            "microphone_audio:000001",
            "microphone_audio:000002",
        ])

    def test_stop_on_failure(self):
        calls = 0

        def failing(root, sid, chunk, model, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic failure")
            return self.fake_execute(root, sid, chunk, model, **kwargs)

        with patch(
            "processing.batch_runner.execute_chunk",
            side_effect=failing,
        ):
            report = execute_batch(
                self.root, self.sid, self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

        self.assertEqual(report["state"], "stopped")
        self.assertEqual(report["completed_chunks"], 1)
        self.assertEqual(
            [item["state"] for item in report["entries"]],
            [
                "completed",
                "failed",
                "not_attempted",
                "not_attempted",
                "not_attempted",
            ],
        )

    def test_capture_state_preserved(self):
        before = manager.load(self.root, self.sid)["capture"]

        with patch(
            "processing.batch_runner.execute_chunk",
            side_effect=self.fake_execute,
        ):
            execute_batch(
                self.root, self.sid, self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

        after = manager.load(self.root, self.sid)["capture"]
        self.assertEqual(before, after)

    def test_invalid_source_checksum(self):
        audio = self.folder / "audio/application.wav"

        # Preserve valid WAV structure while changing its contents.
        with audio.open("r+b") as stream:
            stream.seek(44)
            stream.write(b"\\x01\\x00")

        with self.assertRaisesRegex(
            ValueError, "Source WAV checksum mismatch"
        ):
            execute_batch(self.root, self.sid, self.model)

    def test_malformed_source_wav_rejected(self):
        audio = self.folder / "audio/application.wav"
        audio.write_bytes(b"corrupt")

        with self.assertRaises((EOFError, ValueError, wave.Error)):
            execute_batch(self.root, self.sid, self.model)

    def test_duplicate_source_artifact(self):
        manifest = manager.load(self.root, self.sid)
        manifest["artifacts"].append(
            dict(manifest["artifacts"][0])
        )
        manager._write_atomic(
            self.folder / "manifest.json", manifest
        )

        with self.assertRaises(ValueError):
            execute_batch(self.root, self.sid, self.model)


if __name__ == "__main__":
    unittest.main()
