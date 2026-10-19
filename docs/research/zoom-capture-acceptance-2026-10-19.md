# Zoom Capture Acceptance — 2026-10-19

## Status

Passed with outstanding verification items.

## Environment

- Platform: macOS, Apple Silicon
- Capture framework: ScreenCaptureKit
- Application: Zoom
- Bundle identifier: `us.zoom.xos`
- Capture mode: Application-scoped system audio
- Output: Streaming mono PCM16 WAV, 48 kHz

## Observed results

- Real multi-participant Zoom meeting recorded.
- Session duration: 30 minutes, 53 seconds.
- Interactive Ctrl+C shutdown succeeded.
- Session manifest reached `completed`.
- Audio artifact registered with SHA-256; independent checksum verification passed.
- Remote participants clearly audible.
- Manual playback spot checks at beginning, middle, and end passed.
- No audible degradation reported at inspected positions.
- Downstream processing stages remain pending.

## Remaining validation

- Confirm exclusion of unrelated application audio during Zoom capture.
- Validate long-running microphone capture.
- Test unexpected process termination and partial recording recovery.
- Repeat testing across additional Zoom sessions and audio-device changes.

## Limitations

- Application audio only; local microphone is not independently captured.
- Spot checks do not establish uninterrupted quality across every second.
- This test does not establish Slack or Microsoft Teams compatibility.

## Architecture status

ADR-0001 remains Proposed.
