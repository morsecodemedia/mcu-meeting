import hashlib
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from processing.chunk_coordinator import execute_chunk
from processing.chunk_discovery import discover_checkpoints
from processing.chunk_planning import plan_chunks
from session import manager


class ChunkCoordinatorTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.sid = manager.create(
            self.root, "com.example.coordinator"
        )["session_id"]

        self.folder = self.root / self.sid
        self.audio = self.folder / "audio/application.wav"
        self.model = self.root / "model.bin"

        with wave.open(str(self.audio), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(48000)
            stream.writeframes(b"\x00\x00" * 48000)

        self.model.write_bytes(b"synthetic-model")

        manifest = manager.load(self.root, self.sid)
        manifest["artifacts"].append({
            "kind": "application_audio",
            "path": "audio/application.wav",
            "sha256": hashlib.sha256(
                self.audio.read_bytes()
            ).hexdigest(),
        })
        manager._write_atomic(
            self.folder / "manifest.json", manifest
        )

        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

        self.chunk = plan_chunks(
            1, "application_audio",
            chunk_seconds=1,
            overlap_seconds=0,
        )[0]

    def tearDown(self):
        self.tmp.cleanup()

    def fake_extract(self, source, output, chunk, **kwargs):
        with wave.open(str(output), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\x00\x00" * 16000)

        return {
            "source_sha256": hashlib.sha256(
                Path(source).read_bytes()
            ).hexdigest(),
            "output_sha256": hashlib.sha256(
                Path(output).read_bytes()
            ).hexdigest(),
        }

    def fake_whisper(self, audio, model, output, **kwargs):
        Path(output).write_text(
            '{"model":{"type":"small"},'
            '"params":{"language":"en"},'
            '"transcription":[{"offsets":{"from":0,"to":1000},'
            '"text":"synthetic speech"}]}'
        )

        return {
            "version": "1.9.5",
            "model_sha256": hashlib.sha256(
                Path(model).read_bytes()
            ).hexdigest(),
            "input_sha256": hashlib.sha256(
                Path(audio).read_bytes()
            ).hexdigest(),
            "output_sha256": hashlib.sha256(
                Path(output).read_bytes()
            ).hexdigest(),
            "segments": 1,
        }

    def execute_test_chunk(self):
        with (
            patch(
                "processing.chunk_coordinator._ffmpeg_version",
                return_value="9.0.1",
            ),
            patch(
                "processing.chunk_coordinator.whisper_version",
                return_value="1.9.5",
            ),
            patch(
                "processing.chunk_coordinator.extract_chunk",
                side_effect=self.fake_extract,
            ),
            patch(
                "processing.chunk_coordinator.run_whisper",
                side_effect=self.fake_whisper,
            ),
        ):
            return execute_chunk(
                self.root, self.sid, self.chunk, self.model
            )

    def test_successful_execution(self):
        result = self.execute_test_chunk()

        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["segments"], 1)

        report = discover_checkpoints(self.root, self.sid)
        self.assertEqual(
            report["checkpoints"][0]["classification"],
            "verified_complete",
        )

    def test_existing_checkpoint_refused(self):
        self.execute_test_chunk()

        with self.assertRaises(FileExistsError):
            self.execute_test_chunk()

    def test_source_checksum_mismatch(self):
        self.audio.write_bytes(b"corrupted")

        with self.assertRaises(Exception):
            self.execute_test_chunk()

        report = discover_checkpoints(self.root, self.sid)
        self.assertEqual(report["checkpoints"], [])

    def test_duplicate_source_artifact(self):
        manifest = manager.load(self.root, self.sid)
        manifest["artifacts"].append(
            dict(manifest["artifacts"][0])
        )
        manager._write_atomic(
            self.folder / "manifest.json", manifest
        )

        with self.assertRaises(ValueError):
            self.execute_test_chunk()

    def test_whisper_failure(self):
        with (
            patch(
                "processing.chunk_coordinator._ffmpeg_version",
                return_value="9.0.1",
            ),
            patch(
                "processing.chunk_coordinator.whisper_version",
                return_value="1.9.5",
            ),
            patch(
                "processing.chunk_coordinator.extract_chunk",
                side_effect=self.fake_extract,
            ),
            patch(
                "processing.chunk_coordinator.run_whisper",
                side_effect=RuntimeError("synthetic Whisper failure"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                execute_chunk(
                    self.root, self.sid, self.chunk, self.model
                )

        report = discover_checkpoints(self.root, self.sid)
        self.assertEqual(
            report["checkpoints"][0]["classification"],
            "manual_intervention",
        )

    def test_capture_state_unchanged(self):
        before = manager.load(self.root, self.sid)["capture"]

        self.execute_test_chunk()

        after = manager.load(self.root, self.sid)["capture"]
        self.assertEqual(before, after)


    def test_normalization_failure_preserves_whisper(self):
        def failing_normalize(*args, **kwargs):
            raise RuntimeError("synthetic normalization failure")

        with patch(
            "processing.chunk_coordinator.normalize_file",
            side_effect=failing_normalize,
        ):
            with self.assertRaises(RuntimeError):
                self.execute_test_chunk()

        report = discover_checkpoints(self.root, self.sid)
        record = report["checkpoints"][0]

        self.assertEqual(
            record["classification"],
            "manual_intervention",
        )

        directory = (
            self.folder
            / "processing"
            / "transcription"
            / "application_audio"
            / "000000"
            / record["fingerprint"]
        )

        self.assertTrue((directory / "whisper.json").is_file())
        self.assertFalse((directory / "normalized.json").exists())

    def test_whisper_version_mismatch(self):
        original = self.fake_whisper

        def mismatched(*args, **kwargs):
            result = original(*args, **kwargs)
            result["version"] = "1.9.6"
            return result

        with patch.object(self, "fake_whisper", side_effect=mismatched):
            with self.assertRaises(ValueError):
                self.execute_test_chunk()

        report = discover_checkpoints(self.root, self.sid)
        self.assertEqual(
            report["checkpoints"][0]["classification"],
            "manual_intervention",
        )

    def test_final_verification_failure(self):
        with patch(
            "processing.checkpoint_store.CheckpointStore.verify",
            side_effect=ValueError("synthetic integrity failure"),
        ):
            with self.assertRaises(ValueError):
                self.execute_test_chunk()

        report = discover_checkpoints(self.root, self.sid)
        record = report["checkpoints"][0]

        # The checkpoint was already completed before verification.
        # Recovery must inspect its actual persisted state.
        self.assertEqual(record["state"], "completed")
        self.assertEqual(
            record["classification"],
            "verified_complete",
        )


if __name__ == "__main__":
    unittest.main()
