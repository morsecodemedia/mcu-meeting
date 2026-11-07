"""Immutable publication of versioned human reconciliation reviews."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from processing.assembly_publisher import (
    _publish_exclusive,
    _serialize,
    _sync_directory,
)

from processing.reconciliation_validation import validate_review_v2

SUPPORTED_VERSIONS = frozenset({2})


def publish_review(session_dir, review):
    """Publish a versioned review without replacing existing evidence."""

    if not isinstance(review, dict):
        raise ValueError("Invalid review")

    version = review.get("schema_version")

    if type(version) is not int or version not in SUPPORTED_VERSIONS:
        raise ValueError("Unsupported review version")

    validate_review_v2(review)

    # Validate serialization before any filesystem mutation.
    content = _serialize(review)

    root = Path(session_dir)

    if root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid session directory")

    if review.get("session_id") != root.name:
        raise ValueError("Review session mismatch")

    processing = root / "processing"
    parent = processing / "reconciliation"

    for directory in (processing, parent):
        if directory.is_symlink():
            raise ValueError("Symlinked processing directory")

        directory.mkdir(exist_ok=True)

        if not directory.is_dir():
            raise ValueError("Invalid processing directory")

    destination = parent / f"human-review-v{version}.json"

    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)

    fd, staging_name = tempfile.mkstemp(
        prefix=".review-staging-",
        suffix=".json",
        dir=parent,
    )

    staging = Path(staging_name)
    published = False

    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        _publish_exclusive(staging, destination)
        published = True

        _sync_directory(parent)

        actual = destination.read_bytes()

        if actual != content:
            raise ValueError("Published review content mismatch")

        return {
            "path": str(destination),
            "schema_version": version,
            "sha256": hashlib.sha256(actual).hexdigest(),
        }

    finally:
        if not published and staging.exists():
            staging.unlink()
