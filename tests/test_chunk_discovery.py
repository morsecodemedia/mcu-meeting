import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from processing.chunk_discovery import (
    discover_checkpoints,
    inspect_coordinator_lock,
)
from processing.chunk_storage import (
    create_checkpoint,
    save_transition,
)
from session import manager

FINGERPRINT = "a" * 64
CHUNK_ID = "application_audio:000000"


class ChunkDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sid = manager.create(
            self.root, "com.example.discovery"
        )["session_id"]
        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")
        self.folder = self.root / self.sid

    def tearDown(self):
        self.tmp.cleanup()

    def directory(self):
        return (
            self.folder / "processing" / "transcription"
            / "application_audio" / "000000" / FINGERPRINT
        )

    def create(self, state="pending"):
        create_checkpoint(self.folder, FINGERPRINT, CHUNK_ID)

        if state != "pending":
            save_transition(
                self.folder, FINGERPRINT, CHUNK_ID, "running"
            )

        if state == "failed":
            save_transition(
                self.folder, FINGERPRINT, CHUNK_ID,
                "failed", retryable=True, error="synthetic"
            )

        if state == "completed":
            artifacts = []

            for kind, name in (
                ("whisper_json", "whisper.json"),
                ("normalized_json", "normalized.json"),
            ):
                content = b'{"synthetic":true}'
                (self.directory() / name).write_bytes(content)
                artifacts.append({
                    "kind": kind,
                    "path": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                })

            save_transition(
                self.folder, FINGERPRINT, CHUNK_ID,
                "completed", artifacts=artifacts
            )

    def classification(self):
        report = discover_checkpoints(self.root, self.sid)
        return report["checkpoints"][0]["classification"]

    def test_empty_session(self):
        report = discover_checkpoints(self.root, self.sid)
        self.assertEqual(report["checkpoints"], [])
        self.assertFalse(
            (self.folder / ".processing.lock").exists()
        )

    def test_pending(self):
        self.create()
        self.assertEqual(self.classification(), "not_started")

    def test_running_without_lock(self):
        self.create("running")
        self.assertEqual(self.classification(), "interrupted")

    def test_running_with_lock(self):
        self.create("running")

        with manager.processing_lock(self.root, self.sid):
            self.assertEqual(self.classification(), "active")

    def test_retryable_failure(self):
        self.create("failed")
        self.assertEqual(
            self.classification(), "retryable_failure"
        )

    def test_verified_complete(self):
        self.create("completed")
        self.assertEqual(
            self.classification(), "verified_complete"
        )

    def test_corrupted_artifact(self):
        self.create("completed")
        (self.directory() / "whisper.json").write_bytes(b"corrupt")
        self.assertEqual(
            self.classification(), "integrity_failure"
        )

    def test_invalid_checkpoint(self):
        self.create()
        path = self.directory() / "checkpoint.json"
        path.write_text("{invalid json")
        self.assertEqual(
            self.classification(), "invalid_checkpoint"
        )

    def test_read_only(self):
        self.create("running")

        manifest = (self.folder / "manifest.json")
        checkpoint = self.directory() / "checkpoint.json"

        before_manifest = manifest.read_bytes()
        before_checkpoint = checkpoint.read_bytes()

        discover_checkpoints(self.root, self.sid)

        self.assertEqual(manifest.read_bytes(), before_manifest)
        self.assertEqual(checkpoint.read_bytes(), before_checkpoint)
        self.assertFalse(
            (self.folder / ".processing.lock").exists()
        )

    def test_symlinked_checkpoint_directory(self):
        self.create()
        directory = self.directory()
        moved = self.folder / "external"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)

        self.assertEqual(
            self.classification(), "invalid_checkpoint"
        )


    def test_symlinked_source_directory(self):
        self.create()

        source_dir = (
            self.folder / "processing" / "transcription"
            / "application_audio"
        )
        external = self.folder / "external-source"
        source_dir.rename(external)
        source_dir.symlink_to(external, target_is_directory=True)

        with self.assertRaises(ValueError):
            discover_checkpoints(self.root, self.sid)

    def test_symlinked_index_directory(self):
        self.create()

        index_dir = self.directory().parent
        external = self.folder / "external-index"
        index_dir.rename(external)
        index_dir.symlink_to(external, target_is_directory=True)

        with self.assertRaises(ValueError):
            discover_checkpoints(self.root, self.sid)

    def test_nonregular_lock_file(self):
        lock = self.folder / ".processing.lock"
        lock.mkdir()

        self.assertEqual(
            inspect_coordinator_lock(self.folder),
            "unknown",
        )

    def test_missing_lock_does_not_create_file(self):
        lock = self.folder / ".processing.lock"

        self.assertFalse(lock.exists())
        self.assertEqual(
            inspect_coordinator_lock(self.folder),
            "available",
        )
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
