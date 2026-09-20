"""Small deterministic arithmetic evaluator used by the calc route."""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Callable


MAX_EXPRESSION_LENGTH = 200
MAX_AST_NODES = 64
MAX_ABSOLUTE_VALUE = 1e100
MAX_EXPONENT = 12

_PREFIX = re.compile(r"^\s*(?:请)?(?:帮我)?(?:计算|算一下|算出|calculate)\s*[:：]?\s*", re.I)
_SUFFIX = re.compile(r"\s*[？?。！!]?\s*$")
_ALLOWED_CHARS = re.compile(r"^[0-9eE+\-*/%().\s]+$")
_BINARY: dict[type[ast.operator], Callable[[float | int, float | int], float | int]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[float | int], float | int]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculationError(ValueError):
    """Raised when an expression is unsafe, unsupported, or invalid."""


def extract_expression(query: str) -> str | None:
    expression = _PREFIX.sub("", query, count=1)
    expression = _SUFFIX.sub("", expression)
    if not expression or len(expression) > MAX_EXPRESSION_LENGTH:
        return None
    if not _ALLOWED_CHARS.fullmatch(expression):
        return None
    return expression


def can_calculate(query: str) -> bool:
    expression = extract_expression(query)
    if expression is None:
        return False
    try:
        evaluate_expression(expression)
    except (CalculationError, ArithmeticError, ValueError, SyntaxError):
        return False
    return True


def evaluate_expression(expression: str) -> float | int:
    if not expression or len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculationError("expression is empty or too long")
    if not _ALLOWED_CHARS.fullmatch(expression):
        raise CalculationError("expression contains unsupported characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise CalculationError("expression syntax is invalid") from error
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise CalculationError("expression is too complex")
    return _evaluate(tree.body)


def _evaluate(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalculationError("only numeric constants are supported")
        return _bounded(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _bounded(_UNARY[type(node.op)](_evaluate(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculationError("exponent is too large")
        try:
            return _bounded(_BINARY[type(node.op)](left, right))
        except (OverflowError, ZeroDivisionError) as error:
            raise CalculationError(type(error).__name__) from error
    raise CalculationError("expression contains an unsupported operation")


def _bounded(value: float | int) -> float | int:
    if isinstance(value, float) and not math.isfinite(value):
        raise CalculationError("result must be finite")
    if abs(value) > MAX_ABSOLUTE_VALUE:
        raise CalculationError("result is too large")
    return value
