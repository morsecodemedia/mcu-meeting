# macOS application audio capture

Experimental Swift executable using ScreenCaptureKit. This component is independent of the meeting processing pipeline.

## Build

From the repository root:

```sh
swift build -c release --package-path capture/macos
```

## Usage

```sh
capture/macos/.build/release/mcu-capture --help
capture/macos/.build/release/mcu-capture --bundle-id com.google.Chrome --output /tmp/mcu-chrome.wav
```

Other intended targets: `us.zoom.xos` (Zoom), `com.tinyspeck.slackmacgap` (Slack), `com.microsoft.teams2` (Teams). The executable requires the target application to appear in ScreenCaptureKit's application list and fails rather than falling back to whole-display audio.

## Permissions and behavior

Grant Screen & System Audio Recording permission to the terminal host in macOS System Settings > Privacy & Security. Recording continues until Ctrl+C or the optional --duration limit and produces a mono 16-bit PCM WAV. Audio capture is application-scoped, not meeting-scoped. It does not record microphone audio, provide a durable session manifest, or run transcription. No automatic recording is implemented.

## Verification gates

1. Release build succeeds.
2. `--help` exits 0; malformed arguments exit nonzero.
3. Unknown bundle identifier exits nonzero and produces no WAV.
4. Chrome regression: play Chrome and mpv simultaneously; confirm only Chrome in the WAV.
5. Zoom, Slack and Teams require separate real-call acceptance tests; do not claim support until tested.

## Known limitations

- Interactive Ctrl+C stopping and optional --duration are supported.
- Audio is written incrementally through a bounded queue; extended-duration reliability remains unvalidated.
- Capture timing, interruptions, source process helpers, and long-duration reliability remain unvalidated.
- The existing audio decoder and WAV writer were intentionally preserved in this CLI change.

## Session integration

The repository-root Python CLI (`python3 -m session ... record`) can launch
this executable, validate the WAV, and register it in a durable session.
Capture supports interactive stopping and optional duration; session lifecycle management remains in Python.

## Streaming writer work in progress (Milestone 1.5A)

`Sources/WAVStreamWriter.swift` introduces an incremental mono PCM16 WAV writer.
It is not wired into capture yet; the existing ten-second recorder is unchanged.
A provisional WAV header is finalized on normal shutdown. Abrupt termination may
leave an invalid header, so recovery and bounded callback-to-writer buffering are
required before this is suitable for long meetings. Standard RIFF has a size limit.

### Writer verification (Milestone 1.5A)

Compile the writer with each standalone test file separately using `swiftc`;
`Tests/` is not currently a SwiftPM test target. The smoke test checks basic
WAV output; `WAVStreamWriterFailures.swift` checks invalid sample rates,
empty recordings, repeated finalization, post-finalization writes, and an
unwritable destination. Both tests use disposable temporary files.

The current writer is **not thread-safe** and has no explicit abort operation.
A failed or interrupted write may leave an incomplete WAV. It is not yet
connected to the ScreenCaptureKit callback or suitable for long recordings.

## Streaming integration (Milestone 1.5B.1)

The capture callback submits decoded mono frames to a five-second bounded queue.
A serialized worker writes PCM16 incrementally. Overflow and write errors prevent
finalization. The existing ten-second stop remains until lifecycle controls land.
A hard process kill can leave an incomplete WAV header; recovery is pending.

## Recording controls (Milestone 1.5B.2)

The native executable records until Ctrl+C or an optional `--duration`
limit (maximum 86400 seconds). A normal stop drains queued audio and
finalizes the WAV. Hard kills can leave an incomplete WAV.

Python session orchestration has not yet been updated for interactive
recording. Use the native executable directly for these tests.

## Shared audio core

`MCUAudioCore` is a Swift library target shared by `mcu-capture` and
`mcu-mic-capture`.

It owns `WAVStreamWriter` and `AudioWriteQueue`. Both executables depend
on the shared target rather than maintaining duplicate audio-writing code.

The WAV writer produces incremental mono PCM16 RIFF/WAV output.
The bounded queue serializes writes outside capture callbacks and
reports overflow or I/O failures rather than silently discarding audio.

The microphone executable currently supports CoreAudio input-device
discovery only. AVAudioEngine recording is not yet implemented.

CoreAudio numeric device IDs are runtime identifiers. Device UIDs
should be used for persistent configuration and future explicit
microphone selection.
