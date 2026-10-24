import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from processing.alignment_cli import main


class AlignmentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.session = self.root / "session"
        self.audio = self.session / "audio"
        self.audio.mkdir(parents=True)
        self.manifest = self.session / "manifest.json"
        self.manifest.write_text('{"capture":"preserve"}\n')

    def tearDown(self):
        self.tmp.cleanup()

    def wav(self, name, seconds=2):
        path = self.audio / name
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(48000)
            out.writeframes(b"\x00\x00" * 48000 * seconds)
        return path

    def run_cli(self, *args):
        with patch("sys.argv", ["alignment_cli", str(self.session), *args]):
            main()

    def test_missing_track(self):
        self.wav("application.wav")
        with self.assertRaises(SystemExit) as caught:
            self.run_cli()
        self.assertNotEqual(caught.exception.code, 0)

    def test_malformed_wav(self):
        self.wav("application.wav")
        (self.audio / "microphone.wav").write_bytes(b"invalid wav")
        with self.assertRaises((SystemExit, wave.Error)):
            self.run_cli()

    def test_short_recording_returns_unknown(self):
        self.wav("application.wav")
        self.wav("microphone.wav")
        output = self.root / "report.json"
        self.run_cli("--output", str(output))
        report = json.loads(output.read_text())
        self.assertEqual(report["consensus"]["status"], "unknown")
        self.assertEqual(
            report["consensus"]["reason"], "insufficient_duration"
        )

    def test_manifest_overwrite_rejected(self):
        self.wav("application.wav")
        self.wav("microphone.wav")
        before = self.manifest.read_bytes()
        with self.assertRaises(SystemExit):
            self.run_cli("--output", str(self.manifest))
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_audio_overwrite_rejected(self):
        app = self.wav("application.wav")
        self.wav("microphone.wav")
        before = app.read_bytes()
        with self.assertRaises(SystemExit):
            self.run_cli("--output", str(app))
        self.assertEqual(app.read_bytes(), before)


    def test_truncated_wav_rejected(self):
        self.wav("application.wav")
        mic = self.wav("microphone.wav")

        original = mic.read_bytes()
        mic.write_bytes(original[:-48000])

        with self.assertRaises((SystemExit, ValueError, EOFError)):
            self.run_cli()

    def test_symlink_to_audio_rejected(self):
        app = self.wav("application.wav")
        self.wav("microphone.wav")

        alias = self.root / "audio-alias.wav"
        alias.symlink_to(app)

        original = app.read_bytes()

        with self.assertRaises(SystemExit):
            self.run_cli("--output", str(alias))

        self.assertEqual(app.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
