"""Normalize Whisper JSON while preserving source provenance."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path


VALID_SOURCES = {"application_audio", "microphone_audio"}


def normalize(
    payload: dict,
    *,
    source: str,
    excerpt_start_seconds: float = 0.0,
    model_sha256: str | None = None,
) -> dict:
    if source not in VALID_SOURCES:
        raise ValueError(f"Unsupported audio source: {source}")

    if not isinstance(payload, dict):
        raise ValueError("Whisper payload must be an object")

    if not math.isfinite(excerpt_start_seconds) or excerpt_start_seconds < 0:
        raise ValueError("Invalid excerpt start")

    raw_segments = payload.get("transcription")
    if not isinstance(raw_segments, list):
        raise ValueError("Missing transcription array")

    model = payload.get("model", {})
    if not isinstance(model, dict):
        raise ValueError("Invalid model metadata")

    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("Invalid transcription parameters")

    normalized = []

    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            raise ValueError(f"Invalid segment {index}")

        offsets = segment.get("offsets")
        if not isinstance(offsets, dict):
            raise ValueError(f"Missing offsets at segment {index}")

        start_ms = offsets.get("from")
        end_ms = offsets.get("to")

        if (
            isinstance(start_ms, bool)
            or isinstance(end_ms, bool)
            or not isinstance(start_ms, (int, float))
            or not isinstance(end_ms, (int, float))
            or not math.isfinite(start_ms)
            or not math.isfinite(end_ms)
            or start_ms < 0
            or end_ms <= start_ms
        ):
            raise ValueError(f"Invalid timing at segment {index}")

        text = segment.get("text")
        if not isinstance(text, str):
            raise ValueError(f"Invalid text at segment {index}")

        start = excerpt_start_seconds + start_ms / 1000
        end = excerpt_start_seconds + end_ms / 1000

        normalized.append({
            "id": f"{source}:{index}",
            "source": source,
            "start_seconds": round(start, 6),
            "end_seconds": round(end, 6),
            "text": text.strip(),
            "speaker": "unresolved",
            "attribution_method": None,
        })

    return {
        "schema_version": 1,
        "source": source,
        "excerpt_start_seconds": excerpt_start_seconds,
        "model": {
            "type": model.get("type"),
            "language": params.get("language"),
            "sha256": model_sha256,
        },
        "segments": normalized,
    }


def normalize_file(
    input_path: Path,
    output_path: Path,
    *,
    source: str,
    excerpt_start_seconds: float = 0.0,
    model_sha256: str | None = None,
) -> dict:
    """Normalize Whisper JSON and publish an immutable artifact.

    The source is never modified. The destination must not exist.
    Publication uses an exclusive hard link from a fully written
    temporary file, preventing replacement of an existing artifact.
    """
    input_path = Path(input_path).expanduser().resolve(strict=True)
    output_path = Path(output_path).expanduser().absolute()

    if output_path.is_symlink():
        raise FileExistsError("Output symlinks are not allowed")

    if output_path.exists():
        raise FileExistsError(f"Output already exists: {output_path}")

    if output_path.resolve() == input_path:
        raise ValueError("Output cannot overwrite source JSON")

    # Read once so the checksum describes exactly what was parsed.
    original = input_path.read_bytes()
    payload = json.loads(original.decode("utf-8"))

    result = normalize(
        payload,
        source=source,
        excerpt_start_seconds=excerpt_start_seconds,
        model_sha256=model_sha256,
    )

    result["provenance"] = {
        "source_json_sha256": hashlib.sha256(original).hexdigest(),
        "source_format": "whisper.cpp-json",
    }

    destination = output_path.parent.resolve(strict=True)

    if not destination.is_dir():
        raise NotADirectoryError(destination)

    serialized = (json.dumps(result, indent=2) + "\n").encode("utf-8")

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination,
            prefix=".transcript-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())

        # Atomic no-replace publication on the same filesystem.
        os.link(temporary, output_path)

        # Persist directory metadata for durability.
        directory_fd = os.open(destination, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return result
