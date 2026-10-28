import unittest

from processing.transcript_normalization import normalize


def payload(segments):
    return {
        "model": {"type": "small"},
        "params": {"language": "en"},
        "transcription": segments,
    }


def segment(start, end, text="Hello"):
    return {
        "offsets": {"from": start, "to": end},
        "text": text,
    }


class TranscriptNormalizationTests(unittest.TestCase):

    def test_meeting_relative_timestamps(self):
        result = normalize(
            payload([segment(2860, 5220)]),
            source="microphone_audio",
            excerpt_start_seconds=300,
        )
        item = result["segments"][0]
        self.assertEqual(item["start_seconds"], 302.86)
        self.assertEqual(item["end_seconds"], 305.22)

    def test_source_and_provenance(self):
        result = normalize(
            payload([segment(0, 1000)]),
            source="application_audio",
            model_sha256="abc123",
        )
        self.assertEqual(result["source"], "application_audio")
        self.assertEqual(result["model"]["sha256"], "abc123")
        self.assertEqual(result["segments"][0]["speaker"], "unresolved")

    def test_overlapping_segments_preserved(self):
        result = normalize(
            payload([
                segment(0, 3000, "First"),
                segment(2000, 4000, "Second"),
            ]),
            source="microphone_audio",
        )
        self.assertEqual(len(result["segments"]), 2)

    def test_empty_transcription(self):
        result = normalize(
            payload([]),
            source="application_audio",
        )
        self.assertEqual(result["segments"], [])

    def test_invalid_timing_rejected(self):
        for start, end in [
            (1000, 1000),
            (2000, 1000),
            (-1, 1000),
            (float("nan"), 1000),
        ]:
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError):
                    normalize(
                        payload([segment(start, end)]),
                        source="application_audio",
                    )

    def test_invalid_source_rejected(self):
        with self.assertRaises(ValueError):
            normalize(payload([]), source="unknown")

    def test_missing_transcription_rejected(self):
        with self.assertRaises(ValueError):
            normalize({}, source="application_audio")


    def test_chunk_aware_segment_ids(self):
        first = normalize(
            payload([segment(0, 1000)]),
            source="application_audio",
            chunk_id="application_audio:000000",
        )

        second = normalize(
            payload([segment(0, 1000)]),
            source="application_audio",
            chunk_id="application_audio:000001",
        )

        self.assertNotEqual(
            first["segments"][0]["id"],
            second["segments"][0]["id"],
        )

    def test_chunk_meeting_relative_timestamps(self):
        result = normalize(
            payload([segment(2860, 5220)]),
            source="microphone_audio",
            chunk_id="microphone_audio:000001",
            excerpt_start_seconds=300,
        )

        self.assertEqual(
            result["segments"][0]["start_seconds"], 302.86
        )

    def test_chunk_source_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            normalize(
                payload([]),
                source="application_audio",
                chunk_id="microphone_audio:000000",
            )

    def test_legacy_segment_ids_preserved(self):
        result = normalize(
            payload([segment(0, 1000)]),
            source="application_audio",
        )

        self.assertEqual(
            result["segments"][0]["id"],
            "application_audio:0",
        )


if __name__ == "__main__":
    unittest.main()
