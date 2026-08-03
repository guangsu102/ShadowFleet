from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Literal


RegionProtocolKey = tuple[str, str]  # (region, protocol_type)


@dataclass(frozen=True)
class RegionProtocolGap:
    """Represents a capacity gap for a specific region/protocol combination."""
    region: str
    protocol_type: str
    desired_count: int
    min_alert_threshold: int
    current_online_count: int
    pending_provisioning_tasks: int
    deficit: int
    alert_level: Literal["healthy", "warning", "critical"]


@dataclass
class SchedulerCooldownTracker:
    """Tracks cooldown state for each region/protocol combination to prevent over-scheduling."""
    last_submit_timestamp: dict[RegionProtocolKey, float] = field(default_factory=dict)
    consecutive_failures: dict[RegionProtocolKey, int] = field(default_factory=dict)

    def can_submit(self, key: RegionProtocolKey, cooldown_seconds: float) -> bool:
        import time as _time
        last = self.last_submit_timestamp.get(key, 0.0)
        return (_time.monotonic() - last) >= cooldown_seconds

    def record_submit(self, key: RegionProtocolKey) -> None:
        import time as _time
        self.last_submit_timestamp[key] = _time.monotonic()
        self.consecutive_failures[key] = 0

    def record_failure(self, key: RegionProtocolKey) -> None:
        self.consecutive_failures[key] = self.consecutive_failures.get(key, 0) + 1

    def get_backoff_seconds(self, key: RegionProtocolKey, base_cooldown: float, max_cooldown: float = 300.0) -> float:
        failures = self.consecutive_failures.get(key, 0)
        if failures <= 1:
            return base_cooldown
        if base_cooldown >= max_cooldown:
            return max_cooldown

        max_exponent = math.ceil(math.log2(max_cooldown / base_cooldown))
        exponent = failures - 1
        if exponent >= max_exponent:
            return max_cooldown

        return min(base_cooldown * (2 ** exponent), max_cooldown)


@dataclass(frozen=True)
class SchedulerCycleResult:
    """Result of a single scheduler cycle."""
    cycle_id: str
    timestamp: str
    gaps_analyzed: int
    tasks_submitted: int
    alerts_triggered: int
    gaps: tuple[RegionProtocolGap, ...]
