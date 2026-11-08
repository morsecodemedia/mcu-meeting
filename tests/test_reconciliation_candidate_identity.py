"""Regression tests for assembly-scoped candidate identities."""

import copy
import unittest

from processing.reconciliation_candidate_identity import (
    candidate_identity,
)

ASSEMBLY = "a" * 64


def candidate():
    return {
        "application_segment_id": "application_audio:000001:65",
        "microphone_segment_id": "microphone_audio:000001:42",
        "overlap_start_us": 597_200_000,
        "overlap_end_us": 602_000_000,
        "overlap_duration_us": 4_800_000,
        "window_index": 19,
        "classification": "strong_duplicate_candidate",
        "sequence_similarity": 0.95,
        "token_containment": 0.98,
        "temporal_ratio": 0.99,
    }


class CandidateIdentityTests(unittest.TestCase):

    def test_deterministic(self):
        item = candidate()
        self.assertEqual(
            candidate_identity(ASSEMBLY, item),
            candidate_identity(ASSEMBLY, item),
        )

    def test_digest_format(self):
        digest = candidate_identity(ASSEMBLY, candidate())
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in digest))

    def test_assembly_scoping(self):
        self.assertNotEqual(
            candidate_identity(ASSEMBLY, candidate()),
            candidate_identity("b" * 64, candidate()),
        )

    def test_scoring_independence(self):
        first = candidate()
        second = copy.deepcopy(first)
        second["classification"] = "ambiguous_overlap"
        second["sequence_similarity"] = 0.0
        second["token_containment"] = 0.0
        second["temporal_ratio"] = 0.0

        self.assertEqual(
            candidate_identity(ASSEMBLY, first),
            candidate_identity(ASSEMBLY, second),
        )

    def test_window_independence(self):
        first = candidate()
        second = copy.deepcopy(first)
        second["window_index"] = 99

        self.assertEqual(
            candidate_identity(ASSEMBLY, first),
            candidate_identity(ASSEMBLY, second),
        )

    def test_input_immutability(self):
        item = candidate()
        original = copy.deepcopy(item)

        candidate_identity(ASSEMBLY, item)

        self.assertEqual(item, original)

    def test_invalid_assembly_digest(self):
        with self.assertRaises(ValueError):
            candidate_identity("invalid", candidate())

    def test_invalid_candidate_type(self):
        with self.assertRaises(ValueError):
            candidate_identity(ASSEMBLY, [])

    def test_invalid_application_id(self):
        item = candidate()
        item["application_segment_id"] = "microphone_audio:000001:65"

        with self.assertRaises(ValueError):
            candidate_identity(ASSEMBLY, item)

    def test_invalid_microphone_id(self):
        item = candidate()
        item["microphone_segment_id"] = "application_audio:000001:42"

        with self.assertRaises(ValueError):
            candidate_identity(ASSEMBLY, item)

    def test_malformed_segment_id(self):
        item = candidate()
        item["application_segment_id"] = "application_audio:bad:65"

        with self.assertRaises(ValueError):
            candidate_identity(ASSEMBLY, item)

    def test_negative_overlap_start(self):
        item = candidate()
        item["overlap_start_us"] = -1

        with self.assertRaises(ValueError):
            candidate_identity(ASSEMBLY, item)

    def test_invalid_overlap_interval(self):
        item = candidate()
        item["overlap_end_us"] = item["overlap_start_us"]

        with self.assertRaises(ValueError):
            candidate_identity(ASSEMBLY, item)

    def test_boolean_timestamp_rejected(self):
        item = candidate()
        item["overlap_start_us"] = True

        with self.assertRaises(ValueError):
            candidate_identity(ASSEMBLY, item)

    def test_text_not_part_of_identity(self):
        first = candidate()
        second = copy.deepcopy(first)
        second["application_text"] = "Different text"
        second["microphone_text"] = "Other text"

        self.assertEqual(
            candidate_identity(ASSEMBLY, first),
            candidate_identity(ASSEMBLY, second),
        )


if __name__ == "__main__":
    unittest.main()
