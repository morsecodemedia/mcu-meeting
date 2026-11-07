"""Tests for deterministic reconciliation identities."""

import copy
import unittest

from processing.reconciliation_identity import (
    evidence_identity,
    finding_identity,
)

ASSEMBLY = "a" * 64
EXECUTION = "b" * 64


def sample_finding():
    return {
        "type": "boundary_spanning",
        "chunk_id": "application_audio:000001",
        "segment": {
            "id": "application_audio:000001:65",
            "source": "application_audio",
            "chunk_id": "application_audio:000001",
            "segment_index": 65,
            "start_seconds": 597.2,
            "end_seconds": 602.0,
            "text": "Example transcript text.",
        },
    }


class ReconciliationIdentityTests(unittest.TestCase):

    def test_deterministic(self):
        finding = sample_finding()
        self.assertEqual(
            finding_identity(ASSEMBLY, finding),
            finding_identity(ASSEMBLY, finding),
        )
        self.assertEqual(
            evidence_identity(EXECUTION, finding),
            evidence_identity(EXECUTION, finding),
        )

    def test_digest_shape(self):
        for digest in (
            finding_identity(ASSEMBLY, sample_finding()),
            evidence_identity(EXECUTION, sample_finding()),
        ):
            self.assertEqual(len(digest), 64)
            self.assertTrue(
                all(c in "0123456789abcdef" for c in digest)
            )

    def test_equivalent_timestamps(self):
        first = sample_finding()
        second = copy.deepcopy(first)
        second["segment"]["start_seconds"] = "597.200000"
        second["segment"]["end_seconds"] = "602.000000"

        self.assertEqual(
            finding_identity(ASSEMBLY, first),
            finding_identity(ASSEMBLY, second),
        )
        self.assertEqual(
            evidence_identity(EXECUTION, first),
            evidence_identity(EXECUTION, second),
        )

    def test_input_not_mutated(self):
        finding = sample_finding()
        original = copy.deepcopy(finding)

        finding_identity(ASSEMBLY, finding)
        evidence_identity(EXECUTION, finding)

        self.assertEqual(finding, original)

    def test_assembly_changes_finding_only(self):
        finding = sample_finding()
        self.assertNotEqual(
            finding_identity(ASSEMBLY, finding),
            finding_identity("c" * 64, finding),
        )
        self.assertEqual(
            evidence_identity(EXECUTION, finding),
            evidence_identity(EXECUTION, finding),
        )

    def test_execution_changes_evidence(self):
        finding = sample_finding()
        self.assertNotEqual(
            evidence_identity(EXECUTION, finding),
            evidence_identity("c" * 64, finding),
        )

    def test_finding_type_changes_finding_only(self):
        first = sample_finding()
        second = copy.deepcopy(first)
        second["type"] = "timing_out_of_bounds"

        self.assertNotEqual(
            finding_identity(ASSEMBLY, first),
            finding_identity(ASSEMBLY, second),
        )
        self.assertEqual(
            evidence_identity(EXECUTION, first),
            evidence_identity(EXECUTION, second),
        )

    def test_invalid_digest(self):
        with self.assertRaises(ValueError):
            finding_identity("invalid", sample_finding())
        with self.assertRaises(ValueError):
            evidence_identity("invalid", sample_finding())

    def test_chunk_mismatch(self):
        finding = sample_finding()
        finding["segment"]["chunk_id"] = "application_audio:000002"

        with self.assertRaises(ValueError):
            finding_identity(ASSEMBLY, finding)

    def test_segment_id_mismatch(self):
        finding = sample_finding()
        finding["segment"]["id"] = "application_audio:000001:999"

        with self.assertRaises(ValueError):
            evidence_identity(EXECUTION, finding)

    def test_submicrosecond_rejected(self):
        finding = sample_finding()
        finding["segment"]["start_seconds"] = "597.2000001"

        with self.assertRaises(ValueError):
            finding_identity(ASSEMBLY, finding)

    def test_nonfinite_rejected(self):
        finding = sample_finding()
        finding["segment"]["end_seconds"] = float("inf")

        with self.assertRaises(ValueError):
            evidence_identity(EXECUTION, finding)

    def test_invalid_interval(self):
        finding = sample_finding()
        finding["segment"]["end_seconds"] = 597.2

        with self.assertRaises(ValueError):
            finding_identity(ASSEMBLY, finding)

    def test_unexpected_finding_field(self):
        finding = sample_finding()
        finding["unexpected"] = True

        with self.assertRaises(ValueError):
            finding_identity(ASSEMBLY, finding)

    def test_text_changes_identity(self):
        first = sample_finding()
        second = copy.deepcopy(first)
        second["segment"]["text"] = "Different transcript text."

        self.assertNotEqual(
            finding_identity(ASSEMBLY, first),
            finding_identity(ASSEMBLY, second),
        )
        self.assertNotEqual(
            evidence_identity(EXECUTION, first),
            evidence_identity(EXECUTION, second),
        )


if __name__ == "__main__":
    unittest.main()
