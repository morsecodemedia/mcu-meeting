import unittest

from processing.chunk_checkpoint import (
    new_checkpoint,
    transition_checkpoint,
    validate_checkpoint,
)

FINGERPRINT = "a" * 64
CHUNK_ID = "application_audio:000000"

ARTIFACTS = [
    {"kind": "whisper_json", "path": "whisper.json", "sha256": "b" * 64},
    {"kind": "normalized_json", "path": "normalized.json", "sha256": "c" * 64},
]


class CheckpointTests(unittest.TestCase):

    def test_new_checkpoint(self):
        item = new_checkpoint(FINGERPRINT, CHUNK_ID)
        self.assertEqual(item["state"], "pending")
        self.assertEqual(item["attempts"], 0)

    def test_successful_lifecycle(self):
        item = new_checkpoint(FINGERPRINT, CHUNK_ID)
        item = transition_checkpoint(item, "running")
        item = transition_checkpoint(item, "completed", artifacts=ARTIFACTS)
        self.assertEqual(item["state"], "completed")
        self.assertEqual(item["attempts"], 1)

    def test_retryable_failure(self):
        item = new_checkpoint(FINGERPRINT, CHUNK_ID)
        item = transition_checkpoint(item, "running")
        item = transition_checkpoint(
            item, "failed", retryable=True, error="synthetic failure"
        )
        item = transition_checkpoint(item, "running")
        self.assertEqual(item["attempts"], 2)

    def test_nonretryable_failure(self):
        item = transition_checkpoint(
            transition_checkpoint(
                new_checkpoint(FINGERPRINT, CHUNK_ID), "running"
            ),
            "failed",
            retryable=False,
            error="permanent failure",
        )
        with self.assertRaises(ValueError):
            transition_checkpoint(item, "running")

    def test_input_not_mutated(self):
        original = new_checkpoint(FINGERPRINT, CHUNK_ID)
        transition_checkpoint(original, "running")
        self.assertEqual(original["state"], "pending")

    def test_completed_requires_artifacts(self):
        item = transition_checkpoint(
            new_checkpoint(FINGERPRINT, CHUNK_ID), "running"
        )
        with self.assertRaises(ValueError):
            transition_checkpoint(item, "completed")

    def test_invalid_fingerprint(self):
        with self.assertRaises(ValueError):
            new_checkpoint("invalid", CHUNK_ID)

    def test_invalid_chunk_id(self):
        with self.assertRaises(ValueError):
            new_checkpoint(FINGERPRINT, "../invalid")

    def test_invalid_artifact_path(self):
        item = transition_checkpoint(
            new_checkpoint(FINGERPRINT, CHUNK_ID), "running"
        )
        invalid = [
            {"kind": "whisper_json", "path": "../secret", "sha256": "b" * 64},
            ARTIFACTS[1],
        ]
        with self.assertRaises(ValueError):
            transition_checkpoint(item, "completed", artifacts=invalid)

    def test_duplicate_artifact_kind(self):
        item = transition_checkpoint(
            new_checkpoint(FINGERPRINT, CHUNK_ID), "running"
        )
        invalid = [ARTIFACTS[0], ARTIFACTS[0]]
        with self.assertRaises(ValueError):
            transition_checkpoint(item, "completed", artifacts=invalid)

    def test_boolean_attempt_rejected(self):
        item = new_checkpoint(FINGERPRINT, CHUNK_ID)
        item["attempts"] = True
        with self.assertRaises(ValueError):
            validate_checkpoint(item)

    def test_invalid_transition(self):
        item = new_checkpoint(FINGERPRINT, CHUNK_ID)
        with self.assertRaises(ValueError):
            transition_checkpoint(item, "completed")


if __name__ == "__main__":
    unittest.main()
