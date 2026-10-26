"""Read-only discovery of transcription checkpoint recovery status."""

from __future__ import annotations

import errno
import fcntl
import os
import re
from pathlib import Path

from processing.chunk_recovery import classify_checkpoint
from processing.chunk_storage import load_checkpoint, verify_artifacts
from session import manager

SOURCES = frozenset({"application_audio", "microphone_audio"})
INDEX = re.compile(r"^[0-9]{6,}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def inspect_coordinator_lock(session_dir):
    """Inspect an existing coordinator lock without creating files."""
    path = Path(session_dir) / ".processing.lock"

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return "available"
    except OSError:
        return "unknown"

    try:
        import stat

        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return "unknown"

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "held"
        except OSError:
            return "unknown"

        try:
            return "available"
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _safe_children(directory):
    """List direct children without following directory symlinks."""
    directory = Path(directory)

    if directory.is_symlink():
        raise ValueError("Symlinked checkpoint directory")

    if not directory.is_dir():
        raise ValueError("Invalid checkpoint directory")

    return sorted(directory.iterdir(), key=lambda item: item.name)


def discover_checkpoints(sessions_root, session_id):
    """Return recovery classifications without modifying session files."""
    root = Path(sessions_root).expanduser().resolve(strict=True)
    folder = manager._session_dir(root, session_id)

    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Invalid session directory")

    manifest = manager.load(root, session_id)

    if manifest.get("session_id") != session_id:
        raise ValueError("Session identity mismatch")

    base = folder / "processing" / "transcription"

    if not base.exists() and not base.is_symlink():
        return {
            "session_id": session_id,
            "lock_status": inspect_coordinator_lock(folder),
            "checkpoints": [],
        }

    lock_status = inspect_coordinator_lock(folder)
    results = []

    for source_dir in _safe_children(base):
        source = source_dir.name

        if source not in SOURCES:
            continue

        for index_dir in _safe_children(source_dir):
            for fingerprint_dir in _safe_children(index_dir):
                fingerprint = fingerprint_dir.name
                chunk_id = f"{source}:{index_dir.name}"

                record = {
                    "chunk_id": chunk_id,
                    "fingerprint": fingerprint,
                }

                if (
                    not INDEX.fullmatch(index_dir.name)
                    or not DIGEST.fullmatch(fingerprint)
                    or fingerprint_dir.is_symlink()
                    or not fingerprint_dir.is_dir()
                ):
                    record.update({
                        "classification": "invalid_checkpoint",
                        "action": "manual_investigation",
                    })
                    results.append(record)
                    continue

                try:
                    checkpoint = load_checkpoint(
                        folder, fingerprint, chunk_id
                    )

                    artifact_status = "unknown"

                    if checkpoint["state"] == "completed":
                        try:
                            verify_artifacts(
                                folder, fingerprint, chunk_id
                            )
                            artifact_status = "verified"
                        except (OSError, ValueError, KeyError):
                            artifact_status = "invalid"

                    classification = classify_checkpoint(
                        checkpoint,
                        lock_status=lock_status,
                        artifact_status=artifact_status,
                    )

                    record.update({
                        "state": checkpoint["state"],
                        **classification,
                    })

                except (OSError, ValueError, KeyError, TypeError):
                    record.update({
                        "classification": "invalid_checkpoint",
                        "action": "manual_investigation",
                    })

                results.append(record)

    return {
        "session_id": session_id,
        "lock_status": lock_status,
        "checkpoints": results,
    }
