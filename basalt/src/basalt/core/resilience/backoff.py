"""Exponential Backoff and Jitter Calculation Subsystem Module for Basalt Engine.

Provides constant, linear, and exponential backoff delay algorithms with optional full/equal jitter
to prevent retry thundering herd problems on downstream services.
"""

import random
from enum import Enum

from pydantic import BaseModel, Field

from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class BackoffStrategy(str, Enum):
    """Supported backoff delay growth strategies."""

    CONSTANT = "constant"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


class JitterStrategy(str, Enum):
    """Supported randomized jitter strategies."""

    NONE = "none"
    FULL = "full"
    EQUAL = "equal"


class BackoffPolicy(BaseModel):
    """Configuration model for backoff policy rules."""

    initial_delay_seconds: float = Field(default=1.0, gt=0.0)
    max_delay_seconds: float = Field(default=60.0, gt=0.0)
    backoff_factor: float = Field(default=2.0, ge=1.0)
    strategy: BackoffStrategy = Field(default=BackoffStrategy.EXPONENTIAL)
    jitter: JitterStrategy = Field(default=JitterStrategy.FULL)

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for attempt index using this policy."""
        return BackoffCalculator.calculate_delay(
            attempt=attempt,
            initial_delay_seconds=self.initial_delay_seconds,
            max_delay_seconds=self.max_delay_seconds,
            backoff_factor=self.backoff_factor,
            strategy=self.strategy,
            jitter=self.jitter,
        )


class BackoffCalculator:
    """Calculator utility for backoff delay intervals and randomized jitter."""

    @staticmethod
    def calculate_delay(
        attempt: int,
        initial_delay_seconds: float = 1.0,
        max_delay_seconds: float = 60.0,
        backoff_factor: float = 2.0,
        strategy: str | BackoffStrategy = BackoffStrategy.EXPONENTIAL,
        jitter: str | JitterStrategy = JitterStrategy.FULL,
    ) -> float:
        """Calculate backoff sleep delay interval in seconds for a retry attempt.

        Args:
            attempt: Current retry attempt index (1-indexed, attempt >= 1).
            initial_delay_seconds: Base initial delay in seconds.
            max_delay_seconds: Upper ceiling cap for backoff delay.
            backoff_factor: Multiplier growth factor.
            strategy: Backoff algorithm ('constant', 'linear', 'exponential').
            jitter: Jitter randomization ('none', 'full', 'equal').

        Returns:
            Calculated sleep delay in seconds (floored at 0.0, capped at max_delay_seconds).
        """
        attempt = max(1, attempt)
        initial_delay = max(0.001, initial_delay_seconds)
        max_delay = max(initial_delay, max_delay_seconds)
        factor = max(1.0, backoff_factor)

        strategy_enum = BackoffStrategy(strategy) if isinstance(strategy, str) else strategy
        jitter_enum = JitterStrategy(jitter) if isinstance(jitter, str) else jitter

        # 1. Base delay calculation
        if strategy_enum == BackoffStrategy.CONSTANT:
            base_delay = initial_delay
        elif strategy_enum == BackoffStrategy.LINEAR:
            base_delay = initial_delay * (1.0 + (attempt - 1) * (factor - 1.0))
        else:  # EXPONENTIAL
            base_delay = initial_delay * (factor ** (attempt - 1))

        # 2. Cap base delay at max_delay_seconds
        bounded_delay = min(base_delay, max_delay)

        # 3. Apply randomized jitter strategy
        if jitter_enum == JitterStrategy.FULL:
            # Full Jitter: Sleep between 0 and bounded_delay
            final_delay = random.uniform(0.0, bounded_delay)
        elif jitter_enum == JitterStrategy.EQUAL:
            # Equal Jitter: Half deterministic delay + half randomized delay
            half_delay = bounded_delay / 2.0
            final_delay = half_delay + random.uniform(0.0, half_delay)
        else:
            # No jitter
            final_delay = bounded_delay

        final_delay = max(0.0, min(final_delay, max_delay))
        logger.debug(
            f"Calculated backoff delay for attempt {attempt} ({strategy_enum.value}, jitter={jitter_enum.value}): {final_delay:.3f}s"
        )
        return final_delay

    @staticmethod
    def generate_delay_sequence(
        max_retries: int,
        initial_delay_seconds: float = 1.0,
        max_delay_seconds: float = 60.0,
        backoff_factor: float = 2.0,
        strategy: str | BackoffStrategy = BackoffStrategy.EXPONENTIAL,
        jitter: str | JitterStrategy = JitterStrategy.NONE,
    ) -> list[float]:
        """Generate sequence of delay values for a max retry count."""
        return [
            BackoffCalculator.calculate_delay(
                attempt=i,
                initial_delay_seconds=initial_delay_seconds,
                max_delay_seconds=max_delay_seconds,
                backoff_factor=backoff_factor,
                strategy=strategy,
                jitter=jitter,
            )
            for i in range(1, max_retries + 1)
        ]


def compute_backoff_delay(
    attempt: int,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
) -> float:
    """Helper shortcut function to compute exponential backoff delay."""
    jitter_strat = JitterStrategy.FULL if jitter else JitterStrategy.NONE
    return BackoffCalculator.calculate_delay(
        attempt=attempt,
        initial_delay_seconds=initial_delay,
        max_delay_seconds=max_delay,
        backoff_factor=backoff_factor,
        strategy=BackoffStrategy.EXPONENTIAL,
        jitter=jitter_strat,
    )
