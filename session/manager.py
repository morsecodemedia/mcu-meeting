"""Session storage and capture lifecycle; standard library only."""
from __future__ import annotations

import json
import os
import fcntl
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "0.1.0"
STAGES = ("transcription", "diarization", "speaker_resolution", "knowledge_export")
TRANSITIONS = {
    "created": {"recording", "failed"},
    "recording": {"completed", "interrupted", "failed"},
    "interrupted": {"failed"},
    "completed": set(),
    "failed": set(),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_root() -> Path:
    return Path.home() / ".mcu-meeting" / "sessions"


def _session_dir(root: Path, session_id: str) -> Path:
    if str(uuid.UUID(session_id)) != session_id:
        raise ValueError("session_id must be a canonical UUID")
    return root / session_id


def _write_atomic(path: Path, data: dict) -> None:
    payload = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temp = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        # Best effort directory sync for durability after rename.
        try:
            dirfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except OSError:
            pass
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def create(root: Path, bundle_id: str) -> dict:
    if not bundle_id.strip():
        raise ValueError("bundle ID cannot be empty")
    root = root.expanduser()
    root.mkdir(parents=True, exist_ok=True)
    sid = str(uuid.uuid4())
    folder = _session_dir(root, sid)
    folder.mkdir(mode=0o700)
    (folder / "audio").mkdir()
    (folder / "events").mkdir()
    stage = lambda: {"state": "pending", "attempts": 0, "retryable": False, "error": None}
    data = {
        "schema_version": SCHEMA_VERSION,
        "session_id": sid,
        "created_at": now(),
        "capture": {"state": "created", "target_bundle_id": bundle_id.strip(), "started_at": None, "ended_at": None, "health_events": []},
        "processing": {name: stage() for name in STAGES},
        "artifacts": [],
    }
    _write_atomic(folder / "manifest.json", data)
    return data


def load(root: Path, session_id: str) -> dict:
    path = _session_dir(root.expanduser(), session_id) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def transition(root: Path, session_id: str, state: str) -> dict:
    folder = _session_dir(root.expanduser(), session_id)
    data = load(root, session_id)
    previous = data["capture"]["state"]
    if state not in TRANSITIONS.get(previous, set()):
        raise ValueError(f"invalid capture transition: {previous} -> {state}")
    data["capture"]["state"] = state
    if state == "recording":
        data["capture"]["started_at"] = now()
    if state in {"completed", "interrupted", "failed"}:
        data["capture"]["ended_at"] = now()
    _write_atomic(folder / "manifest.json", data)
    return data


def recovery_candidates(root: Path) -> list[dict]:
    """Read-only report; never infer successful completion from stale state."""
    root = root.expanduser()
    if not root.exists():
        return []
    result = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        path = folder / "manifest.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["capture"]["state"] == "recording":
                result.append({"session_id": data["session_id"], "state": "recording", "action": "inspect before marking interrupted"})
        except (ValueError, KeyError, TypeError):
            result.append({"session_id": folder.name, "state": "unreadable", "action": "manual investigation"})
    return result


PROCESSING_TRANSITIONS = {
    "pending": {"running", "skipped"},
    "running": {"completed", "failed"},
    "failed": {"running"},
    "completed": set(),
    "skipped": set(),
}


def transition_processing(
    root: Path,
    session_id: str,
    stage: str,
    state: str,
    *,
    retryable: bool = False,
    error: str | None = None,
) -> dict:
    """Transition one processing stage without changing capture state."""
    if stage not in STAGES:
        raise ValueError(f"unknown processing stage: {stage}")

    with manifest_lock(root, session_id):

        folder = _session_dir(root.expanduser(), session_id)
        data = load(root, session_id)

        if data["capture"]["state"] != "completed":
            raise ValueError("processing requires completed capture")

        current = data["processing"][stage]
        previous = current["state"]

        if state not in PROCESSING_TRANSITIONS.get(previous, set()):
            raise ValueError(f"invalid processing transition: {previous} -> {state}")

        if previous == "failed" and not current["retryable"]:
            raise ValueError("processing stage is not retryable")

        if state == "running":
            current["attempts"] += 1
            current["retryable"] = False
            current["error"] = None
        elif state == "failed":
            current["retryable"] = bool(retryable)
            current["error"] = error or "processing failed"
        else:
            current["retryable"] = False
            current["error"] = None

        current["state"] = state
        _write_atomic(folder / "manifest.json", data)
        return data


def processing_recovery_candidates(root: Path) -> list[dict]:
    """Read-only inspection of stages left in running state."""
    root = root.expanduser()
    if not root.exists():
        return []

    result = []

    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue

        manifest = folder / "manifest.json"
        if not manifest.is_file():
            continue

        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            for stage in STAGES:
                current = data["processing"][stage]
                if current["state"] == "running":
                    result.append({
                        "session_id": data["session_id"],
                        "stage": stage,
                        "attempts": current["attempts"],
                        "action": "inspect artifacts before retry",
                    })
        except (ValueError, KeyError, TypeError):
            result.append({
                "session_id": folder.name,
                "stage": None,
                "action": "manual investigation",
            })

    return result


class ProcessingLockBusy(RuntimeError):
    """Another process currently owns this session's processing lock."""


@contextmanager
def processing_lock(root: Path, session_id: str):
    """Hold a nonblocking advisory lock for one session."""
    folder = _session_dir(root.expanduser(), session_id)

    if not folder.is_dir():
        raise FileNotFoundError(folder)

    lock_path = folder / ".processing.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)

    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProcessingLockBusy(
                f"processing lock busy: {session_id}"
            ) from exc

        yield

    finally:
        os.close(fd)


class ManifestLockBusy(RuntimeError):
    """Another process owns this session's manifest transaction lock."""


@contextmanager
def manifest_lock(root: Path, session_id: str):
    """Acquire a nonblocking session-scoped manifest lock."""
    folder = _session_dir(root.expanduser(), session_id)

    if not folder.is_dir():
        raise FileNotFoundError(folder)

    lock_path = folder / ".manifest.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)

    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ManifestLockBusy(
                f"manifest lock busy: {session_id}"
            ) from exc

        yield
    finally:
        os.close(fd)
