# Transcript Assembly Contract

## Status

Milestone 1.7B.9B — proposed, pending implementation.

## Inputs

- Deterministic batch plan.
- Normalized chunk transcripts.
- Source-aware chunk identifiers.
- Owned and read intervals.
- Verified checkpoint provenance.

## Output

A deterministic assembled transcript containing:

- Source-aware chronological segments.
- Original segment identifiers.
- Original text and timing.
- Source attribution.
- Assembly provenance.
- Explicit reconciliation findings.

## Ownership rules

1. Include segments wholly within the owning chunk.
2. Exclude segments wholly within trailing context.
3. Flag segments crossing the ownership boundary.
4. Never silently clip or rewrite segment text.
5. Preserve original normalized chunks unchanged.

## Ordering

Sort by:

1. Meeting-relative segment start time.
2. Meeting-relative segment end time.
3. Source order: application before microphone.
4. Chunk index.
5. Original segment index.

This ordering is deterministic, not speaker diarization.

## Reconciliation

Boundary-spanning segments require explicit resolution.

Initial assembly must report unresolved findings rather than
claim a complete, deduplicated transcript.

## Validation

Reject:

- Duplicate segment identifiers.
- Invalid segment timestamps.
- Source/chunk identity mismatches.
- Missing expected chunks.
- Unverified or incomplete checkpoint inputs.

## Limitations

- No semantic deduplication.
- No word-level boundary reconciliation.
- No speaker diarization.
- No automatic cross-source echo removal.
- No automatic checkpoint recovery.

## Next

Implement synthetic assembly fixtures and a pure assembly engine.

## Immutable publication

### Identity

Assembly identity is distinct from chunk execution identity.

The assembly fingerprint incorporates:

- Assembly algorithm version.
- Canonical batch plan.
- Ordered chunk IDs.
- Contributing execution fingerprints.
- Verified normalized artifact SHA-256 values.

### Artifacts

Session-relative:

`processing/assembly/<assembly-fingerprint>/`

Contains:

- `transcript.json`
- `provenance.json`

### Publication guarantees

1. Validate all expected checkpoint inputs before assembly.
2. Preserve original chunk artifacts unchanged.
3. Stage both assembly files in a private temporary directory.
4. Flush file contents before publication.
5. Publish the complete directory without replacing existing output.
6. Synchronize the parent directory.
7. Verify both published artifact checksums.
8. Refuse automatic overwrite or reuse.

Publication must fail closed if any validation fails.

### Reconciliation state

An assembly with unresolved boundary findings may be published
as evidence, but must retain `requires_reconciliation` status.

It must not be represented as a finalized transcript.

### Failure and recovery

An interrupted publication may leave a staging directory.

Recovery must distinguish incomplete staging from a published
assembly and must never silently overwrite either.

No automatic cleanup of previously published evidence.

### Provenance limitation

Verified checkpoint checksums do not independently establish
that a caller-selected execution fingerprint matches the
original model, source audio, or decoding configuration.

Stronger execution-provenance verification remains pending.

## Validated implementation

### Status

Milestone 1.7B.9B implemented and validated.

Assembly algorithm version: 2.
Assembly identity schema version: 1.

### Components

- `processing/transcript_assembly.py`
- `processing/assembly_loader.py`
- `processing/assembly_identity.py`
- `processing/assembly_publisher.py`
- `processing/assembly_coordinator.py`

### Verified assembly workflow

1. Acquire the session processing lock.
2. Validate expected chunk identities and fingerprint mapping.
3. Load completed checkpoints and verify their artifacts.
4. Read normalized transcript bytes and verify SHA-256.
5. Collect verified contribution fingerprints and checksums.
6. Assemble source-aware segments deterministically.
7. Calculate canonical assembly identity.
8. Publish transcript and provenance JSON without replacement.
9. Preserve reconciliation findings and original evidence.

### Timing reconciliation

Assembly algorithm v2 recognizes:

- `boundary_spanning`: segment crosses a chunk ownership boundary.
- `timing_out_of_bounds`: segment extends beyond its read interval.
- `context_only`: segment belongs entirely to trailing context.

Boundary-spanning and timing-out-of-bounds findings contribute
to `unresolved_count`.

Context-only findings are retained as evidence but do not
independently require reconciliation.

Original text and timestamps are never silently modified.

### Real Whisper validation

A 24-second application-audio excerpt was processed using:

- Two 12-second owned chunks.
- Two seconds of trailing context.
- Local Whisper Small transcription.
- Independent checkpoint verification.

Results:

- Eight normalized segments.
- Six included assembled segments.
- One boundary-spanning finding.
- One timing-out-of-bounds finding.
- Assembly state: `requires_reconciliation`.
- Immutable assembly publication succeeded.
- Both contributing checkpoints verified complete.

The timing-out-of-bounds segment ended 420 milliseconds beyond
the available audio endpoint.

No automatic clipping or semantic deduplication was performed.

### Regression validation

- 279 Python tests passed.
- 15 pure assembly tests passed.
- Seven coordinator tests passed.
- Eight verified loader tests passed.
- Ten assembly identity tests passed.
- Seven publisher tests passed.
- Syntax and whitespace validation passed.

### Remaining limitations

- No automatic reconciliation of boundary-spanning speech.
- No semantic duplicate resolution.
- No word-level transcript alignment.
- No cross-source echo removal.
- No speaker diarization.
- No automatic selection of execution fingerprints.
- No independent proof that caller-selected execution
  fingerprints match the intended source/model configuration.
- No assembly recovery or publication-status inspection API.

### Next milestone

Implement explicit reconciliation and recovery workflows without
modifying original normalized transcripts or published assemblies.
