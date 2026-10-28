"""Pure, deterministic assembly of normalized transcription chunks."""

from __future__ import annotations

import copy
import re
from decimal import Decimal, InvalidOperation

SOURCE_ORDER = {
    "application_audio": 0,
    "microphone_audio": 1,
}

CHUNK_ID = re.compile(
    r"^(application_audio|microphone_audio):([0-9]{6,})$"
)

EPSILON = Decimal("0.000001")


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")

    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Invalid {name}") from None

    if not number.is_finite():
        raise ValueError(f"Nonfinite {name}")

    return number


def _segment_key(segment):
    match = CHUNK_ID.fullmatch(segment["chunk_id"])

    return (
        _number(segment["start_seconds"], "start"),
        _number(segment["end_seconds"], "end"),
        SOURCE_ORDER[segment["source"]],
        int(match.group(2)),
        segment["segment_index"],
    )


def assemble_transcript(batch_plan, normalized_chunks):
    """Assemble verified normalized chunks without changing source data.

    normalized_chunks maps chunk IDs to normalized transcript objects.
    Checkpoint integrity verification is required before calling this
    pure function; it is not performed here.
    """
    if not isinstance(batch_plan, dict):
        raise ValueError("Invalid batch plan")

    if not isinstance(normalized_chunks, dict):
        raise ValueError("Invalid normalized chunks")

    expected = {}
    for source_plan in batch_plan["sources"]:
        source = source_plan["source"]

        if source not in SOURCE_ORDER:
            raise ValueError("Unsupported source")

        for chunk in source_plan["chunks"]:
            chunk_id = chunk["chunk_id"]

            if chunk_id in expected:
                raise ValueError("Duplicate planned chunk")

            if chunk["source"] != source:
                raise ValueError("Chunk source mismatch")

            expected[chunk_id] = chunk

    if set(expected) != set(normalized_chunks):
        raise ValueError("Missing or unexpected normalized chunks")

    included = []
    findings = []
    seen_ids = set()

    for chunk_id, chunk in expected.items():
        normalized = normalized_chunks[chunk_id]

        if normalized["chunk_id"] != chunk_id:
            raise ValueError("Normalized chunk ID mismatch")

        if normalized["source"] != chunk["source"]:
            raise ValueError("Normalized source mismatch")

        owned_start = _number(
            chunk["owned_start_seconds"], "owned start"
        )
        owned_end = _number(
            chunk["owned_end_seconds"], "owned end"
        )
        read_start = _number(
            chunk["read_start_seconds"], "read start"
        )
        read_end = _number(
            chunk["read_end_seconds"], "read end"
        )

        if not (
            read_start <= owned_start < owned_end <= read_end
        ):
            raise ValueError("Invalid chunk intervals")

        for index, original in enumerate(normalized["segments"]):
            segment = copy.deepcopy(original)

            segment_id = segment["id"]

            if segment_id in seen_ids:
                raise ValueError("Duplicate segment ID")

            seen_ids.add(segment_id)

            if not segment_id.startswith(chunk_id + ":"):
                raise ValueError("Segment ID/chunk mismatch")

            if segment["source"] != chunk["source"]:
                raise ValueError("Segment source mismatch")

            start = _number(
                segment["start_seconds"], "segment start"
            )
            end = _number(
                segment["end_seconds"], "segment end"
            )

            if start >= end:
                raise ValueError("Invalid segment interval")

            outside_read_interval = (
                start < read_start - EPSILON
                or end > read_end + EPSILON
            )

            segment["chunk_id"] = chunk_id
            segment["segment_index"] = index

            if outside_read_interval:
                findings.append({
                    "type": "timing_out_of_bounds",
                    "chunk_id": chunk_id,
                    "segment": segment,
                })

            elif (
                start >= owned_start - EPSILON
                and end <= owned_end + EPSILON
            ):
                included.append(segment)

            elif start >= owned_end - EPSILON:
                findings.append({
                    "type": "context_only",
                    "chunk_id": chunk_id,
                    "segment": segment,
                })

            else:
                findings.append({
                    "type": "boundary_spanning",
                    "chunk_id": chunk_id,
                    "segment": segment,
                })

    included.sort(key=_segment_key)

    findings.sort(
        key=lambda finding: _segment_key(finding["segment"])
    )

    unresolved = sum(
        item["type"] in (
            "boundary_spanning",
            "timing_out_of_bounds",
        )
        for item in findings
    )

    return {
        "schema_version": 1,
        "state": (
            "requires_reconciliation"
            if unresolved
            else "assembled"
        ),
        "segments": included,
        "findings": findings,
        "segment_count": len(included),
        "unresolved_count": unresolved,
    }
