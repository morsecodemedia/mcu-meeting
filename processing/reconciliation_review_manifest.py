"""Pure construction of evidence-linked reconciliation review manifests."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from processing.reconciliation_candidate_identity import (
    CANDIDATE_IDENTITY_VERSION,
    candidate_identity,
)
from processing.reconciliation_scoring import score_candidate_pairs
from processing.reconciliation_windows import (
    PADDING_US,
    WINDOW_US,
    plan_review_windows,
)

MANIFEST_SCHEMA_VERSION = 1
SCORING_ALGORITHM_VERSION = 1

DIGEST = re.compile(r"^[0-9a-f]{64}$")

CLASSIFICATIONS = (
    "strong_duplicate_candidate",
    "partial_duplicate_candidate",
    "ambiguous_overlap",
    "temporal_overlap_only",
)


def build_review_manifest(assembly_fingerprint, segments):
    """Build a deterministic manifest without modifying input evidence."""

    if (
        not isinstance(assembly_fingerprint, str)
        or not DIGEST.fullmatch(assembly_fingerprint)
    ):
        raise ValueError("Invalid assembly fingerprint")

    windows = plan_review_windows(segments)
    scored = score_candidate_pairs(segments)

    from processing.reconciliation_windows import _us

    by_segment = {item["id"]: item for item in segments}
    by_window = defaultdict(list)
    seen_candidates = set()
    seen_pairs = set()
    counts = Counter()

    for pair in scored:
        app_id = pair["application_segment_id"]
        mic_id = pair["microphone_segment_id"]
        pair_key = (app_id, mic_id)

        if pair_key in seen_pairs:
            raise ValueError("Duplicate candidate segment pair")
        seen_pairs.add(pair_key)

        if app_id not in by_segment or mic_id not in by_segment:
            raise ValueError("Candidate references missing segment")

        app = by_segment[app_id]
        mic = by_segment[mic_id]

        if (
            app["source"] != "application_audio"
            or mic["source"] != "microphone_audio"
        ):
            raise ValueError("Candidate source mismatch")

        expected_start = max(
            _us(app["start_seconds"]),
            _us(mic["start_seconds"]),
        )
        expected_end = min(
            _us(app["end_seconds"]),
            _us(mic["end_seconds"]),
        )

        if expected_end <= expected_start:
            raise ValueError("Candidate has no temporal overlap")

        if (
            pair["overlap_start_us"] != expected_start
            or pair["overlap_end_us"] != expected_end
            or pair["overlap_duration_us"] != expected_end - expected_start
        ):
            raise ValueError("Candidate overlap evidence mismatch")

        candidate_id = candidate_identity(
            assembly_fingerprint, pair
        )

        if candidate_id in seen_candidates:
            raise ValueError("Duplicate candidate identity")

        seen_candidates.add(candidate_id)

        category = pair["classification"]

        if category not in CLASSIFICATIONS:
            raise ValueError("Unsupported candidate classification")

        owner = pair["window_index"]

        # The pair planner owns overlap-window assignment.
        expected_owner = (
            (pair["overlap_start_us"] + pair["overlap_end_us"]) // 2
        ) // WINDOW_US

        if owner != expected_owner:
            raise ValueError("Candidate window ownership mismatch")

        by_window[owner].append({
            "candidate_id": candidate_id,
            "application_segment_id": pair["application_segment_id"],
            "microphone_segment_id": pair["microphone_segment_id"],
            "overlap_start_us": pair["overlap_start_us"],
            "overlap_end_us": pair["overlap_end_us"],
            "temporal_ratio": pair["temporal_ratio"],
            "sequence_similarity": pair["sequence_similarity"],
            "token_containment": pair["token_containment"],
            "classification": category,
        })

        counts[category] += 1

    result_windows = []

    for window in windows:
        index = window["window_index"]

        candidates = sorted(
            by_window.pop(index, []),
            key=lambda item: (
                item["overlap_start_us"],
                item["candidate_id"],
            ),
        )

        result_windows.append({
            **window,
            "candidates": candidates,
        })

    if by_window:
        raise ValueError("Candidate references missing review window")

    owned = [
        segment_id
        for window in result_windows
        for segment_id in window["owned_segment_ids"]
    ]

    if len(owned) != len(set(owned)) or len(owned) != len(segments):
        raise ValueError("Invalid segment ownership")

    if sum(len(w["candidates"]) for w in result_windows) != len(scored):
        raise ValueError("Candidate count mismatch")

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "assembly_fingerprint": assembly_fingerprint,
        "candidate_identity_version": CANDIDATE_IDENTITY_VERSION,
        "scoring_algorithm_version": SCORING_ALGORITHM_VERSION,
        "window_duration_us": WINDOW_US,
        "context_padding_us": PADDING_US,
        "segment_count": len(segments),
        "window_count": len(result_windows),
        "candidate_count": len(scored),
        "classification_counts": {
            category: counts[category]
            for category in CLASSIFICATIONS
        },
        "windows": result_windows,
    }
