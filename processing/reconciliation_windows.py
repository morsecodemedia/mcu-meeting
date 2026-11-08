"""Deterministic bounded review windows for transcript reconciliation."""

from __future__ import annotations

from collections import defaultdict
import re

WINDOW_US = 30_000_000
PADDING_US = 5_000_000
SOURCES = frozenset({"application_audio", "microphone_audio"})
SEGMENT_ID = re.compile(
    r"^(application_audio|microphone_audio):([0-9]{6}):([0-9]+)$"
)


def _us(value):
    from processing.chunk_planning import _microseconds
    return _microseconds(value, "timestamp", allow_zero=True)


def plan_review_windows(segments):
    """Assign every segment to one window without modifying input."""

    if not isinstance(segments, list):
        raise ValueError("Invalid segments")

    indexed = []
    seen = set()

    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Invalid segment")

        sid = segment.get("id")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError("Invalid or duplicate segment ID")

        seen.add(sid)

        if segment.get("source") not in SOURCES:
            raise ValueError("Unsupported recording source")

        match = SEGMENT_ID.fullmatch(sid)
        if match is None or match.group(1) != segment["source"]:
            raise ValueError("Invalid segment identity")

        expected_chunk = f"{match.group(1)}:{match.group(2)}"
        expected_index = int(match.group(3))

        if (
            "chunk_id" in segment
            and segment["chunk_id"] != expected_chunk
        ):
            raise ValueError("Segment chunk identity mismatch")

        if (
            "segment_index" in segment
            and (
                type(segment["segment_index"]) is not int
                or segment["segment_index"] != expected_index
            )
        ):
            raise ValueError("Segment index mismatch")

        start = _us(segment["start_seconds"])
        end = _us(segment["end_seconds"])

        if end <= start:
            raise ValueError("Invalid segment interval")

        midpoint = (start + end) // 2
        owner = midpoint // WINDOW_US

        indexed.append({
            "id": sid,
            "source": segment["source"],
            "start_us": start,
            "end_us": end,
            "owner": owner,
        })

    windows = defaultdict(list)

    for item in indexed:
        windows[item["owner"]].append(item["id"])

    result = []

    for index in sorted(windows):
        start = index * WINDOW_US
        end = start + WINDOW_US

        context = [
            item["id"]
            for item in indexed
            if item["start_us"] < end + PADDING_US
            and item["end_us"] > start - PADDING_US
        ]

        result.append({
            "window_index": index,
            "start_us": start,
            "end_us": end,
            "owned_segment_ids": sorted(windows[index]),
            "context_segment_ids": sorted(set(context)),
        })

    return result


def plan_candidate_pairs(segments):
    """Assign every cross-source temporal overlap to one review window."""

    if not isinstance(segments, list):
        raise ValueError("Invalid segments")

    # Reuse the segment planner's validation and microsecond conversion.
    plan_review_windows(segments)

    indexed = []

    for segment in segments:
        indexed.append({
            "id": segment["id"],
            "source": segment["source"],
            "start_us": _us(segment["start_seconds"]),
            "end_us": _us(segment["end_seconds"]),
        })

    application = [
        item for item in indexed
        if item["source"] == "application_audio"
    ]
    microphone = [
        item for item in indexed
        if item["source"] == "microphone_audio"
    ]

    pairs = []

    for app in application:
        for mic in microphone:
            start = max(app["start_us"], mic["start_us"])
            end = min(app["end_us"], mic["end_us"])

            if end <= start:
                continue

            midpoint = (start + end) // 2
            owner = midpoint // WINDOW_US

            pairs.append({
                "application_segment_id": app["id"],
                "microphone_segment_id": mic["id"],
                "overlap_start_us": start,
                "overlap_end_us": end,
                "overlap_duration_us": end - start,
                "window_index": owner,
            })

    return sorted(
        pairs,
        key=lambda item: (
            item["window_index"],
            item["overlap_start_us"],
            item["application_segment_id"],
            item["microphone_segment_id"],
        ),
    )
