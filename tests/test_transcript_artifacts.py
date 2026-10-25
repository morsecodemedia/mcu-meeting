import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from processing.transcript_normalization import normalize_file


class TranscriptArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "whisper.json"
        self.output = self.root / "normalized.json"
        self.source.write_text(json.dumps({
            "model": {"type": "small"},
            "params": {"language": "en"},
            "transcription": [{
                "offsets": {"from": 0, "to": 1000},
                "text": "Synthetic test speech",
            }],
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def write_artifact(self, output=None):
        return normalize_file(
            self.source,
            output or self.output,
            source="application_audio",
            excerpt_start_seconds=300,
            model_sha256="model-digest",
        )

    def test_provenance_checksum(self):
        expected = hashlib.sha256(self.source.read_bytes()).hexdigest()
        result = self.write_artifact()
        self.assertEqual(
            result["provenance"]["source_json_sha256"], expected
        )
        self.assertEqual(result["model"]["sha256"], "model-digest")
        self.assertEqual(
            json.loads(self.output.read_text())["provenance"],
            result["provenance"],
        )

    def test_existing_output_refused(self):
        self.output.write_text("preserve")
        with self.assertRaises(FileExistsError):
            self.write_artifact()
        self.assertEqual(self.output.read_text(), "preserve")

    def test_source_preserved(self):
        original = self.source.read_bytes()
        self.write_artifact()
        self.assertEqual(self.source.read_bytes(), original)

    def test_output_symlink_refused(self):
        protected = self.root / "protected.json"
        protected.write_text("preserve")
        self.output.symlink_to(protected)

        with self.assertRaises(FileExistsError):
            self.write_artifact()

        self.assertEqual(protected.read_text(), "preserve")

    def test_atomic_link_failure(self):
        with patch(
            "processing.transcript_normalization.os.link",
            side_effect=OSError("synthetic link failure"),
        ):
            with self.assertRaises(OSError):
                self.write_artifact()

        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".transcript-*.tmp")), [])

    def test_reprocessing_requires_new_path(self):
        self.write_artifact()

        with self.assertRaises(FileExistsError):
            self.write_artifact()

        second = self.root / "normalized-v2.json"
        self.write_artifact(second)
        self.assertTrue(second.exists())


    def test_directory_sync_failure(self):
        original_fsync = __import__("os").fsync
        calls = 0

        def fail_directory_sync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic directory sync failure")
            return original_fsync(fd)

        with patch(
            "processing.transcript_normalization.os.fsync",
            side_effect=fail_directory_sync,
        ):
            with self.assertRaises(OSError):
                self.write_artifact()

        self.assertTrue(self.output.exists())

        payload = json.loads(self.output.read_text())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(payload["segments"]), 1)

        self.assertEqual(
            list(self.root.glob(".transcript-*.tmp")), []
        )

        with self.assertRaises(FileExistsError):
            self.write_artifact()


if __name__ == "__main__":
    unittest.main()
