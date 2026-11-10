"""Selective transcription execution under one session processing lock."""

from __future__ import annotations

from processing.checkpoint_store import checkpoint_store
from processing.chunk_coordinator import _execute_chunk_with_store
from processing.processing_plan import _plan_session_processing_with_store


def execute_session_chunks(
    sessions_root,
    session_id,
    model_path,
    *,
    profile=None,
    chunk_seconds=300,
    overlap_seconds=2,
    ffmpeg_binary="ffmpeg",
    whisper_binary="whisper-cli",
):
    """Execute only missing chunks and reuse exact verified checkpoints."""

    with checkpoint_store(sessions_root, session_id) as store:
        return _execute_session_chunks_with_store(
            store,
            sessions_root,
            session_id,
            model_path,
            profile=profile,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
            ffmpeg_binary=ffmpeg_binary,
            whisper_binary=whisper_binary,
        )


def _execute_session_chunks_with_store(
    store,
    sessions_root,
    session_id,
    model_path,
    *,
    profile=None,
    chunk_seconds=300,
    overlap_seconds=2,
    ffmpeg_binary="ffmpeg",
    whisper_binary="whisper-cli",
):
    """Execute selective transcription under an existing processing lock."""
    plan = _plan_session_processing_with_store(
        store,
        sessions_root,
        session_id,
        model_path,
        profile=profile,
        chunk_seconds=chunk_seconds,
        overlap_seconds=overlap_seconds,
        ffmpeg_binary=ffmpeg_binary,
        whisper_binary=whisper_binary,
    )

    blocked = [
        entry for entry in plan["entries"]
        if entry["action"] == "stop"
    ]

    if blocked:
        raise ValueError(
            "Processing blocked by existing checkpoint evidence: "
            + ", ".join(
                entry["chunk_id"] for entry in blocked
            )
        )

    chunks = {
        chunk["chunk_id"]: chunk
        for source in plan["batch_plan"]["sources"]
        for chunk in source["chunks"]
    }

    fingerprints = {}
    executed = []
    reused = []

    for entry in plan["entries"]:
        chunk_id = entry["chunk_id"]
        fingerprint = entry["fingerprint"]

        if entry["action"] == "reuse":
            store.verify(fingerprint, chunk_id)
            reused.append(chunk_id)

        elif entry["action"] == "execute":
            result = _execute_chunk_with_store(
                store,
                sessions_root,
                session_id,
                chunks[chunk_id],
                model_path,
                profile=profile,
                ffmpeg_binary=ffmpeg_binary,
                whisper_binary=whisper_binary,
                expected_fingerprint=fingerprint,
            )

            if (
                result["fingerprint"] != fingerprint
                or result["chunk_id"] != chunk_id
                or result["state"] != "completed"
            ):
                raise ValueError(
                    "Chunk execution identity mismatch"
                )

            store.verify(fingerprint, chunk_id)
            executed.append(chunk_id)

        else:
            raise ValueError("Unsupported processing action")

        fingerprints[chunk_id] = fingerprint

    return {
        "schema_version": 1,
        "session_id": session_id,
        "batch_plan": plan["batch_plan"],
        "fingerprints": fingerprints,
        "executed_chunks": executed,
        "reused_chunks": reused,
        "executed_count": len(executed),
        "reused_count": len(reused),
    }


def process_session(
    sessions_root,
    session_id,
    model_path,
    *,
    profile=None,
    chunk_seconds=300,
    overlap_seconds=2,
    ffmpeg_binary="ffmpeg",
    whisper_binary="whisper-cli",
):
    """Execute transcription and publish or reuse its verified assembly."""

    from pathlib import Path

    from processing.assembly_coordinator import (
        _assemble_session_with_store,
    )
    from processing.assembly_discovery import (
        _verify_publication_with_store,
    )
    from processing.assembly_identity import assembly_fingerprint
    from processing.assembly_loader import (
        _expected_chunks,
        _load_with_store,
    )
    from session import manager

    with checkpoint_store(sessions_root, session_id) as store:
        root = Path(sessions_root).expanduser().resolve(strict=True)
        folder = manager._session_dir(root, session_id)

        _preflight_assembly_root(store, folder, session_id)

        chunks = _execute_session_chunks_with_store(
            store,
            sessions_root,
            session_id,
            model_path,
            profile=profile,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
            ffmpeg_binary=ffmpeg_binary,
            whisper_binary=whisper_binary,
        )

        expected = _expected_chunks(chunks["batch_plan"])

        verified = _load_with_store(
            store,
            folder,
            expected,
            chunks["fingerprints"],
        )

        fingerprint = assembly_fingerprint(
            chunks["batch_plan"],
            verified["contributions"],
        )

        assembly_root = folder / "processing" / "assembly"

        destination = assembly_root / fingerprint

        if destination.exists():
            verification = _verify_publication_with_store(
                store,
                folder,
                destination,
                fingerprint,
                session_id,
            )

            if verification["classification"] != "verified_complete":
                raise ValueError("Existing assembly is not verified")

            return {
                "schema_version": 1,
                "session_id": session_id,
                "chunks": chunks,
                "assembly": {
                    "fingerprint": fingerprint,
                    "state": verification["transcript_state"],
                    "segment_count": verification["segment_count"],
                    "unresolved_count": verification["unresolved_count"],
                    "path": str(destination),
                    "publication": "reused",
                },
            }

        publication = _assemble_session_with_store(
            store,
            root,
            session_id,
            chunks["batch_plan"],
            chunks["fingerprints"],
        )

        if publication["fingerprint"] != fingerprint:
            raise ValueError("Published assembly identity mismatch")

        return {
            "schema_version": 1,
            "session_id": session_id,
            "chunks": chunks,
            "assembly": {
                "fingerprint": fingerprint,
                "state": publication["state"],
                "segment_count": publication["segment_count"],
                "unresolved_count": publication["unresolved_count"],
                "path": publication["path"],
                "publication": "created",
            },
        }


def _preflight_assembly_root(store, folder, session_id):
    """Reject unsafe or unverifiable existing assembly evidence."""

    import re

    from processing.assembly_discovery import (
        _verify_publication_with_store,
    )

    digest = re.compile(r"^[0-9a-f]{64}$")

    processing_dir = folder / "processing"
    assembly_root = processing_dir / "assembly"

    if processing_dir.is_symlink():
        raise ValueError("Symlinked processing directory")

    if processing_dir.exists() and not processing_dir.is_dir():
        raise ValueError("Invalid processing directory")

    if assembly_root.is_symlink():
        raise ValueError("Symlinked assembly root")

    if assembly_root.exists() and not assembly_root.is_dir():
        raise ValueError("Invalid assembly root")

    if not assembly_root.exists():
        return

    for entry in sorted(assembly_root.iterdir()):
        if entry.is_symlink():
            raise ValueError("Symlinked assembly entry")

        if entry.name.startswith(".assembly-staging-"):
            raise ValueError("Incomplete assembly staging evidence")

        if not digest.fullmatch(entry.name) or not entry.is_dir():
            raise ValueError("Unknown assembly entry")

        verification = _verify_publication_with_store(
            store,
            folder,
            entry,
            entry.name,
            session_id,
        )

        if verification["classification"] != "verified_complete":
            raise ValueError("Unverified historical assembly")
