"""Single-chunk checkpoint-backed transcription coordinator."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

from processing.audio_extraction import extract_chunk
from processing.checkpoint_store import checkpoint_store
from processing.chunk_execution_plan import plan_chunk_execution
from processing.chunk_identity import canonical_chunk
from processing.transcript_normalization import normalize_file
from processing.whisper_profile import WhisperProfile
from processing.whisper_runner import run_whisper, whisper_version
from session import manager
from session.recording import verify_wav

DIGEST = re.compile(r"^[0-9a-f]{64}$")
FFMPEG_VERSION = re.compile(r"ffmpeg version (\d+(?:\.\d+){1,3})")


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ffmpeg_version(binary):
    result = subprocess.run(
        [binary, "-version"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError("Unable to determine FFmpeg version")

    match = FFMPEG_VERSION.search(result.stdout)

    if not match:
        raise ValueError("Unrecognized FFmpeg version")

    return match.group(1)


def _source_artifact(manifest, source, session_dir):
    matches = [
        artifact
        for artifact in manifest.get("artifacts", [])
        if artifact.get("kind") == source
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one source artifact: {source}"
        )

    artifact = matches[0]
    expected_path = {
        "application_audio": "audio/application.wav",
        "microphone_audio": "audio/microphone.wav",
    }[source]

    if artifact.get("path") != expected_path:
        raise ValueError("Unexpected source artifact path")

    expected_digest = artifact.get("sha256")

    if (
        not isinstance(expected_digest, str)
        or not DIGEST.fullmatch(expected_digest)
    ):
        raise ValueError("Invalid source artifact checksum")

    path = session_dir / expected_path

    if path.is_symlink():
        raise ValueError("Symlinked source audio")

    actual_digest = verify_wav(path)

    if actual_digest != expected_digest:
        raise ValueError("Source audio checksum mismatch")

    return path, actual_digest


def _artifact_record(path, kind):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Invalid published artifact: {kind}")

    return {
        "kind": kind,
        "path": path.name,
        "sha256": _sha256(path),
    }


def execute_chunk(
    sessions_root,
    session_id,
    chunk,
    model_path,
    *,
    profile=None,
    ffmpeg_binary="ffmpeg",
    whisper_binary="whisper-cli",
):
    """Execute exactly one new chunk under coordinator ownership."""
    if profile is None:
        profile = WhisperProfile()

    bounds = canonical_chunk(chunk)
    source = bounds["source"]

    root = Path(sessions_root).expanduser().resolve(strict=True)
    session_dir = manager._session_dir(root, session_id)

    model = Path(model_path).expanduser().resolve(strict=True)

    if model.is_symlink() or not model.is_file():
        raise ValueError("Invalid Whisper model")

    with checkpoint_store(root, session_id) as store:
        manifest = manager.load(root, session_id)

        source_wav, audio_sha256 = _source_artifact(
            manifest, source, session_dir
        )

        model_sha256 = _sha256(model)
        ffmpeg_version = _ffmpeg_version(ffmpeg_binary)
        engine_version = whisper_version(whisper_binary)

        plan = plan_chunk_execution(
            chunk,
            audio_sha256=audio_sha256,
            model_sha256=model_sha256,
            ffmpeg_version=ffmpeg_version,
            whisper_version=engine_version,
            profile=profile,
        )

        fingerprint = plan["fingerprint"]
        chunk_id = plan["chunk_id"]

        # Exclusive creation refuses all existing checkpoints.
        store.create(fingerprint, chunk_id)
        store.transition(fingerprint, chunk_id, "running")

        directory = session_dir / Path(
            plan["artifacts"]["checkpoint"]
        ).parent

        whisper_json = directory / "whisper.json"
        normalized_json = directory / "normalized.json"

        try:
            with tempfile.TemporaryDirectory(
                prefix="mcu-chunk-"
            ) as temporary:
                extracted = Path(temporary) / "chunk.wav"

                extraction = extract_chunk(
                    source_wav,
                    extracted,
                    chunk,
                    ffmpeg_binary=ffmpeg_binary,
                )

                if extraction["source_sha256"] != audio_sha256:
                    raise ValueError("Extraction source checksum mismatch")

                result = run_whisper(
                    extracted,
                    model,
                    whisper_json,
                    profile=profile,
                    binary=whisper_binary,
                )

                if result["version"] != engine_version:
                    raise ValueError("Whisper version changed during execution")

                if result["model_sha256"] != model_sha256:
                    raise ValueError("Whisper model checksum mismatch")

                if result["input_sha256"] != extraction["output_sha256"]:
                    raise ValueError("Whisper input checksum mismatch")

                normalize_file(
                    whisper_json,
                    normalized_json,
                    source=source,
                    excerpt_start_seconds=(
                        bounds["read_start_us"] / 1000000
                    ),
                    model_sha256=model_sha256,
                    chunk_id=chunk_id,
                )

            artifacts = [
                _artifact_record(whisper_json, "whisper_json"),
                _artifact_record(normalized_json, "normalized_json"),
            ]

            if artifacts[0]["sha256"] != result["output_sha256"]:
                raise ValueError("Whisper output checksum mismatch")

            store.transition(
                fingerprint,
                chunk_id,
                "completed",
                artifacts=artifacts,
            )

            store.verify(fingerprint, chunk_id)

            return {
                "chunk_id": chunk_id,
                "fingerprint": fingerprint,
                "state": "completed",
                "artifacts": artifacts,
                "segments": result["segments"],
            }

        except Exception as exc:
            current = store.load(fingerprint, chunk_id)

            if current["state"] == "running":
                store.transition(
                    fingerprint,
                    chunk_id,
                    "failed",
                    retryable=False,
                    error=f"{type(exc).__name__}: {exc}",
                )

            raise
