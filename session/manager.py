"""Session storage and capture lifecycle; standard library only."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
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
