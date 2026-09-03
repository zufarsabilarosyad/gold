"""Expression Template Interpolation and Safe Condition Evaluator Module for Basalt Engine.

Provides regex-based template string interpolation (${steps.id.output.key}, ${env.VAR}, ${inputs.key})
and safe, sandbox-compliant condition evaluation (==, !=, >, <, >=, <=, in) without raw eval().
"""

import ast
import operator
import re
from collections.abc import Callable
from typing import Any

from basalt.core.dag.exceptions import BasaltError
from basalt.core.engine.context import ExecutionContext
from basalt.utils.logger import get_logger

logger = get_logger(__name__)

# Default regular expression pattern for matching template variables like ${steps.fetch.output.id}
TEMPLATE_PATTERN: re.Pattern[str] = re.compile(r"\$\{([^\}]+)\}")


class ExpressionEvaluationError(BasaltError):
    """Raised when template string interpolation or condition evaluation fails."""

    def __init__(
        self,
        expression: str,
        reason: str,
    ) -> None:
        message = f"Expression evaluation failed for '{expression}': {reason}"
        super().__init__(
            message=message,
            code="EXPRESSION_EVALUATION_ERROR",
            details={"expression": expression, "reason": reason},
        )
        self.expression = expression
        self.reason = reason


class ExpressionEvaluator:
    """Safe template string interpolator and boolean condition evaluator."""

    # Supported safe comparison operators for condition evaluation
    SAFE_OPERATORS: dict[type, Callable[[Any, Any], bool]] = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.In: lambda a, b: a in b,
        ast.NotIn: lambda a, b: a not in b,
    }

    @classmethod
    def interpolate_string(
        cls,
        template_str: str,
        context: ExecutionContext,
    ) -> str:
        """Replace all ${expression} template occurrences in a string with resolved values.

        Args:
            template_str: String containing zero or more ${...} expressions.
            context: Active ExecutionContext.

        Returns:
            String with all expressions interpolated.
        """
        if not template_str or "${" not in template_str:
            return template_str

        def replace_match(match: re.Match[str]) -> str:
            expr_path = match.group(1).strip()
            val = context.resolve_variable_path(expr_path)

            if val is None:
                logger.warning(
                    f"Template expression '${{{expr_path}}}' resolved to None in run '{context.run_id}'"
                )
                return ""

            if isinstance(val, (dict, list)):
                import json

                return json.dumps(val)

            return str(val)

        return TEMPLATE_PATTERN.sub(replace_match, template_str)

    @classmethod
    def interpolate_value(
        cls,
        value: Any,
        context: ExecutionContext,
    ) -> Any:
        """Recursively interpolate template expressions within arbitrary data structures.

        Args:
            value: Plain string, list, dictionary, or primitive value.
            context: Active ExecutionContext.

        Returns:
            Data structure with all string templates interpolated.
        """
        if isinstance(value, str):
            # Check if entire string is a single expression (e.g., "${steps.id.output}")
            stripped = value.strip()
            match = TEMPLATE_PATTERN.fullmatch(stripped)
            if match:
                expr_path = match.group(1).strip()
                resolved = context.resolve_variable_path(expr_path)
                return resolved if resolved is not None else ""
            return cls.interpolate_string(value, context)

        if isinstance(value, dict):
            return {
                cls.interpolate_value(k, context): cls.interpolate_value(v, context)
                for k, v in value.items()
            }

        if isinstance(value, list):
            return [cls.interpolate_value(item, context) for item in value]

        return value

    @classmethod
    def evaluate_condition(
        cls,
        condition_str: str,
        context: ExecutionContext,
    ) -> bool:
        """Safely evaluate a boolean condition expression string without using raw eval().

        Example condition strings:
        - "${steps.fetch_data.output.status_code} == 200"
        - "${inputs.environment} != 'production'"
        - "${steps.validate.output.count} > 0"
        - "'success' in ${steps.run_job.output.tags}"

        Args:
            condition_str: Boolean expression string.
            context: Active ExecutionContext.

        Returns:
            True if condition evaluates to True, False otherwise.

        Raises:
            ExpressionEvaluationError: If condition expression syntax is invalid or unparseable.
        """
        if not condition_str or not condition_str.strip():
            return True

        # First, interpolate all ${...} template variables
        interpolated = cls.interpolate_string(condition_str, context).strip()

        if not interpolated:
            return False

        # Handle simple boolean keyword literal shortcuts
        lowered = interpolated.lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no", "none", "null"):
            return False

        try:
            # Parse string into Python Abstract Syntax Tree (AST)
            tree = ast.parse(interpolated, mode="eval")
            return cls._evaluate_ast_node(tree.body)
        except SyntaxError:
            # Fallback string comparison for raw unquoted comparison strings
            return cls._fallback_evaluate_comparison(interpolated)
        except Exception as exc:
            raise ExpressionEvaluationError(
                expression=condition_str,
                reason=f"AST evaluation error: {exc}",
            ) from exc

    @classmethod
    def _evaluate_ast_node(cls, node: ast.AST) -> bool:
        """Recursively evaluate safe AST node types."""
        if isinstance(node, ast.Constant):
            return bool(node.value)

        if isinstance(node, ast.Name):
            name_lower = node.id.lower()
            if name_lower in ("true", "yes"):
                return True
            if name_lower in ("false", "no", "none"):
                return False
            raise ExpressionEvaluationError(
                expression=node.id,
                reason=f"Unsupported identifier '{node.id}' in condition.",
            )

        if isinstance(node, ast.Compare):
            left_val = cls._extract_literal(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                op_type = type(op)
                if op_type not in cls.SAFE_OPERATORS:
                    raise ExpressionEvaluationError(
                        expression="",
                        reason=f"Unsupported comparison operator '{op_type.__name__}'.",
                    )
                right_val = cls._extract_literal(comparator)
                op_fn = cls.SAFE_OPERATORS[op_type]
                try:
                    if not op_fn(left_val, right_val):
                        return False
                except TypeError:
                    # Incompatible type comparison defaults to False
                    return False
                left_val = right_val
            return True

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not cls._evaluate_ast_node(node.operand)

        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(cls._evaluate_ast_node(val) for val in node.values)
            if isinstance(node.op, ast.Or):
                return any(cls._evaluate_ast_node(val) for val in node.values)

        raise ExpressionEvaluationError(
            expression="",
            reason=f"Unsupported AST node type '{type(node).__name__}' in condition.",
        )

    @classmethod
    def _extract_literal(cls, node: ast.AST) -> Any:
        """Extract literal value from Constant, List, Tuple, or UnaryOp AST nodes."""
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            name_lower = node.id.lower()
            if name_lower == "true":
                return True
            if name_lower == "false":
                return False
            if name_lower == "none":
                return None
            return node.id

        if isinstance(node, (ast.List, ast.Tuple)):
            return [cls._extract_literal(elt) for elt in node.elts]

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            val = cls._extract_literal(node.operand)
            if isinstance(val, (int, float)):
                return -val

        raise ExpressionEvaluationError(
            expression="",
            reason=f"Cannot extract literal from node '{type(node).__name__}'.",
        )

    @classmethod
    def _fallback_evaluate_comparison(cls, expr: str) -> bool:
        """Fallback evaluation for basic comparisons like '200 == 200' or 'prod == prod'."""
        ops = [
            ("==", operator.eq),
            ("!=", operator.ne),
            (">=", operator.ge),
            ("<=", operator.le),
            (">", operator.gt),
            ("<", operator.lt),
        ]
        for symbol, op_fn in ops:
            if symbol in expr:
                left_raw, right_raw = expr.split(symbol, 1)
                left_val = cls._parse_raw_operand(left_raw)
                right_val = cls._parse_raw_operand(right_raw)
                try:
                    return op_fn(left_val, right_val)
                except TypeError:
                    return False
        return bool(expr)

    @classmethod
    def _parse_raw_operand(cls, raw: str) -> Any:
        """Parse raw string operand into float, int, bool, or unquoted string."""
        s = raw.strip().strip("'\"")
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        if s.lower() in ("none", "null"):
            return None
        try:
            if "." in s:
                return float(s)
            return int(s)
        except ValueError:
            return s
