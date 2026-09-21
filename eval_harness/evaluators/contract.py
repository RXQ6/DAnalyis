"""Deterministic structured-output contract evaluation."""

from __future__ import annotations

from typing import Any, Mapping

from ..models import EvalCase, ProcessEvaluation
from ..taxonomy import FailureType


_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
}


class ContractEvaluator:
    name = "contract"

    def evaluate(
        self, case: EvalCase, observation: Mapping[str, Any]
    ) -> ProcessEvaluation:
        contract = case.expectations.get("contract")
        if contract is None:
            return ProcessEvaluation(self.name, False, True, values={"contract_valid": None})
        value = observation.get("contract_value")
        failures: list[str] = []
        kind = contract.get("kind", "structured_output")
        if not isinstance(value, Mapping):
            failures.append("contract value must be an object")
        else:
            required = list(contract.get("required", []))
            if kind == "tool_result":
                required.extend(["ok"])
                if value.get("ok") is True:
                    required.append("data")
                elif value.get("ok") is False:
                    required.append("error")
            elif kind == "skill_invocation":
                required.extend(["skill_name", "status", "tools_used", "contract_valid"])
            for field in dict.fromkeys(required):
                if field not in value:
                    failures.append(f"missing required field: {field}")
            for field, type_name in contract.get("types", {}).items():
                if field in value and type_name in _TYPE_MAP and not isinstance(
                    value[field], _TYPE_MAP[type_name]
                ):
                    failures.append(f"field {field!r} must be {type_name}")
            if kind == "skill_invocation" and value.get("contract_valid") is not True:
                failures.append("skill invocation contract_valid is not true")
        if failures:
            return ProcessEvaluation(
                self.name,
                True,
                False,
                str(FailureType.CONTRACT_ERROR),
                "; ".join(failures),
                {"contract_valid": False, "kind": kind},
            )
        return ProcessEvaluation(
            self.name,
            True,
            True,
            values={"contract_valid": True, "kind": kind},
        )
