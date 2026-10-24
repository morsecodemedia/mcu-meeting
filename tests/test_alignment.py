import unittest
import numpy as np
from processing.alignment import peak_quality, robust_consensus


class AlignmentTests(unittest.TestCase):
    def test_positive_offset(self):
        rng = np.random.default_rng(42)
        a = rng.normal(size=16000)
        b = np.r_[np.zeros(80), a[:-80]]
        result = peak_quality(a, b, 8000)
        self.assertEqual(result["status"], "estimated")
        self.assertAlmostEqual(result["lag_seconds"], .01, places=4)

    def test_negative_offset(self):
        rng = np.random.default_rng(43)
        a = rng.normal(size=16000)
        b = np.r_[a[120:], np.zeros(120)]
        result = peak_quality(a, b, 8000)
        self.assertEqual(result["status"], "estimated")
        self.assertAlmostEqual(result["lag_seconds"], -.015, places=4)

    def test_silence(self):
        result = peak_quality(np.zeros(8000), np.zeros(8000), 8000)
        self.assertEqual(result["status"], "unknown")

    def test_periodic_signal(self):
        t = np.arange(16000) / 8000
        a = np.sin(2 * np.pi * 200 * t)
        result = peak_quality(a, np.roll(a, 80), 8000)
        self.assertEqual(result["status"], "unknown")

    def test_competing_echoes(self):
        rng = np.random.default_rng(101)
        a = rng.normal(size=16000)
        b = np.r_[np.zeros(80), a[:-80]]
        b += np.r_[np.zeros(400), a[:-400]]
        self.assertEqual(peak_quality(a, b, 8000)["status"], "unknown")

    def test_consensus_outlier(self):
        data = [
            {"status": "estimated", "offset_seconds": x}
            for x in (.008, .009, .010, .065)
        ] + [{"status": "unknown"}]
        result = robust_consensus(data)
        self.assertEqual(result["accepted_windows"], 3)
        self.assertEqual(result["rejected_windows"], 2)

    def test_insufficient_consensus(self):
        result = robust_consensus([{"status": "unknown"}])
        self.assertEqual(result["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
