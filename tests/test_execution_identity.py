import copy
import unittest

from processing.chunk_planning import plan_chunks
from processing.execution_identity import (
    execution_fingerprint,
    execution_identity,
)
from processing.whisper_profile import WhisperProfile

AUDIO = "a" * 64
MODEL = "b" * 64


def fingerprint(*, chunk=None, profile=None, **changes):
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

    return execution_fingerprint(chunk, **options)


class ExecutionIdentityTests(unittest.TestCase):

    def test_deterministic(self):
        self.assertEqual(fingerprint(), fingerprint())

    def test_digest_shape(self):
        self.assertEqual(len(fingerprint()), 64)

    def test_audio_change(self):
        self.assertNotEqual(
            fingerprint(),
            fingerprint(audio_sha256="c" * 64),
        )

    def test_model_change(self):
        self.assertNotEqual(
            fingerprint(),
            fingerprint(model_sha256="d" * 64),
        )

    def test_ffmpeg_version_change(self):
        self.assertNotEqual(
            fingerprint(),
            fingerprint(ffmpeg_version="9.0.2"),
        )

    def test_whisper_version_change(self):
        self.assertNotEqual(
            fingerprint(),
            fingerprint(whisper_version="1.9.6"),
        )

    def test_profile_change(self):
        self.assertNotEqual(
            fingerprint(),
            fingerprint(profile=WhisperProfile(beam_size=8)),
        )

    def test_prompt_change(self):
        self.assertNotEqual(
            fingerprint(),
            fingerprint(
                profile=WhisperProfile(initial_prompt="Medical terms.")
            ),
        )

    def test_overlap_change(self):
        first = plan_chunks(
            650, "application_audio", overlap_seconds=2
        )[0]
        second = plan_chunks(
            650, "application_audio", overlap_seconds=4
        )[0]

        self.assertNotEqual(
            fingerprint(chunk=first),
            fingerprint(chunk=second),
        )

    def test_source_change(self):
        application = plan_chunks(
            60, "application_audio"
        )[0]
        microphone = plan_chunks(
            60, "microphone_audio"
        )[0]

        self.assertNotEqual(
            fingerprint(chunk=application),
            fingerprint(chunk=microphone),
        )

    def test_input_not_mutated(self):
        chunk = plan_chunks(650, "application_audio")[0]
        original = copy.deepcopy(chunk)

        fingerprint(chunk=chunk)

        self.assertEqual(chunk, original)

    def test_invalid_model_digest(self):
        with self.assertRaises(ValueError):
            fingerprint(model_sha256="invalid")

    def test_invalid_version(self):
        with self.assertRaises(ValueError):
            fingerprint(ffmpeg_version="unknown")

    def test_invalid_profile(self):
        with self.assertRaises(ValueError):
            fingerprint(profile={})

    def test_unsupported_vad(self):
        with self.assertRaises(ValueError):
            fingerprint(profile=WhisperProfile(vad=True))

    def test_identity_structure(self):
        chunk = plan_chunks(60, "application_audio")[0]

        result = execution_identity(
            chunk,
            audio_sha256=AUDIO,
            model_sha256=MODEL,
            ffmpeg_version="9.0.1",
            whisper_version="1.9.5",
            profile=WhisperProfile(),
        )

        self.assertEqual(result["identity_version"], 3)
        self.assertEqual(result["planner_version"], 1)
        self.assertEqual(result["extraction_version"], 1)
        self.assertEqual(
            result["whisper"]["profile"]["profile_version"], 1
        )


if __name__ == "__main__":
    unittest.main()
