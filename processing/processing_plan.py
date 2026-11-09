"""Pure processing decisions for planned transcription checkpoints."""

from __future__ import annotations

from processing.chunk_checkpoint import validate_checkpoint


def classify_planned_checkpoint(
    expected_fingerprint,
    expected_chunk_id,
    checkpoint,
    *,
    artifact_status="unknown",
):
    """Classify one exact planned checkpoint without modifying evidence."""

    if checkpoint is None:
        return {
            "classification": "missing",
            "action": "execute",
        }

    validate_checkpoint(checkpoint)

    if (
        checkpoint["fingerprint"] != expected_fingerprint
        or checkpoint["chunk_id"] != expected_chunk_id
    ):
        raise ValueError("Checkpoint execution identity mismatch")

    if artifact_status not in {"verified", "invalid", "unknown"}:
        raise ValueError("Invalid artifact status")

    state = checkpoint["state"]

    if state == "completed":
        if artifact_status == "verified":
            return {
                "classification": "reusable",
                "action": "reuse",
            }

        if artifact_status == "invalid":
            return {
                "classification": "blocked_integrity",
                "action": "stop",
            }

        return {
            "classification": "blocked_unknown",
            "action": "stop",
        }

    if state == "failed":
        return {
            "classification": "blocked_failed",
            "action": "stop",
        }

    if state in {"pending", "running"}:
        return {
            "classification": "blocked_incomplete",
            "action": "stop",
        }

    return {
        "classification": "blocked_unknown",
        "action": "stop",
    }



def _checkpoint_directory_status(session_dir, relative_checkpoint):
    """Classify an exact checkpoint directory without following symlinks."""

    import stat
    from pathlib import Path

    session_dir = Path(session_dir)
    relative = Path(relative_checkpoint)

    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid checkpoint path")

    current = session_dir

    for component in relative.parent.parts:
        current = current / component

        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return "missing"

        if stat.S_ISLNK(metadata.st_mode):
            return "invalid"

        if not stat.S_ISDIR(metadata.st_mode):
            return "invalid"

    return "present"

def plan_session_processing(
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
    """Inspect exact execution checkpoints without modifying evidence."""

    from pathlib import Path

    from processing.batch_planning import plan_batch
    from processing.batch_runner import _source_durations
    from processing.chunk_coordinator import (
        _ffmpeg_version,
        _sha256,
    )
    from processing.chunk_discovery import inspect_coordinator_lock
    from processing.chunk_execution_plan import plan_chunk_execution
    from processing.chunk_storage import (
        load_checkpoint,
        verify_artifacts,
    )
    from processing.whisper_profile import WhisperProfile
    from processing.whisper_runner import whisper_version
    from session import manager

    if profile is None:
        profile = WhisperProfile()

    if not isinstance(profile, WhisperProfile):
        raise ValueError("Invalid Whisper profile")

    root = Path(sessions_root).expanduser().resolve(strict=True)
    folder = manager._session_dir(root, session_id)

    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Invalid session directory")

    manifest = manager.load(root, session_id)

    if manifest.get("session_id") != session_id:
        raise ValueError("Session identity mismatch")

    if manifest.get("capture", {}).get("state") != "completed":
        raise ValueError("Capture is not completed")

    model = Path(model_path).expanduser()

    if model.is_symlink() or not model.is_file():
        raise ValueError("Invalid Whisper model")

    model_sha256 = _sha256(model)
    ffmpeg_version = _ffmpeg_version(ffmpeg_binary)
    engine_version = whisper_version(whisper_binary)

    durations = _source_durations(manifest, folder)

    batch = plan_batch(
        durations,
        chunk_seconds=chunk_seconds,
        overlap_seconds=overlap_seconds,
    )

    lock_status = inspect_coordinator_lock(folder)

    entries = []

    for source_plan in batch["sources"]:
        source = source_plan["source"]

        artifacts = [
            item for item in manifest["artifacts"]
            if item.get("kind") == source
        ]

        if len(artifacts) != 1:
            raise ValueError("Invalid source artifact registration")

        audio_sha256 = artifacts[0]["sha256"]

        for chunk in source_plan["chunks"]:
            execution = plan_chunk_execution(
                chunk,
                audio_sha256=audio_sha256,
                model_sha256=model_sha256,
                ffmpeg_version=ffmpeg_version,
                whisper_version=engine_version,
                profile=profile,
            )

            fingerprint = execution["fingerprint"]
            chunk_id = execution["chunk_id"]

            directory_status = _checkpoint_directory_status(
                folder,
                execution["artifacts"]["checkpoint"],
            )

            if directory_status == "invalid":
                decision = {
                    "classification": "blocked_integrity",
                    "action": "stop",
                }

            elif directory_status == "missing":
                decision = classify_planned_checkpoint(
                    fingerprint, chunk_id, None
                )

            else:
                try:
                    checkpoint = load_checkpoint(
                        folder, fingerprint, chunk_id
                    )
                except (OSError, ValueError, KeyError, TypeError):
                    decision = {
                        "classification": "blocked_integrity",
                        "action": "stop",
                    }
                else:
                    status = "unknown"

                    if checkpoint["state"] == "completed":
                        try:
                            verify_artifacts(
                                folder, fingerprint, chunk_id
                            )
                        except (OSError, ValueError, KeyError):
                            status = "invalid"
                        else:
                            status = "verified"

                    decision = classify_planned_checkpoint(
                        fingerprint,
                        chunk_id,
                        checkpoint,
                        artifact_status=status,
                    )

            if lock_status != "available":
                decision = {
                    "classification": "blocked_unknown",
                    "action": "stop",
                }

            entries.append({
                "chunk_id": chunk_id,
                "fingerprint": fingerprint,
                "source": source,
                **decision,
            })

    return {
        "schema_version": 1,
        "session_id": session_id,
        "lock_status": lock_status,
        "batch_plan": batch,
        "model_sha256": model_sha256,
        "ffmpeg_version": ffmpeg_version,
        "whisper_version": engine_version,
        "entries": entries,
        "counts": {
            category: sum(
                item["classification"] == category
                for item in entries
            )
            for category in (
                "missing",
                "reusable",
                "blocked_incomplete",
                "blocked_failed",
                "blocked_integrity",
                "blocked_unknown",
            )
        },
    }
