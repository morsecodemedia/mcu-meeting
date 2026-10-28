import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess

from processing.whisper_runner import run_whisper, whisper_version
from processing.whisper_profile import WhisperProfile


class WhisperRunnerTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.audio = self.root / "audio.wav"
        self.model = self.root / "model.bin"
        self.output = self.root / "whisper.json"

        with wave.open(str(self.audio), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\x00\x00" * 1600)

        self.model.write_bytes(b"synthetic-model")

    def tearDown(self):
        self.tmp.cleanup()

    def subprocess(self, command, **kwargs):
        if "--version" in command:
            return CompletedProcess(
                command, 0, "whisper.cpp version: 1.9.5", ""
            )

        prefix = Path(command[command.index("-of") + 1])
        output = Path(str(prefix) + ".json")
        output.write_text(json.dumps({
            "transcription": [
                {"text": "synthetic transcription"}
            ]
        }))

        return CompletedProcess(command, 0, "", "")

    def test_version(self):
        with patch(
            "processing.whisper_runner.subprocess.run",
            side_effect=self.subprocess,
        ):
            self.assertEqual(whisper_version(), "1.9.5")

    def test_success(self):
        with patch(
            "processing.whisper_runner.subprocess.run",
            side_effect=self.subprocess,
        ):
            result = run_whisper(
                self.audio, self.model, self.output
            )

        self.assertEqual(result["segments"], 1)
        self.assertTrue(self.output.is_file())

    def test_existing_output_refused(self):
        self.output.write_bytes(b"preserve")

        with self.assertRaises(FileExistsError):
            run_whisper(self.audio, self.model, self.output)

        self.assertEqual(self.output.read_bytes(), b"preserve")

    def test_invalid_audio(self):
        with wave.open(str(self.audio), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(8000)
            stream.writeframes(b"\x00\x00" * 800)

        with self.assertRaises(ValueError):
            run_whisper(self.audio, self.model, self.output)

    def test_missing_model(self):
        self.model.unlink()

        with self.assertRaises(FileNotFoundError):
            run_whisper(self.audio, self.model, self.output)

    def test_failed_subprocess(self):
        def failing(command, **kwargs):
            if "--version" in command:
                return CompletedProcess(
                    command, 0, "whisper.cpp version: 1.9.5", ""
                )
            return CompletedProcess(command, 1, "", "synthetic failure")

        with patch(
            "processing.whisper_runner.subprocess.run",
            side_effect=failing,
        ):
            with self.assertRaises(RuntimeError):
                run_whisper(self.audio, self.model, self.output)

        self.assertFalse(self.output.exists())

    def test_invalid_json(self):
        def invalid(command, **kwargs):
            if "--version" in command:
                return CompletedProcess(
                    command, 0, "whisper.cpp version: 1.9.5", ""
                )

            prefix = Path(command[command.index("-of") + 1])
            Path(str(prefix) + ".json").write_text("{invalid")
            return CompletedProcess(command, 0, "", "")

        with patch(
            "processing.whisper_runner.subprocess.run",
            side_effect=invalid,
        ):
            with self.assertRaises(json.JSONDecodeError):
                run_whisper(self.audio, self.model, self.output)

        self.assertFalse(self.output.exists())

    def test_profile_arguments(self):
        commands = []

        def capture(command, **kwargs):
            commands.append(command)
            return self.subprocess(command, **kwargs)

        with patch(
            "processing.whisper_runner.subprocess.run",
            side_effect=capture,
        ):
            run_whisper(
                self.audio,
                self.model,
                self.output,
                profile=WhisperProfile(beam_size=8),
            )

        execution = commands[-1]
        self.assertEqual(
            execution[execution.index("-bs") + 1], "8"
        )


if __name__ == "__main__":
    unittest.main()
