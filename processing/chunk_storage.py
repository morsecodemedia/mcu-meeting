"""Durable transcription checkpoints; no Whisper execution."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path

from processing.chunk_checkpoint import (
    new_checkpoint,
    transition_checkpoint,
    validate_checkpoint,
)

ARTIFACT_NAMES = {
    "whisper_json": "whisper.json",
    "normalized_json": "normalized.json",
}


def _directory(session_dir, checkpoint):
    """Derive a checkpoint directory from validated identity."""
    validate_checkpoint(checkpoint)

    source, index = checkpoint["chunk_id"].split(":", 1)

    # Resolve the trusted session root before deriving storage paths.
    # macOS commonly aliases /var to /private/var.
    root = Path(session_dir).expanduser().resolve(strict=True)

    if not root.is_dir():
        raise NotADirectoryError(root)

    return (
        root
        / "processing"
        / "transcription"
        / source
        / index
        / checkpoint["fingerprint"]
    )


def _safe_directory(path, *, create=False):
    """Reject symlinks in an existing directory chain."""
    path = Path(path)

    # The session root was resolved by _directory().
    # Reject symlinks within the derived checkpoint hierarchy.
    for component in reversed((path, *path.parents)):
        if component.is_symlink():
            raise ValueError(f"Symlinked directory: {component}")

    if create:
        path.mkdir(parents=True, exist_ok=True)

    if not path.is_dir():
        raise FileNotFoundError(path)

    return path


def _atomic_write(path, payload, *, exclusive=False):
    """Write complete bytes before atomic publication."""
    path = Path(path)
    parent = _safe_directory(path.parent)

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=parent,
            prefix=".checkpoint-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

        if exclusive:
            os.link(temporary, path)
        else:
            if path.is_symlink():
                raise ValueError("Symlinked checkpoint destination")
            os.replace(temporary, path)
            temporary = None

        fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _serialize(checkpoint):
    validate_checkpoint(checkpoint)
    return (
        json.dumps(checkpoint, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _checkpoint_path(session_dir, checkpoint):
    return _directory(session_dir, checkpoint) / "checkpoint.json"


def create_checkpoint(session_dir, fingerprint, chunk_id):
    """Create a pending checkpoint without replacing an existing one."""
    checkpoint = new_checkpoint(fingerprint, chunk_id)
    directory = _safe_directory(
        _directory(session_dir, checkpoint),
        create=True,
    )

    _atomic_write(
        directory / "checkpoint.json",
        _serialize(checkpoint),
        exclusive=True,
    )

    return checkpoint


def load_checkpoint(session_dir, fingerprint, chunk_id):
    """Load and validate a checkpoint from its derived location."""
    expected = new_checkpoint(fingerprint, chunk_id)
    directory = _safe_directory(_directory(session_dir, expected))
    path = directory / "checkpoint.json"

    if path.is_symlink() or not path.is_file():
        raise ValueError("Invalid checkpoint file")

    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    validate_checkpoint(checkpoint)

    if (
        checkpoint["fingerprint"] != fingerprint
        or checkpoint["chunk_id"] != chunk_id
    ):
        raise ValueError("Checkpoint identity mismatch")

    return checkpoint


def save_transition(
    session_dir,
    fingerprint,
    chunk_id,
    state,
    *,
    retryable=False,
    error=None,
    artifacts=None,
):
    """Persist a validated transition using atomic replacement."""
    checkpoint = load_checkpoint(session_dir, fingerprint, chunk_id)

    updated = transition_checkpoint(
        checkpoint,
        state,
        retryable=retryable,
        error=error,
        artifacts=artifacts,
    )

    path = _checkpoint_path(session_dir, updated)

    if path.is_symlink():
        raise ValueError("Symlinked checkpoint destination")

    _atomic_write(path, _serialize(updated))
    return updated


def verify_artifacts(session_dir, fingerprint, chunk_id):
    """Verify completed artifact files against declared SHA-256."""
    checkpoint = load_checkpoint(session_dir, fingerprint, chunk_id)

    if checkpoint["state"] != "completed":
        raise ValueError("Checkpoint is not completed")

    directory = _safe_directory(_directory(session_dir, checkpoint))

    for artifact in checkpoint["artifacts"]:
        expected_name = ARTIFACT_NAMES[artifact["kind"]]

        if artifact["path"] != expected_name:
            raise ValueError("Unexpected artifact filename")

        path = directory / expected_name

        # Open without following the final symlink component.
        # Verify the opened descriptor rather than a prior path lookup.
        flags = os.O_RDONLY | os.O_NOFOLLOW

        try:
            fd = os.open(path, flags)
        except OSError as exc:
            if path.is_symlink():
                raise ValueError("Symlinked artifact") from exc
            raise

        try:
            metadata = os.fstat(fd)

            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Artifact is not a regular file")

            digest = hashlib.sha256()

            with os.fdopen(fd, "rb", closefd=False) as stream:
                for block in iter(
                    lambda: stream.read(1024 * 1024), b""
                ):
                    digest.update(block)

            if digest.hexdigest() != artifact["sha256"]:
                raise ValueError(
                    f"Artifact checksum mismatch: {expected_name}"
                )
        finally:
            os.close(fd)

    return True
