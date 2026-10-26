# Chunk Processing Foundation

## Status

Milestone 1.7B.7C implementation complete.
Whisper execution and transcript assembly remain pending.

## Components

- `processing/chunk_planning.py`: deterministic chunk boundaries.
- `processing/chunk_identity.py`: canonical processing fingerprints.
- `processing/chunk_checkpoint.py`: checkpoint lifecycle contract.
- `processing/chunk_storage.py`: durable checkpoint persistence.
- `processing/checkpoint_store.py`: coordinator-owned checkpoint access.
- `processing/chunk_recovery.py`: pure recovery classification.
- `processing/chunk_discovery.py`: read-only recovery discovery.

## Chunk planning

Default owned interval: 300 seconds.
Default trailing context: 2 seconds.

Each chunk owns a nonoverlapping interval. Trailing context is
additional audio for transcription, not additional transcript ownership.

Each audio source is planned independently.

## Processing identity

Identity version: 2.
Planner version: 1.

Fingerprints incorporate:

- Source audio SHA-256.
- Model SHA-256.
- whisper.cpp engine version.
- Canonical chunk boundaries in integer microseconds.
- Supported processing parameters.

The current parameter schema is experimental and does not yet
capture every output-affecting Whisper execution option.

Completed chunk reuse remains disabled until execution provenance
is fully defined and verified.

## Checkpoint lifecycle

States:

- pending
- running
- completed
- failed

Allowed transitions:

- pending -> running
- running -> completed
- running -> failed
- failed -> running, only when retryable

Checkpoint metadata is mutable.
Published transcript artifacts are intended to be immutable.

## Checkpoint storage

Session-relative location:

`processing/transcription/<source>/<index>/<fingerprint>/`

Files:

- `checkpoint.json`
- `whisper.json`
- `normalized.json`

Checkpoint creation refuses existing destinations.

Checkpoint transitions use atomic replacement with file and
directory synchronization.

A failure after publication may leave the newly written,
complete checkpoint in place. Recovery must inspect actual state.

Completed checkpoints require two artifact references.
Artifact verification validates expected filenames and SHA-256.

## Coordinator ownership

`checkpoint_store()` validates session identity and completed
capture state, then holds `.processing.lock` for its lifetime.

The lower-level storage functions remain accessible and depend
on cooperative use of the coordinator-owned API.

Capture state is not changed by checkpoint operations.

## Recovery

Recovery discovery is read-only.

Classifications include:

- not_started
- active
- interrupted
- indeterminate
- retryable_failure
- manual_intervention
- verified_complete
- integrity_failure
- invalid_checkpoint

A missing lock file is inspected without creating one.

Lock availability is a point-in-time observation, not permission
to begin recovery without acquiring the coordinator lock.

Malformed intermediate directory layouts currently fail closed
and may abort discovery rather than produce a partial report.

## Filesystem safety

- Rejects symlinked checkpoint files and directories.
- Rejects symlinked artifact files.
- Uses `O_NOFOLLOW` and `fstat()` for artifact verification.
- Rejects nonregular artifact files.
- Verifies completed artifact SHA-256 checksums.
- Preserves prior checkpoint content when replacement fails
  before publication.

Parent-directory replacement races are not fully eliminated.

## Known limitations

- No Whisper subprocess execution.
- No audio chunk extraction.
- No transcript overlap reconciliation.
- No automatic checkpoint reuse.
- No automatic stale-running state transitions.
- No recovery CLI.
- No integration with aggregate transcription stage.
- No complete protection against malicious concurrent filesystem
  modifications.
- Checkpoint artifact publication is not yet provided by the
  storage API; current tests use synthetic files.

## Validation

October 2026:

- 141 Python regression tests passed.
- 14 recovery discovery tests passed.
- Cross-process coordinator contention verified.
- Atomic replacement and directory-sync fault injection passed.
- Real Zoom recording chunk planning validated for both tracks.

## Next milestone

Implement FFmpeg chunk extraction and whisper.cpp execution
with complete processing provenance, immutable artifact publication,
and explicit recovery behavior.
