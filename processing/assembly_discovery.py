"""Read-only discovery and verification of published assemblies."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from processing.chunk_discovery import inspect_coordinator_lock
from processing.chunk_storage import (
    load_checkpoint,
    verify_artifacts,
)
from session import manager

DIGEST = re.compile(r"^[0-9a-f]{64}$")
STAGING_PREFIX = ".assembly-staging-"
SUPPORTED_ALGORITHMS = frozenset({1, 2})


def _read_json(path):
    """Read JSON from a regular file without following its final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)

    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Assembly artifact is not a regular file")

        with os.fdopen(fd, "rb", closefd=False) as stream:
            value = json.loads(stream.read().decode("utf-8"))

        if not isinstance(value, dict):
            raise ValueError("Assembly JSON must be an object")

        return value
    finally:
        os.close(fd)



def _validate_canonical_identity(identity):
    """Validate stored canonical identity without changing its bytes."""
    if not isinstance(identity, dict):
        raise ValueError("Invalid assembly identity")

    if set(identity) != {
        "identity_version",
        "assembly_algorithm_version",
        "sources",
        "contributions",
    }:
        raise ValueError("Unexpected assembly identity fields")

    if type(identity["identity_version"]) is not int:
        raise ValueError("Invalid identity version")

    if identity["identity_version"] != 1:
        raise ValueError("Unsupported identity version")

    algorithm = identity["assembly_algorithm_version"]

    if type(algorithm) is not int or algorithm not in SUPPORTED_ALGORITHMS:
        raise ValueError("Unsupported assembly algorithm")

    sources = identity["sources"]
    contributions = identity["contributions"]

    if not isinstance(sources, list) or not sources:
        raise ValueError("Invalid assembly sources")

    if not isinstance(contributions, list):
        raise ValueError("Invalid assembly contributions")

    source_order = {
        "application_audio": 0,
        "microphone_audio": 1,
    }

    previous_source_order = -1
    expected_ids = []

    chunk_fields = {
        "chunk_id",
        "source",
        "index",
        "owned_start_us",
        "owned_end_us",
        "read_start_us",
        "read_end_us",
    }

    for source_entry in sources:
        if not isinstance(source_entry, dict):
            raise ValueError("Invalid source entry")

        if set(source_entry) != {"source", "chunks"}:
            raise ValueError("Unexpected source fields")

        source_name = source_entry["source"]

        if source_name not in source_order:
            raise ValueError("Unsupported source")

        order = source_order[source_name]

        if order <= previous_source_order:
            raise ValueError("Noncanonical source order")

        previous_source_order = order

        chunks = source_entry["chunks"]

        if not isinstance(chunks, list) or not chunks:
            raise ValueError("Empty source chunks")

        previous_owned_end = 0

        for expected_index, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                raise ValueError("Invalid canonical chunk")

            if set(chunk) != chunk_fields:
                raise ValueError("Unexpected canonical chunk fields")

            index = chunk["index"]

            if type(index) is not int or index != expected_index:
                raise ValueError("Noncanonical chunk index")

            expected_id = f"{source_name}:{index:06d}"

            if (
                chunk["source"] != source_name
                or chunk["chunk_id"] != expected_id
            ):
                raise ValueError("Canonical chunk identity mismatch")

            values = [
                chunk[name]
                for name in (
                    "owned_start_us",
                    "owned_end_us",
                    "read_start_us",
                    "read_end_us",
                )
            ]

            if any(type(value) is not int for value in values):
                raise ValueError("Invalid microsecond boundary")

            owned_start, owned_end, read_start, read_end = values

            if not (
                0 <= read_start
                <= owned_start
                < owned_end
                <= read_end
            ):
                raise ValueError("Invalid canonical intervals")

            if owned_start != previous_owned_end:
                raise ValueError("Discontinuous chunk ownership")

            if read_start != owned_start:
                raise ValueError("Unexpected read interval start")

            previous_owned_end = owned_end
            expected_ids.append(expected_id)

    if len(contributions) != len(expected_ids):
        raise ValueError("Contribution count mismatch")

    for expected_id, contribution in zip(
        expected_ids, contributions
    ):
        if not isinstance(contribution, dict):
            raise ValueError("Invalid contribution")

        if set(contribution) != {
            "chunk_id",
            "fingerprint",
            "normalized_sha256",
        }:
            raise ValueError("Unexpected contribution fields")

        if contribution["chunk_id"] != expected_id:
            raise ValueError("Contribution order mismatch")

        for name in ("fingerprint", "normalized_sha256"):
            value = contribution[name]

            if not isinstance(value, str) or not DIGEST.fullmatch(value):
                raise ValueError("Invalid contribution digest")

    return identity

def _identity_digest(identity):
    _validate_canonical_identity(identity)

    if identity.get("identity_version") != 1:
        raise ValueError("Unsupported identity version")

    if identity.get("assembly_algorithm_version") not in (
        SUPPORTED_ALGORITHMS
    ):
        raise ValueError("Unsupported assembly algorithm")

    payload = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()


def _verify_publication(folder, directory, fingerprint, session_id):
    provenance = _read_json(directory / "provenance.json")
    transcript = _read_json(directory / "transcript.json")

    if provenance.get("session_id") != session_id:
        raise ValueError("Assembly session mismatch")

    if provenance.get("assembly_fingerprint") != fingerprint:
        raise ValueError("Assembly fingerprint mismatch")

    identity = provenance.get("identity")

    if _identity_digest(identity) != fingerprint:
        raise ValueError("Canonical assembly identity mismatch")

    contributions = identity.get("contributions")

    if not isinstance(contributions, list) or not contributions:
        raise ValueError("Missing assembly contributions")

    seen = set()

    for contribution in contributions:
        if not isinstance(contribution, dict):
            raise ValueError("Invalid contribution")

        chunk_id = contribution.get("chunk_id")
        execution = contribution.get("fingerprint")
        normalized_sha = contribution.get("normalized_sha256")

        if not isinstance(chunk_id, str):
            raise ValueError("Invalid contribution chunk ID")

        if chunk_id in seen:
            raise ValueError("Duplicate contribution")

        seen.add(chunk_id)

        if not (
            isinstance(execution, str)
            and DIGEST.fullmatch(execution)
            and isinstance(normalized_sha, str)
            and DIGEST.fullmatch(normalized_sha)
        ):
            raise ValueError("Invalid contribution fingerprint")

        checkpoint = load_checkpoint(
            folder, execution, chunk_id
        )

        if checkpoint["state"] != "completed":
            raise ValueError("Incomplete contributing checkpoint")

        verify_artifacts(folder, execution, chunk_id)

        matching = [
            artifact
            for artifact in checkpoint["artifacts"]
            if artifact["kind"] == "normalized_json"
        ]

        if len(matching) != 1:
            raise ValueError("Missing normalized artifact")

        if matching[0]["sha256"] != normalized_sha:
            raise ValueError("Contribution checksum mismatch")

    state = transcript.get("state")
    segments = transcript.get("segments")
    findings = transcript.get("findings")

    if state not in ("assembled", "requires_reconciliation"):
        raise ValueError("Invalid transcript state")

    if not isinstance(segments, list):
        raise ValueError("Invalid transcript segments")

    if not isinstance(findings, list):
        raise ValueError("Invalid transcript findings")

    if transcript.get("segment_count") != len(segments):
        raise ValueError("Transcript segment count mismatch")

    unresolved = sum(
        isinstance(item, dict)
        and item.get("type") in (
            "boundary_spanning",
            "timing_out_of_bounds",
        )
        for item in findings
    )

    if transcript.get("unresolved_count") != unresolved:
        raise ValueError("Transcript unresolved count mismatch")

    if state != (
        "requires_reconciliation" if unresolved else "assembled"
    ):
        raise ValueError("Transcript reconciliation state mismatch")

    return {
        "classification": "verified_complete",
        "verification_level": "source_verified",
        "transcript_state": state,
        "segment_count": len(segments),
        "unresolved_count": unresolved,
        "action": (
            "reconciliation_required"
            if unresolved else "available"
        ),
    }


def discover_assemblies(sessions_root, session_id):
    """Classify assembly entries without creating or changing files."""
    root = Path(sessions_root).expanduser().resolve(strict=True)
    folder = manager._session_dir(root, session_id)

    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Invalid session directory")

    manifest = manager.load(root, session_id)

    if manifest.get("session_id") != session_id:
        raise ValueError("Session identity mismatch")

    lock_status = inspect_coordinator_lock(folder)

    processing = folder / "processing"

    if processing.is_symlink():
        raise ValueError("Symlinked processing directory")

    if processing.exists() and not processing.is_dir():
        raise ValueError("Invalid processing directory")

    base = processing / "assembly"

    report = {
        "session_id": session_id,
        "lock_status": lock_status,
        "assemblies": [],
    }

    if not base.exists() and not base.is_symlink():
        return report

    if base.is_symlink() or not base.is_dir():
        raise ValueError("Invalid assembly root")

    for entry in sorted(base.iterdir(), key=lambda p: p.name):
        record = {"name": entry.name}

        if entry.is_symlink():
            record.update({
                "classification": "unknown_entry",
                "action": "manual_investigation",
            })

        elif entry.name.startswith(STAGING_PREFIX):
            record.update({
                "classification": "incomplete_staging",
                "action": "preserve_for_inspection",
            })

        elif not DIGEST.fullmatch(entry.name) or not entry.is_dir():
            record.update({
                "classification": "unknown_entry",
                "action": "manual_investigation",
            })

        else:
            try:
                record.update(_verify_publication(
                    folder, entry, entry.name, session_id
                ))
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                UnicodeError,
            ):
                record.update({
                    "classification": "published_invalid",
                    "action": "manual_investigation",
                })

        report["assemblies"].append(record)

    return report
