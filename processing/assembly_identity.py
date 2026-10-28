"""Deterministic identity for assembled transcripts."""

from __future__ import annotations

import hashlib
import json
import re

from processing.chunk_identity import canonical_chunk

ASSEMBLY_ALGORITHM_VERSION = 2
IDENTITY_VERSION = 1

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def assembly_identity(batch_plan, contributions):
    """Construct canonical assembly identity without filesystem access."""
    if not isinstance(batch_plan, dict):
        raise ValueError("Invalid batch plan")

    if not isinstance(contributions, dict):
        raise ValueError("Invalid contributions")

    sources = batch_plan.get("sources")

    if not isinstance(sources, list) or not sources:
        raise ValueError("Invalid batch sources")

    canonical_sources = []
    expected_ids = []

    for source_plan in sources:
        if not isinstance(source_plan, dict):
            raise ValueError("Invalid source plan")

        source = source_plan.get("source")
        chunks = source_plan.get("chunks")

        if not isinstance(chunks, list):
            raise ValueError("Invalid source chunks")

        canonical_chunks = []

        for chunk in chunks:
            canonical = canonical_chunk(chunk)

            if canonical["source"] != source:
                raise ValueError("Chunk source mismatch")

            chunk_id = canonical["chunk_id"]

            if chunk_id in expected_ids:
                raise ValueError("Duplicate chunk ID")

            expected_ids.append(chunk_id)
            canonical_chunks.append(canonical)

        canonical_sources.append({
            "source": source,
            "chunks": canonical_chunks,
        })

    if not expected_ids:
        raise ValueError("Empty assembly plan")

    if set(contributions) != set(expected_ids):
        raise ValueError("Missing or unexpected contributions")

    ordered_contributions = []

    for chunk_id in expected_ids:
        contribution = contributions[chunk_id]

        if not isinstance(contribution, dict):
            raise ValueError("Invalid contribution")

        fingerprint = contribution.get("fingerprint")
        normalized_sha256 = contribution.get("normalized_sha256")

        for value in (fingerprint, normalized_sha256):
            if not isinstance(value, str) or not SHA256.fullmatch(value):
                raise ValueError("Invalid contribution digest")

        ordered_contributions.append({
            "chunk_id": chunk_id,
            "fingerprint": fingerprint,
            "normalized_sha256": normalized_sha256,
        })

    return {
        "identity_version": IDENTITY_VERSION,
        "assembly_algorithm_version": ASSEMBLY_ALGORITHM_VERSION,
        "sources": canonical_sources,
        "contributions": ordered_contributions,
    }


def assembly_fingerprint(batch_plan, contributions):
    """SHA-256 of canonical assembly identity."""
    identity = assembly_identity(batch_plan, contributions)

    payload = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()
