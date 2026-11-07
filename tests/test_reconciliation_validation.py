"""Tests for strict reconciliation review validation."""

import copy
import tempfile
import unittest
from pathlib import Path

from processing.reconciliation_validation import validate_review_v2
from processing.reconciliation_publisher import publish_review


SESSION = "11111111-1111-4111-8111-111111111111"


def fixture():
    return {
        "schema_version": 2,
        "session_id": SESSION,
        "assembly_fingerprint": "a" * 64,
        "review_status": "partial",
        "source_review_sha256": "b" * 64,
        "decisions": [
            {
                "finding_id": "c" * 64,
                "evidence_id": "d" * 64,
                "decision": "duplicate_confirmed",
                "method": "human_audio_review",
                "legacy_finding_index": 1,
            }
        ],
        "capture_observations": {
            "microphone_contains_acoustic_application_audio": True,
            "source_isolation": "not_guaranteed",
            "cross_source_deduplication": "not_performed",
        },
    }


class ReconciliationValidationTests(unittest.TestCase):

    def setUp(self):
        self.review = fixture()

    def reject(self):
        with self.assertRaises(ValueError):
            validate_review_v2(self.review)

    def test_valid(self):
        self.assertTrue(validate_review_v2(self.review))

    def test_input_immutable(self):
        original = copy.deepcopy(self.review)
        validate_review_v2(self.review)
        self.assertEqual(self.review, original)

    def test_unknown_review_field(self):
        self.review["unexpected"] = True
        self.reject()

    def test_missing_review_field(self):
        del self.review["source_review_sha256"]
        self.reject()

    def test_boolean_schema_version(self):
        self.review["schema_version"] = True
        self.reject()

    def test_invalid_uuid(self):
        self.review["session_id"] = "invalid"
        self.reject()

    def test_noncanonical_uuid(self):
        self.review["session_id"] = (
            "abcdefab-1111-4111-8111-abcdefabcdef".upper()
        )
        self.reject()

    def test_invalid_assembly_digest(self):
        self.review["assembly_fingerprint"] = "INVALID"
        self.reject()

    def test_invalid_source_digest(self):
        self.review["source_review_sha256"] = "invalid"
        self.reject()

    def test_complete_status_rejected(self):
        self.review["review_status"] = "complete"
        self.reject()

    def test_unknown_decision_field(self):
        self.review["decisions"][0]["extra"] = 1
        self.reject()

    def test_invalid_finding_digest(self):
        self.review["decisions"][0]["finding_id"] = "bad"
        self.reject()

    def test_invalid_evidence_digest(self):
        self.review["decisions"][0]["evidence_id"] = "bad"
        self.reject()

    def test_duplicate_finding_id(self):
        duplicate = copy.deepcopy(self.review["decisions"][0])
        duplicate["legacy_finding_index"] = 2
        self.review["decisions"].append(duplicate)
        self.reject()

    def test_duplicate_legacy_index(self):
        duplicate = copy.deepcopy(self.review["decisions"][0])
        duplicate["finding_id"] = "e" * 64
        self.review["decisions"].append(duplicate)
        self.reject()

    def test_boolean_legacy_index(self):
        self.review["decisions"][0]["legacy_finding_index"] = True
        self.reject()

    def test_zero_legacy_index(self):
        self.review["decisions"][0]["legacy_finding_index"] = 0
        self.reject()

    def test_unsupported_decision(self):
        self.review["decisions"][0]["decision"] = "auto_resolved"
        self.reject()

    def test_unsupported_method(self):
        self.review["decisions"][0]["method"] = "machine_guess"
        self.reject()

    def test_unknown_observation(self):
        self.review["capture_observations"]["extra"] = True
        self.reject()

    def test_invalid_microphone_observation(self):
        self.review["capture_observations"][
            "microphone_contains_acoustic_application_audio"
        ] = "yes"
        self.reject()

    def test_invalid_observation_type(self):
        self.review["capture_observations"] = []
        self.reject()

    def test_invalid_decisions_type(self):
        self.review["decisions"] = {}
        self.reject()

    def test_invalid_review_type(self):
        self.review = []
        self.reject()

    def test_invalid_review_does_not_create_directories(self):
        self.review["decisions"][0]["finding_id"] = "bad"

        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / SESSION
            session.mkdir()

            with self.assertRaises(ValueError):
                publish_review(session, self.review)

            self.assertFalse((session / "processing").exists())


if __name__ == "__main__":
    unittest.main()
