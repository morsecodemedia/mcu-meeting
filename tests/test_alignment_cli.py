import unittest

from processing.alignment_cli import analysis_positions


class AlignmentCLITests(unittest.TestCase):

    def test_short_recording_has_no_windows(self):
        self.assertEqual(analysis_positions(5), [])

    def test_exact_window_duration(self):
        self.assertEqual(analysis_positions(12), [0])

    def test_positions_stay_in_bounds(self):
        for duration in (30, 120, 600, 2036):
            with self.subTest(duration=duration):
                positions = analysis_positions(duration)

                self.assertTrue(positions)
                self.assertLessEqual(len(positions), 16)
                self.assertTrue(
                    all(0 <= p <= duration - 12 for p in positions)
                )


if __name__ == "__main__":
    unittest.main()
