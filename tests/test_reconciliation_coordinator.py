"""Regression tests for read-only reconciliation coordination."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from processing.reconciliation_coordinator import reconcile_session
from processing.reconciliation_identity import (
    evidence_identity,
    finding_identity,
)
from processing.reconciliation_migration import migrate_review

SESSION = "11111111-1111-4111-8111-111111111111"
ASSEMBLY = "a" * 64
EXECUTION = "b" * 64


class ReconciliationCoordinatorTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.session = self.root / SESSION
        self.assembly = (
            self.session / "processing/assembly" / ASSEMBLY
        )
        self.reviews = self.session / "processing/reconciliation"

        self.assembly.mkdir(parents=True)
        self.reviews.mkdir(parents=True)

        chunk = "application_audio:000000"

        finding = {
            "type": "boundary_spanning",
            "chunk_id": chunk,
            "segment": {
                "id": f"{chunk}:0",
                "source": "application_audio",
                "chunk_id": chunk,
                "segment_index": 0,
                "start_seconds": 298.0,
                "end_seconds": 302.0,
                "text": "Example speech",
            },
        }

        self.transcript = {
            "state": "requires_reconciliation",
            "segments": [],
            "findings": [finding],
        }

        self.provenance = {
            "session_id": SESSION,
            "assembly_fingerprint": ASSEMBLY,
            "identity": {
                "contributions": [{
                    "chunk_id": chunk,
                    "fingerprint": EXECUTION,
                }],
            },
        }

        self.v1 = {
            "schema_version": 1,
            "session_id": SESSION,
            "assembly_fingerprint": ASSEMBLY,
            "review_status": "partial",
            "decisions": [{
                "finding_index": 1,
                "decision": "duplicate_confirmed",
                "method": "human_audio_review",
            }],
            "capture_observations": {},
        }

        self.v1_bytes = json.dumps(
            self.v1, sort_keys=True
        ).encode("utf-8")

        self.v2 = migrate_review(
            self.v1,
            self.transcript,
            self.provenance,
            source_review_bytes=self.v1_bytes,
        )

        self.write_fixture()

        self.discovery = {
            "session_id": SESSION,
            "lock_status": "available",
            "assemblies": [{
                "name": ASSEMBLY,
                "classification": "verified_complete",
                "verification_level": "source_verified",
                "transcript_state": "requires_reconciliation",
                "segment_count": 0,
                "unresolved_count": 1,
            }],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def write_fixture(self):
        (self.assembly / "transcript.json").write_text(
            json.dumps(self.transcript)
        )
        (self.assembly / "provenance.json").write_text(
            json.dumps(self.provenance)
        )
        (self.reviews / "human-review-v1.json").write_bytes(
            self.v1_bytes
        )
        (self.reviews / "human-review-v2.json").write_text(
            json.dumps(self.v2)
        )

    def run_coordinator(self):
        with patch(
            "processing.reconciliation_coordinator.discover_assemblies",
            return_value=self.discovery,
        ):
            return reconcile_session(self.root, SESSION, ASSEMBLY)

    def test_transcript_state_mismatch_rejected(self):
        self.discovery["assemblies"][0]["transcript_state"] = "assembled"

        with self.assertRaises(ValueError):
            self.run_coordinator()

    def test_segment_count_mismatch_rejected(self):
        self.discovery["assemblies"][0]["segment_count"] = 1

        with self.assertRaises(ValueError):
            self.run_coordinator()

    def test_success(self):
        result = self.run_coordinator()
        self.assertEqual(result["verification_level"], "source_verified")
        self.assertEqual(result["reviewed_count"], 1)
        self.assertEqual(result["pending_count"], 0)

    def test_read_only(self):
        paths = [
            self.assembly / "transcript.json",
            self.assembly / "provenance.json",
            self.reviews / "human-review-v1.json",
            self.reviews / "human-review-v2.json",
        ]
        before = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        }
        self.run_coordinator()
        after = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        }
        self.assertEqual(before, after)

    def test_unverified_assembly_rejected(self):
        self.discovery["assemblies"][0][
            "classification"
        ] = "published_invalid"

        with self.assertRaises(ValueError):
            self.run_coordinator()

    def test_missing_assembly_rejected(self):
        self.discovery["assemblies"] = []
        with self.assertRaises(ValueError):
            self.run_coordinator()

    def test_review_decision_tampering_rejected(self):
        self.v2["decisions"][0]["decision"] = "unresolved"
        self.write_fixture()

        with self.assertRaises(ValueError):
            self.run_coordinator()

    def test_review_evidence_tampering_rejected(self):
        self.v2["decisions"][0]["evidence_id"] = "c" * 64
        self.write_fixture()

        with self.assertRaises(ValueError):
            self.run_coordinator()

    def test_v1_checksum_mismatch_rejected(self):
        self.v1_bytes = b'{"tampered":true}'
        self.write_fixture()

        with self.assertRaises(ValueError):
            self.run_coordinator()

    def test_symlinked_review_rejected(self):
        path = self.reviews / "human-review-v2.json"
        path.unlink()

        target = self.root / "external.json"
        target.write_text(json.dumps(self.v2))
        path.symlink_to(target)

        with self.assertRaises(OSError):
            self.run_coordinator()

    def test_symlinked_review_directory_rejected(self):
        external = self.root / "external"
        self.reviews.rename(external)
        self.reviews.symlink_to(external)

        with self.assertRaises(ValueError):
            self.run_coordinator()

    def test_legacy_index_mismatch_rejected(self):
        self.v2["decisions"][0]["legacy_finding_index"] = 2
        self.write_fixture()

        with self.assertRaises(ValueError):
            self.run_coordinator()

    def test_source_review_missing_rejected(self):
        (self.reviews / "human-review-v1.json").unlink()

        with self.assertRaises(OSError):
            self.run_coordinator()

    def test_duplicate_assembly_record_rejected(self):
        self.discovery["assemblies"].append(
            copy.deepcopy(self.discovery["assemblies"][0])
        )

        with self.assertRaises(ValueError):
            self.run_coordinator()


if __name__ == "__main__":
    unittest.main()
