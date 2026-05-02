from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from utils.logger import set_event_type


T = TypeVar("T")


class TokenBucketRateLimiter:
    def __init__(
        self,
        tokens_per_second: float,
        burst_capacity: int,
    ) -> None:
        if tokens_per_second <= 0:
            raise ValueError("tokens_per_second must be greater than 0")
        if burst_capacity <= 0:
            raise ValueError("burst_capacity must be greater than 0")

        self._tokens_per_second = tokens_per_second
        self._burst_capacity = float(burst_capacity)
        self._available_tokens = float(burst_capacity)
        self._last_refill_time = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                self._refill_tokens()
                if self._available_tokens >= 1:
                    self._available_tokens -= 1
                    return

                deficit = 1 - self._available_tokens
                wait_seconds = deficit / self._tokens_per_second

            time.sleep(wait_seconds)

    def _refill_tokens(self) -> None:
        current_time = time.monotonic()
        elapsed_seconds = current_time - self._last_refill_time
        if elapsed_seconds <= 0:
            return

        replenished_tokens = elapsed_seconds * self._tokens_per_second
        self._available_tokens = min(
            self._burst_capacity,
            self._available_tokens + replenished_tokens,
        )
        self._last_refill_time = current_time


def execute_with_backoff(
    operation_name: str,
    max_retries: int,
    base_delay_seconds: float,
    logger: logging.Logger,
    event_type_prefix: str,
    func: Callable[[], T],
    should_retry: Callable[[BaseException], bool],
) -> T:
    attempt = 0

    while True:
        try:
            return func()
        except BaseException as exc:
            if attempt >= max_retries or not should_retry(exc):
                raise

            delay_seconds = _build_backoff_delay(
                base_delay_seconds=base_delay_seconds,
                attempt=attempt,
            )

            set_event_type(f"{event_type_prefix}_retry_scheduled")
            logger.warning(
                "Retry scheduled for %s after %.2f seconds (attempt %s/%s): %s",
                operation_name,
                delay_seconds,
                attempt + 1,
                max_retries,
                exc,
            )

            time.sleep(delay_seconds)
            attempt += 1


def _build_backoff_delay(base_delay_seconds: float, attempt: int) -> float:
    jitter_seconds = random.uniform(0, 0.3)
    return (base_delay_seconds * (2**attempt)) + jitter_seconds
