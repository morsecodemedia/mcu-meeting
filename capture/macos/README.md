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

Grant Screen & System Audio Recording permission to the terminal host in macOS System Settings > Privacy & Security. Recording lasts 10 seconds and produces a mono 16-bit PCM WAV. Audio capture is application-scoped, not meeting-scoped. It does not record microphone audio, provide a durable session manifest, or run transcription. No automatic recording is implemented.

## Verification gates

1. Release build succeeds.
2. `--help` exits 0; malformed arguments exit nonzero.
3. Unknown bundle identifier exits nonzero and produces no WAV.
4. Chrome regression: play Chrome and mpv simultaneously; confirm only Chrome in the WAV.
5. Zoom, Slack and Teams require separate real-call acceptance tests; do not claim support until tested.

## Known limitations

- Ten-second fixed capture duration; no stop command.
- WAV output accumulates samples in memory, so this is not yet a long-meeting recorder.
- Capture timing, interruptions, source process helpers, and long-duration reliability remain unvalidated.
- The existing audio decoder and WAV writer were intentionally preserved in this CLI change.

## Session integration

The repository-root Python CLI (`python3 -m session ... record`) can launch
this executable, validate the WAV, and register it in a durable session.
Capture itself still runs for ten seconds; no session logic is embedded in Swift.

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
