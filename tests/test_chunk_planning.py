import unittest

from processing.chunk_planning import plan_chunks


class ChunkPlanningTests(unittest.TestCase):

    def test_short_recording(self):
        chunks = plan_chunks(60, "application_audio")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["owned_end_seconds"], 60)
        self.assertEqual(chunks[0]["read_end_seconds"], 60)

    def test_exact_boundary(self):
        chunks = plan_chunks(600, "application_audio")
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[-1]["owned_end_seconds"], 600)

    def test_partial_final_chunk(self):
        chunks = plan_chunks(2036.88, "application_audio")
        self.assertEqual(len(chunks), 7)
        self.assertEqual(
            chunks[-1]["owned_end_seconds"], 2036.88
        )

    def test_independent_source_durations(self):
        app = plan_chunks(2036.88, "application_audio")
        mic = plan_chunks(2036.90, "microphone_audio")
        self.assertEqual(len(app), len(mic))
        self.assertNotEqual(
            app[-1]["owned_end_seconds"],
            mic[-1]["owned_end_seconds"],
        )

    def test_complete_coverage_without_gaps(self):
        for duration in (0.1, 60, 300, 600, 2036.88):
            with self.subTest(duration=duration):
                chunks = plan_chunks(duration, "application_audio")
                self.assertEqual(
                    chunks[0]["owned_start_seconds"], 0
                )
                self.assertEqual(
                    chunks[-1]["owned_end_seconds"], duration
                )
                for previous, current in zip(chunks, chunks[1:]):
                    self.assertEqual(
                        previous["owned_end_seconds"],
                        current["owned_start_seconds"],
                    )

    def test_overlap_is_context_only(self):
        chunks = plan_chunks(650, "application_audio")
        self.assertEqual(chunks[0]["owned_end_seconds"], 300)
        self.assertEqual(chunks[0]["read_end_seconds"], 302)
        self.assertEqual(chunks[1]["owned_start_seconds"], 300)

    def test_deterministic(self):
        first = plan_chunks(2036.88, "application_audio")
        second = plan_chunks(2036.88, "application_audio")
        self.assertEqual(first, second)

    def test_invalid_configuration(self):
        cases = [
            (0, 300, 2),
            (-1, 300, 2),
            (float("nan"), 300, 2),
            (60, 0, 0),
            (60, 300, 300),
            (60, 300, -1),
            (60, 300, float("inf")),
        ]
        for duration, chunk, overlap in cases:
            with self.subTest(values=(duration, chunk, overlap)):
                with self.assertRaises(ValueError):
                    plan_chunks(
                        duration,
                        "application_audio",
                        chunk_seconds=chunk,
                        overlap_seconds=overlap,
                    )

    def test_invalid_source(self):
        with self.assertRaises(ValueError):
            plan_chunks(60, "unknown")


if __name__ == "__main__":
    unittest.main()
