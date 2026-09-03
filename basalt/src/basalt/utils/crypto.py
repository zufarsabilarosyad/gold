"""Cryptographic Utilities Module for Basalt Workflow Engine.

Provides secure token generation, HMAC-SHA256 signature verification,
payload checksum computation, canonical dictionary hashing, and ID generation helpers.
"""

import hashlib
import hmac
import json
import secrets
import uuid
from typing import Any


def generate_uuid() -> str:
    """Generate a random UUIDv4 string.

    Returns:
        36-character canonical UUIDv4 string.
    """
    return str(uuid.uuid4())


def generate_prefixed_id(prefix: str) -> str:
    """Generate a prefixed unique identifier string.

    Args:
        prefix: Short namespace prefix (e.g., 'dag', 'run', 'step', 'trg').

    Returns:
        Formatted string like 'dag_a1b2c3d4e5f67890'.
    """
    random_hex = secrets.token_hex(12)
    clean_prefix = prefix.strip("_").lower()
    return f"{clean_prefix}_{random_hex}"


def generate_run_id() -> str:
    """Generate a prefixed unique run identifier string (e.g. 'run_a1b2c3d4e5f67890')."""
    return generate_prefixed_id("run")


def compute_sha256(data: str | bytes) -> str:
    """Compute standard SHA-256 hexadecimal digest for string or bytes input.

    Args:
        data: Plaintext string or binary content.

    Returns:
        64-character hexadecimal SHA-256 hash digest.
    """
    if isinstance(data, str):
        encoded_bytes = data.encode("utf-8")
    else:
        encoded_bytes = data

    return hashlib.sha256(encoded_bytes).hexdigest()


def compute_hmac_sha256(key: str | bytes, message: str | bytes) -> str:
    """Compute HMAC-SHA256 signature for a message payload using a secret key.

    Args:
        key: Secret authentication key string or bytes.
        message: Payload message string or bytes.

    Returns:
        64-character lower-case hexadecimal HMAC signature.
    """
    key_bytes = key.encode("utf-8") if isinstance(key, str) else key
    msg_bytes = message.encode("utf-8") if isinstance(message, str) else message

    return hmac.new(key_bytes, msg_bytes, hashlib.sha256).hexdigest()


def verify_hmac_sha256(
    key: str | bytes,
    message: str | bytes,
    signature: str,
) -> bool:
    """Verify an HMAC-SHA256 signature using constant-time comparison.

    Args:
        key: Secret authentication key.
        message: Received payload message.
        signature: Claimed HMAC signature hex string.

    Returns:
        True if signature is valid and authentic, False otherwise.
    """
    expected_signature = compute_hmac_sha256(key, message)
    clean_signature = signature.strip().lower()

    # If signature has 'sha256=' prefix (e.g., GitHub Webhooks), strip it
    if clean_signature.startswith("sha256="):
        clean_signature = clean_signature[7:]

    return hmac.compare_digest(expected_signature.lower(), clean_signature)


def generate_secure_token(length_bytes: int = 32) -> str:
    """Generate a cryptographically secure URL-safe random secret token.

    Args:
        length_bytes: Random byte count before URL-safe encoding (default: 32).

    Returns:
        URL-safe base64 encoded token string.
    """
    return secrets.token_urlsafe(length_bytes)


def hash_dictionary(data: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of a dictionary by canonicalizing JSON keys.

    Args:
        data: Arbitrary dictionary data structure.

    Returns:
        64-character SHA-256 hexadecimal hash string.
    """
    canonical_json = json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
    )
    return compute_sha256(canonical_json)


def mask_sensitive_string(
    value: str,
    visible_prefix: int = 4,
    visible_suffix: int = 4,
    mask_char: str = "*",
) -> str:
    """Mask sensitive string secret while preserving short prefix and suffix for identification.

    Args:
        value: Plaintext sensitive secret string (e.g., API key, authorization token).
        visible_prefix: Number of unmasked leading characters.
        visible_suffix: Number of unmasked trailing characters.
        mask_char: Character used to replace hidden content.

    Returns:
        Masked string (e.g., 'strata_live_****a8b9').
    """
    if not value:
        return ""

    val_len = len(value)
    if val_len <= (visible_prefix + visible_suffix):
        return mask_char * min(val_len, 8)

    prefix_str = value[:visible_prefix]
    suffix_str = value[-visible_suffix:]
    masked_middle = mask_char * min(val_len - (visible_prefix + visible_suffix), 8)

    return f"{prefix_str}{masked_middle}{suffix_str}"


def compare_digest_safe(val1: str, val2: str) -> bool:
    """Perform constant-time string comparison to prevent timing side-channel attacks.

    Args:
        val1: First string comparison operand.
        val2: Second string comparison operand.

    Returns:
        True if strings match exactly.
    """
    return hmac.compare_digest(val1.encode("utf-8"), val2.encode("utf-8"))
