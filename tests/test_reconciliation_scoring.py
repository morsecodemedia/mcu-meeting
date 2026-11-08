"""Regression tests for cross-source lexical candidate scoring."""

import copy
import unittest

from processing.reconciliation_scoring import (
    _similarity,
    score_candidate_pairs,
)


def segment(source, index, start, end, text):
    return {
        "id": f"{source}:000000:{index}",
        "source": source,
        "start_seconds": start,
        "end_seconds": end,
        "text": text,
    }


def pair(app_text, mic_text, app_start=0, app_end=10,
         mic_start=0, mic_end=10):
    return [
        segment(
            "application_audio", 0,
            app_start, app_end, app_text,
        ),
        segment(
            "microphone_audio", 0,
            mic_start, mic_end, mic_text,
        ),
    ]


class ReconciliationScoringTests(unittest.TestCase):

    def test_similarity_retains_full_precision(self):
        left = " ".join(f"word{i}" for i in range(10000))
        right = " ".join(f"word{i}" for i in range(9999))
        sequence, _ = _similarity(left, right)
        self.assertNotEqual(sequence, round(sequence, 4))

    def test_identical_text(self):
        result = score_candidate_pairs(
            pair("That sounds good.", "That sounds good.")
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["classification"],
            "strong_duplicate_candidate",
        )
        self.assertEqual(result[0]["sequence_similarity"], 1.0)

    def test_case_and_punctuation_normalization(self):
        sequence, containment = _similarity(
            "Hello, WORLD!",
            "hello world",
        )
        self.assertEqual((sequence, containment), (1.0, 1.0))

    def test_unicode(self):
        sequence, containment = _similarity(
            "Café résumé",
            "CAFÉ RÉSUMÉ",
        )
        self.assertEqual((sequence, containment), (1.0, 1.0))

    def test_empty_text(self):
        self.assertEqual(_similarity("", "Hello"), (0.0, 0.0))
        self.assertEqual(_similarity("", ""), (0.0, 0.0))

    def test_invalid_text(self):
        with self.assertRaises(ValueError):
            _similarity(None, "Hello")

    def test_token_containment(self):
        sequence, containment = _similarity(
            "the quick brown fox",
            "quick brown",
        )
        self.assertEqual(containment, 1.0)
        self.assertLess(sequence, 1.0)

    def test_strong_candidate(self):
        result = score_candidate_pairs(
            pair("one two three", "one two three")
        )
        self.assertEqual(
            result[0]["classification"],
            "strong_duplicate_candidate",
        )

    def test_partial_candidate(self):
        result = score_candidate_pairs(
            pair("one two three four", "one two")
        )
        self.assertEqual(
            result[0]["classification"],
            "partial_duplicate_candidate",
        )

    def test_ambiguous_overlap(self):
        result = score_candidate_pairs(
            pair("one two three", "alpha beta gamma")
        )
        self.assertEqual(
            result[0]["classification"],
            "ambiguous_overlap",
        )

    def test_temporal_overlap_only(self):
        result = score_candidate_pairs(
            pair(
                "one two three",
                "alpha beta gamma",
                app_start=0,
                app_end=10,
                mic_start=8,
                mic_end=18,
            )
        )
        self.assertEqual(
            result[0]["classification"],
            "temporal_overlap_only",
        )

    def test_no_temporal_overlap(self):
        self.assertEqual(
            score_candidate_pairs(
                pair(
                    "same words", "same words",
                    app_start=0, app_end=10,
                    mic_start=10, mic_end=20,
                )
            ),
            [],
        )

    def test_decimal_string_timestamps(self):
        numeric = score_candidate_pairs(
            pair("same words", "same words")
        )
        decimal = score_candidate_pairs(
            pair(
                "same words", "same words",
                app_start="0.000000",
                app_end="10.000000",
                mic_start="0.000000",
                mic_end="10.000000",
            )
        )
        self.assertEqual(numeric, decimal)

    def test_deterministic_order(self):
        segments = pair("same words", "same words")
        self.assertEqual(
            score_candidate_pairs(segments),
            score_candidate_pairs(list(reversed(segments))),
        )

    def test_input_immutability(self):
        segments = pair("same words", "same words")
        original = copy.deepcopy(segments)

        score_candidate_pairs(segments)

        self.assertEqual(segments, original)

    def test_no_automatic_resolution(self):
        result = score_candidate_pairs(
            pair("same words", "same words")
        )
        self.assertNotIn("decision", result[0])
        self.assertNotIn("speaker", result[0])
        self.assertNotIn("remove_segment_id", result[0])

    def test_invalid_timestamp_rejected(self):
        segments = pair("same words", "same words")
        segments[0]["start_seconds"] = "0.0000001"

        with self.assertRaises(ValueError):
            score_candidate_pairs(segments)


if __name__ == "__main__":
    unittest.main()
