"""Regression tests for pure processing-plan classification."""

import copy
from pathlib import Path
import unittest

from processing.chunk_checkpoint import (
    new_checkpoint,
    transition_checkpoint,
)
from processing.processing_plan import classify_planned_checkpoint


FINGERPRINT = "a" * 64
CHUNK_ID = "application_audio:000000"


class ProcessingPlanTests(unittest.TestCase):

    def classify(self, checkpoint, status="unknown"):
        return classify_planned_checkpoint(
            FINGERPRINT,
            CHUNK_ID,
            checkpoint,
            artifact_status=status,
        )

    def test_missing(self):
        result = self.classify(None)
        self.assertEqual(result["classification"], "missing")
        self.assertEqual(result["action"], "execute")

    def test_pending(self):
        result = self.classify(
            new_checkpoint(FINGERPRINT, CHUNK_ID)
        )
        self.assertEqual(
            result["classification"], "blocked_incomplete"
        )

    def test_running(self):
        checkpoint = transition_checkpoint(
            new_checkpoint(FINGERPRINT, CHUNK_ID),
            "running",
        )
        self.assertEqual(
            self.classify(checkpoint)["classification"],
            "blocked_incomplete",
        )

    def test_failed(self):
        checkpoint = transition_checkpoint(
            new_checkpoint(FINGERPRINT, CHUNK_ID),
            "running",
        )
        checkpoint = transition_checkpoint(
            checkpoint,
            "failed",
            retryable=True,
            error="synthetic failure",
        )
        self.assertEqual(
            self.classify(checkpoint)["classification"],
            "blocked_failed",
        )

    def test_completed_verified(self):
        checkpoint = transition_checkpoint(
            new_checkpoint(FINGERPRINT, CHUNK_ID),
            "running",
        )
        checkpoint = transition_checkpoint(
            checkpoint,
            "completed",
            artifacts=[
                {
                    "kind": "whisper_json",
                    "path": "whisper.json",
                    "sha256": "b" * 64,
                },
                {
                    "kind": "normalized_json",
                    "path": "normalized.json",
                    "sha256": "c" * 64,
                },
            ],
        )
        result = self.classify(checkpoint, "verified")
        self.assertEqual(result["classification"], "reusable")
        self.assertEqual(result["action"], "reuse")

    def test_completed_invalid(self):
        checkpoint = transition_checkpoint(
            new_checkpoint(FINGERPRINT, CHUNK_ID),
            "running",
        )
        checkpoint = transition_checkpoint(
            checkpoint,
            "completed",
            artifacts=[
                {
                    "kind": "whisper_json",
                    "path": "whisper.json",
                    "sha256": "b" * 64,
                },
                {
                    "kind": "normalized_json",
                    "path": "normalized.json",
                    "sha256": "c" * 64,
                },
            ],
        )
        self.assertEqual(
            self.classify(checkpoint, "invalid")["classification"],
            "blocked_integrity",
        )

    def test_identity_mismatch(self):
        checkpoint = new_checkpoint("b" * 64, CHUNK_ID)
        with self.assertRaises(ValueError):
            self.classify(checkpoint)

    def test_input_immutability(self):
        checkpoint = new_checkpoint(FINGERPRINT, CHUNK_ID)
        original = copy.deepcopy(checkpoint)
        self.classify(checkpoint)
        self.assertEqual(checkpoint, original)


class CheckpointDirectoryStatusTests(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_directory(self):
        from processing.processing_plan import (
            _checkpoint_directory_status,
        )
        result = _checkpoint_directory_status(
            self.root,
            "processing/transcription/application_audio/"
            "000000/" + "a" * 64 + "/checkpoint.json",
        )
        self.assertEqual(result, "missing")

    def test_existing_directory(self):
        from processing.processing_plan import (
            _checkpoint_directory_status,
        )
        directory = (
            self.root / "processing/transcription/"
            "application_audio/000000" / ("a" * 64)
        )
        directory.mkdir(parents=True)

        result = _checkpoint_directory_status(
            self.root,
            "processing/transcription/application_audio/"
            "000000/" + "a" * 64 + "/checkpoint.json",
        )
        self.assertEqual(result, "present")

    def test_symlinked_directory_rejected(self):
        from processing.processing_plan import (
            _checkpoint_directory_status,
        )
        target = self.root / "target"
        target.mkdir()
        (self.root / "processing").symlink_to(
            target, target_is_directory=True
        )

        result = _checkpoint_directory_status(
            self.root,
            "processing/transcription/application_audio/"
            "000000/" + "a" * 64 + "/checkpoint.json",
        )
        self.assertEqual(result, "invalid")

    def test_regular_file_in_directory_chain_rejected(self):
        from processing.processing_plan import (
            _checkpoint_directory_status,
        )
        (self.root / "processing").write_text("not a directory")

        result = _checkpoint_directory_status(
            self.root,
            "processing/transcription/application_audio/"
            "000000/" + "a" * 64 + "/checkpoint.json",
        )
        self.assertEqual(result, "invalid")


class FilesystemProcessingPlanTests(unittest.TestCase):

    def setUp(self):
        import hashlib
        import tempfile
        import wave

        from session import manager

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sid = manager.create(
            self.root, "com.example.processing-plan"
        )["session_id"]
        self.folder = self.root / self.sid

        self.model = self.root / "model.bin"
        self.model.write_bytes(b"synthetic-model")

        self.audio = self.folder / "audio/application.wav"

        with wave.open(str(self.audio), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(48000)
            stream.writeframes(b"\x00\x00" * 48000)

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

    def tearDown(self):
        self.tmp.cleanup()

    def test_verified_checkpoint_is_reusable(self):
        import hashlib
        import json

        from unittest.mock import patch

        from processing.checkpoint_store import checkpoint_store
        from processing.processing_plan import plan_session_processing

        versions = (
            patch(
                "processing.chunk_coordinator._ffmpeg_version",
                return_value="9.0.1",
            ),
            patch(
                "processing.whisper_runner.whisper_version",
                return_value="1.9.5",
            ),
        )

        with versions[0], versions[1]:
            initial = plan_session_processing(
                self.root,
                self.sid,
                self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

        entry = initial["entries"][0]
        fingerprint = entry["fingerprint"]
        chunk_id = entry["chunk_id"]

        self.assertEqual(entry["classification"], "missing")

        with checkpoint_store(self.root, self.sid) as store:
            store.create(fingerprint, chunk_id)
            store.transition(fingerprint, chunk_id, "running")

            directory = (
                self.folder
                / "processing/transcription/application_audio/000000"
                / fingerprint
            )

            whisper = directory / "whisper.json"
            normalized = directory / "normalized.json"

            whisper.write_text(json.dumps({
                "transcription": [],
            }))

            normalized.write_text(json.dumps({
                "schema_version": 1,
                "chunk_id": chunk_id,
                "source": "application_audio",
                "segments": [],
            }))

            artifacts = [
                {
                    "kind": kind,
                    "path": file.name,
                    "sha256": hashlib.sha256(
                        file.read_bytes()
                    ).hexdigest(),
                }
                for kind, file in (
                    ("whisper_json", whisper),
                    ("normalized_json", normalized),
                )
            ]

            store.transition(
                fingerprint,
                chunk_id,
                "completed",
                artifacts=artifacts,
            )

            self.assertTrue(store.verify(fingerprint, chunk_id))

        with (
            patch(
                "processing.chunk_coordinator._ffmpeg_version",
                return_value="9.0.1",
            ),
            patch(
                "processing.whisper_runner.whisper_version",
                return_value="1.9.5",
            ),
        ):
            result = plan_session_processing(
                self.root,
                self.sid,
                self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

        self.assertEqual(result["entries"][0]["fingerprint"], fingerprint)
        self.assertEqual(
            result["entries"][0]["classification"],
            "reusable",
        )
        self.assertEqual(result["entries"][0]["action"], "reuse")
        self.assertEqual(result["counts"]["reusable"], 1)

    def plan_with_versions(self):
        from unittest.mock import patch
        from processing.processing_plan import plan_session_processing

        with (
            patch(
                "processing.chunk_coordinator._ffmpeg_version",
                return_value="9.0.1",
            ),
            patch(
                "processing.whisper_runner.whisper_version",
                return_value="1.9.5",
            ),
        ):
            return plan_session_processing(
                self.root,
                self.sid,
                self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

    def test_existing_directory_without_checkpoint_is_blocked(self):
        initial = self.plan_with_versions()
        entry = initial["entries"][0]

        directory = (
            self.folder
            / "processing/transcription/application_audio/000000"
            / entry["fingerprint"]
        )
        directory.mkdir(parents=True)

        result = self.plan_with_versions()

        self.assertEqual(
            result["entries"][0]["classification"],
            "blocked_integrity",
        )

    def test_corrupted_completed_artifact_is_blocked(self):
        import hashlib
        import json
        from processing.checkpoint_store import checkpoint_store

        initial = self.plan_with_versions()
        entry = initial["entries"][0]
        fingerprint = entry["fingerprint"]
        chunk_id = entry["chunk_id"]

        with checkpoint_store(self.root, self.sid) as store:
            store.create(fingerprint, chunk_id)
            store.transition(fingerprint, chunk_id, "running")

            directory = (
                self.folder
                / "processing/transcription/application_audio/000000"
                / fingerprint
            )

            whisper = directory / "whisper.json"
            normalized = directory / "normalized.json"

            whisper.write_text(json.dumps({"transcription": []}))
            normalized.write_text(json.dumps({
                "schema_version": 1,
                "chunk_id": chunk_id,
                "source": "application_audio",
                "segments": [],
            }))

            artifacts = [
                {
                    "kind": kind,
                    "path": file.name,
                    "sha256": hashlib.sha256(
                        file.read_bytes()
                    ).hexdigest(),
                }
                for kind, file in (
                    ("whisper_json", whisper),
                    ("normalized_json", normalized),
                )
            ]

            store.transition(
                fingerprint,
                chunk_id,
                "completed",
                artifacts=artifacts,
            )

        normalized.write_text("corrupted evidence")

        result = self.plan_with_versions()

        self.assertEqual(
            result["entries"][0]["classification"],
            "blocked_integrity",
        )

    def test_changed_model_fingerprint_preserves_history(self):
        first = self.plan_with_versions()
        original_fingerprint = first["entries"][0]["fingerprint"]

        self.model.write_bytes(b"another-synthetic-model")

        second = self.plan_with_versions()

        self.assertNotEqual(
            original_fingerprint,
            second["entries"][0]["fingerprint"],
        )
        self.assertEqual(
            second["entries"][0]["classification"],
            "missing",
        )

    def test_held_processing_lock_blocks_plan(self):
        from processing.checkpoint_store import checkpoint_store

        with checkpoint_store(self.root, self.sid):
            result = self.plan_with_versions()

        self.assertEqual(result["lock_status"], "held")
        self.assertEqual(
            result["entries"][0]["classification"],
            "blocked_unknown",
        )
        self.assertEqual(
            result["entries"][0]["action"],
            "stop",
        )

    def test_missing_checkpoint_is_read_only(self):
        from unittest.mock import patch

        from processing.processing_plan import (
            plan_session_processing,
        )

        before = sorted(
            str(path.relative_to(self.folder))
            for path in self.folder.rglob("*")
        )

        with (
            patch(
                "processing.chunk_coordinator._ffmpeg_version",
                return_value="9.0.1",
            ),
            patch(
                "processing.whisper_runner.whisper_version",
                return_value="1.9.5",
            ),
        ):
            result = plan_session_processing(
                self.root,
                self.sid,
                self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

        self.assertEqual(
            len(result["entries"]),
            1,
            msg=repr({
                "entries": result["entries"],
                "batch_plan": result["batch_plan"],
            }),
        )
        self.assertEqual(
            result["entries"][0]["classification"],
            "missing",
        )
        self.assertEqual(
            result["entries"][0]["action"],
            "execute",
        )

        after = sorted(
            str(path.relative_to(self.folder))
            for path in self.folder.rglob("*")
        )

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
