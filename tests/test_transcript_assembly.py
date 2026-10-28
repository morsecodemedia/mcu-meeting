import copy
import unittest

from processing.batch_planning import plan_batch
from processing.transcript_assembly import assemble_transcript


def segment(chunk_id, index, start, end, source="application_audio"):
    return {
        "id": f"{chunk_id}:{index}",
        "source": source,
        "speaker": "unresolved",
        "start_seconds": start,
        "end_seconds": end,
        "text": f"segment {index}",
    }


def normalized(chunk_id, segments, source="application_audio"):
    return {
        "schema_version": 1,
        "chunk_id": chunk_id,
        "source": source,
        "segments": segments,
    }


class TranscriptAssemblyTests(unittest.TestCase):

    def setUp(self):
        self.plan = plan_batch(
            {"application_audio": 20000000},
            chunk_seconds=10,
            overlap_seconds=2,
        )

        self.first = "application_audio:000000"
        self.second = "application_audio:000001"

    def test_owned_segments_included(self):
        data = {
            self.first: normalized(
                self.first,
                [segment(self.first, 0, 1, 5)],
            ),
            self.second: normalized(
                self.second,
                [segment(self.second, 0, 11, 15)],
            ),
        }

        result = assemble_transcript(self.plan, data)

        self.assertEqual(result["state"], "assembled")
        self.assertEqual(result["segment_count"], 2)

    def test_context_only_excluded(self):
        data = {
            self.first: normalized(
                self.first,
                [segment(self.first, 0, 10.2, 11.2)],
            ),
            self.second: normalized(self.second, []),
        }

        result = assemble_transcript(self.plan, data)

        self.assertEqual(result["segment_count"], 0)
        self.assertEqual(result["findings"][0]["type"], "context_only")

    def test_boundary_spanning_flagged(self):
        data = {
            self.first: normalized(
                self.first,
                [segment(self.first, 0, 9.2, 10.8)],
            ),
            self.second: normalized(self.second, []),
        }

        result = assemble_transcript(self.plan, data)

        self.assertEqual(
            result["state"], "requires_reconciliation"
        )
        self.assertEqual(result["unresolved_count"], 1)
        self.assertEqual(result["segment_count"], 0)

    def test_missing_chunk_rejected(self):
        with self.assertRaises(ValueError):
            assemble_transcript(
                self.plan,
                {self.first: normalized(self.first, [])},
            )

    def test_duplicate_segment_id_rejected(self):
        duplicate = segment(self.first, 0, 1, 2)

        data = {
            self.first: normalized(
                self.first,
                [duplicate, copy.deepcopy(duplicate)],
            ),
            self.second: normalized(self.second, []),
        }

        with self.assertRaises(ValueError):
            assemble_transcript(self.plan, data)

    def test_input_not_mutated(self):
        data = {
            self.first: normalized(
                self.first,
                [segment(self.first, 0, 1, 5)],
            ),
            self.second: normalized(self.second, []),
        }

        original = copy.deepcopy(data)

        assemble_transcript(self.plan, data)

        self.assertEqual(data, original)

    def test_cross_source_ordering(self):
        plan = plan_batch(
            {
                "application_audio": 10000000,
                "microphone_audio": 10000000,
            },
            chunk_seconds=10,
            overlap_seconds=0,
        )

        app = "application_audio:000000"
        mic = "microphone_audio:000000"

        data = {
            mic: normalized(
                mic,
                [segment(mic, 0, 1, 2, "microphone_audio")],
                "microphone_audio",
            ),
            app: normalized(
                app,
                [segment(app, 0, 1, 2)],
            ),
        }

        result = assemble_transcript(plan, data)

        self.assertEqual(
            [item["source"] for item in result["segments"]],
            ["application_audio", "microphone_audio"],
        )


    def test_exact_ownership_boundary(self):
        data = {
            self.first: normalized(
                self.first,
                [segment(self.first, 0, 9, 10)],
            ),
            self.second: normalized(
                self.second,
                [segment(self.second, 0, 10, 11)],
            ),
        }

        result = assemble_transcript(self.plan, data)

        self.assertEqual(result["state"], "assembled")
        self.assertEqual(result["segment_count"], 2)
        self.assertEqual(result["unresolved_count"], 0)

    def test_spanning_with_next_chunk_evidence(self):
        data = {
            self.first: normalized(
                self.first,
                [segment(self.first, 0, 9.2, 10.8)],
            ),
            self.second: normalized(
                self.second,
                [segment(self.second, 0, 10, 11)],
            ),
        }

        result = assemble_transcript(self.plan, data)

        self.assertEqual(
            result["state"], "requires_reconciliation"
        )
        self.assertEqual(result["unresolved_count"], 1)
        self.assertEqual(result["segment_count"], 1)

        self.assertEqual(
            result["findings"][0]["type"],
            "boundary_spanning",
        )

    def test_context_only_with_next_chunk_evidence(self):
        data = {
            self.first: normalized(
                self.first,
                [segment(self.first, 0, 10.2, 11.2)],
            ),
            self.second: normalized(
                self.second,
                [segment(self.second, 0, 10.2, 11.2)],
            ),
        }

        result = assemble_transcript(self.plan, data)

        self.assertEqual(result["state"], "assembled")
        self.assertEqual(result["segment_count"], 1)
        self.assertEqual(
            result["findings"][0]["type"],
            "context_only",
        )

    def test_invalid_segment_before_read_start(self):
        data = {
            self.first: normalized(
                self.first,
                [segment(self.first, 0, -0.5, 1)],
            ),
            self.second: normalized(self.second, []),
        }

        result = assemble_transcript(self.plan, data)

        self.assertEqual(
            result["state"], "requires_reconciliation"
        )
        self.assertEqual(result["segment_count"], 0)
        self.assertEqual(result["unresolved_count"], 1)
        self.assertEqual(
            result["findings"][0]["type"],
            "timing_out_of_bounds",
        )

    def test_invalid_segment_after_read_end(self):
        data = {
            self.first: normalized(
                self.first,
                [segment(self.first, 0, 11, 12.5)],
            ),
            self.second: normalized(self.second, []),
        }

        result = assemble_transcript(self.plan, data)

        self.assertEqual(
            result["state"], "requires_reconciliation"
        )
        self.assertEqual(result["segment_count"], 0)
        self.assertEqual(result["unresolved_count"], 1)
        self.assertEqual(
            result["findings"][0]["type"],
            "timing_out_of_bounds",
        )

    def test_cross_source_overlapping_speech_preserved(self):
        plan = plan_batch(
            {
                "application_audio": 10000000,
                "microphone_audio": 10000000,
            },
            chunk_seconds=10,
            overlap_seconds=0,
        )

        app = "application_audio:000000"
        mic = "microphone_audio:000000"

        data = {
            app: normalized(
                app,
                [segment(app, 0, 2, 5)],
            ),
            mic: normalized(
                mic,
                [segment(mic, 0, 2, 5, "microphone_audio")],
                "microphone_audio",
            ),
        }

        result = assemble_transcript(plan, data)

        self.assertEqual(result["segment_count"], 2)
        self.assertEqual(
            {item["source"] for item in result["segments"]},
            {"application_audio", "microphone_audio"},
        )


    def test_timing_overrun_preserved_as_finding(self):
        data = {
            self.first: normalized(self.first, []),
            self.second: normalized(
                self.second,
                [segment(self.second, 0, 19.58, 20.42)],
            ),
        }

        result = assemble_transcript(self.plan, data)

        self.assertEqual(
            result["state"], "requires_reconciliation"
        )
        self.assertEqual(result["segment_count"], 0)
        self.assertEqual(result["unresolved_count"], 1)
        self.assertEqual(
            result["findings"][0]["type"],
            "timing_out_of_bounds",
        )
        self.assertEqual(
            result["findings"][0]["segment"]["end_seconds"],
            20.42,
        )

    def test_timing_prestart_preserved_as_finding(self):
        data = {
            self.first: normalized(
                self.first,
                [segment(self.first, 0, -0.42, 1)],
            ),
            self.second: normalized(self.second, []),
        }

        result = assemble_transcript(self.plan, data)

        self.assertEqual(
            result["state"], "requires_reconciliation"
        )
        self.assertEqual(result["unresolved_count"], 1)
        self.assertEqual(
            result["findings"][0]["type"],
            "timing_out_of_bounds",
        )


if __name__ == "__main__":
    unittest.main()
