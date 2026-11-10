"""Integration tests for selective session transcription execution."""

import hashlib
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from processing.checkpoint_store import checkpoint_store
from processing.processing_plan import plan_session_processing
from processing.session_processing_coordinator import execute_session_chunks
from session import manager


class SessionProcessingCoordinatorTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.sid = manager.create(
            self.root, "com.example.session-processing"
        )["session_id"]

        self.folder = self.root / self.sid

        self.model = self.root / "model.bin"
        self.model.write_bytes(b"synthetic-model")

        audio = self.folder / "audio/application.wav"

        with wave.open(str(audio), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(48000)
            stream.writeframes(bytes(96000))

        manifest = manager.load(self.root, self.sid)
        manifest["artifacts"].append({
            "kind": "application_audio",
            "path": "audio/application.wav",
            "sha256": hashlib.sha256(
                audio.read_bytes()
            ).hexdigest(),
        })

        manager._write_atomic(
            self.folder / "manifest.json",
            manifest,
        )

        manager.transition(self.root, self.sid, "recording")
        manager.transition(self.root, self.sid, "completed")

    def tearDown(self):
        self.tmp.cleanup()

    def fake_execute(
        self,
        store,
        sessions_root,
        session_id,
        chunk,
        model_path,
        **kwargs,
    ):
        from processing.chunk_execution_plan import plan_chunk_execution
        from processing.chunk_coordinator import _sha256
        from processing.whisper_profile import WhisperProfile

        audio = self.folder / "audio/application.wav"

        execution = plan_chunk_execution(
            chunk,
            audio_sha256=hashlib.sha256(
                audio.read_bytes()
            ).hexdigest(),
            model_sha256=_sha256(model_path),
            ffmpeg_version="9.0.1",
            whisper_version="1.9.5",
            profile=kwargs.get("profile") or WhisperProfile(),
        )

        fingerprint = execution["fingerprint"]
        chunk_id = execution["chunk_id"]

        store.create(fingerprint, chunk_id)
        store.transition(fingerprint, chunk_id, "running")

        directory = (
            self.folder
            / Path(execution["artifacts"]["checkpoint"]).parent
        )

        whisper = directory / "whisper.json"
        normalized = directory / "normalized.json"

        whisper.write_text(json.dumps({"transcription": []}))
        normalized.write_text(json.dumps({
            "schema_version": 1,
            "chunk_id": chunk_id,
            "source": "application_audio",
            "segments": [],
        }))

        artifacts = [
            {
                "kind": kind,
                "path": file.name,
                "sha256": hashlib.sha256(
                    file.read_bytes()
                ).hexdigest(),
            }
            for kind, file in (
                ("whisper_json", whisper),
                ("normalized_json", normalized),
            )
        ]

        store.transition(
            fingerprint,
            chunk_id,
            "completed",
            artifacts=artifacts,
        )

        return {
            "chunk_id": chunk_id,
            "fingerprint": fingerprint,
            "state": "completed",
        }

    def run_coordinator(self, executor):
        with (
            patch(
                "processing.chunk_coordinator._ffmpeg_version",
                return_value="9.0.1",
            ),
            patch(
                "processing.whisper_runner.whisper_version",
                return_value="1.9.5",
            ),
            patch(
                "processing.session_processing_coordinator."
                "_execute_chunk_with_store",
                side_effect=executor,
            ) as execute,
        ):
            result = execute_session_chunks(
                self.root,
                self.sid,
                self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

        return result, execute

    def test_fresh_session_executes_missing_chunk(self):
        result, execute = self.run_coordinator(self.fake_execute)

        self.assertEqual(result["executed_count"], 1)
        self.assertEqual(result["reused_count"], 0)
        self.assertEqual(len(result["fingerprints"]), 1)

        execute.assert_called_once()

    def test_second_run_reuses_verified_checkpoint(self):
        self.run_coordinator(self.fake_execute)

        result, execute = self.run_coordinator(
            AssertionError("Executor should not run")
        )

        self.assertEqual(result["executed_count"], 0)
        self.assertEqual(result["reused_count"], 1)
        execute.assert_not_called()

    def test_partial_batch_executes_only_missing_chunks(self):
        audio = self.folder / "audio/application.wav"

        import wave

        with wave.open(str(audio), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(48000)
            stream.writeframes(bytes(96000 * 3))

        manifest = manager.load(self.root, self.sid)
        manifest["artifacts"][0]["sha256"] = hashlib.sha256(
            audio.read_bytes()
        ).hexdigest()

        manager._write_atomic(
            self.folder / "manifest.json",
            manifest,
        )

        # Create only the first checkpoint using the existing
        # synthetic executor and the exact planned chunk.
        with (
            patch(
                "processing.chunk_coordinator._ffmpeg_version",
                return_value="9.0.1",
            ),
            patch(
                "processing.whisper_runner.whisper_version",
                return_value="1.9.5",
            ),
        ):
            plan = plan_session_processing(
                self.root,
                self.sid,
                self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

        self.assertEqual(len(plan["entries"]), 3)

        first_chunk = plan["batch_plan"]["sources"][0]["chunks"][0]

        with checkpoint_store(self.root, self.sid) as store:
            self.fake_execute(
                store,
                self.root,
                self.sid,
                first_chunk,
                self.model,
            )

        result, execute = self.run_coordinator(self.fake_execute)

        self.assertEqual(result["executed_count"], 2)
        self.assertEqual(result["reused_count"], 1)
        self.assertEqual(len(result["fingerprints"]), 3)

        self.assertEqual(
            result["reused_chunks"],
            ["application_audio:000000"],
        )
        self.assertEqual(
            result["executed_chunks"],
            [
                "application_audio:000001",
                "application_audio:000002",
            ],
        )

        self.assertEqual(execute.call_count, 2)

        with checkpoint_store(self.root, self.sid) as store:
            for chunk_id, fingerprint in result["fingerprints"].items():
                self.assertTrue(store.verify(fingerprint, chunk_id))

        repeated, execute_again = self.run_coordinator(
            AssertionError("No new transcription expected")
        )

        self.assertEqual(repeated["executed_count"], 0)
        self.assertEqual(repeated["reused_count"], 3)
        execute_again.assert_not_called()

    def test_process_session_publishes_then_reuses_assembly(self):
        from processing import session_processing_coordinator as module

        def run(*, first):
            with (
                patch(
                    "processing.chunk_coordinator._ffmpeg_version",
                    return_value="9.0.1",
                ),
                patch(
                    "processing.whisper_runner.whisper_version",
                    return_value="1.9.5",
                ),
                patch.object(
                    module,
                    "_execute_chunk_with_store",
                    side_effect=(
                        self.fake_execute
                        if first
                        else AssertionError(
                            "Unexpected transcription execution"
                        )
                    ),
                ) as executor,
                patch(
                    "processing.assembly_coordinator.publish_assembly",
                    wraps=module_publish_assembly,
                ) as publisher,
            ):
                result = module.process_session(
                    self.root,
                    self.sid,
                    self.model,
                    chunk_seconds=1,
                    overlap_seconds=0,
                )

            return result, executor, publisher

        from processing.assembly_coordinator import (
            publish_assembly as module_publish_assembly,
        )

        first, first_executor, first_publisher = run(first=True)

        self.assertEqual(first["chunks"]["executed_count"], 1)
        self.assertEqual(first["assembly"]["publication"], "created")
        first_executor.assert_called_once()
        first_publisher.assert_called_once()

        second, second_executor, second_publisher = run(first=False)

        self.assertEqual(second["chunks"]["executed_count"], 0)
        self.assertEqual(second["chunks"]["reused_count"], 1)
        self.assertEqual(second["assembly"]["publication"], "reused")

        second_executor.assert_not_called()
        second_publisher.assert_not_called()

        self.assertEqual(
            first["assembly"]["fingerprint"],
            second["assembly"]["fingerprint"],
        )
        self.assertEqual(
            first["assembly"]["path"],
            second["assembly"]["path"],
        )

    def test_process_session_rejects_staging_before_execution(self):
        from processing import session_processing_coordinator as module

        staging = (
            self.folder
            / "processing/assembly/.assembly-staging-interrupted"
        )
        staging.mkdir(parents=True)

        with (
            patch(
                "processing.chunk_coordinator._ffmpeg_version",
                return_value="9.0.1",
            ),
            patch(
                "processing.whisper_runner.whisper_version",
                return_value="1.9.5",
            ),
            patch.object(
                module,
                "_execute_chunk_with_store",
                side_effect=AssertionError(
                    "Execution must not precede assembly preflight"
                ),
            ) as executor,
        ):
            with self.assertRaisesRegex(
                ValueError, "Incomplete assembly staging evidence"
            ):
                module.process_session(
                    self.root,
                    self.sid,
                    self.model,
                    chunk_seconds=1,
                    overlap_seconds=0,
                )

        executor.assert_not_called()
        self.assertTrue(staging.is_dir())

    def test_process_session_rejects_unknown_assembly_entry(self):
        from processing import session_processing_coordinator as module

        assembly_root = self.folder / "processing/assembly"
        assembly_root.mkdir(parents=True)
        unknown = assembly_root / "unexpected.txt"
        unknown.write_text("synthetic unexpected evidence")

        with patch.object(
            module,
            "_execute_session_chunks_with_store",
            side_effect=AssertionError(
                "Chunk execution must not begin"
            ),
        ) as executor:
            with self.assertRaisesRegex(
                ValueError, "Unknown assembly entry"
            ):
                module.process_session(
                    self.root,
                    self.sid,
                    self.model,
                    chunk_seconds=1,
                    overlap_seconds=0,
                )

        executor.assert_not_called()
        self.assertTrue(unknown.is_file())

    def test_process_session_rejects_corrupt_historical_assembly(self):
        from processing import session_processing_coordinator as module

        assembly_root = self.folder / "processing/assembly"
        directory = assembly_root / ("a" * 64)
        directory.mkdir(parents=True)

        (directory / "provenance.json").write_text(
            '{"invalid": true}'
        )
        (directory / "transcript.json").write_text(
            '{"invalid": true}'
        )

        with patch.object(
            module,
            "_execute_session_chunks_with_store",
            side_effect=AssertionError(
                "Chunk execution must not begin"
            ),
        ) as executor:
            with self.assertRaises(ValueError):
                module.process_session(
                    self.root,
                    self.sid,
                    self.model,
                    chunk_seconds=1,
                    overlap_seconds=0,
                )

        executor.assert_not_called()
        self.assertTrue(directory.is_dir())

    def test_blocked_checkpoint_prevents_execution(self):
        from processing.processing_plan import plan_session_processing

        with (
            patch(
                "processing.chunk_coordinator._ffmpeg_version",
                return_value="9.0.1",
            ),
            patch(
                "processing.whisper_runner.whisper_version",
                return_value="1.9.5",
            ),
        ):
            plan = plan_session_processing(
                self.root,
                self.sid,
                self.model,
                chunk_seconds=1,
                overlap_seconds=0,
            )

        entry = plan["entries"][0]

        with checkpoint_store(self.root, self.sid) as store:
            store.create(entry["fingerprint"], entry["chunk_id"])

        with self.assertRaises(ValueError):
            self.run_coordinator(
                AssertionError("Executor should not run")
            )


if __name__ == "__main__":
    unittest.main()
