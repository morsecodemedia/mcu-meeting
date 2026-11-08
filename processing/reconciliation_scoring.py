"""Pure lexical scoring for cross-source reconciliation candidates."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from processing.reconciliation_windows import (
    _us,
    plan_candidate_pairs,
)

TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


def _tokens(text):
    if not isinstance(text, str):
        raise ValueError("Invalid transcript text")
    return TOKEN_PATTERN.findall(text.casefold())


def _similarity(left, right):
    a = _tokens(left)
    b = _tokens(right)

    if not a or not b:
        return 0.0, 0.0

    sequence = SequenceMatcher(
        None, a, b, autojunk=False
    ).ratio()

    a_set = set(a)
    b_set = set(b)

    containment = (
        len(a_set & b_set)
        / min(len(a_set), len(b_set))
    )

    return sequence, containment


def score_candidate_pairs(segments):
    """Score temporal overlap candidates without modifying evidence."""

    pairs = plan_candidate_pairs(segments)
    by_id = {segment["id"]: segment for segment in segments}

    scored = []

    for pair in pairs:
        app = by_id[pair["application_segment_id"]]
        mic = by_id[pair["microphone_segment_id"]]

        sequence, containment = _similarity(
            app["text"], mic["text"]
        )

        app_duration_us = (
            _us(app["end_seconds"]) - _us(app["start_seconds"])
        )
        mic_duration_us = (
            _us(mic["end_seconds"]) - _us(mic["start_seconds"])
        )

        temporal_ratio = (
            pair["overlap_duration_us"]
            / min(app_duration_us, mic_duration_us)
        )

        if temporal_ratio >= 0.75 and sequence >= 0.80:
            category = "strong_duplicate_candidate"
        elif temporal_ratio >= 0.50 and (
            sequence >= 0.45 or containment >= 0.65
        ):
            category = "partial_duplicate_candidate"
        elif temporal_ratio >= 0.75:
            category = "ambiguous_overlap"
        else:
            category = "temporal_overlap_only"

        scored.append({
            **pair,
            "temporal_ratio": round(temporal_ratio, 4),
            "sequence_similarity": round(sequence, 4),
            "token_containment": round(containment, 4),
            "classification": category,
        })

    return scored
