"""Deterministic validation for Skill output contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OutputValidation:
    ok: bool
    value: dict[str, Any] | None
    errors: tuple[dict[str, Any], ...]


class OutputContractValidator:
    def validate(
        self,
        raw_output: Any,
        contract: dict[str, Any],
        execution_trace: list[dict[str, Any]],
    ) -> OutputValidation:
        errors: list[dict[str, Any]] = []
        if not isinstance(raw_output, str) or not raw_output.strip():
            return self._failed("$", "invalid_json", "output must be a JSON object string")
        try:
            value = json.loads(raw_output)
        except json.JSONDecodeError:
            return self._failed("$", "invalid_json", "output is not valid JSON")
        if not isinstance(value, dict):
            return self._failed("$", "invalid_type", "output must be an object")

        schema = contract.get("schema")
        if not isinstance(schema, dict):
            return self._failed("$", "invalid_contract", "output contract schema is invalid")
        self._validate_value(value, schema, "$", errors)
        self._validate_evidence(value, execution_trace, errors)
        if value.get("status") == "insufficient_evidence" and not value.get("limitations"):
            errors.append(
                {
                    "path": "$.limitations",
                    "code": "conditional_requirement",
                    "message": "insufficient_evidence requires at least one limitation",
                }
            )
        return OutputValidation(not errors, value if not errors else None, tuple(errors))

    def _validate_value(
        self,
        value: Any,
        rule: dict[str, Any],
        path: str,
        errors: list[dict[str, Any]],
    ) -> None:
        expected_type = rule.get("type")
        matches = {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
        }.get(expected_type, True)
        if not matches:
            errors.append(
                {"path": path, "code": "invalid_type", "message": f"expected {expected_type}"}
            )
            return
        if "enum" in rule and value not in rule["enum"]:
            errors.append(
                {"path": path, "code": "invalid_enum", "message": "value is not allowed"}
            )
        if expected_type == "string":
            if len(value) < rule.get("minLength", 0):
                errors.append(
                    {"path": path, "code": "too_short", "message": "string is too short"}
                )
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                errors.append(
                    {"path": path, "code": "too_long", "message": "string is too long"}
                )
        elif expected_type == "array":
            if len(value) < rule.get("minItems", 0):
                errors.append(
                    {"path": path, "code": "too_few_items", "message": "array has too few items"}
                )
            if "maxItems" in rule and len(value) > rule["maxItems"]:
                errors.append(
                    {"path": path, "code": "too_many_items", "message": "array has too many items"}
                )
            item_rule = rule.get("items")
            if isinstance(item_rule, dict):
                for index, item in enumerate(value):
                    self._validate_value(item, item_rule, f"{path}[{index}]", errors)
        elif expected_type == "object":
            properties = rule.get("properties", {})
            required = rule.get("required", [])
            for key in required:
                if key not in value:
                    errors.append(
                        {
                            "path": f"{path}.{key}",
                            "code": "required",
                            "message": "required field is missing",
                        }
                    )
            if rule.get("additionalProperties") is False:
                for key in value:
                    if key not in properties:
                        errors.append(
                            {
                                "path": f"{path}.{key}",
                                "code": "unknown_field",
                                "message": "field is not allowed",
                            }
                        )
            for key, item in value.items():
                nested = properties.get(key)
                if isinstance(nested, dict):
                    self._validate_value(item, nested, f"{path}.{key}", errors)

    @staticmethod
    def _validate_evidence(
        value: dict[str, Any],
        execution_trace: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> None:
        successful = {
            str(item.get("call_id"))
            for item in execution_trace
            if item.get("success") and item.get("trace_type", "tool") == "tool"
        }
        findings = value.get("findings")
        if not isinstance(findings, list):
            return
        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                continue
            references = finding.get("evidenceCallIds")
            if not isinstance(references, list):
                continue
            for call_id in references:
                if isinstance(call_id, str) and call_id not in successful:
                    errors.append(
                        {
                            "path": f"$.findings[{index}].evidenceCallIds",
                            "code": "unknown_evidence",
                            "message": f"evidence call did not succeed: {call_id}",
                        }
                    )

    @staticmethod
    def _failed(path: str, code: str, message: str) -> OutputValidation:
        return OutputValidation(
            False,
            None,
            ({"path": path, "code": code, "message": message},),
        )

