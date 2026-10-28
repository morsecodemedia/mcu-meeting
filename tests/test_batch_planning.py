import unittest

from processing.batch_planning import (
    duration_microseconds,
    plan_batch,
)


class BatchPlanningTests(unittest.TestCase):

    def test_duration_exact(self):
        self.assertEqual(
            duration_microseconds(48000, 48000),
            1000000,
        )

    def test_duration_fractional(self):
        self.assertEqual(
            duration_microseconds(1, 48000),
            21,
        )

    def test_duration_rounding(self):
        self.assertEqual(
            duration_microseconds(3, 48000),
            63,
        )

    def test_single_source(self):
        result = plan_batch({
            "application_audio": 650000000,
        })

        self.assertEqual(result["total_chunks"], 3)

    def test_dual_source(self):
        result = plan_batch({
            "microphone_audio": 2036900000,
            "application_audio": 2036880000,
        })

        self.assertEqual(result["total_chunks"], 14)
        self.assertEqual(
            [item["source"] for item in result["sources"]],
            ["application_audio", "microphone_audio"],
        )

    def test_independent_durations(self):
        result = plan_batch({
            "application_audio": 600000000,
            "microphone_audio": 650000000,
        })

        self.assertEqual(
            result["sources"][0]["chunk_count"], 2
        )
        self.assertEqual(
            result["sources"][1]["chunk_count"], 3
        )

    def test_no_overlap_ownership(self):
        result = plan_batch({
            "application_audio": 650000000,
        })

        chunks = result["sources"][0]["chunks"]

        for previous, current in zip(chunks, chunks[1:]):
            self.assertEqual(
                previous["owned_end_seconds"],
                current["owned_start_seconds"],
            )

    def test_deterministic(self):
        values = {"application_audio": 650000000}
        self.assertEqual(plan_batch(values), plan_batch(values))

    def test_invalid_source(self):
        with self.assertRaises(ValueError):
            plan_batch({"unknown": 1000000})

    def test_invalid_duration(self):
        with self.assertRaises(ValueError):
            plan_batch({"application_audio": 0})

    def test_boolean_duration_rejected(self):
        with self.assertRaises(ValueError):
            plan_batch({"application_audio": True})

    def test_empty_sources_rejected(self):
        with self.assertRaises(ValueError):
            plan_batch({})


    def test_rounded_duration_never_exceeds_source_frames(self):
        from processing.audio_extraction import _sample_index

        sample_rate = 48000

        for frames in range(1, sample_rate + 1):
            duration_us = duration_microseconds(
                frames, sample_rate
            )

            recovered_frames = _sample_index(
                duration_us, sample_rate
            )

            self.assertLessEqual(
                recovered_frames,
                frames,
                f"Boundary exceeded source at frame {frames}",
            )

            self.assertEqual(
                recovered_frames,
                frames,
                f"Boundary lost source frame {frames}",
            )


if __name__ == "__main__":
    unittest.main()
