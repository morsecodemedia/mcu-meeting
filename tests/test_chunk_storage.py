import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from processing.chunk_storage import (
    create_checkpoint,
    load_checkpoint,
    save_transition,
    verify_artifacts,
)

FINGERPRINT = "a" * 64
CHUNK_ID = "application_audio:000000"


class ChunkStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def directory(self):
        return (
            self.root / "processing" / "transcription"
            / "application_audio" / "000000" / FINGERPRINT
        )

    def create(self):
        return create_checkpoint(self.root, FINGERPRINT, CHUNK_ID)

    def artifacts(self):
        directory = self.directory()
        results = []

        for kind, name, content in (
            ("whisper_json", "whisper.json", b'{"text":"synthetic"}'),
            ("normalized_json", "normalized.json", b'{"segments":[]}'),
        ):
            (directory / name).write_bytes(content)
            results.append({
                "kind": kind,
                "path": name,
                "sha256": hashlib.sha256(content).hexdigest(),
            })

        return results

    def test_create_and_load(self):
        self.create()
        result = load_checkpoint(self.root, FINGERPRINT, CHUNK_ID)
        self.assertEqual(result["state"], "pending")

    def test_existing_checkpoint_refused(self):
        self.create()
        with self.assertRaises(FileExistsError):
            self.create()

    def test_lifecycle_persistence(self):
        self.create()
        save_transition(self.root, FINGERPRINT, CHUNK_ID, "running")
        result = save_transition(
            self.root, FINGERPRINT, CHUNK_ID,
            "completed", artifacts=self.artifacts(),
        )
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["attempts"], 1)

    def test_verified_artifacts(self):
        self.create()
        save_transition(self.root, FINGERPRINT, CHUNK_ID, "running")
        save_transition(
            self.root, FINGERPRINT, CHUNK_ID,
            "completed", artifacts=self.artifacts(),
        )
        self.assertTrue(
            verify_artifacts(self.root, FINGERPRINT, CHUNK_ID)
        )

    def test_checksum_mismatch(self):
        self.create()
        save_transition(self.root, FINGERPRINT, CHUNK_ID, "running")
        artifacts = self.artifacts()
        save_transition(
            self.root, FINGERPRINT, CHUNK_ID,
            "completed", artifacts=artifacts,
        )
        (self.directory() / "whisper.json").write_bytes(b"corrupted")

        with self.assertRaises(ValueError):
            verify_artifacts(self.root, FINGERPRINT, CHUNK_ID)

    def test_missing_artifact(self):
        self.create()
        save_transition(self.root, FINGERPRINT, CHUNK_ID, "running")
        artifacts = self.artifacts()
        save_transition(
            self.root, FINGERPRINT, CHUNK_ID,
            "completed", artifacts=artifacts,
        )
        (self.directory() / "whisper.json").unlink()

        with self.assertRaises(FileNotFoundError):
            verify_artifacts(self.root, FINGERPRINT, CHUNK_ID)

    def test_symlink_artifact_rejected(self):
        self.create()
        save_transition(self.root, FINGERPRINT, CHUNK_ID, "running")
        artifacts = self.artifacts()
        save_transition(
            self.root, FINGERPRINT, CHUNK_ID,
            "completed", artifacts=artifacts,
        )

        target = self.root / "external.json"
        target.write_bytes(b"external")

        path = self.directory() / "whisper.json"
        path.unlink()
        path.symlink_to(target)

        with self.assertRaises(ValueError):
            verify_artifacts(self.root, FINGERPRINT, CHUNK_ID)

    def test_atomic_replace_failure_preserves_checkpoint(self):
        self.create()
        before = (self.directory() / "checkpoint.json").read_bytes()

        with patch(
            "processing.chunk_storage.os.replace",
            side_effect=OSError("synthetic replacement failure"),
        ):
            with self.assertRaises(OSError):
                save_transition(
                    self.root, FINGERPRINT, CHUNK_ID, "running"
                )

        after = (self.directory() / "checkpoint.json").read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(
            list(self.directory().glob(".checkpoint-*.tmp")), []
        )

    def test_symlink_checkpoint_rejected(self):
        self.create()
        original = self.directory() / "checkpoint.json"
        protected = self.root / "protected.json"
        protected.write_text("preserve")

        original.unlink()
        original.symlink_to(protected)

        with self.assertRaises(ValueError):
            load_checkpoint(self.root, FINGERPRINT, CHUNK_ID)

        self.assertEqual(protected.read_text(), "preserve")


    def test_symlinked_checkpoint_directory_rejected(self):
        self.create()

        directory = self.directory()
        source_parent = directory.parent
        external = self.root / "external-storage"
        external.mkdir()

        # Move the fingerprint directory to a different location.
        moved = external / FINGERPRINT
        directory.rename(moved)

        # Replace its original location with a symlink.
        directory.symlink_to(moved, target_is_directory=True)

        with self.assertRaises(ValueError):
            load_checkpoint(self.root, FINGERPRINT, CHUNK_ID)

        # Ensure the original checkpoint remains untouched.
        self.assertTrue((moved / "checkpoint.json").is_file())


    def test_directory_sync_failure_after_transition(self):
        import json
        import os

        self.create()

        original_fsync = os.fsync
        calls = 0

        def fail_directory_sync(fd):
            nonlocal calls
            calls += 1

            if calls == 2:
                raise OSError("synthetic directory sync failure")

            return original_fsync(fd)

        with patch(
            "processing.chunk_storage.os.fsync",
            side_effect=fail_directory_sync,
        ):
            with self.assertRaises(OSError):
                save_transition(
                    self.root,
                    FINGERPRINT,
                    CHUNK_ID,
                    "running",
                )

        checkpoint_path = self.directory() / "checkpoint.json"

        payload = json.loads(checkpoint_path.read_text())

        self.assertEqual(payload["state"], "running")
        self.assertEqual(payload["attempts"], 1)

        self.assertEqual(
            list(self.directory().glob(".checkpoint-*.tmp")),
            [],
        )

        loaded = load_checkpoint(
            self.root,
            FINGERPRINT,
            CHUNK_ID,
        )

        self.assertEqual(loaded["state"], "running")


    def test_directory_artifact_rejected(self):
        self.create()
        save_transition(self.root, FINGERPRINT, CHUNK_ID, "running")
        artifacts = self.artifacts()

        save_transition(
            self.root,
            FINGERPRINT,
            CHUNK_ID,
            "completed",
            artifacts=artifacts,
        )

        path = self.directory() / "whisper.json"
        path.unlink()
        path.mkdir()

        with self.assertRaises(ValueError):
            verify_artifacts(self.root, FINGERPRINT, CHUNK_ID)

    def test_symlink_replacement_rejected(self):
        self.create()
        save_transition(self.root, FINGERPRINT, CHUNK_ID, "running")
        artifacts = self.artifacts()

        save_transition(
            self.root,
            FINGERPRINT,
            CHUNK_ID,
            "completed",
            artifacts=artifacts,
        )

        original = self.directory() / "whisper.json"
        external = self.root / "external-artifact.json"
        external.write_bytes(original.read_bytes())

        original.unlink()
        original.symlink_to(external)

        with self.assertRaises(ValueError):
            verify_artifacts(self.root, FINGERPRINT, CHUNK_ID)

        self.assertTrue(external.is_file())


if __name__ == "__main__":
    unittest.main()
