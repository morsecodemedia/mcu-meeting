# Streaming WAV writer tests

Run the isolated smoke test without executing ScreenCaptureKit:

```sh
swiftc capture/macos/AudioCore/WAVStreamWriter.swift capture/macos/Tests/WAVStreamWriterSmoke.swift -o /tmp/mcu-wav-writer-smoke
/tmp/mcu-wav-writer-smoke
```

The writer is not yet connected to capture. Callback queueing, disk failure,
size-limit boundary, and crash recovery need additional tests before production use.
