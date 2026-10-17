import pytest
from naheng.domain.expressions import ExpressionError, expression_from_dict, parse_expression


@pytest.mark.parametrize("expression", ["__import__('os').system('echo unsafe')", "x.__class__", "open('/tmp/a')", "x[0]", "lambda: 1", "[x for x in y]", "a if x else b", "exp(x, ignored=1)", "'D:/path'", "x; 1"])
def test_forbidden_syntax(expression):
    with pytest.raises(ExpressionError):
        parse_expression(expression, {"x", "y", "a", "b"})


def test_legal_ast_round_trip_and_domain():
    expression = parse_expression("exp(-x) + 2*y", {"x", "y"})
    assert expression.evaluate({"x": 0, "y": 3}) == 7
    assert expression_from_dict(expression.to_dict(), {"x", "y"}).evaluate({"x": 0, "y": 3}) == 7
    with pytest.raises(ExpressionError):
        parse_expression("log(x)", {"x"}).evaluate({"x": -1})
    with pytest.raises(ExpressionError):
        expression_from_dict({"op": "var", "value": "../../secret"})


def test_resource_and_nonfinite_limits():
    with pytest.raises(ExpressionError): parse_expression("1e309")
    with pytest.raises(ExpressionError): parse_expression(" + ".join(["x"]*200), {"x"})
    with pytest.raises(ExpressionError): parse_expression("x+y", {"x"})
