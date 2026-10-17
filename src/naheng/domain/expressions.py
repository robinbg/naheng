"""Small, deterministic expression language; never executes Python source."""
from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Mapping


class ExpressionError(ValueError):
    pass


_FUNCTIONS = {"exp": math.exp, "log": math.log, "sqrt": math.sqrt,
              "abs": abs, "min": min, "max": max}
_BINARY = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div", ast.Pow: "pow"}


@dataclass(frozen=True)
class Expression:
    op: str
    value: float | str | None = None
    args: tuple["Expression", ...] = ()

    def to_dict(self) -> dict:
        result = {"op": self.op}
        if self.value is not None:
            result["value"] = self.value
        if self.args:
            result["args"] = [x.to_dict() for x in self.args]
        return result

    def evaluate(self, variables: Mapping[str, float]) -> float:
        if self.op == "const":
            result = float(self.value)
        elif self.op == "var":
            if self.value not in variables:
                raise ExpressionError(f"missing variable: {self.value}")
            result = float(variables[str(self.value)])
        else:
            values = [x.evaluate(variables) for x in self.args]
            try:
                if self.op == "add": result = values[0] + values[1]
                elif self.op == "sub": result = values[0] - values[1]
                elif self.op == "mul": result = values[0] * values[1]
                elif self.op == "div": result = values[0] / values[1]
                elif self.op == "pow": result = values[0] ** values[1]
                elif self.op == "neg": result = -values[0]
                elif self.op in _FUNCTIONS: result = _FUNCTIONS[self.op](*values)
                else: raise ExpressionError(f"unsupported operation: {self.op}")
            except (ArithmeticError, ValueError, TypeError) as exc:
                raise ExpressionError(f"invalid numerical operation {self.op}: {exc}") from exc
        if isinstance(result, complex) or not math.isfinite(result):
            raise ExpressionError("expression produced a non-finite real result")
        return float(result)


def parse_expression(source: str, allowed_variables: set[str] | None = None) -> Expression:
    if not isinstance(source, str) or len(source) > 4096:
        raise ExpressionError("expression must be a bounded string")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError("invalid expression syntax") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 256:
        raise ExpressionError("expression is too complex")

    def convert(node: ast.AST, depth: int = 0) -> Expression:
        if depth > 32:
            raise ExpressionError("expression is too deep")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if not math.isfinite(float(node.value)) or abs(float(node.value)) > 1e100:
                raise ExpressionError("constant outside numerical domain")
            return Expression("const", float(node.value))
        if isinstance(node, ast.Name):
            if node.id.startswith("_") or (allowed_variables is not None and node.id not in allowed_variables):
                raise ExpressionError(f"variable not allowed: {node.id}")
            return Expression("var", node.id)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return Expression(_BINARY[type(node.op)], args=(convert(node.left, depth+1), convert(node.right, depth+1)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = convert(node.operand, depth+1)
            return value if isinstance(node.op, ast.UAdd) else Expression("neg", args=(value,))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS and not node.keywords:
            arity = len(node.args)
            if arity == 0 or (node.func.id not in ("min", "max") and arity != 1) or arity > 8:
                raise ExpressionError("invalid function arity")
            return Expression(node.func.id, args=tuple(convert(x, depth+1) for x in node.args))
        raise ExpressionError(f"forbidden syntax: {type(node).__name__}")

    return convert(tree.body)


def expression_from_dict(data: dict, allowed_variables: set[str] | None = None) -> Expression:
    """Validate typed AST input as strictly as textual input."""
    count = 0
    def convert(item: dict, depth: int = 0) -> Expression:
        nonlocal count
        count += 1
        if count > 256 or depth > 32 or not isinstance(item, dict) or set(item) - {"op", "value", "args"}:
            raise ExpressionError("invalid or excessive AST")
        op = item.get("op")
        value = item.get("value")
        args = item.get("args", [])
        if not isinstance(args, list): raise ExpressionError("AST args must be a list")
        if op == "const":
            if args or type(value) not in (float, int) or not math.isfinite(float(value)) or abs(value) > 1e100:
                raise ExpressionError("invalid AST constant")
        elif op == "var":
            if args or not isinstance(value, str) or not value.isidentifier() or value.startswith("_") or (allowed_variables is not None and value not in allowed_variables):
                raise ExpressionError("invalid AST variable")
        else:
            if value is not None or op not in {"add", "sub", "mul", "div", "pow", "neg", *_FUNCTIONS}:
                raise ExpressionError("invalid AST operation")
            required = 2 if op in {"add", "sub", "mul", "div", "pow"} else 1
            if (op in {"min", "max"} and not 1 <= len(args) <= 8) or (op not in {"min", "max"} and len(args) != required):
                raise ExpressionError("invalid AST arity")
        return Expression(op, value, tuple(convert(x, depth+1) for x in args))
    return convert(data)
