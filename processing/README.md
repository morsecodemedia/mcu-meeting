# MCU Meeting — Audio Alignment Processing

## Status

Experimental, read-only post-capture analysis.

This module estimates the relative acoustic timing between application
and microphone WAV recordings. It does not modify original recordings
or automatically apply synchronization corrections.

## Dependencies

Processing dependencies are optional and separate from the capture runtime:

- Python 3
- NumPy
- SciPy
- jsonschema (development/test dependency)

Example isolated environment:

```sh
python3 -m venv /tmp/mcu-meeting-alignment-venv
/tmp/mcu-meeting-alignment-venv/bin/python -m pip install numpy scipy jsonschema
```

## Usage

```sh
SID="<session-uuid>"

/tmp/mcu-meeting-alignment-venv/bin/python \
  -m processing.alignment_cli \
  "$HOME/.mcu-meeting/sessions/$SID" \
  --output /tmp/mcu-meeting-alignment-report.json
```

The CLI expects separate 48 kHz mono PCM16 application and microphone WAVs.

## Method

- Select up to 16 duration-aware analysis windows.
- Read bounded 12-second windows from each recording.
- Downsample to 8 kHz.
- Estimate candidate lag using normalized cross-correlation.
- Reject weak and ambiguous correlation peaks.
- Aggregate accepted offsets using median/MAD outlier rejection.
- Return `unknown` when evidence is insufficient.

## Limitations

- Correlation thresholds are heuristic, not calibrated probabilities.
- Acoustic propagation and speaker playback latency affect estimates.
- Clock drift is not yet measured.
- Sample-accurate synchronization is not established.
- Short recordings may not provide enough accepted windows.
- NumPy and SciPy are not required for capture.

## Testing

Full suite, including optional processing dependencies:

```sh
/tmp/mcu-meeting-alignment-venv/bin/python \
  -m unittest discover -s tests -v
```

Capture-only tests using the normal project environment:

```sh
.venv/bin/python -m unittest discover \
  -s tests -p 'test_recording*.py' -v

.venv/bin/python -m unittest discover \
  -s tests -p 'test_dual.py' -v

.venv/bin/python -m unittest discover \
  -s tests -p 'test_session.py' -v
```

The normal capture environment intentionally does not require
NumPy or SciPy.
