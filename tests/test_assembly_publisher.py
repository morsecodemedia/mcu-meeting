import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from processing.assembly_publisher import publish_assembly


@unittest.skipUnless(
    sys.platform == "darwin",
    "macOS exclusive directory publication",
)
class AssemblyPublisherTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fingerprint = "a" * 64
        self.transcript = {
            "schema_version": 1,
            "state": "assembled",
            "segments": [],
            "findings": [],
        }
        self.provenance = {
            "identity_version": 1,
            "assembly_fingerprint": self.fingerprint,
            "contributions": [],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self):
        return publish_assembly(
            self.root,
            self.fingerprint,
            self.transcript,
            self.provenance,
        )

    def test_success(self):
        result = self.publish()
        directory = Path(result["path"])

        self.assertTrue(
            (directory / "transcript.json").is_file()
        )
        self.assertTrue(
            (directory / "provenance.json").is_file()
        )

        self.assertEqual(
            json.loads(
                (directory / "transcript.json").read_text()
            ),
            self.transcript,
        )

    def test_existing_output_refused(self):
        first = self.publish()

        with self.assertRaises(FileExistsError):
            self.publish()

        self.assertTrue(Path(first["path"]).is_dir())

    def test_invalid_fingerprint(self):
        with self.assertRaises(ValueError):
            publish_assembly(
                self.root,
                "invalid",
                self.transcript,
                self.provenance,
            )

    def test_write_failure_cleanup(self):
        with patch(
            "processing.assembly_publisher._write_synced",
            side_effect=OSError("synthetic write failure"),
        ):
            with self.assertRaises(OSError):
                self.publish()

        parent = self.root / "processing/assembly"
        self.assertEqual(list(parent.iterdir()), [])

    def test_parent_sync_failure_preserves_published(self):
        original = __import__(
            "processing.assembly_publisher",
            fromlist=["_sync_directory"],
        )._sync_directory

        def fail_parent(path):
            if Path(path).name == "assembly":
                raise OSError("synthetic parent sync failure")
            return original(path)

        with patch(
            "processing.assembly_publisher._sync_directory",
            side_effect=fail_parent,
        ):
            with self.assertRaises(OSError):
                self.publish()

        destination = (
            self.root
            / "processing/assembly"
            / self.fingerprint
        )

        self.assertTrue(destination.is_dir())

    def test_no_staging_left_after_success(self):
        self.publish()

        parent = self.root / "processing/assembly"

        self.assertEqual(
            [item.name for item in parent.iterdir()],
            [self.fingerprint],
        )


    def test_provenance_fingerprint_mismatch(self):
        self.provenance["assembly_fingerprint"] = "b" * 64

        with self.assertRaisesRegex(
            ValueError,
            "Assembly provenance fingerprint mismatch",
        ):
            self.publish()

        destination = (
            self.root
            / "processing/assembly"
            / self.fingerprint
        )

        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
