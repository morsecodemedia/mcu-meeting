"""Deterministic planning for source-aware transcription batches."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from processing.chunk_planning import plan_chunks

SOURCES = ("application_audio", "microphone_audio")
MICROSECONDS = Decimal(1000000)


def duration_microseconds(frames, sample_rate):
    """Round exact WAV duration to nearest microsecond, ties upward."""
    if type(frames) is not int or frames <= 0:
        raise ValueError("frames must be a positive integer")

    if type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")

    value = (
        Decimal(frames) * MICROSECONDS / Decimal(sample_rate)
    )

    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def plan_batch(
    source_durations_us,
    *,
    chunk_seconds=300,
    overlap_seconds=2,
):
    """Plan available sources in stable application/microphone order."""
    if not isinstance(source_durations_us, dict):
        raise ValueError("source durations must be a dictionary")

    if not source_durations_us:
        raise ValueError("at least one source is required")

    if set(source_durations_us) - set(SOURCES):
        raise ValueError("unsupported source")

    results = []
    total = 0

    for source in SOURCES:
        if source not in source_durations_us:
            continue

        duration_us = source_durations_us[source]

        if type(duration_us) is not int or duration_us <= 0:
            raise ValueError("invalid source duration")

        chunks = plan_chunks(
            Decimal(duration_us) / MICROSECONDS,
            source,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
        )

        results.append({
            "source": source,
            "duration_us": duration_us,
            "chunk_count": len(chunks),
            "chunks": chunks,
        })

        total += len(chunks)

    return {
        "schema_version": 1,
        "sources": results,
        "total_chunks": total,
    }
