"""Launch application capture and finalize a durable session."""
from __future__ import annotations

import hashlib
import os
import struct
import subprocess
import signal
import wave
from pathlib import Path

from . import manager


class CaptureFailed(RuntimeError):
    def __init__(self, session_id: str, reason: str):
        super().__init__(f"session {session_id}: {reason}")
        self.session_id = session_id


def verify_wav(path: Path) -> str:
    """Require nonempty, uncompressed PCM WAV and return SHA-256."""
    if not path.is_file() or path.is_symlink():
        raise ValueError("audio artifact missing or not a regular file")
    with wave.open(str(path), "rb") as wav:
        if wav.getcomptype() != "NONE" or wav.getnframes() <= 0:
            raise ValueError("WAV has no usable PCM frames")
        if wav.getframerate() <= 0 or wav.getnchannels() <= 0 or wav.getsampwidth() not in (1, 2, 3, 4):
            raise ValueError("WAV format invalid")
        expected = wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
        actual = 0
        while True:
            frames = wav.readframes(65536)
            if not frames:
                break
            actual += len(frames)
        if actual != expected:
            raise ValueError("WAV PCM data truncated")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _managed_capture(argv: list[str], *, stop_timeout: float = 15.0) -> subprocess.CompletedProcess:
    """Coordinate SIGINT and child shutdown; never treat a killed child as success."""
    child = subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, text=True)
    interrupted = False
    try:
        while True:
            try:
                _, stderr = child.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                continue
            except KeyboardInterrupt:
                interrupted = True
                child.send_signal(signal.SIGINT)
                try:
                    _, stderr = child.communicate(timeout=stop_timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    child.kill()
                    _, stderr = child.communicate()
                    raise KeyboardInterrupt('capture did not stop gracefully')
                break
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()
    if interrupted and child.returncode != 0:
        raise KeyboardInterrupt(f'capture stopped with exit {child.returncode}')
    return subprocess.CompletedProcess(argv, child.returncode, stdout='', stderr=stderr)


def record(root: Path, bundle_id: str, executable: Path, *, runner=None, duration: float | None = None) -> dict:
    """Create session first; never claim completion without validated audio."""
    executable = executable.expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(f"capture executable missing or not executable: {executable}")
    if duration is not None and (not isinstance(duration, (int, float)) or not 0 < duration <= 86400):
        raise ValueError("duration must be > 0 and <= 86400 seconds")
    data = manager.create(root, bundle_id)
    sid = data["session_id"]
    folder = root.expanduser() / sid
    audio = folder / "audio" / "application.wav"
    manager.transition(root, sid, "recording")
    try:
        argv = [str(executable), "--bundle-id", bundle_id, "--output", str(audio)]
        if duration is not None:
            argv.extend(["--duration", str(duration)])
        if runner is not None:
            result = runner(argv, check=False, capture_output=True, text=True)
        else:
            result = _managed_capture(argv)
        if result.returncode != 0:
            raise RuntimeError(f"capture exited {result.returncode}: {(result.stderr or '')[-500:]}")
        digest = verify_wav(audio)
        current = manager.load(root, sid)
        current["artifacts"].append({"kind": "application_audio", "path": "audio/application.wav", "sha256": digest})
        # Atomic artifact registration precedes completion. A crash between
        # these writes leaves a recoverable recording, never false success.
        manager._write_atomic(folder / "manifest.json", current)
        manager.transition(root, sid, "completed")
        return manager.load(root, sid)
    except BaseException as exc:
        # KeyboardInterrupt and termination during the child run are
        # interruptions, ordinary failures are failed captures.
        state = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
        try:
            manager.transition(root, sid, state)
        except Exception:
            pass  # Existing recording state remains discoverable by recover.
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise CaptureFailed(sid, str(exc)) from exc
