from __future__ import annotations

import unittest

from day8_semantic_cases import CASES, evaluate_case, run_case


class MultiStepSemanticTests(unittest.TestCase):
    def test_all_semantic_cases(self) -> None:
        for case in CASES:
            with self.subTest(case=case.case_id):
                state, model = run_case(case)
                self.assertEqual(evaluate_case(case, state, model), [])


if __name__ == "__main__":
    unittest.main()

