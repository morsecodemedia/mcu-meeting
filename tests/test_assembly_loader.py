import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from processing.assembly_loader import load_verified_chunks
from processing.batch_planning import plan_batch
from processing.checkpoint_store import checkpoint_store
from session import manager


class AssemblyLoaderTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.sid = manager.create(
            self.root, "com.example.assembly"
        )["session_id"]

        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

        self.plan = plan_batch(
            {"application_audio": 10000000},
            chunk_seconds=10,
            overlap_seconds=0,
        )

        self.chunk_id = "application_audio:000000"
        self.fingerprint = "a" * 64
        self.fingerprints = {
            self.chunk_id: self.fingerprint
        }

        self.folder = self.root / self.sid
        self.directory = (
            self.folder
            / "processing/transcription/application_audio/000000"
            / self.fingerprint
        )

    def tearDown(self):
        self.tmp.cleanup()

    def create_completed_checkpoint(self):
        with checkpoint_store(self.root, self.sid) as store:
            store.create(self.fingerprint, self.chunk_id)
            store.transition(
                self.fingerprint, self.chunk_id, "running"
            )

            whisper = self.directory / "whisper.json"
            normalized = self.directory / "normalized.json"

            whisper.write_text(json.dumps({
                "transcription": []
            }))

            normalized.write_text(json.dumps({
                "schema_version": 1,
                "chunk_id": self.chunk_id,
                "source": "application_audio",
                "segments": [],
            }))

            artifacts = []

            for kind, path in (
                ("whisper_json", whisper),
                ("normalized_json", normalized),
            ):
                artifacts.append({
                    "kind": kind,
                    "path": path.name,
                    "sha256": hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest(),
                })

            store.transition(
                self.fingerprint,
                self.chunk_id,
                "completed",
                artifacts=artifacts,
            )

    def test_success(self):
        self.create_completed_checkpoint()

        result = load_verified_chunks(
            self.root, self.sid, self.plan, self.fingerprints
        )

        self.assertEqual(
            result[self.chunk_id]["segments"], []
        )

    def test_missing_fingerprint(self):
        with self.assertRaises(ValueError):
            load_verified_chunks(
                self.root, self.sid, self.plan, {}
            )

    def test_incomplete_checkpoint(self):
        with checkpoint_store(self.root, self.sid) as store:
            store.create(self.fingerprint, self.chunk_id)

        with self.assertRaises(ValueError):
            load_verified_chunks(
                self.root, self.sid, self.plan, self.fingerprints
            )

    def test_corrupted_normalized_artifact(self):
        self.create_completed_checkpoint()

        path = self.directory / "normalized.json"
        path.write_text('{"corrupted":true}')

        with self.assertRaises(ValueError):
            load_verified_chunks(
                self.root, self.sid, self.plan, self.fingerprints
            )

    def test_chunk_identity_mismatch(self):
        self.create_completed_checkpoint()

        # Modify the artifact and update checkpoint integrity metadata
        # through a separate fixture rather than bypassing validation.
        path = self.directory / "normalized.json"
        payload = json.loads(path.read_text())
        payload["chunk_id"] = "application_audio:999999"
        path.write_text(json.dumps(payload))

        # Integrity verification must reject the modified artifact.
        with self.assertRaises(ValueError):
            load_verified_chunks(
                self.root, self.sid, self.plan, self.fingerprints
            )

    def test_capture_state_preserved(self):
        self.create_completed_checkpoint()

        before = manager.load(self.root, self.sid)["capture"]

        load_verified_chunks(
            self.root, self.sid, self.plan, self.fingerprints
        )

        after = manager.load(self.root, self.sid)["capture"]
        self.assertEqual(before, after)


    def test_valid_checksum_wrong_chunk_identity(self):
        from unittest.mock import patch

        original = self.create_completed_checkpoint

        def create_wrong_identity():
            original()

            path = self.directory / "normalized.json"
            payload = json.loads(path.read_text())
            payload["chunk_id"] = "application_audio:999999"

            content = json.dumps(payload).encode("utf-8")
            path.write_bytes(content)

            checkpoint_path = self.directory / "checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text())

            for artifact in checkpoint["artifacts"]:
                if artifact["kind"] == "normalized_json":
                    artifact["sha256"] = hashlib.sha256(
                        content
                    ).hexdigest()

            checkpoint_path.write_text(json.dumps(checkpoint))

        create_wrong_identity()

        with self.assertRaisesRegex(
            ValueError, "Normalized chunk identity mismatch"
        ):
            load_verified_chunks(
                self.root,
                self.sid,
                self.plan,
                self.fingerprints,
            )


    def test_verified_contribution_metadata(self):
        from processing.assembly_loader import (
            load_verified_assembly_inputs,
        )

        self.create_completed_checkpoint()

        result = load_verified_assembly_inputs(
            self.root,
            self.sid,
            self.plan,
            self.fingerprints,
        )

        self.assertEqual(
            set(result),
            {"chunks", "contributions"},
        )

        self.assertIn(self.chunk_id, result["chunks"])

        contribution = result["contributions"][self.chunk_id]

        self.assertEqual(
            contribution["fingerprint"],
            self.fingerprint,
        )

        normalized_path = self.directory / "normalized.json"

        self.assertEqual(
            contribution["normalized_sha256"],
            hashlib.sha256(
                normalized_path.read_bytes()
            ).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
