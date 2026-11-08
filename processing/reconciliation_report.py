"""Pure reconciliation reporting from verified assembly evidence."""

from __future__ import annotations

from collections import Counter

from processing.reconciliation_identity import (
    evidence_identity,
    finding_identity,
)
from processing.reconciliation_validation import validate_review_v2


def build_reconciliation_report(
    session_id,
    assembly_fingerprint,
    transcript,
    provenance,
    review,
):
    """Match review decisions to assembly findings without mutation."""

    validate_review_v2(review)

    if review["session_id"] != session_id:
        raise ValueError("Review session mismatch")

    if review["assembly_fingerprint"] != assembly_fingerprint:
        raise ValueError("Review assembly mismatch")

    if provenance.get("session_id") != session_id:
        raise ValueError("Provenance session mismatch")

    if provenance.get("assembly_fingerprint") != assembly_fingerprint:
        raise ValueError("Provenance assembly mismatch")

    findings = transcript.get("findings")

    if not isinstance(findings, list):
        raise ValueError("Invalid assembly findings")

    identity = provenance.get("identity")

    if not isinstance(identity, dict):
        raise ValueError("Invalid provenance identity")

    contributions = identity.get("contributions")

    if not isinstance(contributions, list):
        raise ValueError("Invalid provenance contributions")

    executions = {}

    for item in contributions:
        if not isinstance(item, dict):
            raise ValueError("Invalid contribution")

        chunk_id = item.get("chunk_id")
        fingerprint = item.get("fingerprint")

        if not isinstance(chunk_id, str) or chunk_id in executions:
            raise ValueError("Invalid or duplicate contribution")

        executions[chunk_id] = fingerprint

    indexed = []

    for index, finding in enumerate(findings, 1):
        chunk_id = finding["chunk_id"]

        if chunk_id not in executions:
            raise ValueError("Missing execution provenance")

        indexed.append({
            "finding_index": index,
            "finding_id": finding_identity(
                assembly_fingerprint, finding
            ),
            "evidence_id": evidence_identity(
                executions[chunk_id], finding
            ),
            "finding_type": finding["type"],
            "chunk_id": chunk_id,
            "source": finding["segment"]["source"],
            "start_seconds": finding["segment"]["start_seconds"],
            "end_seconds": finding["segment"]["end_seconds"],
        })

    by_id = {item["finding_id"]: item for item in indexed}

    if len(by_id) != len(indexed):
        raise ValueError("Duplicate assembly finding identity")

    reviewed = []
    matched = set()
    counts = Counter()

    for decision in review["decisions"]:
        finding_id = decision["finding_id"]

        if finding_id not in by_id:
            raise ValueError("Review references unknown finding")

        item = by_id[finding_id]

        if decision["evidence_id"] != item["evidence_id"]:
            raise ValueError("Review evidence identity mismatch")

        if decision["legacy_finding_index"] != item["finding_index"]:
            raise ValueError("Legacy finding index mismatch")

        if finding_id in matched:
            raise ValueError("Duplicate review decision")

        matched.add(finding_id)
        counts[decision["decision"]] += 1

        reviewed.append({
            **item,
            "decision": decision["decision"],
            "method": decision["method"],
        })

    pending = [
        item for item in indexed
        if item["finding_id"] not in matched
    ]

    return {
        "session_id": session_id,
        "assembly_fingerprint": assembly_fingerprint,
        "transcript_state": transcript.get("state"),
        "total_findings": len(indexed),
        "reviewed_count": len(reviewed),
        "pending_count": len(pending),
        "decision_counts": dict(sorted(counts.items())),
        "reviewed": reviewed,
        "pending": pending,
        "capture_observations": review["capture_observations"].copy(),
    }
