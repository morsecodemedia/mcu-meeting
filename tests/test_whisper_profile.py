import unittest

from processing.whisper_profile import WhisperProfile


class WhisperProfileTests(unittest.TestCase):

    def test_defaults(self):
        profile = WhisperProfile()
        self.assertEqual(profile.language, "en")
        self.assertEqual(profile.beam_size, 5)
        self.assertEqual(profile.best_of, 5)

    def test_deterministic_serialization(self):
        first = WhisperProfile().canonical_json()
        second = WhisperProfile().canonical_json()
        self.assertEqual(first, second)

    def test_equivalent_decimal_representations(self):
        first = WhisperProfile(temperature=0.2)
        second = WhisperProfile(temperature=0.20)
        self.assertEqual(first.canonical(), second.canonical())

    def test_profile_changes_identity(self):
        first = WhisperProfile()
        second = WhisperProfile(beam_size=8)
        self.assertNotEqual(first.canonical_json(), second.canonical_json())

    def test_cli_arguments(self):
        args = WhisperProfile().cli_arguments()
        self.assertEqual(args[args.index("-bs") + 1], "5")
        self.assertEqual(args[args.index("-bo") + 1], "5")
        self.assertEqual(args[args.index("-tp") + 1], "0")

    def test_prompt_included(self):
        args = WhisperProfile(
            initial_prompt="Technical discussion."
        ).cli_arguments()
        self.assertIn("--prompt", args)
        self.assertIn("Technical discussion.", args)

    def test_no_fallback(self):
        args = WhisperProfile(
            no_fallback=True
        ).cli_arguments()
        self.assertIn("-nf", args)

    def test_flash_attention_disabled(self):
        args = WhisperProfile(
            flash_attention=False
        ).cli_arguments()
        self.assertIn("-nfa", args)

    def test_invalid_temperature(self):
        with self.assertRaises(ValueError):
            WhisperProfile(temperature=1.5)

    def test_invalid_beam_size(self):
        with self.assertRaises(ValueError):
            WhisperProfile(beam_size=0)

    def test_boolean_numeric_rejected(self):
        with self.assertRaises(ValueError):
            WhisperProfile(best_of=True)

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            WhisperProfile(entropy_threshold=float("nan"))

    def test_vad_requires_separate_profile(self):
        with self.assertRaises(ValueError):
            WhisperProfile(vad=True).cli_arguments()


if __name__ == "__main__":
    unittest.main()
