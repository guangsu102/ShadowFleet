"""
告警管理服务

提供告警分级、聚合、去重、静默等功能
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class AlertSeverity(Enum):
    """告警严重级别"""
    CRITICAL = "critical"  # P0 - 严重，需要立即处理
    ERROR = "error"        # P1 - 错误，需要尽快处理
    WARNING = "warning"    # P2 - 警告，需要关注
    INFO = "info"          # P3 - 信息，仅通知


@dataclass(frozen=True)
class Alert:
    """告警"""
    severity: AlertSeverity
    title: str
    message: str
    source: str  # 告警来源（如：provisioning, healing, orphan_cleanup）
    labels: dict[str, str]  # 标签（用于聚合和去重）
    timestamp: str
    fingerprint: str  # 告警指纹（用于去重）


@dataclass
class AlertRule:
    """告警规则"""
    name: str
    severity: AlertSeverity
    throttle_seconds: int  # 节流时间（秒）
    aggregation_window_seconds: int  # 聚合窗口（秒）
    max_alerts_per_window: int  # 窗口内最大告警数


class AlertManager:
    """
    告警管理器

    功能：
    1. 告警分级
    2. 告警去重
    3. 告警聚合
    4. 告警节流
    5. 告警静默
    """

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.alert_manager")

        # 告警历史（用于去重和聚合）
        self._alert_history: dict[str, list[Alert]] = {}

        # 静默规则
        self._silences: dict[str, datetime] = {}

        # 锁
        self._lock = threading.Lock()

        # 告警规则
        self._rules = self._load_alert_rules()

    def _load_alert_rules(self) -> dict[str, AlertRule]:
        """加载告警规则"""
        return {
            "orphan_resources": AlertRule(
                name="orphan_resources",
                severity=AlertSeverity.WARNING,
                throttle_seconds=3600,  # 1 小时内只发送一次
                aggregation_window_seconds=300,  # 5 分钟聚合窗口
                max_alerts_per_window=10,
            ),
            "database_sync": AlertRule(
                name="database_sync",
                severity=AlertSeverity.ERROR,
                throttle_seconds=1800,  # 30 分钟内只发送一次
                aggregation_window_seconds=300,
                max_alerts_per_window=5,
            ),
            "provisioning_failure": AlertRule(
                name="provisioning_failure",
                severity=AlertSeverity.ERROR,
                throttle_seconds=600,  # 10 分钟内只发送一次
                aggregation_window_seconds=300,
                max_alerts_per_window=5,
            ),
            "circuit_breaker_open": AlertRule(
                name="circuit_breaker_open",
                severity=AlertSeverity.CRITICAL,
                throttle_seconds=300,  # 5 分钟内只发送一次
                aggregation_window_seconds=60,
                max_alerts_per_window=3,
            ),
            "domain_health": AlertRule(
                name="domain_health",
                severity=AlertSeverity.WARNING,
                throttle_seconds=1800,
                aggregation_window_seconds=600,
                max_alerts_per_window=10,
            ),
        }

    def send_alert(
        self,
        severity: AlertSeverity,
        title: str,
        message: str,
        source: str,
        labels: dict[str, str] | None = None,
    ) -> bool:
        """
        发送告警

        Args:
            severity: 严重级别
            title: 告警标题
            message: 告警消息
            source: 告警来源
            labels: 标签

        Returns:
            是否发送成功
        """
        if labels is None:
            labels = {}

        # 1. 创建告警
        alert = Alert(
            severity=severity,
            title=title,
            message=message,
            source=source,
            labels=labels,
            timestamp=datetime.utcnow().isoformat(),
            fingerprint=self._generate_fingerprint(title, source, labels),
        )

        # 2. 检查是否被静默
        if self._is_silenced(alert):
            self._logger.debug("Alert is silenced: %s", alert.title)
            return False

        # 3. 检查是否需要去重
        if self._is_duplicate(alert):
            self._logger.debug("Alert is duplicate: %s", alert.title)
            return False

        # 4. 检查是否需要节流
        if self._should_throttle(alert):
            self._logger.debug("Alert is throttled: %s", alert.title)
            return False

        # 5. 记录告警历史
        self._record_alert(alert)

        # 6. 发送告警
        return self._send_alert_impl(alert)

    def _generate_fingerprint(
        self,
        title: str,
        source: str,
        labels: dict[str, str],
    ) -> str:
        """生成告警指纹（用于去重）"""
        # 使用标题、来源和标签生成唯一指纹
        content = f"{title}:{source}:{sorted(labels.items())}"
        return hashlib.md5(content.encode()).hexdigest()

    def _is_silenced(self, alert: Alert) -> bool:
        """检查告警是否被静默"""
        with self._lock:
            silence_key = f"{alert.source}:{alert.fingerprint}"

            if silence_key in self._silences:
                silence_until = self._silences[silence_key]

                if datetime.utcnow() < silence_until:
                    return True
                else:
                    # 静默已过期，删除
                    del self._silences[silence_key]

        return False

    def _is_duplicate(self, alert: Alert) -> bool:
        """检查告警是否重复"""
        with self._lock:
            if alert.fingerprint not in self._alert_history:
                return False

            # 获取最近的告警
            recent_alerts = self._alert_history[alert.fingerprint]

            if not recent_alerts:
                return False

            # 检查最近 5 分钟内是否有相同告警
            last_alert = recent_alerts[-1]
            last_time = datetime.fromisoformat(last_alert.timestamp)
            now = datetime.utcnow()

            if (now - last_time).total_seconds() < 300:  # 5 分钟
                return True

        return False

    def _should_throttle(self, alert: Alert) -> bool:
        """检查是否需要节流"""
        rule = self._rules.get(alert.source)
        if not rule:
            return False

        with self._lock:
            if alert.fingerprint not in self._alert_history:
                return False

            recent_alerts = self._alert_history[alert.fingerprint]

            if not recent_alerts:
                return False

            # 检查节流时间内是否已发送
            last_alert = recent_alerts[-1]
            last_time = datetime.fromisoformat(last_alert.timestamp)
            now = datetime.utcnow()

            if (now - last_time).total_seconds() < rule.throttle_seconds:
                return True

        return False

    def _record_alert(self, alert: Alert) -> None:
        """记录告警历史"""
        with self._lock:
            if alert.fingerprint not in self._alert_history:
                self._alert_history[alert.fingerprint] = []

            self._alert_history[alert.fingerprint].append(alert)

            # 只保留最近 100 条
            if len(self._alert_history[alert.fingerprint]) > 100:
                self._alert_history[alert.fingerprint] = self._alert_history[alert.fingerprint][-100:]

    def _send_alert_impl(self, alert: Alert) -> bool:
        """实际发送告警"""
        try:
            # 根据严重级别选择不同的图标
            severity_emoji = {
                AlertSeverity.CRITICAL: "🚨",
                AlertSeverity.ERROR: "❌",
                AlertSeverity.WARNING: "⚠️",
                AlertSeverity.INFO: "ℹ️",
            }

            emoji = severity_emoji.get(alert.severity, "📢")

            # 构建消息
            message_lines = [
                f"{emoji} **{alert.title}**",
                f"",
                f"**级别**: {alert.severity.value.upper()}",
                f"**来源**: {alert.source}",
                f"**时间**: {alert.timestamp}",
                f"",
                f"{alert.message}",
            ]

            # 添加标签
            if alert.labels:
                message_lines.append("")
                message_lines.append("**标签**:")
                for key, value in alert.labels.items():
                    message_lines.append(f"- {key}: {value}")

            message = "\n".join(message_lines)

            # 发送到 Telegram
            if self._runtime.config.telegram.enabled:
                from models.message_models import TelegramMessage, TelegramNotificationType
                self._runtime.tg_reporter.send(
                    TelegramMessage(
                        type=TelegramNotificationType.SYSTEM_ALERT,
                        level=alert.severity.value.upper(),
                        title=alert.title,
                        body=message,
                    )
                )

            self._logger.info("Alert sent: %s", alert.title)
            return True

        except Exception as exc:
            self._logger.exception("Failed to send alert: %s", exc)
            return False

    def silence_alert(
        self,
        source: str,
        fingerprint: str,
        duration_seconds: int,
    ) -> None:
        """
        静默告警

        Args:
            source: 告警来源
            fingerprint: 告警指纹
            duration_seconds: 静默时长（秒）
        """
        with self._lock:
            silence_key = f"{source}:{fingerprint}"
            silence_until = datetime.utcnow() + timedelta(seconds=duration_seconds)
            self._silences[silence_key] = silence_until

            self._logger.info(
                "Alert silenced: %s until %s",
                silence_key,
                silence_until.isoformat(),
            )

    def get_alert_stats(self) -> dict:
        """获取告警统计"""
        with self._lock:
            total_alerts = sum(len(alerts) for alerts in self._alert_history.values())
            active_silences = sum(
                1 for silence_until in self._silences.values()
                if datetime.utcnow() < silence_until
            )

            return {
                "total_alerts": total_alerts,
                "unique_alerts": len(self._alert_history),
                "active_silences": active_silences,
            }
