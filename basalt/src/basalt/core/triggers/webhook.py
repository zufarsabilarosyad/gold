"""HTTP Webhook Ingestion & Signature Verification Subsystem Module for Basalt Engine.

Provides WebhookTrigger, WebhookAuthenticationError, WebhookRegistry, and HMAC signature
verification utilities (HMAC-SHA256) for securing incoming external HTTP webhook events.
"""

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

from basalt.core.dag.ast import TriggerSpec, TriggerType
from basalt.core.dag.exceptions import BasaltError
from basalt.core.triggers.base import BaseTrigger, TriggerEvent
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class WebhookAuthenticationError(BasaltError):
    """Raised when incoming webhook fails HMAC signature authentication."""

    def __init__(self, trigger_id: str, reason: str) -> None:
        super().__init__(
            message=f"Webhook authentication failed for trigger '{trigger_id}': {reason}",
            code="WEBHOOK_AUTH_ERROR",
            details={"trigger_id": trigger_id, "reason": reason},
        )


class WebhookSignatureVerifier:
    """Utility class for verifying HMAC-SHA256/SHA1 signatures on webhook payloads."""

    @staticmethod
    def compute_signature(payload_bytes: bytes, secret: str, algorithm: str = "sha256") -> str:
        """Compute HMAC hex digest for payload_bytes using secret key.

        Args:
            payload_bytes: Raw HTTP request body byte string.
            secret: Shared secret string key.
            algorithm: Digest algorithm ('sha256' or 'sha1').

        Returns:
            Hex digest signature string.
        """
        digest_mod = getattr(hashlib, algorithm.lower(), hashlib.sha256)
        secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
        return hmac.new(secret_bytes, payload_bytes, digest_mod).hexdigest()

    @classmethod
    def verify_signature(
        cls,
        payload_bytes: bytes,
        secret: str,
        signature_header: str,
        algorithm: str = "sha256",
    ) -> bool:
        """Verify signature_header matches calculated HMAC signature using constant-time comparison.

        Supports headers formatted like 'sha256=abcdef...' or raw hex string 'abcdef...'.
        """
        if not signature_header or not secret:
            return False

        sig_val = signature_header.strip()
        if "=" in sig_val:
            _, sig_val = sig_val.split("=", 1)

        expected_sig = cls.compute_signature(payload_bytes, secret, algorithm=algorithm)
        return hmac.compare_digest(expected_sig.lower(), sig_val.lower())


class WebhookTrigger(BaseTrigger):
    """Event trigger driven by incoming HTTP webhook POST calls."""

    def __init__(self, trigger_spec: TriggerSpec, dag_id: str) -> None:
        super().__init__(trigger_spec, dag_id)
        if trigger_spec.type != TriggerType.WEBHOOK:
            raise ValueError(
                f"WebhookTrigger requires TriggerType.WEBHOOK, got '{trigger_spec.type}'"
            )
        self.secret = trigger_spec.webhook_secret

    def should_fire(self, current_time: datetime | None = None) -> bool:
        """Webhook triggers are reactive and do not fire on periodic evaluation ticks."""
        return False

    def get_next_fire_time(self, current_time: datetime | None = None) -> datetime | None:
        """Webhook triggers do not have pre-scheduled future fire times."""
        return None

    def process_webhook(
        self,
        raw_body: bytes,
        headers: dict[str, str],
        payload_dict: dict[str, Any] | None = None,
        signature_header_name: str = "X-Basalt-Signature",
    ) -> TriggerEvent:
        """Process an incoming HTTP webhook request and construct TriggerEvent.

        Args:
            raw_body: Raw request body bytes.
            headers: HTTP request headers dictionary.
            payload_dict: Parsed JSON body dictionary.
            signature_header_name: Header key carrying HMAC signature.

        Returns:
            Constructed TriggerEvent object.

        Raises:
            WebhookAuthenticationError: If HMAC signature verification fails.
            ValueError: If trigger is disabled.
        """
        if not self.is_active:
            raise ValueError(f"WebhookTrigger '{self.spec.id}' is currently inactive/disabled.")

        # Header lookup case-insensitive helper
        header_map = {k.lower(): v for k, v in headers.items()}
        signature_val = header_map.get(signature_header_name.lower())

        if not signature_val:
            signature_val = header_map.get("x-hub-signature-256") or header_map.get("x-signature")

        # 1. Verify HMAC signature if secret is configured
        if self.secret:
            if not signature_val:
                raise WebhookAuthenticationError(
                    trigger_id=self.spec.id,
                    reason=f"Missing required signature header '{signature_header_name}'",
                )

            valid = WebhookSignatureVerifier.verify_signature(
                payload_bytes=raw_body,
                secret=self.secret,
                signature_header=signature_val,
                algorithm="sha256",
            )
            if not valid:
                raise WebhookAuthenticationError(
                    trigger_id=self.spec.id,
                    reason="HMAC-SHA256 signature verification mismatch",
                )

        # 2. Construct TriggerEvent
        now = datetime.now(UTC)
        self.last_fired_at = now

        event_payload = {
            "webhook_body": payload_dict or {},
            "headers": headers,
        }

        event = TriggerEvent(
            trigger_id=self.spec.id,
            dag_id=self.dag_id,
            trigger_type=TriggerType.WEBHOOK,
            timestamp=now,
            payload=event_payload,
        )

        logger.info(
            f"WebhookTrigger '{self.spec.id}' processed incoming webhook event '{event.event_id}' for DAG '{self.dag_id}'"
        )
        return event


class WebhookRegistry:
    """In-memory registry index mapping trigger IDs to registered WebhookTrigger instances."""

    def __init__(self) -> None:
        self._triggers: dict[str, WebhookTrigger] = {}

    def register(self, trigger: WebhookTrigger) -> None:
        """Register a WebhookTrigger instance."""
        self._triggers[trigger.spec.id] = trigger
        logger.info(f"Registered WebhookTrigger '{trigger.spec.id}' in WebhookRegistry")

    def unregister(self, trigger_id: str) -> bool:
        """Remove a WebhookTrigger by ID."""
        if trigger_id in self._triggers:
            del self._triggers[trigger_id]
            logger.info(f"Unregistered WebhookTrigger '{trigger_id}' from WebhookRegistry")
            return True
        return False

    def get(self, trigger_id: str) -> WebhookTrigger | None:
        """Fetch a registered WebhookTrigger by ID."""
        return self._triggers.get(trigger_id)

    def list_active(self) -> list[WebhookTrigger]:
        """List all active registered WebhookTriggers."""
        return [t for t in self._triggers.values() if t.is_active]

    def clear(self) -> None:
        """Clear all registered triggers."""
        self._triggers.clear()


def create_webhook_trigger(
    trigger_id: str,
    dag_id: str,
    secret: str | None = None,
    enabled: bool = True,
) -> WebhookTrigger:
    """Helper shortcut function to create a WebhookTrigger instance."""
    spec = TriggerSpec(
        id=trigger_id,
        type=TriggerType.WEBHOOK,
        webhook_secret=secret,
        enabled=enabled,
    )
    return WebhookTrigger(trigger_spec=spec, dag_id=dag_id)
