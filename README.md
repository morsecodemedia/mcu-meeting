# MCU Meeting

Local-first meeting capture and intelligence subsystem.

## Purpose

MCU Meeting records meeting audio, processes transcripts, resolves speaker
identities, and produces durable structured artifacts for downstream knowledge
systems.

It operates independently of MCU and may optionally be integrated as a Git
submodule.

## Architecture

- Native macOS audio capture using ScreenCaptureKit and AVFoundation.
- Independent system/application and microphone audio tracks.
- Durable session artifacts with stable identifiers.
- Resumable post-meeting processing.
- Human-reviewable speaker identity assignments.
- Versioned structured outputs for downstream knowledge ingestion.

## Project status

Early development. Architecture is provisional.

The first milestone focuses on reliable capture and durable session management.
Live transcription, automatic meeting detection, and knowledge ingestion are
outside the initial implementation scope.

## Documentation

See `docs/architecture/` for architecture decisions and
`docs/research/` for reference implementation findings.

## Development

The project is currently macOS-focused.

Build instructions, test commands, and CLI usage will be documented as
their implementations are introduced.
