import copy
import unittest

from processing.assembly_identity import (
    assembly_fingerprint,
    assembly_identity,
)
from processing.batch_planning import plan_batch


class AssemblyIdentityTests(unittest.TestCase):

    def setUp(self):
        self.plan = plan_batch(
            {"application_audio": 20000000},
            chunk_seconds=10,
            overlap_seconds=0,
        )

        self.contributions = {
            "application_audio:000000": {
                "fingerprint": "a" * 64,
                "normalized_sha256": "b" * 64,
            },
            "application_audio:000001": {
                "fingerprint": "c" * 64,
                "normalized_sha256": "d" * 64,
            },
        }

    def test_deterministic(self):
        self.assertEqual(
            assembly_fingerprint(self.plan, self.contributions),
            assembly_fingerprint(self.plan, self.contributions),
        )

    def test_digest_shape(self):
        self.assertEqual(
            len(assembly_fingerprint(
                self.plan, self.contributions
            )),
            64,
        )

    def test_contribution_order_independent(self):
        reversed_contributions = dict(
            reversed(list(self.contributions.items()))
        )

        self.assertEqual(
            assembly_fingerprint(self.plan, self.contributions),
            assembly_fingerprint(self.plan, reversed_contributions),
        )

    def test_execution_fingerprint_change(self):
        changed = copy.deepcopy(self.contributions)
        changed["application_audio:000000"]["fingerprint"] = "e" * 64

        self.assertNotEqual(
            assembly_fingerprint(self.plan, self.contributions),
            assembly_fingerprint(self.plan, changed),
        )

    def test_normalized_checksum_change(self):
        changed = copy.deepcopy(self.contributions)
        changed["application_audio:000001"]["normalized_sha256"] = "e" * 64

        self.assertNotEqual(
            assembly_fingerprint(self.plan, self.contributions),
            assembly_fingerprint(self.plan, changed),
        )

    def test_chunk_boundary_change(self):
        changed_plan = plan_batch(
            {"application_audio": 20000000},
            chunk_seconds=10,
            overlap_seconds=1,
        )

        self.assertNotEqual(
            assembly_fingerprint(self.plan, self.contributions),
            assembly_fingerprint(changed_plan, self.contributions),
        )

    def test_missing_contribution(self):
        with self.assertRaises(ValueError):
            assembly_fingerprint(
                self.plan,
                {"application_audio:000000":
                    self.contributions["application_audio:000000"]},
            )

    def test_invalid_digest(self):
        changed = copy.deepcopy(self.contributions)
        changed["application_audio:000000"]["fingerprint"] = "invalid"

        with self.assertRaises(ValueError):
            assembly_fingerprint(self.plan, changed)

    def test_input_not_mutated(self):
        plan = copy.deepcopy(self.plan)
        contributions = copy.deepcopy(self.contributions)

        assembly_fingerprint(self.plan, self.contributions)

        self.assertEqual(self.plan, plan)
        self.assertEqual(self.contributions, contributions)

    def test_identity_versions(self):
        result = assembly_identity(self.plan, self.contributions)

        self.assertEqual(result["identity_version"], 1)
        self.assertEqual(result["assembly_algorithm_version"], 2)


if __name__ == "__main__":
    unittest.main()
