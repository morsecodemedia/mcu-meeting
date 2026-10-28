"""Sequential, stop-on-first-failure transcription batch runner."""

from __future__ import annotations

import wave
from pathlib import Path

from processing.batch_planning import (
    duration_microseconds,
    plan_batch,
)
from processing.chunk_coordinator import execute_chunk
from processing.whisper_profile import WhisperProfile
from session import manager
from session.recording import verify_wav

SOURCES = {
    "application_audio": "audio/application.wav",
    "microphone_audio": "audio/microphone.wav",
}


def _source_durations(manifest, session_dir):
    """Verify registered WAVs and derive durations from frame counts."""
    artifacts = manifest.get("artifacts", [])

    if not isinstance(artifacts, list):
        raise ValueError("Invalid manifest artifacts")

    durations = {}

    for source, relative_path in SOURCES.items():
        matches = [
            item for item in artifacts
            if isinstance(item, dict) and item.get("kind") == source
        ]

        if not matches:
            continue

        if len(matches) != 1:
            raise ValueError(f"Duplicate source artifact: {source}")

        item = matches[0]

        if item.get("path") != relative_path:
            raise ValueError("Unexpected source artifact path")

        path = session_dir / relative_path

        if path.is_symlink() or not path.is_file():
            raise ValueError("Invalid source WAV")

        if verify_wav(path) != item.get("sha256"):
            raise ValueError("Source WAV checksum mismatch")

        with wave.open(str(path), "rb") as stream:
            if (
                stream.getframerate() != 48000
                or stream.getnchannels() != 1
                or stream.getsampwidth() != 2
            ):
                raise ValueError("Unsupported source WAV format")

            durations[source] = duration_microseconds(
                stream.getnframes(),
                stream.getframerate(),
            )

    if not durations:
        raise ValueError("No registered source audio")

    return durations


def execute_batch(
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
    """Execute a batch sequentially, preserving partial progress."""
    if profile is None:
        profile = WhisperProfile()

    root = Path(sessions_root).expanduser().resolve(strict=True)
    folder = manager._session_dir(root, session_id)

    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Invalid session directory")

    manifest = manager.load(root, session_id)

    if manifest.get("session_id") != session_id:
        raise ValueError("Session identity mismatch")

    if manifest.get("capture", {}).get("state") != "completed":
        raise ValueError("Batch requires completed capture")

    durations = _source_durations(manifest, folder)

    plan = plan_batch(
        durations,
        chunk_seconds=chunk_seconds,
        overlap_seconds=overlap_seconds,
    )

    entries = [
        {
            "chunk_id": chunk["chunk_id"],
            "source": source["source"],
            "state": "not_attempted",
        }
        for source in plan["sources"]
        for chunk in source["chunks"]
    ]

    report = {
        "schema_version": 1,
        "session_id": session_id,
        "state": "completed",
        "total_chunks": len(entries),
        "completed_chunks": 0,
        "entries": entries,
    }

    index = 0

    for source in plan["sources"]:
        for chunk in source["chunks"]:
            try:
                result = execute_chunk(
                    root,
                    session_id,
                    chunk,
                    model_path,
                    profile=profile,
                    ffmpeg_binary=ffmpeg_binary,
                    whisper_binary=whisper_binary,
                )
            except Exception as exc:
                entries[index]["state"] = "failed"
                entries[index]["error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                report["state"] = "stopped"
                return report

            entries[index]["state"] = "completed"
            entries[index]["fingerprint"] = result["fingerprint"]
            entries[index]["segments"] = result["segments"]

            report["completed_chunks"] += 1
            index += 1

    return report
