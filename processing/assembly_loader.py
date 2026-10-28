"""Load normalized chunks from verified, completed checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from processing.checkpoint_store import checkpoint_store
from processing.chunk_identity import canonical_chunk
from session import manager


def _read_verified_json(path, expected_sha256):
    """Read one regular file and hash the bytes actually parsed."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)

    try:
        metadata = os.fstat(fd)

        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Normalized artifact is not a regular file")

        with os.fdopen(fd, "rb", closefd=False) as stream:
            content = stream.read()

        actual = hashlib.sha256(content).hexdigest()

        if actual != expected_sha256:
            raise ValueError("Normalized artifact checksum mismatch")

        return json.loads(content.decode("utf-8"))

    finally:
        os.close(fd)


def _expected_chunks(batch_plan):
    if not isinstance(batch_plan, dict):
        raise ValueError("Invalid batch plan")

    sources = batch_plan.get("sources")

    if not isinstance(sources, list) or not sources:
        raise ValueError("Invalid batch sources")

    expected = {}

    for source_plan in sources:
        if not isinstance(source_plan, dict):
            raise ValueError("Invalid source plan")

        source = source_plan.get("source")
        chunks = source_plan.get("chunks")

        if not isinstance(chunks, list):
            raise ValueError("Invalid planned chunks")

        for chunk in chunks:
            canonical = canonical_chunk(chunk)

            if canonical["source"] != source:
                raise ValueError("Planned source mismatch")

            chunk_id = canonical["chunk_id"]

            if chunk_id in expected:
                raise ValueError("Duplicate planned chunk")

            expected[chunk_id] = canonical

    if not expected:
        raise ValueError("Empty batch plan")

    return expected


def _load_verified_inputs(
    sessions_root,
    session_id,
    batch_plan,
    fingerprints,
):
    """Return verified transcripts and their checkpoint contributions."""
    expected = _expected_chunks(batch_plan)

    if not isinstance(fingerprints, dict):
        raise ValueError("Invalid fingerprint mapping")

    if set(fingerprints) != set(expected):
        raise ValueError("Missing or unexpected fingerprints")

    root = Path(sessions_root).expanduser().resolve(strict=True)
    folder = manager._session_dir(root, session_id)

    with checkpoint_store(root, session_id) as store:
        return _load_with_store(
            store, folder, expected, fingerprints
        )


def _load_with_store(store, folder, expected, fingerprints):
    """Load verified inputs using an already-active checkpoint store."""
    results = {}
    contributions = {}

    for chunk_id, chunk in expected.items():
        fingerprint = fingerprints[chunk_id]

        checkpoint = store.load(fingerprint, chunk_id)

        if checkpoint["state"] != "completed":
            raise ValueError(
                f"Incomplete checkpoint: {chunk_id}"
            )

        store.verify(fingerprint, chunk_id)

        artifacts = [
            artifact
            for artifact in checkpoint["artifacts"]
            if artifact["kind"] == "normalized_json"
        ]

        if len(artifacts) != 1:
            raise ValueError(
                f"Missing normalized artifact: {chunk_id}"
            )

        artifact = artifacts[0]

        directory = (
            folder
            / "processing"
            / "transcription"
            / chunk["source"]
            / f'{chunk["index"]:06d}'
            / fingerprint
        )

        path = directory / "normalized.json"

        normalized = _read_verified_json(
            path,
            artifact["sha256"],
        )

        if not isinstance(normalized, dict):
            raise ValueError("Invalid normalized JSON")

        if normalized.get("chunk_id") != chunk_id:
            raise ValueError("Normalized chunk identity mismatch")

        if normalized.get("source") != chunk["source"]:
            raise ValueError("Normalized source mismatch")

        if not isinstance(normalized.get("segments"), list):
            raise ValueError("Invalid normalized segments")

        results[chunk_id] = normalized
        contributions[chunk_id] = {
            "fingerprint": fingerprint,
            "normalized_sha256": artifact["sha256"],
        }

    return {
        "chunks": results,
        "contributions": contributions,
    }


def load_verified_assembly_inputs(
    sessions_root,
    session_id,
    batch_plan,
    fingerprints,
):
    """Return verified chunks and contribution metadata."""
    return _load_verified_inputs(
        sessions_root,
        session_id,
        batch_plan,
        fingerprints,
    )


def load_verified_chunks(
    sessions_root,
    session_id,
    batch_plan,
    fingerprints,
):
    """Backward-compatible normalized chunk loader."""
    return _load_verified_inputs(
        sessions_root,
        session_id,
        batch_plan,
        fingerprints,
    )["chunks"]
