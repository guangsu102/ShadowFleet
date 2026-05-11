"""
熔断器（Circuit Breaker）实现

保护外部服务调用，防止级联故障
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

T = TypeVar("T")


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"        # 关闭状态，正常通过
    OPEN = "open"            # 打开状态，快速失败
    HALF_OPEN = "half_open"  # 半开状态，试探恢复


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    failure_threshold: int = 5           # 失败阈值（连续失败次数）
    success_threshold: int = 2           # 成功阈值（半开状态需要的成功次数）
    timeout_seconds: int = 60            # 打开状态超时时间（秒）
    half_open_max_calls: int = 3         # 半开状态允许的最大请求数


class CircuitBreakerError(RuntimeError):
    """熔断器错误"""
    pass


class CircuitBreakerOpenError(CircuitBreakerError):
    """熔断器打开错误（快速失败）"""
    pass


class CircuitBreaker:
    """
    熔断器实现

    使用示例：
    ```python
    breaker = CircuitBreaker(
        name="xboard_api",
        failure_threshold=5,
        timeout_seconds=60,
    )

    try:
        result = breaker.call(lambda: xboard_repo.get_node(node_id))
    except CircuitBreakerOpenError:
        # 熔断器打开，快速失败
        logger.warning("Circuit breaker is open, using fallback")
        result = fallback_value
    ```
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout_seconds: int = 60,
        half_open_max_calls: int = 3,
    ) -> None:
        self.name = name
        self.config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            success_threshold=success_threshold,
            timeout_seconds=timeout_seconds,
            half_open_max_calls=half_open_max_calls,
        )

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """获取当前状态"""
        with self._lock:
            return self._state

    def call(self, func: Callable[[], T]) -> T:
        """
        通过熔断器调用函数

        Args:
            func: 要调用的函数

        Returns:
            函数返回值

        Raises:
            CircuitBreakerOpenError: 熔断器打开，快速失败
            Exception: 函数执行失败
        """
        with self._lock:
            current_state = self._state

            # 1. 检查是否需要从 OPEN 转为 HALF_OPEN
            if current_state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    current_state = CircuitState.HALF_OPEN
                else:
                    # 仍然是 OPEN 状态，快速失败
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is OPEN"
                    )

            # 2. HALF_OPEN 状态，限制请求数
            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is HALF_OPEN, max calls reached"
                    )
                self._half_open_calls += 1

        # 3. 执行函数调用（在锁外执行，避免阻塞）
        try:
            result = func()
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """处理成功调用"""
        with self._lock:
            self._failure_count = 0

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1

                # 成功次数达到阈值，转为 CLOSED
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
                    self._half_open_calls = 0

    def _on_failure(self) -> None:
        """处理失败调用"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # 半开状态失败，立即转回 OPEN
                self._state = CircuitState.OPEN
                self._success_count = 0
                self._half_open_calls = 0
            elif self._state == CircuitState.CLOSED:
                # 关闭状态，检查是否达到失败阈值
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN

    def _should_attempt_reset(self) -> bool:
        """判断是否应该尝试重置（从 OPEN 转为 HALF_OPEN）"""
        if self._last_failure_time is None:
            return False

        elapsed = time.time() - self._last_failure_time
        return elapsed >= self.config.timeout_seconds

    def reset(self) -> None:
        """手动重置熔断器"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = None

    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "half_open_calls": self._half_open_calls,
                "last_failure_time": self._last_failure_time,
            }


class CircuitBreakerRegistry:
    """
    熔断器注册表

    管理所有熔断器实例
    """

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
    ) -> CircuitBreaker:
        """获取或创建熔断器"""
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    timeout_seconds=timeout_seconds,
                )
            return self._breakers[name]

    def get_all_stats(self) -> list[dict]:
        """获取所有熔断器的统计信息"""
        with self._lock:
            return [breaker.get_stats() for breaker in self._breakers.values()]

    def reset_all(self) -> None:
        """重置所有熔断器"""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()


# 全局熔断器注册表
_global_registry = CircuitBreakerRegistry()


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    timeout_seconds: int = 60,
) -> CircuitBreaker:
    """获取全局熔断器实例"""
    return _global_registry.get_or_create(name, failure_threshold, timeout_seconds)
