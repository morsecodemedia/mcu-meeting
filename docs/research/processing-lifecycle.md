# Durable Processing Lifecycle

## Status

Milestone 1.7B.6A-1.7B.6C implementation complete.
Whisper orchestration and chunk checkpoints remain pending.

## Architecture

MCU Meeting maintains separate capture and processing lifecycles.

Capture state remains unchanged by post-capture processing.

Processing stages:
- transcription
- diarization
- speaker_resolution
- knowledge_export

Each stage tracks:
- state
- attempts
- retryable
- error

## Processing transitions

Allowed transitions:

- pending -> running
- pending -> skipped
- running -> completed
- running -> failed
- failed -> running, only when retryable

Completed and skipped stages are terminal.

Starting or retrying a stage increments its attempt count.
Starting clears the previous error and retryable flag.

Processing requires a completed capture.

## Lock ownership

Two session-scoped advisory locks are used.

### Coordinator lock

File: `.processing.lock`

Purpose: Prevent multiple processing coordinators from executing
the same session simultaneously.

Intended lifetime: Entire processing attempt.

### Manifest transaction lock

File: `.manifest.lock`

Purpose: Protect short read-modify-write manifest transactions.

Intended lifetime: One manifest transaction.

Both locks use nonblocking `fcntl.flock()` on macOS.

Contention raises an explicit exception.

Lock files remain on disk. Operating-system locks are released
when their owning file descriptors close, including process exit.

## Lock ordering

A coordinator acquires `.processing.lock` before executing work.

Manifest updates acquire `.manifest.lock` while the coordinator
lock remains held.

Do not acquire `.processing.lock` while holding `.manifest.lock`.

This ordering avoids nested acquisition of the same lock.

## Recovery

`processing_recovery_candidates()` performs read-only inspection
of processing stages left in `running` state.

A stale running state is not automatically considered completed
or failed.

Recovery must inspect processing artifacts and their provenance
before retrying or changing aggregate stage state.

## Current limitations

- Chunk checkpoints are not yet implemented.
- The coordinator does not yet execute Whisper.
- Existing capture writers do not yet participate in `.manifest.lock`.
- Advisory locks protect only cooperating processes.
- There is no automatic stale-running reconciliation.
- Processing transition APIs acquire the manifest lock, but
  coordinator lock ownership is not enforced by those APIs.

## Validation

October 2026:

- 6 lock tests passed.
- 5 processing lifecycle tests passed.
- 57 total Python tests passed.
- Cross-process manifest contention verified.
- Coordinator and manifest locks can be nested safely.

## Next milestone

Implement chunk-level transcription orchestration with
durable checkpoints, immutable artifacts, and resumable processing.
