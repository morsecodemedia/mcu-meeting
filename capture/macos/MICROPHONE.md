# Standalone microphone capture (Milestone 1.6B.2)

`mcu-mic-capture devices` enumerates CoreAudio inputs with device UIDs and marks the default.

`mcu-mic-capture record --output /tmp/mcu-microphone-test.wav --duration 15` records
from the macOS **default input** until the duration expires. Without `--duration`,
press Ctrl+C once to request graceful shutdown and WAV finalization.

Grant Microphone permission to the terminal application under macOS System Settings >
Privacy & Security > Microphone. The adapter prints the selected input device.
It does not yet accept `--device-uid`; explicit device selection will be a separate gate.

The first adapter supports noninterleaved Float32 input from AVAudioEngine and writes
mono PCM16 at the device's sample rate through MCUAudioCore. Multiple channels are
averaged. Unsupported formats fail explicitly. The tap submits to a bounded writer
queue, with overflow treated as a failure. Hard kills can leave incomplete WAV files.

This standalone recorder is not synchronized with application capture and is not yet
registered in the Python session manifest. Device changes, interruption recovery,
and production-length microphone recordings require further validation.
