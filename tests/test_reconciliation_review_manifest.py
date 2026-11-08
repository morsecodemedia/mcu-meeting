"""Regression tests for pure reconciliation review manifests."""

import copy
import unittest
from unittest.mock import patch

from processing.reconciliation_candidate_identity import candidate_identity
from processing.reconciliation_review_manifest import (
    build_review_manifest,
)

ASSEMBLY = "a" * 64


def segment(source, index, start, end, text):
    return {
        "id": f"{source}:000000:{index}",
        "chunk_id": f"{source}:000000",
        "segment_index": index,
        "source": source,
        "start_seconds": start,
        "end_seconds": end,
        "text": text,
    }


def fixture():
    return [
        segment("application_audio", 0, 10, 20, "That sounds good."),
        segment("microphone_audio", 0, 12, 22, "That sounds good."),
        segment("application_audio", 1, 40, 45, "Different speech."),
        segment("microphone_audio", 1, 41, 46, "Another statement."),
    ]


class ReconciliationReviewManifestTests(unittest.TestCase):

    def setUp(self):
        self.segments = fixture()

    def build(self):
        return build_review_manifest(ASSEMBLY, self.segments)

    def test_success(self):
        result = self.build()

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["candidate_identity_version"], 1)
        self.assertEqual(result["scoring_algorithm_version"], 1)
        self.assertEqual(result["segment_count"], 4)
        self.assertEqual(result["window_count"], 2)
        self.assertEqual(result["candidate_count"], 2)

    def test_deterministic(self):
        self.assertEqual(self.build(), self.build())

    def test_input_order_independence(self):
        expected = self.build()

        self.segments.reverse()

        self.assertEqual(self.build(), expected)

    def test_input_immutability(self):
        original = copy.deepcopy(self.segments)

        self.build()

        self.assertEqual(self.segments, original)

    def test_unique_segment_ownership(self):
        result = self.build()

        owned = [
            sid
            for window in result["windows"]
            for sid in window["owned_segment_ids"]
        ]

        self.assertEqual(len(owned), 4)
        self.assertEqual(len(set(owned)), 4)

    def test_unique_candidate_identity(self):
        result = self.build()

        ids = [
            candidate["candidate_id"]
            for window in result["windows"]
            for candidate in window["candidates"]
        ]

        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_candidate_identity_matches_source(self):
        result = self.build()

        for window in result["windows"]:
            for candidate in window["candidates"]:
                self.assertEqual(
                    candidate["candidate_id"],
                    candidate_identity(ASSEMBLY, candidate),
                )

    def test_candidate_ownership(self):
        result = self.build()

        for window in result["windows"]:
            for candidate in window["candidates"]:
                midpoint = (
                    candidate["overlap_start_us"]
                    + candidate["overlap_end_us"]
                ) // 2

                self.assertEqual(
                    window["window_index"],
                    midpoint // 30_000_000,
                )

    def test_no_transcript_text_copied(self):
        result = self.build()

        for window in result["windows"]:
            for candidate in window["candidates"]:
                self.assertNotIn("text", candidate)
                self.assertNotIn("application_text", candidate)
                self.assertNotIn("microphone_text", candidate)

    def test_no_verification_claim(self):
        self.assertNotIn("verification_level", self.build())

    def test_no_automatic_resolution(self):
        result = self.build()

        for window in result["windows"]:
            for candidate in window["candidates"]:
                self.assertNotIn("decision", candidate)
                self.assertNotIn("speaker", candidate)
                self.assertNotIn("remove_segment_id", candidate)

    def test_invalid_assembly(self):
        with self.assertRaises(ValueError):
            build_review_manifest("invalid", self.segments)

    def test_duplicate_segment_rejected(self):
        self.segments.append(copy.deepcopy(self.segments[0]))

        with self.assertRaises(ValueError):
            self.build()

    def test_invalid_timestamp_rejected(self):
        self.segments[0]["start_seconds"] = "10.0000001"

        with self.assertRaises(ValueError):
            self.build()

    def test_missing_window_rejected(self):
        from processing import reconciliation_review_manifest as module

        original = module.plan_review_windows

        def missing_window(segments):
            return original(segments)[:-1]

        with patch.object(module, "plan_review_windows", missing_window):
            with self.assertRaises(ValueError):
                self.build()

    def test_duplicate_candidate_rejected(self):
        from processing import reconciliation_review_manifest as module

        original = module.score_candidate_pairs

        def duplicate(segments):
            result = original(segments)
            return result + [copy.deepcopy(result[0])]

        with patch.object(module, "score_candidate_pairs", duplicate):
            with self.assertRaises(ValueError):
                self.build()

    def test_candidate_owner_mismatch_rejected(self):
        from processing import reconciliation_review_manifest as module

        original = module.score_candidate_pairs

        def wrong_owner(segments):
            result = original(segments)
            result[0]["window_index"] += 1
            return result

        with patch.object(module, "score_candidate_pairs", wrong_owner):
            with self.assertRaises(ValueError):
                self.build()

    def test_classification_counts(self):
        result = self.build()

        self.assertEqual(
            sum(result["classification_counts"].values()),
            result["candidate_count"],
        )


class CandidateEvidenceConsistencyTests(unittest.TestCase):

    def setUp(self):
        self.segments = fixture()

    def build_with_mutation(self, mutate):
        from processing import reconciliation_review_manifest as module

        original = module.score_candidate_pairs

        def modified(segments):
            result = original(segments)
            mutate(result)
            return result

        with patch.object(module, "score_candidate_pairs", modified):
            return build_review_manifest(ASSEMBLY, self.segments)

    def test_missing_segment_rejected(self):
        def mutate(pairs):
            pairs[0]["application_segment_id"] = (
                "application_audio:999999:0"
            )

        with self.assertRaises(ValueError):
            self.build_with_mutation(mutate)

    def test_incorrect_overlap_start_rejected(self):
        def mutate(pairs):
            pairs[0]["overlap_start_us"] += 1

        with self.assertRaises(ValueError):
            self.build_with_mutation(mutate)

    def test_incorrect_overlap_end_rejected(self):
        def mutate(pairs):
            pairs[0]["overlap_end_us"] -= 1

        with self.assertRaises(ValueError):
            self.build_with_mutation(mutate)

    def test_incorrect_overlap_duration_rejected(self):
        def mutate(pairs):
            pairs[0]["overlap_duration_us"] += 1

        with self.assertRaises(ValueError):
            self.build_with_mutation(mutate)

    def test_duplicate_segment_pair_rejected(self):
        def mutate(pairs):
            duplicate = copy.deepcopy(pairs[0])
            duplicate["overlap_start_us"] += 1
            pairs.append(duplicate)

        with self.assertRaises(ValueError):
            self.build_with_mutation(mutate)


if __name__ == "__main__":
    unittest.main()
