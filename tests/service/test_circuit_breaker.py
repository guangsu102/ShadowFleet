"""
Unit tests for CircuitBreaker service
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerOpenError,
    CircuitState,
)


class TestCircuitState:
    """Test CircuitState enum."""

    def test_circuit_states(self) -> None:
        """Test all circuit states are defined."""
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestCircuitBreakerConfig:
    """Test CircuitBreakerConfig dataclass."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout_seconds == 60
        assert config.half_open_max_calls == 3

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=1,
            timeout_seconds=30,
            half_open_max_calls=2,
        )
        assert config.failure_threshold == 3
        assert config.success_threshold == 1
        assert config.timeout_seconds == 30
        assert config.half_open_max_calls == 2


class TestCircuitBreakerErrors:
    """Test CircuitBreaker exception classes."""

    def test_circuit_breaker_error(self) -> None:
        """Test CircuitBreakerError can be raised."""
        with pytest.raises(CircuitBreakerError):
            raise CircuitBreakerError("Test error")

    def test_circuit_breaker_open_error(self) -> None:
        """Test CircuitBreakerOpenError can be raised."""
        with pytest.raises(CircuitBreakerOpenError):
            raise CircuitBreakerOpenError("Circuit is open")

    def test_open_error_is_circuit_breaker_error(self) -> None:
        """Test CircuitBreakerOpenError inherits from CircuitBreakerError."""
        assert issubclass(CircuitBreakerOpenError, CircuitBreakerError)


class TestCircuitBreaker:
    """Test CircuitBreaker implementation."""

    def test_initialization_default_config(self) -> None:
        """Test CircuitBreaker initializes with default config."""
        cb = CircuitBreaker(name="test")
        assert cb.name == "test"
        assert cb.state == CircuitState.CLOSED

    def test_initialization_custom_config(self) -> None:
        """Test CircuitBreaker initializes with custom config."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        assert cb.name == "test"
        assert cb.state == CircuitState.CLOSED
        assert cb.config.failure_threshold == 3

    def test_call_success_returns_result(self) -> None:
        """Test successful call returns the result."""
        cb = CircuitBreaker(name="test")

        def success_func() -> str:
            return "success"

        result = cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitState.CLOSED

    def test_call_failure_increments_failure_count(self) -> None:
        """Test failed call increments failure count."""
        cb = CircuitBreaker(name="test", failure_threshold=3)

        def failing_func() -> None:
            raise RuntimeError("Test failure")

        with pytest.raises(RuntimeError):
            cb.call(failing_func)

        assert cb.state == CircuitState.CLOSED

    def test_circuit_opens_after_threshold_failures(self) -> None:
        """Test circuit opens after reaching failure threshold."""
        cb = CircuitBreaker(name="test", failure_threshold=3)

        def failing_func() -> None:
            raise RuntimeError("Test failure")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                cb.call(failing_func)

        assert cb.state == CircuitState.OPEN

    def test_open_circuit_raises_immediately(self) -> None:
        """Test open circuit raises CircuitBreakerOpenError immediately."""
        cb = CircuitBreaker(name="test", failure_threshold=2)

        def failing_func() -> None:
            raise RuntimeError("Test failure")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(failing_func)

        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            cb.call(failing_func)

    def test_circuit_transitions_to_half_open_after_timeout(self) -> None:
        """Test circuit transitions to half-open after timeout."""
        cb = CircuitBreaker(name="test", failure_threshold=2, timeout_seconds=1)

        def failing_func() -> None:
            raise RuntimeError("Test failure")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(failing_func)

        assert cb.state == CircuitState.OPEN

        time.sleep(1.1)

        def success_func() -> str:
            return "success"

        result = cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_closes_after_success_threshold(self) -> None:
        """Test half-open circuit closes after success threshold."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            success_threshold=2,
            timeout_seconds=1,
        )

        def failing_func() -> None:
            raise RuntimeError("Test failure")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(failing_func)

        time.sleep(1.1)

        def success_func() -> str:
            return "success"

        cb.call(success_func)
        assert cb.state == CircuitState.HALF_OPEN

        cb.call(success_func)
        assert cb.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self) -> None:
        """Test half-open circuit reopens on failure."""
        cb = CircuitBreaker(name="test", failure_threshold=2, timeout_seconds=1)

        def failing_func() -> None:
            raise RuntimeError("Test failure")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(failing_func)

        time.sleep(1.1)

        with pytest.raises(RuntimeError):
            cb.call(failing_func)

        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self) -> None:
        """Test successful call resets failure count."""
        cb = CircuitBreaker(name="test", failure_threshold=3)

        def failing_func() -> None:
            raise RuntimeError("Test failure")

        def success_func() -> str:
            return "success"

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(failing_func)

        cb.call(success_func)

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(failing_func)

        assert cb.state == CircuitState.CLOSED

    def test_concurrent_calls_thread_safe(self) -> None:
        """Test circuit breaker is thread-safe."""
        import threading

        cb = CircuitBreaker(name="test", failure_threshold=10)
        results: list[str] = []
        lock = threading.Lock()

        def success_func() -> str:
            return "success"

        def worker() -> None:
            result = cb.call(success_func)
            with lock:
                results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        assert all(r == "success" for r in results)

    def test_call_with_args_and_kwargs(self) -> None:
        """Test circuit breaker passes args correctly."""
        cb = CircuitBreaker(name="test")

        def func_with_args(a: int, b: int) -> int:
            return a + b

        result = cb.call(lambda: func_with_args(1, 2))
        assert result == 3

    def test_get_state(self) -> None:
        """Test get_state returns current state."""
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED

    def test_reset_closes_circuit(self) -> None:
        """Test reset method closes circuit and clears counters."""
        cb = CircuitBreaker(name="test", failure_threshold=2)

        def failing_func() -> None:
            raise RuntimeError("Test failure")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(failing_func)

        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED

        def success_func() -> str:
            return "success"

        result = cb.call(success_func)
        assert result == "success"
