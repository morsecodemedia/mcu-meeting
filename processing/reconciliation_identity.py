"""Deterministic identities for reconciliation findings and evidence."""

from __future__ import annotations

import hashlib
import json
import re

from processing.chunk_planning import _microseconds

IDENTITY_VERSION = 1

SHA256 = re.compile(r"^[0-9a-f]{64}$")
SOURCES = frozenset({"application_audio", "microphone_audio"})
FINDING_TYPES = frozenset({
    "boundary_spanning",
    "timing_out_of_bounds",
})


def _digest(value):
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()


def _validate_digest(value, name):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"Invalid {name}")


def _canonical_finding(finding):
    if not isinstance(finding, dict):
        raise ValueError("Invalid finding")

    if set(finding) != {"type", "chunk_id", "segment"}:
        raise ValueError("Unexpected finding fields")

    kind = finding["type"]

    if kind not in FINDING_TYPES:
        raise ValueError("Unsupported finding type")

    segment = finding["segment"]

    if not isinstance(segment, dict):
        raise ValueError("Invalid segment")

    required = {
        "id",
        "source",
        "chunk_id",
        "segment_index",
        "start_seconds",
        "end_seconds",
        "text",
    }

    if not required.issubset(segment):
        raise ValueError("Missing segment identity fields")

    source = segment["source"]
    chunk_id = finding["chunk_id"]
    index = segment["segment_index"]

    if source not in SOURCES:
        raise ValueError("Unsupported source")

    if (
        not isinstance(chunk_id, str)
        or not re.fullmatch(rf"{source}:[0-9]{{6}}", chunk_id)
    ):
        raise ValueError("Invalid chunk ID")

    if segment["chunk_id"] != chunk_id:
        raise ValueError("Finding/segment chunk mismatch")

    if type(index) is not int or index < 0:
        raise ValueError("Invalid segment index")

    expected_id = f"{chunk_id}:{index}"

    if segment["id"] != expected_id:
        raise ValueError("Segment ID mismatch")

    start = _microseconds(
        segment["start_seconds"],
        "start_seconds",
        allow_zero=True,
    )

    end = _microseconds(
        segment["end_seconds"],
        "end_seconds",
        allow_zero=True,
    )

    if end <= start:
        raise ValueError("Invalid segment interval")

    text = segment["text"]

    if not isinstance(text, str):
        raise ValueError("Invalid segment text")

    return {
        "finding_type": kind,
        "source": source,
        "chunk_id": chunk_id,
        "segment_id": expected_id,
        "start_us": start,
        "end_us": end,
        "text": text,
    }


def finding_identity(assembly_fingerprint, finding):
    """Return an assembly-scoped finding SHA-256."""
    _validate_digest(assembly_fingerprint, "assembly fingerprint")

    evidence = _canonical_finding(finding)

    return _digest({
        "schema_version": IDENTITY_VERSION,
        "assembly_fingerprint": assembly_fingerprint,
        "finding_type": evidence["finding_type"],
        "chunk_id": evidence["chunk_id"],
        "segment_id": evidence["segment_id"],
        "start_us": evidence["start_us"],
        "end_us": evidence["end_us"],
        "text": evidence["text"],
    })


def evidence_identity(execution_fingerprint, finding):
    """Return an execution-scoped transcription evidence SHA-256.

    Caller must verify execution_fingerprint against provenance.
    """
    _validate_digest(execution_fingerprint, "execution fingerprint")

    evidence = _canonical_finding(finding)

    return _digest({
        "schema_version": IDENTITY_VERSION,
        "source": evidence["source"],
        "chunk_id": evidence["chunk_id"],
        "execution_fingerprint": execution_fingerprint,
        "segment_id": evidence["segment_id"],
        "start_us": evidence["start_us"],
        "end_us": evidence["end_us"],
        "text": evidence["text"],
    })
