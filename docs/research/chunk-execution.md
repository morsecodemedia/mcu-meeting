# Chunk Transcription Execution

## Status

Milestone 1.7B.8C implementation validated.

Single-chunk execution is functional using FFmpeg, whisper.cpp,
source-aware normalization, and durable checkpoints.

Multi-chunk orchestration and transcript assembly remain pending.

## Components

- `processing/audio_extraction.py`: deterministic audio extraction.
- `processing/whisper_profile.py`: versioned Whisper configuration.
- `processing/execution_identity.py`: v3 execution fingerprint.
- `processing/whisper_runner.py`: controlled Whisper execution.
- `processing/chunk_execution_plan.py`: deterministic execution plan.
- `processing/chunk_coordinator.py`: single-chunk orchestration.
- `processing/transcript_normalization.py`: chunk-aware normalization.

## Execution sequence

1. Acquire the session processing lock.
2. Require completed capture.
3. Resolve the source artifact from the manifest.
4. Verify the source WAV and SHA-256.
5. Verify model and tool versions.
6. Construct execution fingerprint v3.
7. Create checkpoint and transition to running.
8. Extract temporary 16 kHz mono PCM16 audio.
9. Execute whisper.cpp using the versioned profile.
10. Publish immutable whisper.json.
11. Normalize with source-aware, chunk-specific identifiers.
12. Publish immutable normalized.json.
13. Verify artifact checksums.
14. Transition checkpoint to completed.
15. Verify completed checkpoint integrity.

## Execution identity

Identity version: 3.

Includes:

- Original source WAV SHA-256.
- Whisper model SHA-256.
- FFmpeg version.
- whisper.cpp version.
- Canonical Whisper profile v1.
- Extraction algorithm version and configuration.
- Chunk planner version.
- Source-aware chunk boundaries.

The previous v2 fingerprint remains unchanged.

## Artifact layout

Session-relative:

processing/transcription/<source>/<index>/<fingerprint>/

Files:

- checkpoint.json
- whisper.json
- normalized.json

Extracted WAV chunks are temporary and regenerable.

## Timestamp semantics

Whisper timestamps are relative to the extracted chunk.

Normalization adds the chunk read-start timestamp to produce
meeting-relative segment timestamps.

Segment identifiers include the chunk ID.

Overlapping context segments remain preserved until transcript
assembly performs ownership reconciliation.

## Failure behavior

Failures after the running transition are recorded as failed
when possible.

Published artifacts are never overwritten automatically.

A failed checkpoint may contain valid partial artifacts.

A failure after checkpoint completion does not reverse the
completed state. Recovery inspects the actual persisted state
and artifact integrity.

Existing checkpoints are refused.

## Recovery limitations

- No automatic retry.
- No completed checkpoint reuse.
- No automatic interrupted checkpoint restart.
- No partial-artifact reconciliation.
- No multi-chunk coordinator.
- No transcript assembly or overlap deduplication.

## Provenance limitations

The execution fingerprint records the configured Whisper profile
and detected tool versions.

Not every operational runtime parameter is represented, including
thread count and GPU execution environment.

Automatic checkpoint reuse remains disabled.

## Validation

October 2026:

- 212 Python regression tests passed.
- 9 coordinator regression tests passed.
- Real Whisper Small transcription passed.
- Real checkpoint-backed transcription passed.
- Both published JSON artifact checksums verified.
- Normalized provenance and chunk-specific identifiers verified.
- Capture state preserved.

## Next milestone

Implement multi-chunk orchestration and source-aware transcript
assembly, including ownership reconciliation, interruption
handling, and explicit checkpoint recovery policy.
