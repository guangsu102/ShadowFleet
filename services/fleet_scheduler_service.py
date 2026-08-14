from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from decimal import Decimal
import time

from database.asset_repo import AssetRepo
from database.provisioning_task_repo import ProvisioningTaskCreateRequest, ProvisioningTaskRepo
from database.state_repo import StateRepo
from services.asset_selector_service import AssetSelectorService, AssetSelectionError, AssetSelectionRequest
from services.fleet_scheduler_models import (
    RegionProtocolGap,
    SchedulerCooldownTracker,
    SchedulerCycleResult,
)
from services.provisioning_models import ProvisionRequest
from services.runtime_service import RuntimeContext
from models.config_models import AppConfig, FleetSchedulerConfig
from utils.logger import generate_correlation_id, set_correlation_id, set_event_type


class FleetSchedulerServiceError(RuntimeError):
    pass


class FleetSchedulerService:
    """Fleet Auto-Scheduler: automatically replenishes nodes to match desired counts."""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.fleet_scheduler")
        self._state_repo = StateRepo(runtime_context)
        self._task_repo = ProvisioningTaskRepo(runtime_context)
        self._asset_repo = AssetRepo(runtime_context)
        self._asset_selector = AssetSelectorService(runtime_context)
        self._cooldown = SchedulerCooldownTracker()
        self._cycle_counter = 0
        self._cached_group_ids: list[int] | None = None

    def run_scheduler_cycle(self, triggered_by: str = "scheduled") -> SchedulerCycleResult:
        """Execute one scheduler cycle. Returns the result with gap analysis and submitted tasks."""
        correlation_id = generate_correlation_id()
        original_correlation_id = self._runtime.correlation_id
        set_correlation_id(correlation_id)

        self._cycle_counter += 1
        cycle_id = f"sch-{int(time.time())}-{self._cycle_counter}"
        timestamp = self._runtime_context_timestamp()

        try:
            set_event_type("scheduler_cycle_started")
            gaps = self._calculate_all_gaps()
            tasks_submitted = 0
            alerts_triggered = 0

            for gap in gaps:
                if gap.deficit <= 0:
                    continue

                key = (gap.region, gap.protocol_type)
                cooldown = self._cooldown.get_backoff_seconds(
                    key,
                    base_cooldown=self._config.cooldown_seconds,
                )
                if not self._cooldown.can_submit(key, cooldown):
                    self._logger.debug(
                        "Skipping %s/%s: in cooldown (%.1fs remaining)",
                        gap.region,
                        gap.protocol_type,
                        cooldown,
                    )
                    continue

                if tasks_submitted >= self._config.max_tasks_per_cycle:
                    self._logger.info(
                        "Reached max tasks per cycle (%d), stopping submission",
                        self._config.max_tasks_per_cycle,
                    )
                    break

                task_id = self._submit_provisioning_task(gap)
                if task_id is not None:
                    tasks_submitted += 1
                    self._cooldown.record_submit(key)
                    self._logger.info(
                        "Scheduled node for %s/%s gap=%d task_id=%d",
                        gap.region,
                        gap.protocol_type,
                        gap.deficit,
                        task_id,
                    )
                else:
                    self._cooldown.record_failure(key)
                    if gap.alert_level == "critical":
                        alerts_triggered += 1
                        self._logger.warning(
                            "Critical gap but failed to submit: %s/%s (online=%d, desired=%d, deficit=%d)",
                            gap.region,
                            gap.protocol_type,
                            gap.current_online_count,
                            gap.desired_count,
                            gap.deficit,
                        )

            if tasks_submitted > 0:
                set_event_type("scheduler_tasks_submitted")
            else:
                set_event_type("scheduler_cycle_idle")

            self._logger.info(
                "Scheduler cycle completed cycle_id=%s gaps=%d tasks=%d alerts=%d triggered_by=%s",
                cycle_id,
                len(gaps),
                tasks_submitted,
                alerts_triggered,
                triggered_by,
            )

            return SchedulerCycleResult(
                cycle_id=cycle_id,
                timestamp=timestamp,
                gaps_analyzed=len(gaps),
                tasks_submitted=tasks_submitted,
                alerts_triggered=alerts_triggered,
                gaps=tuple(gaps),
            )

        finally:
            set_correlation_id(original_correlation_id)
            set_event_type("general")

    def fill_gap_for_region_protocol(
        self,
        region: str,
        protocol_type: str,
        count: int = 1,
        reason: str = "abandonment_replenishment",
    ) -> list[int]:
        """
        Manually trigger replenishment for a specific region/protocol.
        Used after account abandonment to quickly fill capacity gaps.
        Returns list of submitted task IDs.
        """
        task_ids: list[int] = []

        for i in range(count):
            gap = self._calculate_single_gap(region, protocol_type)
            if gap is None or gap.deficit <= 0:
                self._logger.info(
                    "No gap to fill for %s/%s (current=%d, desired=%d)",
                    region,
                    protocol_type,
                    gap.current_online_count if gap else 0,
                    gap.desired_count if gap else 0,
                )
                break

            key = (region, protocol_type)
            task_id = self._submit_provisioning_task(gap, reason=reason)
            if task_id is not None:
                task_ids.append(task_id)
                self._cooldown.record_submit(key)
                self._logger.info(
                    "Emergency fill for %s/%s: submitted task_id=%d (%d/%d)",
                    region,
                    protocol_type,
                    task_id,
                    i + 1,
                    count,
                )
            else:
                self._cooldown.record_failure(key)
                self._logger.warning(
                    "Failed to submit emergency fill task for %s/%s",
                    region,
                    protocol_type,
                )
                break

        return task_ids

    def _runtime_context_timestamp(self) -> str:
        from services.monitor_support import utcnow
        return utcnow()

    def _calculate_all_gaps(self) -> list[RegionProtocolGap]:
        """Calculate capacity gaps for all region/protocol combinations in fleet_matrix."""
        gaps: list[RegionProtocolGap] = []

        current_online = self._get_online_node_counts()
        pending_tasks = self._get_pending_task_counts()
        current_config = self._get_current_config()

        for region, protocol_map in current_config.fleet_matrix.items():
            if not self._is_region_enabled(region):
                continue

            for protocol, protocol_config in protocol_map.items():
                if not self._is_protocol_enabled(protocol):
                    continue

                key = (region, protocol)
                online_count = current_online.get(key, 0)
                pending = pending_tasks.get(key, 0)
                deficit = max(protocol_config.desired_count - online_count - pending, 0)

                alert_level = self._calculate_alert_level(
                    online_count,
                    protocol_config.min_alert_threshold,
                    protocol_config.desired_count,
                )

                gaps.append(
                    RegionProtocolGap(
                        region=region,
                        protocol_type=protocol,
                        desired_count=protocol_config.desired_count,
                        min_alert_threshold=protocol_config.min_alert_threshold,
                        current_online_count=online_count,
                        pending_provisioning_tasks=pending,
                        deficit=deficit,
                        alert_level=alert_level,
                    )
                )

        return gaps

    def _calculate_single_gap(self, region: str, protocol_type: str) -> RegionProtocolGap | None:
        """Calculate gap for a specific region/protocol combination."""
        current_config = self._get_current_config()
        protocol_map = current_config.fleet_matrix.get(region)
        if protocol_map is None:
            return None

        protocol_config = protocol_map.get(protocol_type)
        if protocol_config is None:
            return None

        current_online = self._get_online_node_counts()
        pending_tasks = self._get_pending_task_counts()
        key = (region, protocol_type)

        online_count = current_online.get(key, 0)
        pending = pending_tasks.get(key, 0)
        deficit = max(protocol_config.desired_count - online_count - pending, 0)

        alert_level = self._calculate_alert_level(
            online_count,
            protocol_config.min_alert_threshold,
            protocol_config.desired_count,
        )

        return RegionProtocolGap(
            region=region,
            protocol_type=protocol_type,
            desired_count=protocol_config.desired_count,
            min_alert_threshold=protocol_config.min_alert_threshold,
            current_online_count=online_count,
            pending_provisioning_tasks=pending,
            deficit=deficit,
            alert_level=alert_level,
        )

    def _get_online_node_counts(self) -> dict[tuple[str, str], int]:
        """
        Get count of online nodes grouped by (region, protocol).

        IMPORTANT: Count nodes with status='online' OR 'healing'.
        - Nodes in 'provisioning' status are NOT counted as online capacity.
        - Nodes in 'healing' status ARE counted because they are temporarily being repaired
          and will return to online status. We should NOT create new nodes to replace them.
        This prevents the scheduler from thinking capacity exists when nodes are still being created,
        while avoiding duplicate node creation when existing nodes are being healed.
        """
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for node in self._state_repo.list_active_nodes():
            if node.status not in ("online", "healing"):
                continue
            region = node.aws_region or "unknown"
            protocol = node.node_type
            counts[(region, protocol)] += 1
        return counts

    def _get_pending_task_counts(self) -> dict[tuple[str, str], int]:
        """
        Get count of pending capacity grouped by (region, protocol).

        CRITICAL FIX: Count both:
        1. Provisioning tasks in 'queued' or 'running' status
        2. Fleet nodes in 'provisioning' status (task succeeded but node not yet online)

        This prevents the scheduler from creating duplicate tasks when nodes are
        transitioning from task completion to online status.
        """
        counts: dict[tuple[str, str], int] = defaultdict(int)

        # Count provisioning tasks that are still in progress
        for task in self._task_repo.list_recent_tasks(limit=1000):
            if task.status not in ("queued", "running"):
                continue
            payload = task.request_payload
            region = payload.get("region", "unknown")
            protocol = payload.get("protocol_type", "unknown")
            counts[(region, protocol)] += 1

        # Count nodes in provisioning status (task succeeded but node not yet online)
        for node in self._state_repo.list_active_nodes():
            if node.status != "provisioning":
                continue
            region = node.aws_region or "unknown"
            protocol = node.node_type
            counts[(region, protocol)] += 1

        return counts

    def _submit_provisioning_task(
        self,
        gap: RegionProtocolGap,
        reason: str = "scheduled",
    ) -> int | None:
        """Submit a provisioning task to fill a capacity gap."""
        try:
            asset_result = self._select_cloud_asset_for_gap(gap)

            node_name = self._generate_unique_node_name(gap.region, gap.protocol_type)

            # 根据协议类型设置默认配置
            protocol_defaults = self._get_protocol_defaults(gap.protocol_type)

            # 自动查询所有权限组 ID
            group_ids = self._get_all_group_ids()

            request = ProvisionRequest(
                protocol_type=gap.protocol_type,
                node_name=node_name,
                port="443",
                server_port=443,
                rate=Decimal("100"),
                asset_type=asset_result.asset_type,
                region=gap.region,
                require_cdn_proxy=False,
                cert_mode="dns",
                status_reason=f"Auto-scheduled: {reason}",
                # 添加协议特定字段
                sni_domain=protocol_defaults.get("sni_domain"),
                reality_dest=protocol_defaults.get("reality_dest"),
                allow_insecure=protocol_defaults.get("allow_insecure", True),
                network=protocol_defaults.get("network", "grpc"),
                flow=protocol_defaults.get("flow"),
                # Reality 密钥留空，让 NodeAutoConfigService 自动生成
                reality_private_key=None,
                reality_public_key=None,
                # 使用自动查询的所有权限组 ID
                group_ids=group_ids if group_ids else None,
            )

            correlation_id = generate_correlation_id()
            task_id = self._task_repo.create_task(
                ProvisioningTaskCreateRequest(
                    correlation_id=correlation_id,
                    request_payload=self._serialize_request(request),
                    max_attempts=self._runtime.config.app.max_retries + 1,
                )
            )

            self._logger.info(
                "Created provisioning task id=%d for %s/%s node=%s reason=%s",
                task_id,
                gap.region,
                gap.protocol_type,
                node_name,
                reason,
            )
            return task_id

        except Exception as exc:
            self._logger.exception(
                "Failed to submit provisioning task for %s/%s: %s",
                gap.region,
                gap.protocol_type,
                exc,
            )
            return None

    def _select_cloud_asset_for_gap(self, gap: RegionProtocolGap):
        last_error: AssetSelectionError | None = None
        for asset_type in self._enabled_cloud_asset_types():
            try:
                return self._asset_selector.select_asset(
                    AssetSelectionRequest(
                        protocol_type=gap.protocol_type,
                        asset_type=asset_type,
                        region=gap.region,
                        require_cdn_proxy=False,
                    )
                )
            except AssetSelectionError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise FleetSchedulerServiceError("No cloud asset types configured for scheduling")

    def _enabled_cloud_asset_types(self) -> tuple[str, ...]:
        configured = getattr(self._config, "enabled_asset_types", None)
        if not isinstance(configured, (list, tuple)):
            return ("digitalocean", "vultr", "azure", "oci", "kamatera", "aws")

        enabled: list[str] = []
        for asset_type in configured:
            if asset_type not in ("digitalocean", "vultr", "azure", "oci", "kamatera", "aws"):
                continue
            if asset_type not in enabled:
                enabled.append(asset_type)
        return tuple(enabled)

    def _generate_unique_node_name(self, region: str, protocol_type: str) -> str:
        """Generate a unique node name for auto-provisioned nodes."""
        region_prefix_map = {
            "ap-northeast-1": "jpt",
            "ap-northeast-2": "krs",
            "ap-northeast-3": "jpo",
            "ap-east-1": "hkh",
            "us-west-1": "usl",
            "us-west-2": "uso",
            "us-east-1": "use",
            "ap-southeast-1": "sgp",
            "ap-southeast-2": "syd",
            "eu-west-1": "eui",
            "eu-central-1": "euf",
        }
        protocol_prefix_map = {
            "AnyTLS": "atl",
            "Trojan": "tro",
            "vless": "vls",
            "vmess": "vms",
            "Hysteria2": "hy2",
        }

        # Use mapped prefix or sanitize unknown region (replace hyphens and truncate)
        if region in region_prefix_map:
            rp = region_prefix_map[region]
        else:
            # Sanitize unknown region: remove hyphens and take first 3 chars
            rp = region.replace("-", "").replace("_", "")[:3].lower()

        pp = protocol_prefix_map.get(protocol_type, protocol_type[:3].lower())

        timestamp = int(time.time())
        suffix = abs(hash(f"{region}{protocol_type}{timestamp}")) % 10000

        return f"sf-{rp}-{pp}-{timestamp % 100:02d}{suffix:04d}"

    def _serialize_request(self, request: ProvisionRequest) -> dict:
        """Serialize ProvisionRequest for task storage."""
        return {
            "protocol_type": request.protocol_type,
            "node_name": request.node_name,
            "port": request.port,
            "server_port": request.server_port,
            "rate": str(request.rate),
            "asset_type": request.asset_type,
            "region": request.region,
            "domain_name": request.domain_name,
            "require_cdn_proxy": request.require_cdn_proxy,
            "cert_mode": request.cert_mode,
            "cert_domain": request.cert_domain,
            "cert_provider": request.cert_provider,
            "cert_email": request.cert_email,
            "cert_dns_env": request.cert_dns_env,
            "code": request.code,
            "parent_id": request.parent_id,
            "group_ids": request.group_ids,
            "route_ids": request.route_ids,
            "tags": request.tags,
            "protocol_settings": request.protocol_settings,
            "show": request.show,
            "sort": request.sort,
            "rate_time_enable": request.rate_time_enable,
            "rate_time_ranges": request.rate_time_ranges,
            "status_reason": request.status_reason,
            # Protocol-specific fields
            "sni_domain": request.sni_domain,
            "reality_private_key": request.reality_private_key,
            "reality_public_key": request.reality_public_key,
            "reality_dest": request.reality_dest,
            "allow_insecure": request.allow_insecure,
            "network": request.network,
            "flow": request.flow,
            # SSH fields
            "ssh_host": request.ssh_host,
            "ssh_port": request.ssh_port,
            "ssh_username": request.ssh_username,
            "ssh_password": request.ssh_password,
            "ssh_private_key": request.ssh_private_key,
        }

    def _get_protocol_defaults(self, protocol_type: str) -> dict[str, str | bool]:
        """获取协议的默认配置"""
        protocol_type_lower = protocol_type.lower()

        if protocol_type_lower == "anytls":
            return {
                "sni_domain": "www.bilibili.com",
                "allow_insecure": True,
            }
        elif protocol_type_lower == "trojan":
            return {
                "sni_domain": "www.bilibili.com",
                "allow_insecure": True,
                "network": "grpc",
            }
        elif protocol_type_lower == "vmess":
            return {
                "sni_domain": "www.bilibili.com",
                "allow_insecure": True,
                "network": "grpc",
            }
        elif protocol_type_lower == "vless":
            return {
                "sni_domain": "www.bilibili.com",
                "reality_dest": "www.bilibili.com",
                "allow_insecure": True,
                "network": "grpc",
                "flow": "xtls-rprx-vision",
            }
        else:
            return {}

    def _get_all_group_ids(self) -> list[int]:
        """查询 Xboard 数据库中的所有权限组 ID（带缓存）"""
        if self._cached_group_ids is not None:
            return self._cached_group_ids

        try:
            from database.xboard_repo import XboardRepo
            xboard_repo = XboardRepo(self._runtime)
            group_ids = xboard_repo.get_all_group_ids()
            self._logger.info(
                "Loaded %d group IDs from Xboard: %s",
                len(group_ids),
                group_ids,
            )
            self._cached_group_ids = group_ids
            return group_ids
        except Exception as e:
            self._logger.warning(
                "Failed to query group IDs from Xboard: %s, using empty list",
                e,
            )
            self._cached_group_ids = []
            return []

    def _is_region_enabled(self, region: str) -> bool:
        """Check if a region is enabled for scheduling."""
        enabled = self._config.enabled_regions
        if "*" in enabled:
            return True
        return region in enabled

    def _is_protocol_enabled(self, protocol: str) -> bool:
        """Check if a protocol is enabled for scheduling."""
        enabled = self._config.enabled_protocols
        if "*" in enabled:
            return True
        return protocol in enabled

    @staticmethod
    def _calculate_alert_level(
        online_count: int,
        min_threshold: int,
        desired_count: int,
    ) -> str:
        """Calculate alert level based on online count vs thresholds."""
        if online_count < min_threshold:
            return "critical"
        if online_count < desired_count:
            return "warning"
        return "healthy"

    @property
    def _config(self) -> "FleetSchedulerConfig":
        """Get current fleet scheduler config from holder (supports hot-reload)."""
        if self._runtime.config_holder is not None:
            return self._runtime.config_holder.config.fleet_scheduler
        return self._runtime.config.fleet_scheduler

    def _get_current_config(self) -> "AppConfig":
        """Get the current AppConfig (supports hot-reload)."""
        if self._runtime.config_holder is not None:
            return self._runtime.config_holder.config
        return self._runtime.config

    @property
    def _runtime_context(self) -> RuntimeContext:
        return self._runtime
