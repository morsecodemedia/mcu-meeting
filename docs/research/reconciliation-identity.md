# Reconciliation Identity Contract

## Status

Milestone 1.7B.9C.2 — implemented.

Identity, migration, validation, and immutable publication implemented and regression-tested.

## Purpose

Provide deterministic identities for reconciliation findings
and their underlying transcription evidence.

Original normalized transcripts and immutable assemblies
must remain unchanged.

## Finding identity

Finding IDs are scoped to one published assembly.

Canonical identity fields:

- schema_version
- assembly_fingerprint
- finding_type
- chunk_id
- segment_id
- start_us
- end_us
- text

The finding ID is SHA-256 of canonical JSON with sorted keys,
compact separators, UTF-8 encoding, and non-ASCII preservation.

## Evidence identity

Evidence IDs identify source transcription evidence across
assembly versions.

Canonical identity fields:

- schema_version
- source
- chunk_id
- execution_fingerprint
- segment_id
- start_us
- end_us
- text

The execution fingerprint must come from verified assembly
provenance, not from caller-supplied unverified metadata.

## Canonicalization

- Schema version is an integer, not a boolean.
- Timestamps are normalized to integer microseconds.
- Nonfinite timestamps are rejected.
- Submicrosecond precision is rejected.
- Digest fields are lowercase SHA-256.
- Original text is preserved exactly.
- No semantic normalization or fuzzy matching.
- Unexpected identity fields are rejected.

## Review decisions

Supported initial decisions:

- duplicate_confirmed
- content_recovery_required
- unresolved

Each decision must reference:

- finding_id
- evidence_id
- decision
- method

The review artifact must also reference the session ID
and assembly fingerprint.

## Migration

The existing human-review-v1.json contains positional
finding indices 3, 9, and 10.

Migration must:

1. Load the exact referenced immutable assembly.
2. Verify the assembly fingerprint.
3. Resolve positional indices against its findings.
4. Derive finding and evidence identities.
5. Preserve original decisions and review method.
6. Write a new review artifact without replacing v1.
7. Reject missing, ambiguous, or mismatched evidence.

## Guarantees

- Original WAV files remain unchanged.
- Original normalized transcripts remain unchanged.
- Published assemblies remain unchanged.
- Review decisions remain separate artifacts.
- Identity generation is deterministic.
- Historical review artifacts remain preserved.

## Limitations

- Evidence identity does not establish speaker identity.
- Acoustic leakage may create cross-source duplicate speech.
- Evidence identity is not semantic deduplication.
- A new Whisper execution may produce different evidence IDs.
- Cross-version equivalence requires explicit mapping.
- Review identity does not independently verify published
  transcript bytes.

## Implementation boundaries

- Identity generation is pure and deterministic.
- Migration operates on supplied data; it does not independently verify filesystem evidence.
- Review validation enforces the v2 structural contract.
- Immutable publication uses macOS exclusive rename.
- Only partial reviews are supported.
- The caller must verify assembly and checkpoint provenance.
- Structural validation does not establish reviewer authenticity or semantic correctness.

## Next

Implement a read-only verified reconciliation coordinator.
