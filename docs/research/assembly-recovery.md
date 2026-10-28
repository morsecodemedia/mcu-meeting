# Assembly Recovery and Discovery

## Status

Milestone 1.7B.9C.1 — proposed contract.

Implementation and regression validation pending.

## Purpose

Discover previously published transcript assemblies without
modifying session data, checkpoints, or published artifacts.

## Discovery scope

Session-relative directory:

`processing/assembly/`

Expected published assembly layout:

`<assembly-fingerprint>/transcript.json`
`<assembly-fingerprint>/provenance.json`

Staging directories use the prefix:

`.assembly-staging-`

## Classifications

### verified_complete

A structurally valid published assembly with:

- Valid fingerprint directory name.
- Regular, non-symlinked JSON artifacts.
- Valid JSON object structures.
- Matching session identity.
- Matching provenance assembly fingerprint.
- Recomputed canonical assembly identity fingerprint.
- Verified contributing checkpoint artifacts.
- Valid transcript state and reconciliation counts.

This classification does not independently prove that the
published transcript bytes equal the original published bytes.

### published_invalid

A published assembly fails one or more required checks.

Recovery must preserve the existing directory.

### incomplete_staging

A staging directory remains from an interrupted publication.

No automatic deletion, reuse, or promotion.

### unknown_entry

An unexpected file, symlink, or directory is present.

Do not follow unexpected symlinks.

## Verification levels

- `structural`: publication structure and internal identity
  are consistent.
- `source_verified`: contributing checkpoint artifacts also
  pass integrity verification.
- `content_reproduced`: reserved for future deterministic
  transcript reproduction and byte comparison.

The initial scanner must not report `content_reproduced`.

## Transcript states

Publication classification and transcript state are independent.

Supported transcript states:

- `assembled`
- `requires_reconciliation`

An unresolved transcript may still be a valid publication.

## Read-only guarantees

Discovery must not:

- Create directories or lock files.
- Modify manifests.
- Rewrite checkpoints.
- Rewrite assembly artifacts.
- Delete staging directories.
- Automatically reconcile transcript findings.
- Automatically select alternative fingerprints.

## Failure behavior

Invalid publications are classified, not repaired.

Unexpected filesystem entries are preserved.

The scanner must not follow symlinks in the assembly tree.

Concurrent publication activity may produce an incomplete
snapshot. Report coordinator lock status separately.

## Known limitations

- No independently persisted assembly artifact checksums.
- No deterministic transcript reproduction during discovery.
- No automatic repair or cleanup.
- No automatic checkpoint continuation.
- No semantic reconciliation.
- No independent proof of the original model/source selection.

## Next

Implement read-only assembly discovery and synthetic regression
tests for valid publications, corruption, staging, symlinks,
and unresolved transcript states.

## Validated implementation

Milestone 1.7B.9C.1 implements read-only assembly discovery.

### Implementation

- `processing/assembly_discovery.py`
- `tests/test_assembly_discovery.py`

### Verified behavior

- Canonical assembly identity validation.
- Algorithm versions 1 and 2 supported.
- Source checkpoint integrity verification.
- Valid and unresolved publications distinguished.
- Corrupt and missing publication artifacts detected.
- Symlinked assembly entries and processing ancestors rejected.
- Incomplete staging directories preserved.
- Unexpected entries classified without modification.
- Published manifests, checkpoints, and artifacts remain unchanged.

### Verification limitations

`source_verified` establishes source checkpoint integrity
and publication consistency, not independent verification
of published transcript bytes.

Filesystem validation uses path checks and descriptor-safe
artifact reads but does not eliminate all concurrent
filesystem replacement races.

No automatic repair, staging cleanup, or reconciliation
is performed.
