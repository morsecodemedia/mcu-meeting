# Processing Orchestration Contract

## Status

Milestone 1.7B.9D — proposed.

## Objective

Connect completed meeting capture to verified transcript assembly through
a deterministic, recoverable processing workflow.

## Lock ownership

One session-scoped processing coordinator owns the processing lock.

Existing public chunk and assembly functions remain backward-compatible.

Store-aware internal helpers operate under an already-active checkpoint
store and must not acquire the processing lock again.

## Execution identity

Chunk reuse requires:

- Exact planned chunk identity
- Exact execution fingerprint
- Completed checkpoint state
- Verified published artifacts

Execution fingerprints include source audio, model, engine versions,
execution profile, and chunk boundaries.

Different fingerprints represent separate historical executions.

## Recovery policy

- Missing checkpoint: eligible for initial execution.
- Verified matching checkpoint: reuse.
- Active checkpoint: do not interfere.
- Interrupted checkpoint: stop for inspection.
- Retryable failure: explicit retry policy required.
- Non-retryable failure: stop.
- Invalid checkpoint or artifact: stop without mutation.

No automatic repair or artifact replacement.

## Assembly

Assembly requires a complete fingerprint mapping for all planned chunks.

Only verified completed checkpoints may contribute.

Published assemblies remain immutable.

## Initial acceptance

- Existing public chunk execution behavior unchanged.
- Existing public assembly behavior unchanged.
- Store-aware helpers do not reacquire the processing lock.
- Store-aware chunk execution retains exclusive checkpoint creation.
- Verified checkpoint reuse without Whisper execution is a future
  processing-coordinator acceptance requirement.
- Failed or ambiguous evidence is preserved.
- Capture state is not modified.
- Existing regression suite remains green.

## Deferred

- Automatic retry transitions
- Stale-running checkpoint recovery
- Full end-to-end CLI
- Diarization and speaker resolution
- Meeting intelligence and knowledge export
