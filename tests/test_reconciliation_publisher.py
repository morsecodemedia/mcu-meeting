"""Regression tests for immutable human-review publication."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from processing.reconciliation_publisher import publish_review


@unittest.skipUnless(
    sys.platform == "darwin",
    "macOS exclusive review publication",
)
class ReconciliationPublisherTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.session = self.root / "11111111-1111-4111-8111-111111111111"
        self.session.mkdir()

        self.review = {
            "schema_version": 2,
            "session_id": self.session.name,
            "assembly_fingerprint": "a" * 64,
            "review_status": "partial",
            "source_review_sha256": "b" * 64,
            "decisions": [],
            "capture_observations": {},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self):
        return publish_review(self.session, self.review)

    def destination(self):
        return (
            self.session
            / "processing/reconciliation/human-review-v2.json"
        )

    def staging_files(self):
        parent = self.destination().parent
        if not parent.exists():
            return []
        return list(parent.glob(".review-staging-*"))

    def test_success(self):
        result = self.publish()
        destination = self.destination()

        self.assertEqual(result["path"], str(destination))
        self.assertTrue(destination.is_file())
        self.assertEqual(
            json.loads(destination.read_text()),
            self.review,
        )
        self.assertEqual(len(result["sha256"]), 64)
        self.assertEqual(self.staging_files(), [])

    def test_existing_output_refused(self):
        self.publish()
        original = self.destination().read_bytes()

        with self.assertRaises(FileExistsError):
            self.publish()

        self.assertEqual(
            self.destination().read_bytes(),
            original,
        )

    def test_symlinked_destination_refused(self):
        target = self.session / "target.json"
        target.write_text("protected")

        self.destination().parent.mkdir(parents=True)
        self.destination().symlink_to(target)

        with self.assertRaises(FileExistsError):
            self.publish()

        self.assertEqual(target.read_text(), "protected")

    def test_symlinked_parent_refused(self):
        external = self.root / "external"
        external.mkdir()

        processing = self.session / "processing"
        processing.symlink_to(external)

        with self.assertRaises(ValueError):
            self.publish()

        self.assertEqual(list(external.iterdir()), [])

    def test_invalid_review_version(self):
        self.review["schema_version"] = True

        with self.assertRaises(ValueError):
            self.publish()

        self.assertFalse(
            (self.session / "processing").exists()
        )

    def test_session_mismatch(self):
        self.review["session_id"] = "wrong"

        with self.assertRaises(ValueError):
            self.publish()

    def test_write_failure_cleanup(self):
        with patch(
            "processing.reconciliation_publisher.os.fsync",
            side_effect=OSError("synthetic write failure"),
        ):
            with self.assertRaises(OSError):
                self.publish()

        self.assertFalse(self.destination().exists())
        self.assertEqual(self.staging_files(), [])

    def test_rename_failure_cleanup(self):
        with patch(
            "processing.reconciliation_publisher._publish_exclusive",
            side_effect=OSError("synthetic rename failure"),
        ):
            with self.assertRaises(OSError):
                self.publish()

        self.assertFalse(self.destination().exists())
        self.assertEqual(self.staging_files(), [])

    def test_parent_sync_failure_preserves_publication(self):
        with patch(
            "processing.reconciliation_publisher._sync_directory",
            side_effect=OSError("synthetic directory sync failure"),
        ):
            with self.assertRaises(OSError):
                self.publish()

        self.assertTrue(self.destination().is_file())
        self.assertEqual(
            json.loads(self.destination().read_text()),
            self.review,
        )

    def test_no_staging_after_success(self):
        self.publish()
        self.assertEqual(self.staging_files(), [])

    def test_invalid_review_type(self):
        with self.assertRaises(ValueError):
            publish_review(self.session, [])

    def test_missing_session_directory(self):
        missing = self.root / "missing"

        with self.assertRaises(ValueError):
            publish_review(missing, self.review)


if __name__ == "__main__":
    unittest.main()
