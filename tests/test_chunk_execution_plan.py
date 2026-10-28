import copy
import unittest

from processing.chunk_execution_plan import plan_chunk_execution
from processing.chunk_planning import plan_chunks
from processing.whisper_profile import WhisperProfile

AUDIO = "a" * 64
MODEL = "b" * 64


def plan(*, chunk=None, profile=None, **changes):
    if chunk is None:
        chunk = plan_chunks(650, "application_audio")[0]

    if profile is None:
        profile = WhisperProfile()

    options = {
        "audio_sha256": AUDIO,
        "model_sha256": MODEL,
        "ffmpeg_version": "9.0.1",
        "whisper_version": "1.9.5",
        "profile": profile,
    }
    options.update(changes)

    return plan_chunk_execution(chunk, **options)


class ChunkExecutionPlanTests(unittest.TestCase):

    def test_deterministic(self):
        self.assertEqual(plan(), plan())

    def test_identity_matches_path(self):
        result = plan()
        fingerprint = result["fingerprint"]

        for path in result["artifacts"].values():
            self.assertIn(f"/{fingerprint}/", path)

    def test_checkpoint_layout(self):
        result = plan()

        self.assertTrue(
            result["artifacts"]["checkpoint"].endswith(
                "/application_audio/000000/"
                + result["fingerprint"]
                + "/checkpoint.json"
            )
        )

    def test_source_separation(self):
        application = plan(
            chunk=plan_chunks(60, "application_audio")[0]
        )
        microphone = plan(
            chunk=plan_chunks(60, "microphone_audio")[0]
        )

        self.assertNotEqual(
            application["fingerprint"],
            microphone["fingerprint"],
        )

    def test_profile_change_invalidates(self):
        self.assertNotEqual(
            plan()["fingerprint"],
            plan(profile=WhisperProfile(beam_size=8))["fingerprint"],
        )

    def test_ffmpeg_change_invalidates(self):
        self.assertNotEqual(
            plan()["fingerprint"],
            plan(ffmpeg_version="9.0.2")["fingerprint"],
        )

    def test_overlap_change_invalidates(self):
        first = plan(
            chunk=plan_chunks(
                650, "application_audio", overlap_seconds=2
            )[0]
        )
        second = plan(
            chunk=plan_chunks(
                650, "application_audio", overlap_seconds=4
            )[0]
        )

        self.assertNotEqual(
            first["fingerprint"],
            second["fingerprint"],
        )

    def test_timeline_boundaries(self):
        result = plan(
            chunk=plan_chunks(650, "application_audio")[1]
        )

        self.assertEqual(
            result["owned_interval_us"],
            {"start": 300000000, "end": 600000000},
        )
        self.assertEqual(
            result["read_interval_us"],
            {"start": 300000000, "end": 602000000},
        )

    def test_no_absolute_paths(self):
        result = plan()

        for path in result["artifacts"].values():
            self.assertFalse(path.startswith("/"))
            self.assertNotIn("/Users/", path)

    def test_input_not_mutated(self):
        chunk = plan_chunks(650, "application_audio")[0]
        original = copy.deepcopy(chunk)

        plan(chunk=chunk)

        self.assertEqual(chunk, original)

    def test_invalid_digest(self):
        with self.assertRaises(ValueError):
            plan(audio_sha256="invalid")

    def test_invalid_profile(self):
        with self.assertRaises(ValueError):
            plan(profile={})


if __name__ == "__main__":
    unittest.main()
