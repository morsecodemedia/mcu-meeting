"""Deterministic, assembly-scoped cross-source candidate identities."""

from __future__ import annotations

import hashlib
import json
import re

CANDIDATE_IDENTITY_VERSION = 1

DIGEST = re.compile(r"^[0-9a-f]{64}$")
APPLICATION_ID = re.compile(r"^application_audio:[0-9]{6}:[0-9]+$")
MICROPHONE_ID = re.compile(r"^microphone_audio:[0-9]{6}:[0-9]+$")


def candidate_identity(assembly_fingerprint, candidate):
    """Return a deterministic candidate SHA-256 without modifying input."""

    if (
        not isinstance(assembly_fingerprint, str)
        or not DIGEST.fullmatch(assembly_fingerprint)
    ):
        raise ValueError("Invalid assembly fingerprint")

    if not isinstance(candidate, dict):
        raise ValueError("Invalid candidate")

    app = candidate.get("application_segment_id")
    mic = candidate.get("microphone_segment_id")
    start = candidate.get("overlap_start_us")
    end = candidate.get("overlap_end_us")

    if not isinstance(app, str) or not APPLICATION_ID.fullmatch(app):
        raise ValueError("Invalid application segment ID")

    if not isinstance(mic, str) or not MICROPHONE_ID.fullmatch(mic):
        raise ValueError("Invalid microphone segment ID")

    if type(start) is not int or start < 0:
        raise ValueError("Invalid overlap start")

    if type(end) is not int or end <= start:
        raise ValueError("Invalid overlap end")

    canonical = {
        "schema_version": CANDIDATE_IDENTITY_VERSION,
        "assembly_fingerprint": assembly_fingerprint,
        "application_segment_id": app,
        "microphone_segment_id": mic,
        "overlap_start_us": start,
        "overlap_end_us": end,
    }

    payload = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()
