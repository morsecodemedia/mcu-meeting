# Transcript Normalization and Immutable Artifacts

## Status

Milestone 1.7B.4–1.7B.5 implementation complete.
Production session-pipeline integration remains pending.

## Purpose

Normalize whisper.cpp JSON into source-aware, meeting-relative
transcript segments while preserving source provenance.

## Input

- whisper.cpp JSON transcription.
- Audio source: `application_audio` or `microphone_audio`.
- Excerpt start offset in seconds.
- Optional model SHA-256 checksum.

## Normalized output

Each segment includes:

- Stable source-local identifier.
- Audio source.
- Meeting-relative start and end timestamps.
- Transcribed text.
- Speaker set to `unresolved`.
- Attribution method set to `null`.

Segment overlap is preserved. No diarization or acoustic echo
deduplication is performed.

## Provenance

Published artifacts include:

- Original Whisper JSON SHA-256.
- Source format identifier.
- Model type and language.
- Model SHA-256 when provided.

The original Whisper JSON and audio recordings are not modified.

## Immutable publication

`normalize_file()`:

1. Rejects an existing destination.
2. Rejects output symlinks.
3. Writes JSON into a temporary file in the destination directory.
4. Flushes and synchronizes the temporary file.
5. Publishes through an exclusive hard link.
6. Synchronizes the destination directory.
7. Removes the temporary file.

An existing normalized transcript is never silently replaced.

## Failure and recovery

If publication fails before the hard link is created, no destination
artifact is published.

If directory synchronization fails after publication, a complete
destination artifact may remain even though the operation raises an
exception.

Recovery must inspect and validate the existing artifact before
deciding whether to retry using a new destination.

Do not delete or overwrite a potentially valid artifact automatically.

## Limitations

- Speaker attribution is not implemented.
- Acoustic echo deduplication is not implemented.
- Model SHA-256 must currently be supplied by the caller.
- Transcript segments retain Whisper's approximate timestamps.
- Session manifest integration and processing state transitions
  remain future work.
- Source-local identifiers are stable for a given ordered transcript,
  but are not globally unique across separate transcription runs.

## Validation

On 2026-10-24:

- 14 transcript tests passed.
- 46 total Python tests passed.
- Synthetic directory-sync failure recovery passed.
- Real Whisper Small outputs were normalized successfully:
  14 application segments and 19 microphone segments.

## Privacy

Real meeting transcripts and speaker annotations remain outside Git.
Only synthetic test content and implementation documentation should
be committed.
