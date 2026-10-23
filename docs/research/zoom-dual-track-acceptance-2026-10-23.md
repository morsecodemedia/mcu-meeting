# Zoom Dual-Track Capture Acceptance — 2026-10-23

## Status

Passed: live capture, artifact integrity, and manual audio-quality checks.

## Session

- Session ID: 05fda6fe-706c-4e3a-a021-5dccb97bf8f5
- Application: Zoom (`us.zoom.xos`)
- Capture state: completed
- Stop reason: user
- Duration: approximately 34 minutes
- Capture health events: none reported

## Audio artifacts

### Application audio

- Path: audio/application.wav
- Duration: 2036.88 seconds
- Format: 48 kHz mono PCM16
- SHA-256: verified against manifest
- Remote participants clearly audible
- Local speaker not audible
- Beginning, middle, and end playback checks passed

### Microphone audio

- Path: audio/microphone.wav
- Duration: 2036.90 seconds
- Format: 48 kHz mono PCM16
- SHA-256: verified against manifest
- Local speaker clearly audible
- Remote participants faintly audible through acoustic speaker bleed
- Beginning, middle, and end playback checks passed

## Timing

- Process launch offset: approximately 1.53 milliseconds
- Track duration difference: approximately 20 milliseconds
- These measurements do not establish sample-accurate alignment.

## Processing implications

- Prefer application audio for remote speech.
- Prefer microphone audio for local speech.
- Detect acoustic bleed adaptively.
- Avoid duplicate transcription of overlapping remote speech.
- Preserve original WAV artifacts.

## Remaining limitations

- Sample-accurate synchronization is unverified.
- Acoustic bleed varies with room and device placement.
- Device-change recovery is unverified.
- Additional extended-duration sessions are needed for reliability confidence.
- Transcription and speaker attribution remain unimplemented.

## Architecture

ADR-0001 remains Proposed.
