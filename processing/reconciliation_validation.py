"""Pure structural validation for reconciliation review v2."""

import re
import uuid

SHA256 = re.compile(r"^[0-9a-f]{64}$")

DECISIONS = frozenset({
    "duplicate_confirmed",
    "content_recovery_required",
    "unresolved",
})

METHODS = frozenset({"human_audio_review"})

REVIEW_FIELDS = frozenset({
    "schema_version",
    "session_id",
    "assembly_fingerprint",
    "review_status",
    "source_review_sha256",
    "decisions",
    "capture_observations",
})

DECISION_FIELDS = frozenset({
    "finding_id",
    "evidence_id",
    "decision",
    "method",
    "legacy_finding_index",
})

OBSERVATION_FIELDS = frozenset({
    "microphone_contains_acoustic_application_audio",
    "source_isolation",
    "cross_source_deduplication",
})


def _digest(value):
    return isinstance(value, str) and bool(SHA256.fullmatch(value))


def validate_review_v2(review):
    """Reject malformed v2 reviews without modifying input."""

    if not isinstance(review, dict) or set(review) != REVIEW_FIELDS:
        raise ValueError("Invalid review fields")

    if type(review["schema_version"]) is not int or review["schema_version"] != 2:
        raise ValueError("Unsupported review version")

    sid = review["session_id"]
    if not isinstance(sid, str):
        raise ValueError("Invalid session ID")
    try:
        parsed = uuid.UUID(sid)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Invalid session UUID") from exc
    if str(parsed) != sid:
        raise ValueError("Noncanonical session UUID")

    for name in ("assembly_fingerprint", "source_review_sha256"):
        if not _digest(review[name]):
            raise ValueError(f"Invalid {name}")

    if review["review_status"] != "partial":
        raise ValueError("Only partial reviews supported")

    decisions = review["decisions"]
    if not isinstance(decisions, list):
        raise ValueError("Invalid decisions")

    seen = set()
    seen_indices = set()
    for entry in decisions:
        if not isinstance(entry, dict) or set(entry) != DECISION_FIELDS:
            raise ValueError("Invalid decision fields")

        for name in ("finding_id", "evidence_id"):
            if not _digest(entry[name]):
                raise ValueError(f"Invalid {name}")

        if entry["finding_id"] in seen:
            raise ValueError("Duplicate finding ID")
        seen.add(entry["finding_id"])

        if entry["decision"] not in DECISIONS:
            raise ValueError("Unsupported decision")

        if entry["method"] not in METHODS:
            raise ValueError("Unsupported method")

        index = entry["legacy_finding_index"]
        if type(index) is not int or index <= 0:
            raise ValueError("Invalid legacy finding index")
        if index in seen_indices:
            raise ValueError("Duplicate legacy finding index")
        seen_indices.add(index)

    observations = review["capture_observations"]
    if not isinstance(observations, dict):
        raise ValueError("Invalid capture observations")

    if not set(observations).issubset(OBSERVATION_FIELDS):
        raise ValueError("Unexpected capture observation")

    if "microphone_contains_acoustic_application_audio" in observations:
        if type(observations["microphone_contains_acoustic_application_audio"]) is not bool:
            raise ValueError("Invalid microphone observation")

    for name in ("source_isolation", "cross_source_deduplication"):
        if name in observations:
            if not isinstance(observations[name], str) or not observations[name]:
                raise ValueError(f"Invalid {name}")

    return True
