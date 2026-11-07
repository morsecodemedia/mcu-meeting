"""Pure migration of positional human reviews to stable identities."""

from __future__ import annotations

import hashlib
import json
import re

from processing.reconciliation_identity import (
    evidence_identity,
    finding_identity,
)

DIGEST = re.compile(r"^[0-9a-f]{64}$")

DECISIONS = frozenset({
    "duplicate_confirmed",
    "content_recovery_required",
    "unresolved",
})

METHODS = frozenset({
    "human_audio_review",
})


def migrate_review(
    review,
    transcript,
    provenance,
    *,
    source_review_bytes,
):
    """Build a v2 review without modifying any input."""

    if not isinstance(review, dict):
        raise ValueError("Invalid source review")

    if type(review.get("schema_version")) is not int:
        raise ValueError("Invalid source review version")

    if review["schema_version"] != 1:
        raise ValueError("Unsupported source review version")

    sid = review.get("session_id")
    assembly = review.get("assembly_fingerprint")

    if not isinstance(sid, str) or not sid:
        raise ValueError("Invalid session ID")

    if not isinstance(assembly, str) or not DIGEST.fullmatch(assembly):
        raise ValueError("Invalid assembly fingerprint")

    if not isinstance(provenance, dict):
        raise ValueError("Invalid provenance")

    if provenance.get("session_id") != sid:
        raise ValueError("Provenance session mismatch")

    if provenance.get("assembly_fingerprint") != assembly:
        raise ValueError("Provenance assembly mismatch")

    if not isinstance(transcript, dict):
        raise ValueError("Invalid transcript")

    findings = transcript.get("findings")

    if not isinstance(findings, list):
        raise ValueError("Invalid findings")

    if not isinstance(source_review_bytes, bytes):
        raise ValueError("Invalid source review bytes")

    if json.loads(source_review_bytes) != review:
        raise ValueError("Source review bytes mismatch")

    contributions = provenance.get("identity", {}).get(
        "contributions"
    )

    if not isinstance(contributions, list):
        raise ValueError("Invalid provenance contributions")

    executions = {}

    for item in contributions:
        if not isinstance(item, dict):
            raise ValueError("Invalid contribution")

        chunk_id = item.get("chunk_id")
        fingerprint = item.get("fingerprint")

        if not isinstance(chunk_id, str) or chunk_id in executions:
            raise ValueError("Duplicate or invalid contribution")

        if not isinstance(fingerprint, str) or not DIGEST.fullmatch(fingerprint):
            raise ValueError("Invalid execution fingerprint")

        executions[chunk_id] = fingerprint

    entries = review.get("decisions")

    if not isinstance(entries, list):
        raise ValueError("Invalid review decisions")

    migrated = []
    seen_indices = set()

    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid review decision")

        index = entry.get("finding_index")

        if type(index) is not int or not 1 <= index <= len(findings):
            raise ValueError("Invalid finding index")

        if index in seen_indices:
            raise ValueError("Duplicate finding index")

        seen_indices.add(index)

        decision = entry.get("decision")
        method = entry.get("method")

        if decision not in DECISIONS:
            raise ValueError("Unsupported review decision")

        if method not in METHODS:
            raise ValueError("Unsupported review method")

        finding = findings[index - 1]
        chunk_id = finding["chunk_id"]

        if chunk_id not in executions:
            raise ValueError("Missing execution provenance")

        migrated.append({
            "finding_id": finding_identity(assembly, finding),
            "evidence_id": evidence_identity(
                executions[chunk_id], finding
            ),
            "decision": decision,
            "method": method,
            "legacy_finding_index": index,
        })

    return {
        "schema_version": 2,
        "session_id": sid,
        "assembly_fingerprint": assembly,
        "review_status": review.get("review_status"),
        "source_review_sha256": hashlib.sha256(
            source_review_bytes
        ).hexdigest(),
        "decisions": migrated,
        "capture_observations": review.get(
            "capture_observations", {}
        ),
    }
