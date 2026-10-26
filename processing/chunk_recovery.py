"""Pure recovery classification for transcription checkpoints."""

from __future__ import annotations

from processing.chunk_checkpoint import validate_checkpoint

LOCK_STATUSES = frozenset({
    "held",
    "available",
    "unknown",
})

ARTIFACT_STATUSES = frozenset({
    "verified",
    "invalid",
    "unknown",
})


def classify_checkpoint(
    checkpoint,
    *,
    lock_status="unknown",
    artifact_status="unknown",
):
    """Classify checkpoint recovery without changing its state.

    lock_status:
        held      - coordinator lock is held
        available - coordinator lock is available
        unknown   - ownership could not be established

    artifact_status:
        verified - completed artifacts passed integrity verification
        invalid  - artifact verification failed
        unknown  - verification has not been performed
    """
    if lock_status not in LOCK_STATUSES:
        raise ValueError("invalid lock status")

    if artifact_status not in ARTIFACT_STATUSES:
        raise ValueError("invalid artifact status")

    try:
        validate_checkpoint(checkpoint)
    except (ValueError, TypeError, KeyError):
        return {
            "classification": "invalid_checkpoint",
            "action": "manual_investigation",
        }

    state = checkpoint["state"]

    if state == "pending":
        classification = "not_started"
        action = "eligible_for_initial_processing"

    elif state == "running":
        if lock_status == "held":
            classification = "active"
            action = "leave_unchanged"
        elif lock_status == "available":
            classification = "interrupted"
            action = "inspect_artifacts_before_retry"
        else:
            classification = "indeterminate"
            action = "investigate_lock_ownership"

    elif state == "failed":
        if checkpoint["retryable"]:
            classification = "retryable_failure"
            action = "eligible_for_explicit_retry"
        else:
            classification = "manual_intervention"
            action = "investigate_failure"

    elif state == "completed":
        if artifact_status == "verified":
            classification = "verified_complete"
            action = "preserve_artifacts"
        elif artifact_status == "invalid":
            classification = "integrity_failure"
            action = "investigate_artifact_integrity"
        else:
            classification = "indeterminate"
            action = "verify_artifacts"

    return {
        "classification": classification,
        "action": action,
    }
