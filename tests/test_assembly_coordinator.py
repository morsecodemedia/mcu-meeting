"""Regression tests for verified assembly coordination."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from processing.assembly_coordinator import assemble_session
from processing.batch_planning import plan_batch
from processing.checkpoint_store import checkpoint_store
from session import manager


@unittest.skipUnless(
    sys.platform == "darwin",
    "macOS immutable assembly publication",
)
class AssemblyCoordinatorTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sid = manager.create(
            self.root, "com.example.assembly-coordinator"
        )["session_id"]

        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

        self.folder = self.root / self.sid

        self.plan = plan_batch(
            {"application_audio": 10000000},
            chunk_seconds=10,
            overlap_seconds=0,
        )

        self.chunk_id = "application_audio:000000"
        self.fingerprint = "a" * 64
        self.fingerprints = {
            self.chunk_id: self.fingerprint,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def create_checkpoint(self, *, completed=True, segments=None):
        if segments is None:
            segments = []

        with checkpoint_store(self.root, self.sid) as store:
            store.create(self.fingerprint, self.chunk_id)

            if not completed:
                return

            store.transition(
                self.fingerprint,
                self.chunk_id,
                "running",
            )

            directory = (
                self.folder
                / "processing/transcription/application_audio/000000"
                / self.fingerprint
            )

            whisper = directory / "whisper.json"
            normalized = directory / "normalized.json"

            whisper.write_text(json.dumps({
                "transcription": [],
            }))

            normalized.write_text(json.dumps({
                "schema_version": 1,
                "chunk_id": self.chunk_id,
                "source": "application_audio",
                "segments": segments,
            }))

            artifacts = [
                {
                    "kind": kind,
                    "path": path.name,
                    "sha256": hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest(),
                }
                for kind, path in (
                    ("whisper_json", whisper),
                    ("normalized_json", normalized),
                )
            ]

            store.transition(
                self.fingerprint,
                self.chunk_id,
                "completed",
                artifacts=artifacts,
            )

    def execute(self):
        return assemble_session(
            self.root,
            self.sid,
            self.plan,
            self.fingerprints,
        )

    def test_successful_publication(self):
        self.create_checkpoint()

        result = self.execute()

        self.assertEqual(result["state"], "assembled")
        self.assertEqual(result["segment_count"], 0)

        directory = Path(result["path"])

        self.assertTrue(
            (directory / "transcript.json").is_file()
        )
        self.assertTrue(
            (directory / "provenance.json").is_file()
        )

        provenance = json.loads(
            (directory / "provenance.json").read_text()
        )

        self.assertEqual(
            provenance["assembly_fingerprint"],
            result["fingerprint"],
        )

        self.assertEqual(
            provenance["identity"]["contributions"][0]["fingerprint"],
            self.fingerprint,
        )

    def test_existing_output_refused(self):
        self.create_checkpoint()
        first = self.execute()

        with self.assertRaises(FileExistsError):
            self.execute()

        self.assertTrue(Path(first["path"]).is_dir())

    def test_incomplete_checkpoint_rejected(self):
        self.create_checkpoint(completed=False)

        with self.assertRaises(ValueError):
            self.execute()

        self.assertFalse(
            (self.folder / "processing/assembly").exists()
        )

    def test_invalid_fingerprint_mapping(self):
        self.create_checkpoint()

        with self.assertRaises(ValueError):
            assemble_session(
                self.root,
                self.sid,
                self.plan,
                {},
            )

    def test_capture_state_preserved(self):
        self.create_checkpoint()

        before = manager.load(
            self.root, self.sid
        )["capture"]

        self.execute()

        after = manager.load(
            self.root, self.sid
        )["capture"]

        self.assertEqual(before, after)

    def test_single_processing_lock(self):
        self.create_checkpoint()

        from processing import checkpoint_store as module

        original = module.checkpoint_store
        calls = 0

        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        with patch(
            "processing.assembly_coordinator.checkpoint_store",
            side_effect=counted,
        ):
            self.execute()

        self.assertEqual(calls, 1)

    def test_unresolved_boundary_preserved(self):
        self.plan = plan_batch(
            {"application_audio": 20000000},
            chunk_seconds=10,
            overlap_seconds=2,
        )

        first = self.chunk_id
        second = "application_audio:000001"

        self.create_checkpoint(segments=[
            {
                "id": first + ":0",
                "source": "application_audio",
                "speaker": "unresolved",
                "start_seconds": 9.2,
                "end_seconds": 10.8,
                "text": "Speech crossing the boundary",
            },
        ])

        second_fingerprint = "b" * 64

        with checkpoint_store(self.root, self.sid) as store:
            store.create(second_fingerprint, second)
            store.transition(
                second_fingerprint, second, "running"
            )

            directory = (
                self.folder
                / "processing/transcription/application_audio/000001"
                / second_fingerprint
            )

            whisper = directory / "whisper.json"
            normalized = directory / "normalized.json"

            whisper.write_text(json.dumps({
                "transcription": [],
            }))

            normalized.write_text(json.dumps({
                "schema_version": 1,
                "chunk_id": second,
                "source": "application_audio",
                "segments": [{
                    "id": second + ":0",
                    "source": "application_audio",
                    "speaker": "unresolved",
                    "start_seconds": 10.0,
                    "end_seconds": 11.0,
                    "text": "Speech after the boundary",
                }],
            }))

            artifacts = [
                {
                    "kind": kind,
                    "path": path.name,
                    "sha256": hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest(),
                }
                for kind, path in (
                    ("whisper_json", whisper),
                    ("normalized_json", normalized),
                )
            ]

            store.transition(
                second_fingerprint,
                second,
                "completed",
                artifacts=artifacts,
            )

        self.fingerprints[second] = second_fingerprint

        result = self.execute()

        self.assertEqual(
            result["state"], "requires_reconciliation"
        )
        self.assertEqual(result["unresolved_count"], 1)
        self.assertEqual(result["segment_count"], 1)

        directory = Path(result["path"])
        transcript = json.loads(
            (directory / "transcript.json").read_text()
        )

        self.assertEqual(
            transcript["findings"][0]["type"],
            "boundary_spanning",
        )
        self.assertEqual(
            transcript["findings"][0]["segment"]["text"],
            "Speech crossing the boundary",
        )
        self.assertEqual(
            transcript["segments"][0]["text"],
            "Speech after the boundary",
        )


if __name__ == "__main__":
    unittest.main()
