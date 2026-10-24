"""Read-only acoustic alignment CLI."""
import argparse
import json
import wave
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly
from .alignment import peak_quality, robust_consensus
from session.recording import verify_wav

RATE = 8000
WINDOW_SECONDS = 12
MAX_WINDOWS = 16


def analysis_positions(duration):
    if duration < WINDOW_SECONDS:
        return []
    available = duration - WINDOW_SECONDS
    count = min(MAX_WINDOWS, max(1, int(duration // 120) + 1))
    if count == 1:
        return [max(0, available / 2)]
    return [
        available * index / (count - 1)
        for index in range(count)
    ]


def read_window(path, position):
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(),
                wav.getframerate()) != (1, 2, 48000):
            raise ValueError("Expected mono PCM16 48 kHz WAV")
        if position + 12 > wav.getnframes() / wav.getframerate():
            raise ValueError("Window outside recording")
        wav.setpos(int(position * 48000))
        raw = wav.readframes(12 * 48000)
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    return resample_poly(samples, 1, 6)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    folder = args.session_dir.expanduser().resolve()
    audio_dir = folder / "audio"
    app = audio_dir / "application.wav"
    mic = audio_dir / "microphone.wav"

    if not app.is_file() or not mic.is_file():
        parser.error("Both WAV tracks are required")

    try:
        verify_wav(app)
        verify_wav(mic)
    except (OSError, ValueError, EOFError) as exc:
        parser.error(f"Invalid capture audio: {exc}")

    if args.output:
        output = args.output.expanduser().resolve()
        if output == folder / "manifest.json" or (
            output == audio_dir or audio_dir in output.parents
        ):
            parser.error("Refusing to overwrite capture artifacts")

    windows = []
    with wave.open(str(app), "rb") as wav:
        app_duration = wav.getnframes() / wav.getframerate()
    with wave.open(str(mic), "rb") as wav:
        mic_duration = wav.getnframes() / wav.getframerate()

        duration = min(app_duration, mic_duration)
    positions = analysis_positions(duration)

    for position in positions:
        reference = read_window(app, position)
        observed = read_window(mic, position)
        result = peak_quality(reference, observed, RATE)
        windows.append({"position_seconds": position, **result})

    consensus_input = [
        {"status": "estimated", "offset_seconds": item["lag_seconds"]}
        if item["status"] == "estimated"
        else {"status": "unknown"}
        for item in windows
    ]
    consensus = (
        robust_consensus(consensus_input)
        if positions
        else {
            "status": "unknown",
            "reason": "insufficient_duration",
            "offset_seconds": None,
            "accepted_windows": 0,
            "rejected_windows": 0,
            "drift_ppm": None,
        }
    )
    report = {
        "schema_version": 1,
        "method": "bounded_normalized_cross_correlation",
        "precision": "provisional_acoustic",
        "consensus": consensus,
        "windows": windows,
        "warnings": [
            "Acoustic propagation and playback latency are included.",
            "Sample-accurate synchronization is not established.",
            "Clock drift has not been measured."
        ]
    }

    payload = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
