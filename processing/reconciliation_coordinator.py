"""Read-only, source-verified reconciliation coordination."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from processing.assembly_discovery import discover_assemblies
from processing.reconciliation_migration import migrate_review
from processing.reconciliation_report import build_reconciliation_report
from processing.reconciliation_validation import validate_review_v2

DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _read_regular(path):
    """Read a regular file without following its final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"Not a regular artifact: {path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def _read_json(path):
    value = json.loads(_read_regular(path).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid JSON artifact: {path}")
    return value


def reconcile_session(sessions_root, session_id, assembly_fingerprint):
    """Verify published evidence and return a read-only review report."""

    if (
        not isinstance(assembly_fingerprint, str)
        or not DIGEST.fullmatch(assembly_fingerprint)
    ):
        raise ValueError("Invalid assembly fingerprint")

    root = Path(sessions_root).expanduser().resolve(strict=True)

    discovery = discover_assemblies(root, session_id)

    matches = [
        item for item in discovery["assemblies"]
        if item["name"] == assembly_fingerprint
    ]

    if len(matches) != 1:
        raise ValueError("Expected exactly one matching assembly")

    record = matches[0]

    if (
        record.get("classification") != "verified_complete"
        or record.get("verification_level") != "source_verified"
    ):
        raise ValueError("Assembly is not source verified")

    session = root / session_id
    processing = session / "processing"
    assembly_root = processing / "assembly"
    assembly = assembly_root / assembly_fingerprint
    reviews = processing / "reconciliation"

    for directory in (
        session, processing, assembly_root, assembly, reviews
    ):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"Invalid artifact directory: {directory}")

    transcript = _read_json(assembly / "transcript.json")
    provenance = _read_json(assembly / "provenance.json")

    review = _read_json(reviews / "human-review-v2.json")
    validate_review_v2(review)

    if review["session_id"] != session_id:
        raise ValueError("Review session mismatch")

    if review["assembly_fingerprint"] != assembly_fingerprint:
        raise ValueError("Review assembly mismatch")

    original = _read_regular(reviews / "human-review-v1.json")

    if hashlib.sha256(original).hexdigest() != review["source_review_sha256"]:
        raise ValueError("Original review checksum mismatch")

    original_review = json.loads(original.decode("utf-8"))

    if not isinstance(original_review, dict):
        raise ValueError("Invalid original review")

    if original_review.get("session_id") != session_id:
        raise ValueError("Original review session mismatch")

    if original_review.get("assembly_fingerprint") != assembly_fingerprint:
        raise ValueError("Original review assembly mismatch")

    expected_review = migrate_review(
        original_review,
        transcript,
        provenance,
        source_review_bytes=original,
    )

    if review != expected_review:
        raise ValueError("Human review migration consistency mismatch")

    report = build_reconciliation_report(
        session_id,
        assembly_fingerprint,
        transcript,
        provenance,
        review,
    )

    if report["total_findings"] != record["unresolved_count"]:
        raise ValueError("Assembly finding count mismatch")

    if report["transcript_state"] != record["transcript_state"]:
        raise ValueError("Assembly transcript state mismatch")

    segments = transcript.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Invalid transcript segments")

    if len(segments) != record["segment_count"]:
        raise ValueError("Assembly segment count mismatch")

    report["verification_level"] = record["verification_level"]
    report["transcript_state"] = record["transcript_state"]
    report["segment_count"] = record["segment_count"]
    report["review_status"] = review["review_status"]

    return report
