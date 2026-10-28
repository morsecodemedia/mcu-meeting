import math
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from processing.audio_extraction import extract_chunk
from processing.chunk_planning import plan_chunks


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class AudioExtractionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.wav"
        self.output = self.root / "chunk.wav"

        with wave.open(str(self.source), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(48000)

            frames = bytearray()

            for index in range(48000):
                sample = int(
                    5000 * math.sin(2 * math.pi * 440 * index / 48000)
                )
                frames.extend(struct.pack("<h", sample))

            stream.writeframes(frames)

        self.chunk = plan_chunks(
            1, "application_audio",
            chunk_seconds=1,
            overlap_seconds=0,
        )[0]

    def tearDown(self):
        self.tmp.cleanup()

    def test_successful_extraction(self):
        result = extract_chunk(
            self.source, self.output, self.chunk
        )

        self.assertTrue(self.output.is_file())
        self.assertEqual(result["output_sample_rate"], 16000)
        self.assertEqual(result["output_frames"], 16000)
        self.assertEqual(result["actual_duration_seconds"], 1.0)

    def test_existing_output_refused(self):
        self.output.write_bytes(b"preserve")

        with self.assertRaises(FileExistsError):
            extract_chunk(self.source, self.output, self.chunk)

        self.assertEqual(self.output.read_bytes(), b"preserve")

    def test_source_preserved(self):
        original = self.source.read_bytes()

        extract_chunk(self.source, self.output, self.chunk)

        self.assertEqual(self.source.read_bytes(), original)

    def test_symlink_output_rejected(self):
        protected = self.root / "protected.wav"
        protected.write_bytes(b"preserve")
        self.output.symlink_to(protected)

        with self.assertRaises(FileExistsError):
            extract_chunk(self.source, self.output, self.chunk)

        self.assertEqual(protected.read_bytes(), b"preserve")

    def test_out_of_bounds_rejected(self):
        chunk = dict(self.chunk)
        chunk["read_end_seconds"] = 2

        with self.assertRaises(ValueError):
            extract_chunk(self.source, self.output, chunk)

    def test_missing_ffmpeg(self):
        with self.assertRaises(FileNotFoundError):
            extract_chunk(
                self.source,
                self.output,
                self.chunk,
                ffmpeg_binary="missing-ffmpeg-executable",
            )

        self.assertFalse(self.output.exists())

    def test_ffmpeg_failure_cleanup(self):
        with patch(
            "processing.audio_extraction.subprocess.run",
            side_effect=RuntimeError("synthetic failure"),
        ):
            with self.assertRaises(RuntimeError):
                extract_chunk(
                    self.source, self.output, self.chunk
                )

        self.assertFalse(self.output.exists())
        self.assertEqual(
            list(self.root.glob(".audio-chunk-*.wav")), []
        )


    def test_fractional_boundaries(self):
        cases = [
            (0.001, 0.501),
            (0.000021, 0.999979),
            (0.123456, 0.876543),
        ]

        for index, (start, end) in enumerate(cases):
            with self.subTest(start=start, end=end):
                chunk = dict(self.chunk)
                chunk["owned_start_seconds"] = start
                chunk["read_start_seconds"] = start
                chunk["owned_end_seconds"] = end
                chunk["read_end_seconds"] = end

                output = self.root / f"fractional-{index}.wav"

                result = extract_chunk(
                    self.source, output, chunk
                )

                self.assertTrue(output.is_file())
                self.assertGreater(result["output_frames"], 0)

    def test_short_final_chunk(self):
        chunk = dict(self.chunk)
        chunk["owned_start_seconds"] = 0.9
        chunk["read_start_seconds"] = 0.9
        chunk["owned_end_seconds"] = 1.0
        chunk["read_end_seconds"] = 1.0

        result = extract_chunk(
            self.source, self.output, chunk
        )

        self.assertEqual(result["output_frames"], 1600)


if __name__ == "__main__":
    unittest.main()
