"""Validation and Input Sanitization Utilities Module for Basalt Workflow Engine.

Provides input validators, path traversal security guards, string sanitizers,
identifier format matchers, and URL/Cron format checkers.
"""

import json
import re
from collections.abc import Container
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import croniter

# Standard identifier regex pattern: 1-64 alphanumeric characters, underscores, or hyphens
IDENTIFIER_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Unprintable control characters regex pattern
CONTROL_CHARS_PATTERN: re.Pattern[str] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def is_valid_identifier(identifier: str) -> bool:
    """Check if string satisfies Basalt identifier format rules.

    Args:
        identifier: Candidate identifier string (e.g., DAG ID, step ID).

    Returns:
        True if string is a valid identifier, False otherwise.
    """
    if not isinstance(identifier, str):
        return False
    return bool(IDENTIFIER_PATTERN.match(identifier))


def validate_identifier(identifier: str, field_name: str = "identifier") -> str:
    """Validate string satisfies identifier rules or raise ValueError.

    Args:
        identifier: Candidate identifier string.
        field_name: Field name used in error message context.

    Returns:
        Validated identifier string.

    Raises:
        ValueError: If identifier format is invalid.
    """
    if not is_valid_identifier(identifier):
        raise ValueError(
            f"Invalid {field_name} '{identifier}'. Must be 1-64 characters matching "
            "alphanumeric, underscore, or hyphen pattern ^[a-zA-Z0-9_-]+$."
        )
    return identifier


def validate_safe_path(
    target_path: str | Path,
    base_directory: str | Path | None = None,
    allow_absolute: bool = False,
) -> Path:
    """Guard against path traversal attacks by verifying target path resides within base directory.

    Args:
        target_path: Candidate target file or directory path.
        base_directory: Safe root base directory (defaults to cwd if None).
        allow_absolute: Whether absolute paths are allowed directly.

    Returns:
        Resolved absolute Path object if safe.

    Raises:
        ValueError: If path attempts to escape base directory (e.g., '../..').
    """
    target_resolved = Path(target_path).resolve()
    if allow_absolute and target_resolved.is_absolute():
        return target_resolved

    base_resolved = Path(base_directory or Path.cwd()).resolve()

    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(
            f"Path traversal detected: Path '{target_path}' escapes base directory '{base_resolved}'."
        ) from exc

    return target_resolved


def sanitize_string(
    input_string: str,
    max_length: int | None = 1024,
    strip_whitespace: bool = True,
) -> str:
    """Sanitize string by stripping control characters, leading/trailing whitespace, and capping length.

    Args:
        input_string: Raw input text string.
        max_length: Maximum allowed character length cap (or None for unlimited).
        strip_whitespace: Whether to strip leading/trailing whitespace.

    Returns:
        Sanitized string.
    """
    if not isinstance(input_string, str):
        return ""

    # Remove unprintable control characters
    sanitized = CONTROL_CHARS_PATTERN.sub("", input_string)

    if strip_whitespace:
        sanitized = sanitized.strip()

    if max_length is not None and max_length > 0 and len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    return sanitized


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename by replacing unsafe OS characters with underscores.

    Args:
        filename: Candidate filename string.

    Returns:
        Safe filename string.
    """
    clean_name = sanitize_string(filename, max_length=255)
    # Replace non-alphanumeric (except dot, underscore, hyphen) with underscore
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", clean_name)
    # Remove leading dots to prevent hidden files
    safe_name = safe_name.lstrip(".")
    return safe_name or "unnamed_file"


def validate_cron_expression(cron_expression: str) -> bool:
    """Validate standard 5-field cron expression syntax.

    Args:
        cron_expression: Cron expression string (e.g., '*/5 * * * *').

    Returns:
        True if expression syntax is valid, False otherwise.
    """
    if not isinstance(cron_expression, str) or not cron_expression.strip():
        return False
    return croniter.croniter.is_valid(cron_expression.strip())


def validate_http_url(
    url: str,
    allowed_schemes: Container[str] = ("http", "https"),
) -> bool:
    """Validate URL syntax and scheme.

    Args:
        url: Candidate URL string.
        allowed_schemes: Iterable of allowed URL schemes (default: http, https).

    Returns:
        True if valid URL with permitted scheme, False otherwise.
    """
    if not isinstance(url, str) or not url.strip():
        return False

    try:
        parsed = urlparse(url.strip())
        return bool(parsed.scheme in allowed_schemes and parsed.netloc)
    except Exception:
        return False


def validate_json_serializable(data: Any) -> bool:
    """Verify whether an arbitrary Python object can be serialized to JSON.

    Args:
        data: Arbitrary Python object structure.

    Returns:
        True if json.dumps succeeds, False otherwise.
    """
    try:
        json.dumps(data, default=str)
        return True
    except (TypeError, ValueError):
        return False


def validate_positive_number(
    value: int | float,
    field_name: str = "value",
    allow_zero: bool = False,
) -> int | float:
    """Validate number is positive or non-negative.

    Args:
        value: Candidate number value.
        field_name: Field name for error messages.
        allow_zero: Whether 0 is considered valid.

    Returns:
        Validated number.

    Raises:
        ValueError: If number fails threshold check.
    """
    if not isinstance(value, (int, float)):
        raise ValueError(f"Field '{field_name}' must be a number, got {type(value).__name__}.")

    if allow_zero:
        if value < 0:
            raise ValueError(f"Field '{field_name}' must be non-negative (>= 0), got {value}.")
    else:
        if value <= 0:
            raise ValueError(f"Field '{field_name}' must be positive (> 0), got {value}.")

    return value


# Alias for backward compatibility
validate_url = validate_http_url
