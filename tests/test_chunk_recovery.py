import copy
import unittest

from processing.chunk_checkpoint import (
    new_checkpoint,
    transition_checkpoint,
)
from processing.chunk_recovery import classify_checkpoint

FINGERPRINT = "a" * 64
CHUNK_ID = "application_audio:000000"

ARTIFACTS = [
    {
        "kind": "whisper_json",
        "path": "whisper.json",
        "sha256": "b" * 64,
    },
    {
        "kind": "normalized_json",
        "path": "normalized.json",
        "sha256": "c" * 64,
    },
]


def checkpoint(state, retryable=False):
    item = new_checkpoint(FINGERPRINT, CHUNK_ID)

    if state == "pending":
        return item

    item = transition_checkpoint(item, "running")

    if state == "running":
        return item

    if state == "failed":
        return transition_checkpoint(
            item,
            "failed",
            retryable=retryable,
            error="synthetic failure",
        )

    if state == "completed":
        return transition_checkpoint(
            item,
            "completed",
            artifacts=ARTIFACTS,
        )

    raise ValueError(state)


class RecoveryClassificationTests(unittest.TestCase):

    def test_pending(self):
        result = classify_checkpoint(checkpoint("pending"))
        self.assertEqual(result["classification"], "not_started")

    def test_running_active(self):
        result = classify_checkpoint(
            checkpoint("running"),
            lock_status="held",
        )
        self.assertEqual(result["classification"], "active")

    def test_running_interrupted(self):
        result = classify_checkpoint(
            checkpoint("running"),
            lock_status="available",
        )
        self.assertEqual(result["classification"], "interrupted")

    def test_running_unknown_lock(self):
        result = classify_checkpoint(
            checkpoint("running"),
            lock_status="unknown",
        )
        self.assertEqual(result["classification"], "indeterminate")

    def test_retryable_failure(self):
        result = classify_checkpoint(
            checkpoint("failed", retryable=True)
        )
        self.assertEqual(result["classification"], "retryable_failure")

    def test_nonretryable_failure(self):
        result = classify_checkpoint(
            checkpoint("failed", retryable=False)
        )
        self.assertEqual(result["classification"], "manual_intervention")

    def test_completed_verified(self):
        result = classify_checkpoint(
            checkpoint("completed"),
            artifact_status="verified",
        )
        self.assertEqual(result["classification"], "verified_complete")

    def test_completed_invalid(self):
        result = classify_checkpoint(
            checkpoint("completed"),
            artifact_status="invalid",
        )
        self.assertEqual(result["classification"], "integrity_failure")

    def test_completed_unverified(self):
        result = classify_checkpoint(checkpoint("completed"))
        self.assertEqual(result["classification"], "indeterminate")

    def test_invalid_checkpoint(self):
        item = checkpoint("pending")
        item["fingerprint"] = "invalid"

        result = classify_checkpoint(item)
        self.assertEqual(result["classification"], "invalid_checkpoint")

    def test_input_not_mutated(self):
        item = checkpoint("running")
        original = copy.deepcopy(item)

        classify_checkpoint(item, lock_status="available")

        self.assertEqual(item, original)

    def test_invalid_evidence_rejected(self):
        with self.assertRaises(ValueError):
            classify_checkpoint(
                checkpoint("running"),
                lock_status="definitely_running",
            )

        with self.assertRaises(ValueError):
            classify_checkpoint(
                checkpoint("completed"),
                artifact_status="probably_valid",
            )


if __name__ == "__main__":
    unittest.main()
