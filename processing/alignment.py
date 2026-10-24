"""Experimental audio alignment; no production dependencies."""
import numpy as np
from scipy.signal import correlate, correlation_lags


def estimate_offset(reference, observed, sample_rate, max_lag_seconds=0.25):
    """Positive lag means observed audio occurs later than reference."""
    reference = np.asarray(reference, dtype=np.float64)
    observed = np.asarray(observed, dtype=np.float64)

    if reference.ndim != 1 or observed.ndim != 1:
        raise ValueError("Expected mono audio arrays")
    if len(reference) < 2 or len(observed) < 2:
        return {"status": "unknown", "reason": "insufficient_samples"}
    if not np.all(np.isfinite(reference)) or not np.all(np.isfinite(observed)):
        return {"status": "unknown", "reason": "nonfinite_samples"}
    if not np.isfinite(sample_rate) or sample_rate <= 0:
        raise ValueError("Invalid sample rate")
    if not np.isfinite(max_lag_seconds) or max_lag_seconds <= 0:
        raise ValueError("Invalid lag range")

    reference = reference - reference.mean()
    observed = observed - observed.mean()

    if np.std(reference) < 1e-6 or np.std(observed) < 1e-6:
        return {"status": "unknown", "reason": "insufficient_signal"}

    maximum = min(
        int(sample_rate * max_lag_seconds),
        len(reference) - 1,
        len(observed) - 1,
    )

    correlation = correlate(observed, reference, mode="full", method="fft")
    lags = correlation_lags(len(observed), len(reference), mode="full")

    indices = np.flatnonzero(np.abs(lags) <= maximum)
    candidates = []

    for index in indices:
        lag = int(lags[index])
        if lag >= 0:
            a = reference[:min(len(reference), len(observed) - lag)]
            b = observed[lag:lag + len(a)]
        else:
            a = reference[-lag:]
            b = observed[:len(a)]

        denominator = np.linalg.norm(a) * np.linalg.norm(b)
        score = abs(float(correlation[index])) / denominator if denominator else 0
        candidates.append(score)

    scores = np.asarray(candidates)
    winner = int(np.argmax(scores))
    lag = int(lags[indices[winner]])
    score = float(scores[winner])

    if score < 0.20:
        return {
            "status": "unknown",
            "reason": "weak_correlation",
            "similarity": round(score, 4),
        }

    return {
        "status": "estimated",
        "offset_seconds": lag / sample_rate,
        "similarity": round(score, 4),
        "method": "bounded_normalized_cross_correlation",
    }


def robust_consensus(results):
    """Aggregate accepted window estimates; reject large outliers."""
    accepted = [
        item for item in results
        if item.get("status") == "estimated"
    ]

    if len(accepted) < 3:
        return {"status": "unknown", "reason": "insufficient_valid_windows"}

    offsets = np.array([item["offset_seconds"] for item in accepted])
    median = float(np.median(offsets))
    deviations = np.abs(offsets - median)
    mad = float(np.median(deviations))
    tolerance = max(0.003, 3 * 1.4826 * mad)

    inliers = offsets[deviations <= tolerance]

    if len(inliers) < 3:
        return {"status": "unknown", "reason": "insufficient_consensus"}

    return {
        "status": "estimated",
        "offset_seconds": float(np.median(inliers)),
        "accepted_windows": len(inliers),
        "rejected_windows": len(results) - len(inliers),
        "method": "median_mad_consensus",
        "drift_ppm": None,
    }


def peak_quality(
    reference,
    observed,
    sample_rate,
    max_lag_seconds=0.25,
    exclusion_seconds=0.005,
):
    """Evaluate competing normalized correlation peaks."""
    reference = np.asarray(reference, dtype=np.float64)
    observed = np.asarray(observed, dtype=np.float64)

    if reference.ndim != 1 or observed.ndim != 1:
        raise ValueError("Expected mono audio arrays")
    if not np.isfinite(sample_rate) or sample_rate <= 0:
        raise ValueError("Invalid sample rate")
    if not np.isfinite(max_lag_seconds) or max_lag_seconds <= 0:
        raise ValueError("Invalid lag range")
    if not np.isfinite(exclusion_seconds) or exclusion_seconds <= 0:
        raise ValueError("Invalid exclusion radius")
    if min(len(reference), len(observed)) < 2:
        return {"status": "unknown", "reason": "insufficient_samples"}
    if not np.all(np.isfinite(reference)) or not np.all(np.isfinite(observed)):
        return {"status": "unknown", "reason": "nonfinite_samples"}

    reference = reference - reference.mean()
    observed = observed - observed.mean()

    if np.std(reference) < 1e-6 or np.std(observed) < 1e-6:
        return {"status": "unknown", "reason": "insufficient_signal"}

    correlation = correlate(observed, reference, mode="full", method="fft")
    lags = correlation_lags(len(observed), len(reference), mode="full")

    maximum = min(
        int(sample_rate * max_lag_seconds),
        len(reference) - 1,
        len(observed) - 1,
    )

    indices = np.flatnonzero(np.abs(lags) <= maximum)
    scores = []

    for index in indices:
        lag = int(lags[index])

        if lag >= 0:
            a = reference[:min(len(reference), len(observed) - lag)]
            b = observed[lag:lag + len(a)]
        else:
            a = reference[-lag:]
            b = observed[:len(a)]

        denominator = np.linalg.norm(a) * np.linalg.norm(b)
        score = abs(float(correlation[index])) / denominator if denominator else 0
        scores.append(score)

    scores = np.asarray(scores)
    winner = int(np.argmax(scores))
    winning_lag = int(lags[indices[winner]])
    winning_score = float(scores[winner])

    exclusion = max(1, int(sample_rate * exclusion_seconds))
    competitors = np.abs(lags[indices] - winning_lag) > exclusion

    if not np.any(competitors):
        return {"status": "unknown", "reason": "no_competing_lags"}

    second_score = float(np.max(scores[competitors]))
    ratio = winning_score / max(second_score, 1e-12)

    result = {
        "lag_seconds": winning_lag / sample_rate,
        "similarity": round(winning_score, 4),
        "competing_similarity": round(second_score, 4),
        "peak_ratio": round(ratio, 4),
    }

    # Exploratory thresholds, not calibrated probabilities.
    if winning_score < 0.20:
        return {"status": "unknown", "reason": "weak_correlation", **result}

    if ratio < 1.15:
        return {"status": "unknown", "reason": "ambiguous_peak", **result}

    return {"status": "estimated", **result}
