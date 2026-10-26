import unittest

from processing.chunk_identity import fingerprint
from processing.chunk_planning import plan_chunks

AUDIO = "a" * 64
MODEL = "b" * 64


def identity(**changes):
    chunk = plan_chunks(650, "application_audio")[0]
    options = {
        "audio_sha256": AUDIO,
        "model_sha256": MODEL,
        "engine_version": "1.9.5",
        "parameters": {
            "language": "en",
            "beam_size": 5,
            "temperature": 0,
        },
    }
    options.update(changes)
    return fingerprint(chunk, **options)


class ChunkIdentityTests(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(identity(), identity())

    def test_parameter_order_independent(self):
        first = identity(parameters={"language": "en", "beam_size": 5})
        second = identity(parameters={"beam_size": 5, "language": "en"})
        self.assertEqual(first, second)

    def test_audio_change_invalidates(self):
        self.assertNotEqual(identity(), identity(audio_sha256="c" * 64))

    def test_model_change_invalidates(self):
        self.assertNotEqual(identity(), identity(model_sha256="d" * 64))

    def test_engine_change_invalidates(self):
        self.assertNotEqual(identity(), identity(engine_version="1.9.6"))

    def test_parameter_change_invalidates(self):
        self.assertNotEqual(
            identity(),
            identity(parameters={"language": "en", "beam_size": 8}),
        )

    def test_overlap_change_invalidates(self):
        first = plan_chunks(650, "application_audio",
                            overlap_seconds=2)[0]
        second = plan_chunks(650, "application_audio",
                             overlap_seconds=4)[0]
        self.assertNotEqual(
            fingerprint(first, audio_sha256=AUDIO,
                        model_sha256=MODEL, engine_version="1.9.5",
                        parameters={}),
            fingerprint(second, audio_sha256=AUDIO,
                        model_sha256=MODEL, engine_version="1.9.5",
                        parameters={}),
        )

    def test_invalid_digest_rejected(self):
        with self.assertRaises(ValueError):
            identity(audio_sha256="invalid")

    def test_nonfinite_parameter_rejected(self):
        with self.assertRaises(ValueError):
            identity(parameters={"temperature": float("nan")})


    def test_equivalent_timestamp_representations(self):
        from processing.chunk_identity import canonical_chunk

        chunk = plan_chunks(650, "application_audio")[0]
        equivalent = dict(chunk)
        equivalent["owned_end_seconds"] = 300

        self.assertEqual(
            canonical_chunk(chunk),
            canonical_chunk(equivalent),
        )

    def test_invalid_chunk_id(self):
        from processing.chunk_identity import canonical_chunk

        chunk = plan_chunks(650, "application_audio")[0]
        chunk["chunk_id"] = "wrong"

        with self.assertRaises(ValueError):
            canonical_chunk(chunk)

    def test_invalid_boundary_order(self):
        from processing.chunk_identity import canonical_chunk

        chunk = plan_chunks(650, "application_audio")[0]
        chunk["read_end_seconds"] = 100

        with self.assertRaises(ValueError):
            canonical_chunk(chunk)

    def test_submicrosecond_boundary_rejected(self):
        from processing.chunk_identity import canonical_chunk

        chunk = plan_chunks(650, "application_audio")[0]
        chunk["read_end_seconds"] = 302.0000001

        with self.assertRaises(ValueError):
            canonical_chunk(chunk)

    def test_unknown_parameter_rejected(self):
        with self.assertRaises(ValueError):
            identity(parameters={"unsupported_flag": True})

    def test_boolean_numeric_parameter_rejected(self):
        with self.assertRaises(ValueError):
            identity(parameters={"beam_size": True})

    def test_explicit_defaults_match_implicit_defaults(self):
        from processing.chunk_identity import DEFAULT_PARAMETERS

        self.assertEqual(
            identity(parameters={}),
            identity(parameters=dict(DEFAULT_PARAMETERS)),
        )

    def test_invalid_sample_format_rejected(self):
        with self.assertRaises(ValueError):
            identity(parameters={"sample_format": "float32"})


if __name__ == "__main__":
    unittest.main()
