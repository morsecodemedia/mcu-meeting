# Reconciliation Review Manifest

## Status

Milestone 1.7B.9C.5 — proposed contract.

## Purpose

Represent cross-source reconciliation candidates as deterministic,
bounded review units linked to an immutable transcript assembly.

## Inputs

- Verified assembly fingerprint
- Assembled transcript segments
- Deterministic review windows
- Scored cross-source candidate pairs

## Candidate identity

Candidate identities are assembly-scoped.

Canonical identity fields:

- schema_version
- assembly_fingerprint
- application_segment_id
- microphone_segment_id
- overlap_start_us
- overlap_end_us

Identity generation uses SHA-256 over canonical JSON.

Scoring results are excluded from candidate identity.

## Review windows

- Window duration: 30 seconds
- Context padding: 5 seconds
- Segment ownership: segment midpoint
- Candidate ownership: overlap midpoint
- Each segment has exactly one owning window.
- Each candidate has exactly one owning window.
- Context references do not establish ownership.
- Segments are never split.

## Scoring

Initial classifications:

- strong_duplicate_candidate
- partial_duplicate_candidate
- ambiguous_overlap
- temporal_overlap_only

Scores and classifications are advisory.

The scoring algorithm must be explicitly versioned.

## Evidence preservation

- Original transcript assembly remains immutable.
- Manifest stores references rather than duplicated transcript text.
- No automatic deduplication.
- No automatic speaker attribution.
- No automatic deletion or merging of transcript segments.
- Candidate decisions remain separate versioned artifacts.

## Verification boundary

A pure manifest builder validates supplied structures but cannot
independently establish source verification.

Filesystem orchestration must verify assembly and checkpoint
provenance before publication.

## Acceptance

For the existing meeting:

- 887 original segments
- 68 review windows
- 797 unique cross-source candidates
- No duplicate candidate ownership
- No missing segment ownership
- Original evidence unchanged

## Next

Implement pure candidate identity and manifest-building functions,
then add regression tests before introducing publication.
