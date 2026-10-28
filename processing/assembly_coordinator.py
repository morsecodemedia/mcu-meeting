"""Verified, single-lock assembly and immutable publication."""

from __future__ import annotations

from pathlib import Path

from processing.assembly_identity import (
    assembly_fingerprint,
    assembly_identity,
)
from processing.assembly_loader import _expected_chunks, _load_with_store
from processing.assembly_publisher import publish_assembly
from processing.checkpoint_store import checkpoint_store
from processing.transcript_assembly import assemble_transcript
from session import manager


def assemble_session(
    sessions_root,
    session_id,
    batch_plan,
    fingerprints,
):
    """Assemble verified chunks and publish one immutable assembly."""
    expected = _expected_chunks(batch_plan)

    if not isinstance(fingerprints, dict):
        raise ValueError("Invalid fingerprint mapping")

    if set(fingerprints) != set(expected):
        raise ValueError("Missing or unexpected fingerprints")

    root = Path(sessions_root).expanduser().resolve(strict=True)
    folder = manager._session_dir(root, session_id)

    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Invalid session directory")

    with checkpoint_store(root, session_id) as store:
        verified = _load_with_store(
            store,
            folder,
            expected,
            fingerprints,
        )

        contributions = verified["contributions"]

        identity = assembly_identity(
            batch_plan,
            contributions,
        )

        fingerprint = assembly_fingerprint(
            batch_plan,
            contributions,
        )

        transcript = assemble_transcript(
            batch_plan,
            verified["chunks"],
        )

        provenance = {
            "schema_version": 1,
            "session_id": session_id,
            "assembly_fingerprint": fingerprint,
            "identity": identity,
        }

        publication = publish_assembly(
            folder,
            fingerprint,
            transcript,
            provenance,
        )

    return {
        "schema_version": 1,
        "session_id": session_id,
        "fingerprint": fingerprint,
        "state": transcript["state"],
        "segment_count": transcript["segment_count"],
        "unresolved_count": transcript["unresolved_count"],
        "path": publication["path"],
        "checksums": publication["checksums"],
    }
