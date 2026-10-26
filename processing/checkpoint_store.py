"""Coordinator-owned access to durable transcription checkpoints."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from processing import chunk_storage
from session import manager


class CheckpointStore:
    """Checkpoint operations scoped to an active coordinator lock."""

    def __init__(self, session_dir: Path):
        self._session_dir = session_dir
        self._active = True

    def _require_active(self):
        if not self._active:
            raise RuntimeError("CheckpointStore is closed")

    def close(self):
        self._active = False

    def create(self, fingerprint: str, chunk_id: str):
        self._require_active()
        return chunk_storage.create_checkpoint(
            self._session_dir, fingerprint, chunk_id
        )

    def load(self, fingerprint: str, chunk_id: str):
        self._require_active()
        return chunk_storage.load_checkpoint(
            self._session_dir, fingerprint, chunk_id
        )

    def transition(self, fingerprint: str, chunk_id: str, state: str,
                   *, retryable=False, error=None, artifacts=None):
        self._require_active()
        return chunk_storage.save_transition(
            self._session_dir,
            fingerprint,
            chunk_id,
            state,
            retryable=retryable,
            error=error,
            artifacts=artifacts,
        )

    def verify(self, fingerprint: str, chunk_id: str):
        self._require_active()
        return chunk_storage.verify_artifacts(
            self._session_dir, fingerprint, chunk_id
        )


@contextmanager
def checkpoint_store(sessions_root: Path, session_id: str):
    """Validate session and hold coordinator lock for store lifetime."""
    root = Path(sessions_root).expanduser().resolve(strict=True)

    # Validate canonical UUID and derive the session directory.
    folder = manager._session_dir(root, session_id)

    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Invalid session directory")

    with manager.processing_lock(root, session_id):
        manifest = manager.load(root, session_id)

        if manifest.get("session_id") != session_id:
            raise ValueError("Session identity mismatch")

        if manifest.get("capture", {}).get("state") != "completed":
            raise ValueError("Checkpoint mutation requires completed capture")

        store = CheckpointStore(folder)

        try:
            yield store
        finally:
            store.close()
