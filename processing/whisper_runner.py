"""Controlled whisper.cpp execution and immutable JSON publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import wave
from pathlib import Path

from processing.whisper_profile import WhisperProfile

VERSION = re.compile(r"whisper\.cpp version:\s*(\d+(?:\.\d+){1,3})")


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file(path):
    """Open and inspect a file without following its final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"Not a regular file: {path}")
    finally:
        os.close(fd)


def _validate_audio(path):
    _regular_file(path)

    with wave.open(str(path), "rb") as stream:
        if (
            stream.getframerate() != 16000
            or stream.getnchannels() != 1
            or stream.getsampwidth() != 2
            or stream.getcomptype() != "NONE"
        ):
            raise ValueError("Whisper input must be 16 kHz mono PCM16")

        if stream.getnframes() == 0:
            raise ValueError("Whisper input is empty")


def _validate_json(path):
    _regular_file(path)

    with Path(path).open("r", encoding="utf-8") as stream:
        payload = json.load(stream)

    if not isinstance(payload, dict):
        raise ValueError("Whisper JSON must be an object")

    transcription = payload.get("transcription")

    if not isinstance(transcription, list):
        raise ValueError("Whisper JSON missing transcription array")

    for segment in transcription:
        if not isinstance(segment, dict):
            raise ValueError("Invalid Whisper segment")

        if not isinstance(segment.get("text"), str):
            raise ValueError("Whisper segment missing text")

    return payload


def whisper_version(binary="whisper-cli"):
    """Return the installed whisper.cpp version."""
    result = subprocess.run(
        [binary, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError("Unable to determine whisper.cpp version")

    match = VERSION.search(result.stdout + result.stderr)

    if not match:
        raise ValueError("Unrecognized whisper.cpp version output")

    return match.group(1)


def run_whisper(
    input_wav,
    model_path,
    output_json,
    *,
    profile=None,
    binary="whisper-cli",
):
    """Execute Whisper and exclusively publish validated JSON."""
    if profile is None:
        profile = WhisperProfile()

    if not isinstance(profile, WhisperProfile):
        raise ValueError("Invalid Whisper profile")

    options = profile.cli_arguments()

    audio = Path(input_wav).expanduser().resolve(strict=True)
    model = Path(model_path).expanduser().resolve(strict=True)
    output = Path(output_json).expanduser().absolute()

    _validate_audio(audio)
    _regular_file(model)

    if output.is_symlink() or output.exists():
        raise FileExistsError(f"Output already exists: {output}")

    if output == audio or output == model:
        raise ValueError("Output collides with input")

    parent = output.parent.resolve(strict=True)

    if not parent.is_dir():
        raise NotADirectoryError(parent)

    version = whisper_version(binary)

    with tempfile.TemporaryDirectory(
        prefix=".whisper-run-",
        dir=parent,
    ) as temporary:
        prefix = Path(temporary) / "result"

        command = [
            binary,
            "-m", str(model),
            "-f", str(audio),
            *options,
            "-oj",
            "-of", str(prefix),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Whisper execution failed: {result.stderr.strip()}"
            )

        generated = Path(str(prefix) + ".json")
        payload = _validate_json(generated)

        # Synchronize the validated output before publication.
        with generated.open("rb") as stream:
            os.fsync(stream.fileno())

        # Exclusive publication; never replace an existing artifact.
        os.link(generated, output)

        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        return {
            "engine": "whisper.cpp",
            "version": version,
            "model_sha256": _sha256(model),
            "input_sha256": _sha256(audio),
            "output_sha256": _sha256(output),
            "profile": profile.canonical(),
            "segments": len(payload["transcription"]),
        }
