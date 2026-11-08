"""Regression tests for deterministic reconciliation review windows."""

import copy
import unittest

from processing.reconciliation_windows import (
    plan_review_windows,
    plan_candidate_pairs,
)


def segment(index, start, end, source="application_audio"):
    return {
        "id": f"{source}:000000:{index}",
        "source": source,
        "start_seconds": start,
        "end_seconds": end,
    }


class ReconciliationWindowTests(unittest.TestCase):

    def test_single_segment(self):
        result = plan_review_windows([segment(0, 1, 5)])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["window_index"], 0)
        self.assertEqual(
            result[0]["owned_segment_ids"],
            ["application_audio:000000:0"],
        )

    def test_exact_midpoint_boundary(self):
        result = plan_review_windows([segment(0, 28, 32)])

        self.assertEqual(result[0]["window_index"], 1)

    def test_midpoint_before_boundary(self):
        result = plan_review_windows([segment(0, 27, 32)])

        self.assertEqual(result[0]["window_index"], 0)

    def test_multiple_windows(self):
        result = plan_review_windows([
            segment(0, 1, 5),
            segment(1, 35, 40),
            segment(2, 65, 70),
        ])

        self.assertEqual(
            [w["window_index"] for w in result],
            [0, 1, 2],
        )

    def test_each_segment_owned_once(self):
        segments = [
            segment(i, i * 7, i * 7 + 4)
            for i in range(20)
        ]

        result = plan_review_windows(segments)

        owned = [
            sid
            for window in result
            for sid in window["owned_segment_ids"]
        ]

        self.assertEqual(len(owned), len(segments))
        self.assertEqual(len(set(owned)), len(segments))

    def test_deterministic_input_order(self):
        segments = [
            segment(0, 1, 5),
            segment(1, 35, 40),
            segment(2, 28, 32),
        ]

        self.assertEqual(
            plan_review_windows(segments),
            plan_review_windows(list(reversed(segments))),
        )

    def test_input_not_mutated(self):
        segments = [segment(0, 1, 5)]
        original = copy.deepcopy(segments)

        plan_review_windows(segments)

        self.assertEqual(segments, original)

    def test_context_padding(self):
        segments = [
            segment(0, 25, 29),
            segment(1, 31, 35),
        ]

        result = plan_review_windows(segments)

        first = next(w for w in result if w["window_index"] == 0)
        second = next(w for w in result if w["window_index"] == 1)

        self.assertIn(
            "application_audio:000000:1",
            first["context_segment_ids"],
        )
        self.assertIn(
            "application_audio:000000:0",
            second["context_segment_ids"],
        )

    def test_empty_segments(self):
        self.assertEqual(plan_review_windows([]), [])

    def test_duplicate_segment_id(self):
        segments = [
            segment(0, 1, 5),
            segment(0, 6, 10),
        ]

        with self.assertRaises(ValueError):
            plan_review_windows(segments)

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            plan_review_windows([segment(0, 5, 5)])

    def test_negative_timestamp(self):
        with self.assertRaises(ValueError):
            plan_review_windows([segment(0, -1, 5)])

    def test_submicrosecond_timestamp(self):
        with self.assertRaises(ValueError):
            plan_review_windows([
                segment(0, "1.0000001", 5)
            ])

    def test_nonfinite_timestamp(self):
        with self.assertRaises(ValueError):
            plan_review_windows([
                segment(0, 1, float("inf"))
            ])

    def test_invalid_segments_type(self):
        with self.assertRaises(ValueError):
            plan_review_windows({})

    def test_invalid_segment_type(self):
        with self.assertRaises(ValueError):
            plan_review_windows([None])


class CandidatePairTests(unittest.TestCase):

    def test_single_overlap(self):
        segments = [
            segment(0, 10, 20),
            segment(0, 15, 25, "microphone_audio"),
        ]
        pairs = plan_candidate_pairs(segments)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["overlap_start_us"], 15_000_000)
        self.assertEqual(pairs[0]["overlap_end_us"], 20_000_000)
        self.assertEqual(pairs[0]["overlap_duration_us"], 5_000_000)
        self.assertEqual(pairs[0]["window_index"], 0)

    def test_no_overlap(self):
        segments = [
            segment(0, 10, 20),
            segment(0, 20, 30, "microphone_audio"),
        ]
        self.assertEqual(plan_candidate_pairs(segments), [])

    def test_same_source_not_paired(self):
        segments = [
            segment(0, 10, 20),
            segment(1, 15, 25),
        ]
        self.assertEqual(plan_candidate_pairs(segments), [])

    def test_overlap_midpoint_boundary(self):
        segments = [
            segment(0, 27, 33),
            segment(0, 29, 35, "microphone_audio"),
        ]
        pairs = plan_candidate_pairs(segments)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["window_index"], 1)

    def test_cross_window_pair_preserved(self):
        segments = [
            segment(0, 25, 35),
            segment(0, 28, 32, "microphone_audio"),
        ]
        pairs = plan_candidate_pairs(segments)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["overlap_start_us"], 28_000_000)
        self.assertEqual(pairs[0]["overlap_end_us"], 32_000_000)

    def test_one_to_many_overlaps(self):
        segments = [
            segment(0, 10, 30),
            segment(0, 12, 18, "microphone_audio"),
            segment(1, 20, 25, "microphone_audio"),
        ]
        pairs = plan_candidate_pairs(segments)

        self.assertEqual(len(pairs), 2)
        self.assertEqual(
            len({p["application_segment_id"] for p in pairs}), 1
        )

    def test_deterministic_input_order(self):
        segments = [
            segment(0, 10, 30),
            segment(0, 12, 18, "microphone_audio"),
            segment(1, 20, 25, "microphone_audio"),
        ]
        self.assertEqual(
            plan_candidate_pairs(segments),
            plan_candidate_pairs(list(reversed(segments))),
        )

    def test_input_immutability(self):
        segments = [
            segment(0, 10, 20),
            segment(0, 15, 25, "microphone_audio"),
        ]
        original = copy.deepcopy(segments)

        plan_candidate_pairs(segments)

        self.assertEqual(segments, original)

    def test_duplicate_segment_id_rejected(self):
        segments = [
            segment(0, 10, 20),
            segment(0, 15, 25),
        ]
        with self.assertRaises(ValueError):
            plan_candidate_pairs(segments)

    def test_invalid_interval_rejected(self):
        segments = [
            segment(0, 20, 10),
            segment(0, 15, 25, "microphone_audio"),
        ]
        with self.assertRaises(ValueError):
            plan_candidate_pairs(segments)

    def test_submicrosecond_rejected(self):
        segments = [
            segment(0, "10.0000001", 20),
            segment(0, 15, 25, "microphone_audio"),
        ]
        with self.assertRaises(ValueError):
            plan_candidate_pairs(segments)

    def test_empty_input(self):
        self.assertEqual(plan_candidate_pairs([]), [])


class RecordingSourceValidationTests(unittest.TestCase):

    def test_unknown_source_rejected_by_window_planner(self):
        segments = [
            segment(0, 10, 20, "unknown_audio"),
        ]

        with self.assertRaises(ValueError):
            plan_review_windows(segments)

    def test_unknown_source_rejected_by_pair_planner(self):
        segments = [
            segment(0, 10, 20),
            segment(0, 15, 25, "unknown_audio"),
        ]

        with self.assertRaises(ValueError):
            plan_candidate_pairs(segments)


class SegmentIdentityValidationTests(unittest.TestCase):

    def test_source_id_mismatch_rejected(self):
        item = segment(0, 10, 20)
        item["source"] = "microphone_audio"

        with self.assertRaises(ValueError):
            plan_review_windows([item])

    def test_source_id_mismatch_rejected_by_pair_planner(self):
        item = segment(0, 10, 20)
        item["source"] = "microphone_audio"

        with self.assertRaises(ValueError):
            plan_candidate_pairs([item])

    def test_malformed_segment_id_rejected(self):
        item = segment(0, 10, 20)
        item["id"] = "application_audio:bad:0"

        with self.assertRaises(ValueError):
            plan_review_windows([item])

    def test_negative_segment_index_rejected(self):
        item = segment(0, 10, 20)
        item["id"] = "application_audio:000000:-1"

        with self.assertRaises(ValueError):
            plan_review_windows([item])

    def test_valid_microphone_identity(self):
        item = segment(42, 10, 20, "microphone_audio")
        result = plan_review_windows([item])

        self.assertEqual(len(result), 1)


class SegmentMetadataValidationTests(unittest.TestCase):

    def test_valid_metadata(self):
        item = segment(3, 10, 20)
        item["chunk_id"] = "application_audio:000000"
        item["segment_index"] = 3
        self.assertEqual(len(plan_review_windows([item])), 1)

    def test_chunk_mismatch_rejected(self):
        item = segment(3, 10, 20)
        item["chunk_id"] = "application_audio:000001"
        with self.assertRaises(ValueError):
            plan_review_windows([item])

    def test_segment_index_mismatch_rejected(self):
        item = segment(3, 10, 20)
        item["segment_index"] = 4
        with self.assertRaises(ValueError):
            plan_candidate_pairs([item])


if __name__ == "__main__":
    unittest.main()
