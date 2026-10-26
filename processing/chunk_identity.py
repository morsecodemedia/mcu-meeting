"""Canonical transcription chunk identity; no filesystem I/O."""

import hashlib
import json
import re

from processing.chunk_planning import _microseconds

IDENTITY_VERSION = 2
PLANNER_VERSION = 1

SHA256 = re.compile(r"^[0-9a-f]{64}$")
SOURCES = frozenset({"application_audio", "microphone_audio"})

PARAMETER_KEYS = frozenset({
    "language",
    "beam_size",
    "temperature",
    "sample_rate",
    "channels",
    "sample_format",
})

DEFAULT_PARAMETERS = {
    "language": "en",
    "beam_size": 5,
    "temperature": 0,
    "sample_rate": 16000,
    "channels": 1,
    "sample_format": "pcm_s16le",
}


def canonical_parameters(parameters):
    """Validate and expand the supported processing configuration."""
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")

    unknown = set(parameters) - PARAMETER_KEYS
    if unknown:
        raise ValueError(f"unsupported parameters: {sorted(unknown)}")

    result = dict(DEFAULT_PARAMETERS)
    result.update(parameters)

    if not isinstance(result["language"], str) or not result["language"]:
        raise ValueError("invalid language")

    for name in ("beam_size", "sample_rate", "channels"):
        value = result[name]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"invalid {name}")

    if result["sample_rate"] != 16000:
        raise ValueError("sample_rate must be 16000")

    if result["channels"] != 1:
        raise ValueError("channels must be 1")

    if result["sample_format"] != "pcm_s16le":
        raise ValueError("unsupported sample_format")

    result["temperature_micro"] = _microseconds(
        result.pop("temperature"),
        "temperature",
        allow_zero=True,
    )

    return result


def canonical_chunk(chunk):
    """Validate chunk structure and canonicalize boundaries."""
    if not isinstance(chunk, dict):
        raise ValueError("chunk must be an object")

    source = chunk.get("source")
    index = chunk.get("index")

    if source not in SOURCES:
        raise ValueError("unsupported source")

    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("invalid chunk index")

    expected_id = f"{source}:{index:06d}"
    if chunk.get("chunk_id") != expected_id:
        raise ValueError("chunk ID does not match source/index")

    names = (
        "owned_start_seconds",
        "owned_end_seconds",
        "read_start_seconds",
        "read_end_seconds",
    )

    values = {}

    for name in names:
        if name not in chunk:
            raise ValueError(f"missing {name}")

        values[name.replace("_seconds", "_us")] = _microseconds(
            chunk[name],
            name,
            allow_zero=True,
        )

    if not (
        0 <= values["read_start_us"]
        <= values["owned_start_us"]
        < values["owned_end_us"]
        <= values["read_end_us"]
    ):
        raise ValueError("invalid chunk boundaries")

    return {
        "chunk_id": expected_id,
        "source": source,
        "index": index,
        **values,
    }


def fingerprint(chunk, *, audio_sha256, model_sha256,
                engine_version, parameters):
    """Return a deterministic processing identity SHA-256."""
    for name, digest in (
        ("audio_sha256", audio_sha256),
        ("model_sha256", model_sha256),
    ):
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError(f"invalid {name}")

    if not isinstance(engine_version, str) or not engine_version.strip():
        raise ValueError("engine_version required")

    identity = {
        "identity_version": IDENTITY_VERSION,
        "planner_version": PLANNER_VERSION,
        "chunk": canonical_chunk(chunk),
        "audio_sha256": audio_sha256,
        "model_sha256": model_sha256,
        "engine": {
            "name": "whisper.cpp",
            "version": engine_version.strip(),
        },
        "parameters": canonical_parameters(parameters),
    }

    canonical = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(canonical).hexdigest()
