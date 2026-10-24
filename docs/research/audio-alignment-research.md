# Acoustic Alignment Research — Milestone 1.7A

Status: Provisional, research-only.

## Evidence

October 23, 2026 Zoom session:
`05fda6fe-706c-4e3a-a021-5dccb97bf8f5`

The initial correlation experiment produced a provisional
9.19 ms lag using 14 accepted windows.

Peak ambiguity rejection reduced this to 9 accepted windows
and a provisional 8.0 ms lag.

## Method

- 12-second windows sampled across the recording.
- Resampling from 48 kHz to 8 kHz.
- Normalized cross-correlation.
- Bounded lag search.
- Competing peak exclusion.
- Median/MAD consensus and outlier rejection.

## Limitations

The thresholds are heuristic, not calibrated probabilities.

Acoustic propagation and speaker playback latency affect
the measured lag.

Process launch timing does not establish sample alignment.

Clock drift has not been measured.

Do not automatically shift or mix the original audio tracks.

## Reference

jamestomasino/transcriber was reviewed for local transcription,
audio preparation, speaker analysis, and retryable processing.
Its default audio-retention behavior is not adopted.

## Reproducible implementation — Milestone 1.7A.8–1.7A.9

The alignment estimator was migrated from isolated research scripts
into the optional `processing` package.

The CLI uses duration-aware window selection, supporting recordings
shorter than the original 34-minute research fixture.

Recordings shorter than 12 seconds return `unknown` with reason
`insufficient_duration`. Other insufficient-evidence cases also
return `unknown` rather than inventing an alignment offset.

Input WAV integrity is validated using the session recording validator.
Missing tracks, malformed WAVs, and truncated PCM are rejected.

The CLI prevents output paths from overwriting the capture manifest
or original audio artifacts, including symlink aliases to those files.

The full Python test suite passed on 2026-10-24:

- 17 alignment tests
- 15 session and capture tests
- 32 total tests

The estimator remains provisional. No audio correction is applied.
