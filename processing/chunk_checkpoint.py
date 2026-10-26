"""Pure validation and lifecycle rules for transcription checkpoints."""

import copy
import re

SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHUNK_ID = re.compile(
    r"^(application_audio|microphone_audio):[0-9]{6,}$"
)

STATES = frozenset({
    "pending", "running", "completed", "failed"
})

TRANSITIONS = {
    "pending": frozenset({"running"}),
    "running": frozenset({"completed", "failed"}),
    "failed": frozenset({"running"}),
    "completed": frozenset(),
}

ARTIFACT_KINDS = frozenset({
    "whisper_json", "normalized_json"
})


def new_checkpoint(fingerprint, chunk_id):
    """Create an unpersisted checkpoint."""
    checkpoint = {
        "schema_version": 1,
        "fingerprint": fingerprint,
        "chunk_id": chunk_id,
        "state": "pending",
        "attempts": 0,
        "retryable": False,
        "error": None,
        "artifacts": [],
    }
    validate_checkpoint(checkpoint)
    return checkpoint


def validate_checkpoint(checkpoint):
    """Validate checkpoint structure and lifecycle invariants."""
    if not isinstance(checkpoint, dict):
        raise ValueError("checkpoint must be an object")

    required = {
        "schema_version", "fingerprint", "chunk_id",
        "state", "attempts", "retryable", "error", "artifacts"
    }

    if set(checkpoint) != required:
        raise ValueError("checkpoint fields do not match schema")

    if type(checkpoint["schema_version"]) is not int:
        raise ValueError("invalid schema version")

    if checkpoint["schema_version"] != 1:
        raise ValueError("unsupported schema version")

    fingerprint = checkpoint["fingerprint"]
    if not isinstance(fingerprint, str) or not SHA256.fullmatch(fingerprint):
        raise ValueError("invalid fingerprint")

    chunk_id = checkpoint["chunk_id"]
    if not isinstance(chunk_id, str) or not CHUNK_ID.fullmatch(chunk_id):
        raise ValueError("invalid chunk ID")

    state = checkpoint["state"]
    if state not in STATES:
        raise ValueError("invalid checkpoint state")

    attempts = checkpoint["attempts"]
    if type(attempts) is not int or attempts < 0:
        raise ValueError("invalid attempt count")

    retryable = checkpoint["retryable"]
    if type(retryable) is not bool:
        raise ValueError("invalid retryable flag")

    error = checkpoint["error"]
    if error is not None and (
        not isinstance(error, str) or not error.strip()
    ):
        raise ValueError("invalid error")

    artifacts = checkpoint["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("artifacts must be an array")

    seen = set()

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("invalid artifact")

        if set(artifact) != {"kind", "path", "sha256"}:
            raise ValueError("invalid artifact fields")

        kind = artifact["kind"]
        path = artifact["path"]
        digest = artifact["sha256"]

        if kind not in ARTIFACT_KINDS or kind in seen:
            raise ValueError("invalid or duplicate artifact kind")

        seen.add(kind)

        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or "\\" in path
            or any(part in ("", ".", "..") for part in path.split("/"))
        ):
            raise ValueError("invalid artifact path")

        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError("invalid artifact checksum")

    if state == "pending":
        if attempts != 0 or retryable or error is not None or artifacts:
            raise ValueError("invalid pending checkpoint")

    if state == "running":
        if attempts < 1 or retryable or error is not None:
            raise ValueError("invalid running checkpoint")

    if state == "failed":
        if attempts < 1 or error is None:
            raise ValueError("invalid failed checkpoint")

    if state == "completed":
        if attempts < 1 or retryable or error is not None:
            raise ValueError("invalid completed checkpoint")

        if seen != ARTIFACT_KINDS:
            raise ValueError("completed checkpoint requires both artifacts")

    return checkpoint


def transition_checkpoint(
    checkpoint,
    state,
    *,
    retryable=False,
    error=None,
    artifacts=None,
):
    """Return a new checkpoint without mutating the input."""
    validate_checkpoint(checkpoint)

    previous = checkpoint["state"]

    if state not in TRANSITIONS[previous]:
        raise ValueError(f"invalid transition: {previous} -> {state}")

    if previous == "failed" and not checkpoint["retryable"]:
        raise ValueError("checkpoint is not retryable")

    result = copy.deepcopy(checkpoint)
    result["state"] = state

    if state == "running":
        result["attempts"] += 1
        result["retryable"] = False
        result["error"] = None
        result["artifacts"] = []

    elif state == "failed":
        result["retryable"] = bool(retryable)
        result["error"] = error or "processing failed"

    elif state == "completed":
        result["retryable"] = False
        result["error"] = None
        result["artifacts"] = copy.deepcopy(artifacts or [])

    validate_checkpoint(result)
    return result
