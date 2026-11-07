"""Regression tests for pure human-review migration."""

import copy
import json
import unittest

from processing.reconciliation_migration import migrate_review


ASSEMBLY = "a" * 64
EXECUTION = "b" * 64
SESSION = "11111111-1111-4111-8111-111111111111"


def fixture():
    review = {
        "schema_version": 1,
        "session_id": SESSION,
        "assembly_fingerprint": ASSEMBLY,
        "review_status": "partial",
        "decisions": [
            {
                "finding_index": 1,
                "decision": "duplicate_confirmed",
                "method": "human_audio_review",
            }
        ],
        "capture_observations": {
            "source_isolation": "not_guaranteed"
        },
    }

    transcript = {
        "schema_version": 1,
        "findings": [
            {
                "type": "boundary_spanning",
                "chunk_id": "application_audio:000000",
                "segment": {
                    "id": "application_audio:000000:0",
                    "source": "application_audio",
                    "chunk_id": "application_audio:000000",
                    "segment_index": 0,
                    "start_seconds": 298.5,
                    "end_seconds": 302.0,
                    "text": "Example speech",
                },
            }
        ],
    }

    provenance = {
        "session_id": SESSION,
        "assembly_fingerprint": ASSEMBLY,
        "identity": {
            "contributions": [
                {
                    "chunk_id": "application_audio:000000",
                    "fingerprint": EXECUTION,
                }
            ]
        },
    }

    return review, transcript, provenance


def migrate(review, transcript, provenance):
    source = json.dumps(
        review, sort_keys=True
    ).encode("utf-8")

    return migrate_review(
        review,
        transcript,
        provenance,
        source_review_bytes=source,
    )


class ReconciliationMigrationTests(unittest.TestCase):

    def setUp(self):
        self.review, self.transcript, self.provenance = fixture()

    def run_migration(self):
        return migrate(
            self.review,
            self.transcript,
            self.provenance,
        )

    def test_success(self):
        result = self.run_migration()

        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(len(result["decisions"]), 1)
        self.assertEqual(
            result["decisions"][0]["decision"],
            "duplicate_confirmed",
        )
        self.assertEqual(
            result["decisions"][0]["legacy_finding_index"], 1
        )
        self.assertEqual(
            len(result["decisions"][0]["finding_id"]), 64
        )
        self.assertEqual(
            len(result["decisions"][0]["evidence_id"]), 64
        )

    def test_deterministic(self):
        self.assertEqual(
            self.run_migration(),
            self.run_migration(),
        )

    def test_inputs_not_mutated(self):
        original = copy.deepcopy(
            (self.review, self.transcript, self.provenance)
        )

        self.run_migration()

        self.assertEqual(
            (self.review, self.transcript, self.provenance),
            original,
        )

    def test_source_bytes_mismatch(self):
        with self.assertRaises(ValueError):
            migrate_review(
                self.review,
                self.transcript,
                self.provenance,
                source_review_bytes=b'{"wrong":true}',
            )

    def test_invalid_source_version(self):
        self.review["schema_version"] = 2

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_session_mismatch(self):
        self.provenance["session_id"] = "other"

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_assembly_mismatch(self):
        self.provenance["assembly_fingerprint"] = "c" * 64

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_missing_findings(self):
        del self.transcript["findings"]

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_invalid_finding_index(self):
        self.review["decisions"][0]["finding_index"] = 99

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_boolean_finding_index(self):
        self.review["decisions"][0]["finding_index"] = True

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_duplicate_finding_index(self):
        self.review["decisions"].append(
            copy.deepcopy(self.review["decisions"][0])
        )

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_unsupported_decision(self):
        self.review["decisions"][0]["decision"] = "auto_resolved"

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_unsupported_method(self):
        self.review["decisions"][0]["method"] = "unverified"

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_missing_execution_provenance(self):
        self.provenance["identity"]["contributions"] = []

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_duplicate_execution_contribution(self):
        self.provenance["identity"]["contributions"].append(
            copy.deepcopy(
                self.provenance["identity"]["contributions"][0]
            )
        )

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_invalid_execution_digest(self):
        self.provenance["identity"]["contributions"][0][
            "fingerprint"
        ] = "invalid"

        with self.assertRaises(ValueError):
            self.run_migration()

    def test_capture_observations_preserved(self):
        result = self.run_migration()

        self.assertEqual(
            result["capture_observations"],
            self.review["capture_observations"],
        )


if __name__ == "__main__":
    unittest.main()
