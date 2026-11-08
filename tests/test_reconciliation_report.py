"""Regression tests for pure reconciliation reporting."""

import copy
import unittest

from processing.reconciliation_identity import (
    evidence_identity,
    finding_identity,
)
from processing.reconciliation_report import build_reconciliation_report

SESSION = "11111111-1111-4111-8111-111111111111"
ASSEMBLY = "a" * 64
EXECUTION = "b" * 64


def fixture():
    findings = []

    for index in range(2):
        chunk = f"application_audio:{index:06d}"

        findings.append({
            "type": "boundary_spanning",
            "chunk_id": chunk,
            "segment": {
                "id": f"{chunk}:0",
                "source": "application_audio",
                "chunk_id": chunk,
                "segment_index": 0,
                "start_seconds": 298.0 + index * 300,
                "end_seconds": 302.0 + index * 300,
                "text": f"Example speech {index}",
            },
        })

    transcript = {
        "state": "requires_reconciliation",
        "findings": findings,
    }

    provenance = {
        "session_id": SESSION,
        "assembly_fingerprint": ASSEMBLY,
        "identity": {
            "contributions": [
                {
                    "chunk_id": finding["chunk_id"],
                    "fingerprint": EXECUTION,
                }
                for finding in findings
            ]
        },
    }

    first = findings[0]

    review = {
        "schema_version": 2,
        "session_id": SESSION,
        "assembly_fingerprint": ASSEMBLY,
        "review_status": "partial",
        "source_review_sha256": "c" * 64,
        "decisions": [{
            "finding_id": finding_identity(ASSEMBLY, first),
            "evidence_id": evidence_identity(EXECUTION, first),
            "decision": "duplicate_confirmed",
            "method": "human_audio_review",
            "legacy_finding_index": 1,
        }],
        "capture_observations": {
            "source_isolation": "not_guaranteed",
        },
    }

    return transcript, provenance, review


class ReconciliationReportTests(unittest.TestCase):

    def setUp(self):
        self.transcript, self.provenance, self.review = fixture()

    def build(self):
        return build_reconciliation_report(
            SESSION, ASSEMBLY,
            self.transcript, self.provenance, self.review,
        )

    def test_success(self):
        result = self.build()
        self.assertEqual(result["total_findings"], 2)
        self.assertEqual(result["reviewed_count"], 1)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(
            result["decision_counts"], {"duplicate_confirmed": 1}
        )

    def test_no_verification_claim(self):
        self.assertNotIn("verification_level", self.build())

    def test_input_immutability(self):
        original = copy.deepcopy((
            self.transcript, self.provenance, self.review
        ))
        self.build()
        self.assertEqual(
            (self.transcript, self.provenance, self.review),
            original,
        )

    def test_unknown_finding_rejected(self):
        self.review["decisions"][0]["finding_id"] = "d" * 64
        with self.assertRaises(ValueError):
            self.build()

    def test_evidence_mismatch_rejected(self):
        self.review["decisions"][0]["evidence_id"] = "d" * 64
        with self.assertRaises(ValueError):
            self.build()

    def test_legacy_index_mismatch_rejected(self):
        self.review["decisions"][0]["legacy_finding_index"] = 2
        with self.assertRaises(ValueError):
            self.build()

    def test_missing_provenance_rejected(self):
        self.provenance["identity"]["contributions"] = []
        with self.assertRaises(ValueError):
            self.build()

    def test_duplicate_contribution_rejected(self):
        self.provenance["identity"]["contributions"].append(
            copy.deepcopy(
                self.provenance["identity"]["contributions"][0]
            )
        )
        with self.assertRaises(ValueError):
            self.build()

    def test_duplicate_finding_identity_rejected(self):
        self.transcript["findings"].append(
            copy.deepcopy(self.transcript["findings"][0])
        )
        with self.assertRaises(ValueError):
            self.build()

    def test_session_mismatch_rejected(self):
        self.review["session_id"] = (
            "22222222-2222-4222-8222-222222222222"
        )
        with self.assertRaises(ValueError):
            self.build()

    def test_assembly_mismatch_rejected(self):
        self.review["assembly_fingerprint"] = "d" * 64
        with self.assertRaises(ValueError):
            self.build()

    def test_capture_observations_preserved(self):
        result = self.build()
        self.assertEqual(
            result["capture_observations"],
            self.review["capture_observations"],
        )


if __name__ == "__main__":
    unittest.main()
