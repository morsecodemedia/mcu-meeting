"""Deterministic FFmpeg extraction for transcription chunks."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import wave
from decimal import Decimal
from pathlib import Path

from processing.chunk_identity import canonical_chunk

SOURCE_RATE = 48000
OUTPUT_RATE = 16000
OUTPUT_CHANNELS = 1
OUTPUT_SAMPLE_WIDTH = 2


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sample_index(microseconds, rate):
    """Round a timestamp to the nearest sample, ties upward."""
    return (microseconds * rate + 500000) // 1000000


def _validate_source(path):
    with wave.open(str(path), "rb") as stream:
        if (
            stream.getframerate() != SOURCE_RATE
            or stream.getnchannels() != 1
            or stream.getsampwidth() != 2
            or stream.getcomptype() != "NONE"
        ):
            raise ValueError("Unsupported source WAV format")

        return stream.getnframes()


def _validate_output(path, expected_frames):
    with wave.open(str(path), "rb") as stream:
        if (
            stream.getframerate() != OUTPUT_RATE
            or stream.getnchannels() != OUTPUT_CHANNELS
            or stream.getsampwidth() != OUTPUT_SAMPLE_WIDTH
            or stream.getcomptype() != "NONE"
        ):
            raise ValueError("Invalid extracted WAV format")

        actual_frames = stream.getnframes()

    if abs(actual_frames - expected_frames) > 1:
        raise ValueError(
            f"Extracted duration mismatch: "
            f"{actual_frames} != {expected_frames}"
        )

    return actual_frames


def extract_chunk(
    source_wav,
    output_wav,
    chunk,
    *,
    ffmpeg_binary="ffmpeg",
    ffprobe_binary="ffprobe",
):
    """Extract one chunk and publish it without overwriting files."""
    source = Path(source_wav).expanduser().resolve(strict=True)
    output = Path(output_wav).expanduser().absolute()

    if not source.is_file():
        raise ValueError("Source is not a regular file")

    if output.is_symlink() or output.exists():
        raise FileExistsError(f"Output already exists: {output}")

    if output.resolve() == source:
        raise ValueError("Output cannot overwrite source WAV")

    bounds = canonical_chunk(chunk)
    source_frames = _validate_source(source)

    start = _sample_index(bounds["read_start_us"], SOURCE_RATE)
    end = _sample_index(bounds["read_end_us"], SOURCE_RATE)

    if start < 0 or end <= start or end > source_frames:
        raise ValueError("Chunk exceeds source WAV boundaries")

    expected_output_frames = _sample_index(
        bounds["read_end_us"], OUTPUT_RATE
    ) - _sample_index(bounds["read_start_us"], OUTPUT_RATE)

    parent = output.parent.resolve(strict=True)

    if not parent.is_dir():
        raise NotADirectoryError(parent)

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            dir=parent,
            prefix=".audio-chunk-",
            suffix=".wav",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)

        # Select exact input samples, then resample to 16 kHz mono.
        command = [
            ffmpeg_binary,
            "-hide_banner",
            "-nostdin",
            "-loglevel", "error",
            "-i", str(source),
            "-af",
            f"atrim=start_sample={start}:end_sample={end},"
            "asetpts=PTS-STARTPTS",
            "-ar", str(OUTPUT_RATE),
            "-ac", str(OUTPUT_CHANNELS),
            "-c:a", "pcm_s16le",
            "-y",
            str(temporary),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg extraction failed: {result.stderr.strip()}"
            )

        actual_frames = _validate_output(
            temporary, expected_output_frames
        )

        # Ensure completed bytes are synchronized before publication.
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())

        # Exclusive publication: existing destinations are preserved.
        os.link(temporary, output)

        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        return {
            "source_sha256": _sha256(source),
            "output_sha256": _sha256(output),
            "read_start_us": bounds["read_start_us"],
            "read_end_us": bounds["read_end_us"],
            "source_start_sample": start,
            "source_end_sample": end,
            "output_frames": actual_frames,
            "output_sample_rate": OUTPUT_RATE,
            "actual_duration_seconds": actual_frames / OUTPUT_RATE,
        }

    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
