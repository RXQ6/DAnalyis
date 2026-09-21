from __future__ import annotations

import json
import unittest

from skill_runtime import OutputContractValidator, SkillRegistry


class SkillOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = SkillRegistry().load("data-diagnosis").output_contract
        self.validator = OutputContractValidator()
        self.trace = [
            {
                "call_id": "call-ok",
                "tool_name": "detect_anomaly",
                "success": True,
            }
        ]

    def output(self, **overrides):
        value = {
            "status": "completed",
            "summary": "发现一个异常分组。",
            "findings": [
                {
                    "title": "异常分组",
                    "severity": "high",
                    "detail": "工具结果显示该分组偏离其他分组。",
                    "evidenceCallIds": ["call-ok"],
                }
            ],
            "recommendations": ["核对该分组来源"],
            "limitations": [],
        }
        value.update(overrides)
        return json.dumps(value, ensure_ascii=False)

    def test_valid_output_and_evidence_pass(self) -> None:
        result = self.validator.validate(self.output(), self.contract, self.trace)

        self.assertTrue(result.ok)
        self.assertEqual(result.value["status"], "completed")

    def test_unknown_evidence_is_rejected(self) -> None:
        findings = [
            {
                "title": "异常",
                "severity": "medium",
                "detail": "说明",
                "evidenceCallIds": ["missing-call"],
            }
        ]
        result = self.validator.validate(
            self.output(findings=findings), self.contract, self.trace
        )

        self.assertFalse(result.ok)
        self.assertIn("unknown_evidence", {error["code"] for error in result.errors})

    def test_invalid_json_and_invalid_enum_are_rejected(self) -> None:
        invalid_json = self.validator.validate("not-json", self.contract, self.trace)
        invalid_enum = self.validator.validate(
            self.output(findings=[], status="guessed"), self.contract, self.trace
        )

        self.assertFalse(invalid_json.ok)
        self.assertFalse(invalid_enum.ok)
        self.assertIn("invalid_enum", {error["code"] for error in invalid_enum.errors})

    def test_insufficient_evidence_requires_limitations(self) -> None:
        result = self.validator.validate(
            self.output(status="insufficient_evidence", findings=[], limitations=[]),
            self.contract,
            self.trace,
        )

        self.assertFalse(result.ok)
        self.assertIn(
            "conditional_requirement", {error["code"] for error in result.errors}
        )


if __name__ == "__main__":
    unittest.main()
