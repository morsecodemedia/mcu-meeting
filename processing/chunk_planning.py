"""Deterministic, source-aware transcription chunk planning."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

VALID_SOURCES = frozenset({
    "application_audio",
    "microphone_audio",
})

MICROSECONDS = 1_000_000


def _microseconds(value, name, *, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")

    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be numeric") from None

    if not number.is_finite():
        raise ValueError(f"{name} must be finite")

    if number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"{name} must be positive")

    scaled = number * MICROSECONDS

    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"{name} supports at most microsecond precision"
        )

    return int(scaled)


def plan_chunks(
    duration_seconds,
    source,
    *,
    chunk_seconds=300,
    overlap_seconds=2,
):
    """Return deterministic chunks with distinct owned/read intervals.

    Each chunk owns [start, end), except the final endpoint
    corresponds to the recording's end. Trailing overlap is
    read-only context belonging to the following chunk.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Unsupported source: {source}")

    duration = _microseconds(duration_seconds, "duration")
    chunk = _microseconds(chunk_seconds, "chunk_seconds")
    overlap = _microseconds(
        overlap_seconds, "overlap_seconds", allow_zero=True
    )

    if overlap >= chunk:
        raise ValueError("overlap must be smaller than chunk duration")

    results = []
    index = 0

    for owned_start in range(0, duration, chunk):
        owned_end = min(owned_start + chunk, duration)
        read_end = min(owned_end + overlap, duration)

        results.append({
            "chunk_id": f"{source}:{index:06d}",
            "source": source,
            "index": index,
            "owned_start_seconds": owned_start / MICROSECONDS,
            "owned_end_seconds": owned_end / MICROSECONDS,
            "read_start_seconds": owned_start / MICROSECONDS,
            "read_end_seconds": read_end / MICROSECONDS,
            "context_end_seconds": read_end / MICROSECONDS,
        })

        index += 1

    return results
