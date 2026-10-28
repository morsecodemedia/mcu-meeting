"""Pure, deterministic planning for one transcription chunk."""

from __future__ import annotations

import copy
import re

from processing.execution_identity import (
    execution_fingerprint,
    execution_identity,
)
from processing.whisper_profile import WhisperProfile

DIGEST = re.compile(r"^[0-9a-f]{64}$")


def plan_chunk_execution(
    chunk,
    *,
    audio_sha256,
    model_sha256,
    ffmpeg_version,
    whisper_version,
    profile,
):
    """Return a canonical execution plan without filesystem access."""
    if not isinstance(profile, WhisperProfile):
        raise ValueError("profile must be WhisperProfile")

    identity = execution_identity(
        chunk,
        audio_sha256=audio_sha256,
        model_sha256=model_sha256,
        ffmpeg_version=ffmpeg_version,
        whisper_version=whisper_version,
        profile=profile,
    )

    fingerprint = execution_fingerprint(
        chunk,
        audio_sha256=audio_sha256,
        model_sha256=model_sha256,
        ffmpeg_version=ffmpeg_version,
        whisper_version=whisper_version,
        profile=profile,
    )

    canonical_chunk = identity["chunk"]
    source = canonical_chunk["source"]
    index = canonical_chunk["index"]

    relative_root = (
        f"processing/transcription/"
        f"{source}/{index:06d}/{fingerprint}"
    )

    return {
        "schema_version": 1,
        "chunk_id": canonical_chunk["chunk_id"],
        "fingerprint": fingerprint,
        "source": source,
        "index": index,
        "owned_interval_us": {
            "start": canonical_chunk["owned_start_us"],
            "end": canonical_chunk["owned_end_us"],
        },
        "read_interval_us": {
            "start": canonical_chunk["read_start_us"],
            "end": canonical_chunk["read_end_us"],
        },
        "artifacts": {
            "checkpoint": f"{relative_root}/checkpoint.json",
            "whisper_json": f"{relative_root}/whisper.json",
            "normalized_json": f"{relative_root}/normalized.json",
        },
        "execution": {
            "ffmpeg": copy.deepcopy(identity["ffmpeg"]),
            "whisper": copy.deepcopy(identity["whisper"]),
            "audio_sha256": identity["audio_sha256"],
            "model_sha256": identity["model_sha256"],
        },
    }
