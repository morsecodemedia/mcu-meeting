"""Regression tests for read-only assembly discovery."""

import copy
import unittest
from pathlib import Path

from processing.assembly_discovery import (
    _identity_digest,
    _validate_canonical_identity,
)
from processing.assembly_identity import assembly_identity
from processing.batch_planning import plan_batch


class AssemblyDiscoveryIdentityTests(unittest.TestCase):

    def setUp(self):
        plan = plan_batch(
            {
                "application_audio": 20000000,
                "microphone_audio": 10000000,
            },
            chunk_seconds=10,
            overlap_seconds=2,
        )

        contributions = {}

        for source in plan["sources"]:
            for chunk in source["chunks"]:
                chunk_id = chunk["chunk_id"]

                contributions[chunk_id] = {
                    "fingerprint": "a" * 64,
                    "normalized_sha256": "b" * 64,
                }

        self.identity = assembly_identity(plan, contributions)

    def validate(self, identity=None):
        return _validate_canonical_identity(
            self.identity if identity is None else identity
        )

    def test_valid_identity(self):
        self.assertEqual(
            self.validate(),
            self.identity,
        )

        self.assertEqual(
            len(_identity_digest(self.identity)),
            64,
        )

    def test_input_not_mutated(self):
        original = copy.deepcopy(self.identity)

        self.validate()

        self.assertEqual(self.identity, original)

    def test_algorithm_v1_supported(self):
        identity = copy.deepcopy(self.identity)
        identity["assembly_algorithm_version"] = 1

        self.validate(identity)

    def test_unsupported_algorithm_rejected(self):
        identity = copy.deepcopy(self.identity)
        identity["assembly_algorithm_version"] = 999

        with self.assertRaises(ValueError):
            self.validate(identity)

    def test_unexpected_identity_field_rejected(self):
        identity = copy.deepcopy(self.identity)
        identity["unexpected"] = True

        with self.assertRaises(ValueError):
            self.validate(identity)

    def test_reordered_sources_rejected(self):
        identity = copy.deepcopy(self.identity)
        identity["sources"].reverse()

        with self.assertRaises(ValueError):
            self.validate(identity)

    def test_duplicate_source_rejected(self):
        identity = copy.deepcopy(self.identity)
        identity["sources"].append(
            copy.deepcopy(identity["sources"][0])
        )

        with self.assertRaises(ValueError):
            self.validate(identity)

    def test_chunk_index_gap_rejected(self):
        identity = copy.deepcopy(self.identity)
        chunk = identity["sources"][0]["chunks"][1]

        chunk["index"] = 3
        chunk["chunk_id"] = "application_audio:000003"

        with self.assertRaises(ValueError):
            self.validate(identity)

    def test_ownership_gap_rejected(self):
        identity = copy.deepcopy(self.identity)
        chunk = identity["sources"][0]["chunks"][1]

        chunk["owned_start_us"] += 1000000
        chunk["read_start_us"] += 1000000

        with self.assertRaises(ValueError):
            self.validate(identity)

    def test_noninteger_boundary_rejected(self):
        identity = copy.deepcopy(self.identity)
        identity["sources"][0]["chunks"][0][
            "owned_end_us"
        ] = 10000000.0

        with self.assertRaises(ValueError):
            self.validate(identity)

    def test_contribution_order_rejected(self):
        identity = copy.deepcopy(self.identity)
        identity["contributions"].reverse()

        with self.assertRaises(ValueError):
            self.validate(identity)

    def test_missing_contribution_rejected(self):
        identity = copy.deepcopy(self.identity)
        identity["contributions"].pop()

        with self.assertRaises(ValueError):
            self.validate(identity)

    def test_invalid_digest_rejected(self):
        identity = copy.deepcopy(self.identity)
        identity["contributions"][0][
            "normalized_sha256"
        ] = "invalid"

        with self.assertRaises(ValueError):
            self.validate(identity)

    def test_unexpected_chunk_field_rejected(self):
        identity = copy.deepcopy(self.identity)
        identity["sources"][0]["chunks"][0][
            "unexpected"
        ] = True

        with self.assertRaises(ValueError):
            self.validate(identity)



class AssemblyDiscoveryFilesystemTests(unittest.TestCase):
    """Filesystem classifications using isolated synthetic sessions."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from session import manager

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.sid = manager.create(
            self.root, "com.example.assembly-discovery"
        )["session_id"]

        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

        self.folder = self.root / self.sid
        self.base = self.folder / "processing" / "assembly"

    def tearDown(self):
        self.tmp.cleanup()

    def discover(self):
        from processing.assembly_discovery import discover_assemblies
        return discover_assemblies(self.root, self.sid)

    def classification(self):
        records = self.discover()["assemblies"]
        self.assertEqual(len(records), 1)
        return records[0]["classification"]

    def test_empty_session(self):
        report = self.discover()

        self.assertEqual(report["assemblies"], [])
        self.assertFalse(self.base.exists())
        self.assertFalse(
            (self.folder / ".processing.lock").exists()
        )

    def test_incomplete_staging(self):
        self.base.mkdir(parents=True)
        (self.base / ".assembly-staging-test").mkdir()

        self.assertEqual(
            self.classification(),
            "incomplete_staging",
        )

    def test_unknown_file(self):
        self.base.mkdir(parents=True)
        (self.base / "unexpected.txt").write_text("unknown")

        self.assertEqual(
            self.classification(),
            "unknown_entry",
        )

    def test_symlinked_assembly_entry(self):
        self.base.mkdir(parents=True)

        target = self.folder / "external"
        target.mkdir()

        (self.base / ("a" * 64)).symlink_to(
            target, target_is_directory=True
        )

        self.assertEqual(
            self.classification(),
            "unknown_entry",
        )

    def test_symlinked_assembly_root(self):
        processing = self.folder / "processing"
        processing.mkdir()

        target = self.folder / "external-assembly"
        target.mkdir()

        self.base.symlink_to(
            target, target_is_directory=True
        )

        with self.assertRaises(ValueError):
            self.discover()

    def test_symlinked_processing_ancestor(self):
        target = self.folder / "external-processing"
        (target / "assembly").mkdir(parents=True)

        (self.folder / "processing").symlink_to(
            target, target_is_directory=True
        )

        # This is a security regression test. The scanner must
        # reject the symlinked ancestor before traversing it.
        with self.assertRaises(ValueError):
            self.discover()

    def test_read_only_staging(self):
        self.base.mkdir(parents=True)

        staging = self.base / ".assembly-staging-test"
        staging.mkdir()

        evidence = staging / "partial.json"
        evidence.write_bytes(b"partial evidence")

        manifest = self.folder / "manifest.json"

        before_manifest = manifest.read_bytes()
        before_evidence = evidence.read_bytes()

        self.discover()

        self.assertEqual(
            manifest.read_bytes(), before_manifest
        )
        self.assertEqual(
            evidence.read_bytes(), before_evidence
        )
        self.assertFalse(
            (self.folder / ".processing.lock").exists()
        )



@unittest.skipUnless(
    __import__("sys").platform == "darwin",
    "macOS immutable assembly publication",
)
class AssemblyDiscoveryPublicationTests(unittest.TestCase):
    """Verify real publications using isolated synthetic checkpoints."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from session import manager

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.sid = manager.create(
            self.root, "com.example.assembly-recovery"
        )["session_id"]

        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

        self.folder = self.root / self.sid
        self.chunk_id = "application_audio:000000"
        self.execution_fingerprint = "a" * 64

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self, *, unresolved=False):
        import hashlib
        import json

        from processing.assembly_coordinator import assemble_session
        from processing.batch_planning import plan_batch
        from processing.checkpoint_store import checkpoint_store

        segments = []

        if unresolved:
            segments.append({
                "id": self.chunk_id + ":0",
                "source": "application_audio",
                "speaker": "unresolved",
                "start_seconds": 9.5,
                "end_seconds": 10.42,
                "text": "Synthetic endpoint overrun",
            })

        with checkpoint_store(self.root, self.sid) as store:
            store.create(
                self.execution_fingerprint,
                self.chunk_id,
            )

            store.transition(
                self.execution_fingerprint,
                self.chunk_id,
                "running",
            )

            directory = (
                self.folder
                / "processing/transcription/application_audio/000000"
                / self.execution_fingerprint
            )

            whisper = directory / "whisper.json"
            normalized = directory / "normalized.json"

            whisper.write_text(json.dumps({
                "transcription": [],
            }))

            normalized.write_text(json.dumps({
                "schema_version": 1,
                "chunk_id": self.chunk_id,
                "source": "application_audio",
                "segments": segments,
            }))

            artifacts = [
                {
                    "kind": kind,
                    "path": path.name,
                    "sha256": hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest(),
                }
                for kind, path in (
                    ("whisper_json", whisper),
                    ("normalized_json", normalized),
                )
            ]

            store.transition(
                self.execution_fingerprint,
                self.chunk_id,
                "completed",
                artifacts=artifacts,
            )

        plan = plan_batch(
            {"application_audio": 10000000},
            chunk_seconds=10,
            overlap_seconds=0,
        )

        return assemble_session(
            self.root,
            self.sid,
            plan,
            {self.chunk_id: self.execution_fingerprint},
        )

    def discover_record(self):
        from processing.assembly_discovery import discover_assemblies

        report = discover_assemblies(self.root, self.sid)

        self.assertEqual(len(report["assemblies"]), 1)
        return report["assemblies"][0]

    def test_valid_publication(self):
        self.publish()

        record = self.discover_record()

        self.assertEqual(
            record["classification"], "verified_complete"
        )
        self.assertEqual(
            record["verification_level"], "source_verified"
        )
        self.assertEqual(record["transcript_state"], "assembled")

    def test_unresolved_publication(self):
        self.publish(unresolved=True)

        record = self.discover_record()

        self.assertEqual(
            record["classification"], "verified_complete"
        )
        self.assertEqual(
            record["transcript_state"], "requires_reconciliation"
        )
        self.assertEqual(record["unresolved_count"], 1)
        self.assertEqual(
            record["action"], "reconciliation_required"
        )

    def test_corrupt_transcript_json(self):
        result = self.publish()

        (Path(result["path"]) / "transcript.json").write_text(
            "{invalid json"
        )

        self.assertEqual(
            self.discover_record()["classification"],
            "published_invalid",
        )

    def test_missing_provenance(self):
        result = self.publish()

        (Path(result["path"]) / "provenance.json").unlink()

        self.assertEqual(
            self.discover_record()["classification"],
            "published_invalid",
        )

    def test_tampered_provenance_fingerprint(self):
        import json

        result = self.publish()
        path = Path(result["path"]) / "provenance.json"

        provenance = json.loads(path.read_text())
        provenance["assembly_fingerprint"] = "b" * 64
        path.write_text(json.dumps(provenance))

        self.assertEqual(
            self.discover_record()["classification"],
            "published_invalid",
        )

    def test_corrupted_checkpoint_artifact(self):
        result = self.publish()

        normalized = (
            self.folder
            / "processing/transcription/application_audio/000000"
            / self.execution_fingerprint
            / "normalized.json"
        )

        normalized.write_text('{"corrupted":true}')

        self.assertEqual(
            self.discover_record()["classification"],
            "published_invalid",
        )

    def test_symlinked_transcript(self):
        result = self.publish()
        directory = Path(result["path"])

        transcript = directory / "transcript.json"
        target = self.folder / "external-transcript.json"

        transcript.rename(target)
        transcript.symlink_to(target)

        self.assertEqual(
            self.discover_record()["classification"],
            "published_invalid",
        )

    def test_read_only_publication(self):
        result = self.publish()
        directory = Path(result["path"])

        manifest = self.folder / "manifest.json"
        checkpoint = (
            self.folder
            / "processing/transcription/application_audio/000000"
            / self.execution_fingerprint
            / "checkpoint.json"
        )

        paths = [
            manifest,
            checkpoint,
            directory / "transcript.json",
            directory / "provenance.json",
        ]

        before = {
            str(path): path.read_bytes()
            for path in paths
        }

        self.discover_record()

        after = {
            str(path): path.read_bytes()
            for path in paths
        }

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
