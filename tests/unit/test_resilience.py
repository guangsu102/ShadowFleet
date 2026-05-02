"""Unit tests for utils.resilience module."""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock

import pytest

from utils.resilience import (
    TokenBucketRateLimiter,
    _build_backoff_delay,
    execute_with_backoff,
)


class TestTokenBucketRateLimiter:
    """Tests for TokenBucketRateLimiter class."""

    def test_initialization_with_valid_params(self) -> None:
        """Should initialize with valid tokens equal to burst_capacity."""
        limiter = TokenBucketRateLimiter(tokens_per_second=10.0, burst_capacity=5)
        assert limiter._available_tokens == 5.0
        assert limiter._tokens_per_second == 10.0
        assert limiter._burst_capacity == 5.0

    def test_initialization_with_zero_tokens_per_second_raises(self) -> None:
        """Zero tokens_per_second should raise ValueError."""
        with pytest.raises(ValueError, match="tokens_per_second must be greater than 0"):
            TokenBucketRateLimiter(tokens_per_second=0, burst_capacity=5)

    def test_initialization_with_negative_burst_raises(self) -> None:
        """Negative burst_capacity should raise ValueError."""
        with pytest.raises(ValueError, match="burst_capacity must be greater than 0"):
            TokenBucketRateLimiter(tokens_per_second=10, burst_capacity=0)

    def test_acquire_decrements_tokens(self) -> None:
        """Acquiring a token should decrement available tokens."""
        limiter = TokenBucketRateLimiter(tokens_per_second=10.0, burst_capacity=5)
        initial_tokens = limiter._available_tokens
        limiter.acquire()
        assert limiter._available_tokens == initial_tokens - 1

    def test_acquire_multiple_tokens_decrements_correctly(self) -> None:
        """Acquiring multiple tokens should decrement correctly."""
        limiter = TokenBucketRateLimiter(tokens_per_second=100.0, burst_capacity=10)
        for _ in range(5):
            limiter.acquire()
        assert limiter._available_tokens == 5.0

    def test_acquire_refills_tokens_over_time(self) -> None:
        """Tokens should be refilled over time."""
        limiter = TokenBucketRateLimiter(tokens_per_second=100.0, burst_capacity=5)
        limiter.acquire()
        limiter.acquire()
        time.sleep(0.05)  # 50ms should add ~5 tokens at 100/s
        limiter._refill_tokens()
        assert limiter._available_tokens >= 4.0  # Should have refilled

    def test_acquire_respects_burst_capacity(self) -> None:
        """Tokens should never exceed burst_capacity."""
        limiter = TokenBucketRateLimiter(tokens_per_second=1000.0, burst_capacity=5)
        limiter.acquire()
        time.sleep(1.0)  # Should refill at 1000/s
        limiter._refill_tokens()
        assert limiter._available_tokens <= 5.0

    def test_concurrent_acquire_thread_safe(self) -> None:
        """Acquire should be thread-safe with locking."""
        import threading

        limiter = TokenBucketRateLimiter(tokens_per_second=100.0, burst_capacity=10)
        results: list[int] = []

        def acquire_tokens():
            limiter.acquire()
            results.append(1)

        threads = [threading.Thread(target=acquire_tokens) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5


class TestBuildBackoffDelay:
    """Tests for _build_backoff_delay function."""

    def test_backoff_increases_with_attempt(self) -> None:
        """Delay should increase exponentially with attempt."""
        delays = [_build_backoff_delay(1.0, i) for i in range(5)]
        for i in range(1, len(delays)):
            assert delays[i] > delays[i - 1] * 0.5  # Should generally increase

    def test_backoff_has_jitter(self) -> None:
        """Delay should vary due to jitter even for same attempt."""
        delays = [_build_backoff_delay(1.0, 2) for _ in range(10)]
        assert len(set(delays)) > 1  # Should have variance

    def test_backoff_base_calculation(self) -> None:
        """Delay should include base * 2^attempt component."""
        delay = _build_backoff_delay(1.0, 0)
        assert 1.0 <= delay <= 1.3  # base + max jitter

        delay = _build_backoff_delay(2.0, 1)
        assert 4.0 <= delay <= 4.3  # 2 * 2^1 + max jitter


class TestExecuteWithBackoff:
    """Tests for execute_with_backoff function."""

    def test_successful_execution_returns_result(self) -> None:
        """Successful function should return result without retry."""
        logger = MagicMock(spec=logging.Logger)
        result = execute_with_backoff(
            operation_name="test_op",
            max_retries=3,
            base_delay_seconds=0.01,
            logger=logger,
            event_type_prefix="test",
            func=lambda: "success",
            should_retry=lambda e: False,
        )
        assert result == "success"
        assert logger.warning.call_count == 0

    def test_retry_on_retryable_error(self) -> None:
        """Should retry when should_retry returns True."""
        logger = MagicMock(spec=logging.Logger)
        attempt_count = 0

        def failing_func():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise ValueError("retryable error")
            return "success"

        result = execute_with_backoff(
            operation_name="test_op",
            max_retries=3,
            base_delay_seconds=0.001,
            logger=logger,
            event_type_prefix="test",
            func=failing_func,
            should_retry=lambda e: isinstance(e, ValueError),
        )
        assert result == "success"
        assert attempt_count == 2
        assert logger.warning.call_count == 1

    def test_max_retries_exceeded_raises(self) -> None:
        """Should raise when max retries exceeded."""
        logger = MagicMock(spec=logging.Logger)

        def always_fails():
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            execute_with_backoff(
                operation_name="test_op",
                max_retries=2,
                base_delay_seconds=0.001,
                logger=logger,
                event_type_prefix="test",
                func=always_fails,
                should_retry=lambda e: True,
            )
        assert logger.warning.call_count == 2

    def test_non_retryable_error_raises_immediately(self) -> None:
        """Should not retry when should_retry returns False."""
        logger = MagicMock(spec=logging.Logger)

        def non_retryable_error():
            raise ValueError("non retryable")

        with pytest.raises(ValueError):
            execute_with_backoff(
                operation_name="test_op",
                max_retries=3,
                base_delay_seconds=0.01,
                logger=logger,
                event_type_prefix="test",
                func=non_retryable_error,
                should_retry=lambda e: False,
            )
        assert logger.warning.call_count == 0
