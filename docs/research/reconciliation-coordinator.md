# Verified Reconciliation Coordinator

## Status

Milestone 1.7B.9C.3 — implemented and regression-tested.

The coordinator is read-only. It verifies published assembly evidence and v1/v2 review consistency but does not resolve transcript content.

## Purpose

Produce a read-only, evidence-verified reconciliation report for a
published transcript assembly and its versioned human review.

The coordinator does not resolve transcript content or publish a
replacement assembly.

## Inputs

- Sessions root
- Session ID
- Assembly fingerprint
- Human review v2 artifact

## Verification sequence

1. Discover published assemblies using `discover_assemblies()`.
2. Require exactly one matching assembly.
3. Require `classification == verified_complete`.
4. Require `verification_level == source_verified`.
5. Load the exact published transcript and provenance.
6. Validate the v2 review structure.
7. Require matching session and assembly identities.
8. Verify the original v1 review checksum against
   `source_review_sha256`.
9. Build the execution fingerprint mapping from verified
   assembly provenance.
10. Recompute every finding and evidence identity.
11. Reject unmatched, duplicated, or contradictory decisions.
12. Return reviewed and pending findings.

## Review matching

- `finding_id` is assembly-specific.
- `evidence_id` is execution-specific.
- Both must match the same original finding.
- Legacy indices are checked for consistency but are not the
  primary identity.
- A decision must not reference an absent finding.
- The coordinator must not infer semantic duplication.

## Report

The report contains:

- session_id
- assembly_fingerprint
- verification_level
- transcript_state
- total_findings
- reviewed_count
- pending_count
- decision_counts
- reviewed findings
- pending findings
- capture observations

The report must not include a fabricated speaker identity.

## Safety and integrity

- All operations are read-only.
- Reject symlinked review artifacts.
- Reject invalid or unverified assemblies.
- Reject missing or mismatched source reviews.
- Reject duplicate or conflicting decisions.
- Preserve original WAV files, checkpoints, normalized
  transcripts, published assemblies, and human reviews.
- Do not automatically deduplicate microphone and application
  speech.
- Do not infer speaker identity from capture source.

## Current limitation

The coordinator verifies provenance and decision references,
not the semantic correctness of human judgments.

## Acceptance

For the existing real meeting:

- Assembly verification: source_verified
- Transcript segments: 887
- Total findings: 10
- Reviewed findings: 3
- Pending findings: 7
- Review status: partial
- Original artifacts: unchanged

## Next

Introduce versioned reconciliation outcomes and explicit human review updates without modifying the original assembly.
