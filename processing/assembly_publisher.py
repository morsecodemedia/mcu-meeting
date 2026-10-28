"""Immutable, no-replace publication of assembled transcripts on macOS."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

DIGEST = re.compile(r"^[0-9a-f]{64}$")
RENAME_EXCL = 0x00000004


def _serialize(value):
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _write_synced(path, content):
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_exclusive(source, destination):
    if sys.platform != "darwin":
        raise RuntimeError(
            "Exclusive assembly publication currently requires macOS"
        )

    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameatx_np

    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int

    result = rename(
        -2,
        os.fsencode(source),
        -2,
        os.fsencode(destination),
        RENAME_EXCL,
    )

    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def publish_assembly(
    session_dir,
    fingerprint,
    transcript,
    provenance,
):
    """Publish both JSON artifacts as one immutable directory."""
    if not isinstance(fingerprint, str) or not DIGEST.fullmatch(
        fingerprint
    ):
        raise ValueError("Invalid assembly fingerprint")

    if not isinstance(transcript, dict):
        raise ValueError("Invalid transcript")

    if not isinstance(provenance, dict):
        raise ValueError("Invalid provenance")

    if provenance.get("assembly_fingerprint") != fingerprint:
        raise ValueError("Assembly provenance fingerprint mismatch")

    root = Path(session_dir)

    if root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid session directory")

    parent = root / "processing" / "assembly"
    parent.mkdir(parents=True, exist_ok=True)

    if parent.is_symlink():
        raise ValueError("Symlinked assembly directory")

    destination = parent / fingerprint

    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)

    transcript_bytes = _serialize(transcript)
    provenance_bytes = _serialize(provenance)

    staging = Path(tempfile.mkdtemp(
        prefix=".assembly-staging-",
        dir=parent,
    ))

    published = False

    try:
        _write_synced(
            staging / "transcript.json",
            transcript_bytes,
        )
        _write_synced(
            staging / "provenance.json",
            provenance_bytes,
        )

        _sync_directory(staging)

        _publish_exclusive(staging, destination)
        published = True

        _sync_directory(parent)

        checksums = {}

        for name, expected in (
            ("transcript.json", transcript_bytes),
            ("provenance.json", provenance_bytes),
        ):
            path = destination / name
            actual = path.read_bytes()

            if actual != expected:
                raise ValueError(
                    f"Published artifact mismatch: {name}"
                )

            checksums[name] = hashlib.sha256(actual).hexdigest()

        return {
            "fingerprint": fingerprint,
            "path": str(destination),
            "checksums": checksums,
        }

    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)
