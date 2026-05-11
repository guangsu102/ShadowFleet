# 告警机制完善实现指南

## 问题分析

### 当前告警机制的问题

查看现有的 Telegram 通知：

**问题**：
1. ❌ 所有告警都是同等级别，无法区分紧急程度
2. ❌ 短时间内大量重复告警（告警风暴）
3. ❌ 没有告警聚合，相同问题重复发送
4. ❌ 无法静默或抑制告警
5. ❌ 缺少告警升级机制

**影响**：
- 告警疲劳：运维人员忽略重要告警
- 信息过载：无法快速定位关键问题
- 响应延迟：重要告警被淹没

---

## 解决方案

### 1. 告警分级系统

```python
# services/alert_manager.py
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
                from services.telegram_notifier import TelegramNotifier
                notifier = TelegramNotifier(self._runtime)
                notifier.send_message(message)
            
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

    def aggregate_alerts(self, time_window_seconds: int = 300) -> list[dict]:
        """
        聚合告警
        
        Args:
            time_window_seconds: 时间窗口（秒）
            
        Returns:
            聚合后的告警列表
        """
        with self._lock:
            now = datetime.utcnow()
            cutoff_time = now - timedelta(seconds=time_window_seconds)
            
            aggregated: dict[str, dict] = {}
            
            for fingerprint, alerts in self._alert_history.items():
                # 过滤时间窗口内的告警
                recent_alerts = [
                    alert for alert in alerts
                    if datetime.fromisoformat(alert.timestamp) > cutoff_time
                ]
                
                if not recent_alerts:
                    continue
                
                # 聚合
                first_alert = recent_alerts[0]
                aggregated[fingerprint] = {
                    "title": first_alert.title,
                    "source": first_alert.source,
                    "severity": first_alert.severity.value,
                    "count": len(recent_alerts),
                    "first_seen": recent_alerts[0].timestamp,
                    "last_seen": recent_alerts[-1].timestamp,
                }
            
            return list(aggregated.values())
```

---

### 2. 使用示例

```python
# 在各个服务中使用 AlertManager

from services.alert_manager import AlertManager, AlertSeverity

# 1. 孤儿资源告警
def send_orphan_alert(runtime_context: RuntimeContext, orphan_count: int):
    alert_manager = AlertManager(runtime_context)
    
    alert_manager.send_alert(
        severity=AlertSeverity.WARNING,
        title="孤儿资源检测告警",
        message=f"检测到 {orphan_count} 个孤儿资源",
        source="orphan_resources",
        labels={
            "count": str(orphan_count),
        },
    )

# 2. 数据库同步告警
def send_sync_alert(runtime_context: RuntimeContext, inconsistency_count: int):
    alert_manager = AlertManager(runtime_context)
    
    alert_manager.send_alert(
        severity=AlertSeverity.ERROR,
        title="数据库同步异常",
        message=f"发现 {inconsistency_count} 个不一致记录",
        source="database_sync",
        labels={
            "inconsistency_count": str(inconsistency_count),
        },
    )

# 3. 熔断器告警
def send_circuit_breaker_alert(runtime_context: RuntimeContext, breaker_name: str):
    alert_manager = AlertManager(runtime_context)
    
    alert_manager.send_alert(
        severity=AlertSeverity.CRITICAL,
        title="熔断器打开",
        message=f"熔断器 {breaker_name} 已打开，服务不可用",
        source="circuit_breaker_open",
        labels={
            "breaker_name": breaker_name,
        },
    )

# 4. Provisioning 失败告警
def send_provisioning_failure_alert(
    runtime_context: RuntimeContext,
    node_name: str,
    error: str,
):
    alert_manager = AlertManager(runtime_context)
    
    alert_manager.send_alert(
        severity=AlertSeverity.ERROR,
        title="节点创建失败",
        message=f"节点 {node_name} 创建失败: {error}",
        source="provisioning_failure",
        labels={
            "node_name": node_name,
        },
    )
```

---

### 3. 添加 API 端点

```python
# api/router/health.py

@router.get("/alerts/stats")
async def get_alert_stats(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> dict:
    """获取告警统计"""
    from services.alert_manager import AlertManager
    
    alert_manager = AlertManager(ctx)
    stats = alert_manager.get_alert_stats()
    
    return {
        "stats": stats,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/alerts/aggregated")
async def get_aggregated_alerts(
    time_window_seconds: int = 300,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> dict:
    """获取聚合后的告警"""
    from services.alert_manager import AlertManager
    
    alert_manager = AlertManager(ctx)
    aggregated = alert_manager.aggregate_alerts(time_window_seconds)
    
    return {
        "alerts": aggregated,
        "time_window_seconds": time_window_seconds,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/alerts/silence")
async def silence_alert(
    request: dict,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> dict:
    """静默告警"""
    from services.alert_manager import AlertManager
    
    alert_manager = AlertManager(ctx)
    
    alert_manager.silence_alert(
        source=request["source"],
        fingerprint=request["fingerprint"],
        duration_seconds=request.get("duration_seconds", 3600),
    )
    
    return {
        "message": "Alert silenced successfully",
        "timestamp": datetime.utcnow().isoformat(),
    }
```

---

### 4. 告警升级机制

```python
# services/alert_escalation.py
"""
告警升级机制

当告警持续一定时间未处理时，自动升级
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from services.alert_manager import Alert, AlertSeverity

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class AlertEscalation:
    """告警升级器"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.alert_escalation")
        
        # 待升级的告警
        self._pending_alerts: dict[str, tuple[Alert, datetime]] = {}
        self._lock = threading.Lock()
        
        # 升级规则（秒）
        self._escalation_rules = {
            AlertSeverity.CRITICAL: 300,   # 5 分钟后升级
            AlertSeverity.ERROR: 1800,     # 30 分钟后升级
            AlertSeverity.WARNING: 3600,   # 1 小时后升级
        }

    def track_alert(self, alert: Alert) -> None:
        """追踪告警（用于升级）"""
        with self._lock:
            self._pending_alerts[alert.fingerprint] = (alert, datetime.utcnow())

    def resolve_alert(self, fingerprint: str) -> None:
        """标记告警已解决"""
        with self._lock:
            if fingerprint in self._pending_alerts:
                del self._pending_alerts[fingerprint]

    def check_escalations(self) -> None:
        """检查是否需要升级告警"""
        with self._lock:
            now = datetime.utcnow()
            
            for fingerprint, (alert, tracked_at) in list(self._pending_alerts.items()):
                # 获取升级时间
                escalation_seconds = self._escalation_rules.get(alert.severity)
                if not escalation_seconds:
                    continue
                
                # 检查是否需要升级
                if (now - tracked_at).total_seconds() > escalation_seconds:
                    self._escalate_alert(alert)
                    # 更新追踪时间
                    self._pending_alerts[fingerprint] = (alert, now)

    def _escalate_alert(self, alert: Alert) -> None:
        """升级告警"""
        self._logger.warning("Escalating alert: %s", alert.title)
        
        # 发送升级通知
        from services.alert_manager import AlertManager
        alert_manager = AlertManager(self._runtime)
        
        alert_manager.send_alert(
            severity=AlertSeverity.CRITICAL,
            title=f"[升级] {alert.title}",
            message=f"告警持续未处理，已自动升级\n\n原始消息:\n{alert.message}",
            source=f"{alert.source}_escalated",
            labels=alert.labels,
        )
```

---

## 使用示例

### 1. 查看告警统计

```bash
curl http://localhost:8000/api/v1/health/alerts/stats \
  -H "Authorization: Bearer <token>"

# 输出：
{
  "stats": {
    "total_alerts": 150,
    "unique_alerts": 25,
    "active_silences": 3
  },
  "timestamp": "2026-05-10T12:00:00.000000"
}
```

### 2. 查看聚合告警

```bash
curl http://localhost:8000/api/v1/health/alerts/aggregated?time_window_seconds=600 \
  -H "Authorization: Bearer <token>"

# 输出：
{
  "alerts": [
    {
      "title": "孤儿资源检测告警",
      "source": "orphan_resources",
      "severity": "warning",
      "count": 5,
      "first_seen": "2026-05-10T11:50:00.000000",
      "last_seen": "2026-05-10T11:59:00.000000"
    },
    {
      "title": "数据库同步异常",
      "source": "database_sync",
      "severity": "error",
      "count": 2,
      "first_seen": "2026-05-10T11:55:00.000000",
      "last_seen": "2026-05-10T11:58:00.000000"
    }
  ],
  "time_window_seconds": 600,
  "timestamp": "2026-05-10T12:00:00.000000"
}
```

### 3. 静默告警

```bash
curl -X POST http://localhost:8000/api/v1/health/alerts/silence \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "orphan_resources",
    "fingerprint": "abc123def456",
    "duration_seconds": 7200
  }'

# 输出：
{
  "message": "Alert silenced successfully",
  "timestamp": "2026-05-10T12:00:00.000000"
}
```

---

## 总结

### 实现的功能

1. ✅ **告警分级**：CRITICAL、ERROR、WARNING、INFO
2. ✅ **告警去重**：基于指纹去重
3. ✅ **告警节流**：防止告警风暴
4. ✅ **告警聚合**：相同告警聚合显示
5. ✅ **告警静默**：手动静默指定告警
6. ✅ **告警升级**：长时间未处理自动升级
7. ✅ **统计信息**：告警统计和历史

### 优先级

**P1 高优先级**，因为：
- 减少告警疲劳
- 提高运维效率
- 实现相对简单（2-3 天）
- 立即改善用户体验
