"""Lightweight asynchronous circuit breaker pattern implementation.

Protects the application from cascading failures when calling external APIs.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class CircuitBreakerOpenException(Exception):
    """Raised when an execution is attempted while the circuit breaker is open."""

    pass


class AsyncCircuitBreaker:
    """Lightweight async circuit breaker.

    States:
        CLOSED: Normal operation. All calls go through.
        OPEN: Failure threshold reached. Calls are blocked immediately.
        HALF_OPEN: Cooldown period expired. A probe call is allowed.
    """

    def __init__(
        self, failure_threshold: int = 5, recovery_timeout: float = 30.0
    ) -> None:
        """Initialize the circuit breaker.

        Args:
            failure_threshold: Number of consecutive failures to open the circuit.
            recovery_timeout: Cooldown duration in seconds before attempting recovery.
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_state_change = time.monotonic()

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute the function, wrapped in circuit breaker logic."""
        now = time.monotonic()
        if self.state == "OPEN":
            if now - self.last_state_change > self.recovery_timeout:
                logger.info("Circuit breaker entering HALF_OPEN state")
                self.state = "HALF_OPEN"
                self.last_state_change = now
            else:
                raise CircuitBreakerOpenException("Circuit breaker is OPEN")

        try:
            res = await func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                logger.info(
                    "Circuit breaker entering CLOSED state after successful probe"
                )
                self.state = "CLOSED"
                self.failure_count = 0
                self.last_state_change = now
            return res
        except Exception as e:
            self.failure_count += 1
            if (
                self.state in ("CLOSED", "HALF_OPEN")
                and self.failure_count >= self.failure_threshold
            ):
                logger.warning(
                    "Circuit breaker entering OPEN state "
                    "due to %d consecutive failures",
                    self.failure_count,
                )
                self.state = "OPEN"
                self.last_state_change = now
            raise e
