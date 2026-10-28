# Sequential Batch Transcription

## Status

Milestone 1.7B.9A validated.

Sequential multi-chunk transcription is functional.
Transcript assembly and checkpoint continuation remain pending.

## Components

- `processing/batch_planning.py`
- `processing/batch_runner.py`
- `processing/chunk_coordinator.py`

## Planning

Source durations are derived from verified WAV frame counts.

Durations are rounded to integer microseconds using
ROUND_HALF_UP.

The planner preserves the existing chunk schema.

Default owned interval: 300 seconds.
Default trailing context: 2 seconds.

Application audio is processed before microphone audio.
Chunks execute in ascending index order.

Source durations are independent.

## Execution

Each chunk invokes the existing single-chunk coordinator.

The coordinator acquires and releases its own session processing
lock for each chunk.

The batch is not atomic. Other processing activity may occur
between chunks.

## Failure behavior

Execution stops on the first chunk failure.

The returned batch report distinguishes:

- completed
- failed
- not_attempted

Previously completed checkpoints and published artifacts remain
untouched.

Existing checkpoints are refused.

The batch does not automatically retry, resume, or reuse work.

Preflight validation errors raise exceptions before batch execution.

## Artifact integrity

Each completed chunk publishes:

- checkpoint.json
- whisper.json
- normalized.json

Checkpoint recovery independently verifies published artifacts.

## Timestamp semantics

Normalized timestamps are meeting-relative.

Each chunk has source-aware, globally unique segment IDs.

Trailing overlap remains transcription context only.
Ownership reconciliation is deferred to transcript assembly.

## Validation

October 2026:

- 232 Python regression tests passed.
- 7 batch runner tests passed.
- 13 batch planning tests passed.
- 48 kHz WAV frame-boundary round-trip validated.
- Real two-chunk FFmpeg/Whisper integration passed.
- Two completed checkpoints independently verified.
- Three normalized segments validated for timeline continuity.
- Capture state preserved.

## Known limitations

- No transcript assembly.
- No overlap reconciliation.
- No automatic checkpoint reuse.
- No interrupted-batch continuation.
- No batch-wide processing lock.
- No durable batch-level report publication.
- No parallel chunk execution.

## Next milestone

Implement source-aware transcript assembly with deterministic
ordering, chunk ownership reconciliation, and explicit handling
of segments crossing chunk boundaries.
