"""Versioned execution provenance for transcription chunks."""

from __future__ import annotations

import hashlib
import json
import re

from processing.chunk_identity import canonical_chunk
from processing.whisper_profile import WhisperProfile

IDENTITY_VERSION = 3
PLANNER_VERSION = 1
EXTRACTION_VERSION = 1

SHA256 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")

EXTRACTION_PROFILE = {
    "source_sample_rate": 48000,
    "source_channels": 1,
    "source_sample_format": "pcm_s16le",
    "output_sample_rate": 16000,
    "output_channels": 1,
    "output_sample_format": "pcm_s16le",
    "filter": "atrim=start_sample:end_sample,asetpts=PTS-STARTPTS",
    "sample_rounding": "nearest_ties_up",
    "resampling": "ffmpeg_default",
}


def execution_identity(
    chunk,
    *,
    audio_sha256,
    model_sha256,
    ffmpeg_version,
    whisper_version,
    profile,
):
    """Build a canonical, JSON-safe execution identity."""
    for name, digest in (
        ("audio_sha256", audio_sha256),
        ("model_sha256", model_sha256),
    ):
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError(f"invalid {name}")

    for name, version in (
        ("ffmpeg_version", ffmpeg_version),
        ("whisper_version", whisper_version),
    ):
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            raise ValueError(f"invalid {name}")

    if not isinstance(profile, WhisperProfile):
        raise ValueError("profile must be WhisperProfile")

    # cli_arguments() also rejects unsupported execution features,
    # including VAD in profile v1.
    profile.cli_arguments()

    return {
        "identity_version": IDENTITY_VERSION,
        "planner_version": PLANNER_VERSION,
        "extraction_version": EXTRACTION_VERSION,
        "chunk": canonical_chunk(chunk),
        "audio_sha256": audio_sha256,
        "model_sha256": model_sha256,
        "ffmpeg": {
            "version": ffmpeg_version,
            "profile": dict(EXTRACTION_PROFILE),
        },
        "whisper": {
            "engine": "whisper.cpp",
            "version": whisper_version,
            "profile": profile.canonical(),
        },
    }


def execution_fingerprint(
    chunk,
    *,
    audio_sha256,
    model_sha256,
    ffmpeg_version,
    whisper_version,
    profile,
):
    """Return SHA-256 of canonical execution provenance."""
    identity = execution_identity(
        chunk,
        audio_sha256=audio_sha256,
        model_sha256=model_sha256,
        ffmpeg_version=ffmpeg_version,
        whisper_version=whisper_version,
        profile=profile,
    )

    payload = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()
