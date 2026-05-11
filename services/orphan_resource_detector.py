"""
孤儿资源检测服务

负责检测和报告系统中的孤儿资源，包括：
1. EC2 实例：在 AWS 中存在但 SQLite 中无记录
2. DNS 记录：在 Cloudflare 中存在但 SQLite 中无记录
3. 资产分配：SQLite 中标记为 allocated 但对应节点已删除
4. Xboard 节点：在 Xboard 中存在但 SQLite 中无记录
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from database.asset_repo import AssetRepo
from database.state_repo import StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.aws.ec2_client import EC2Client
from infrastructure.cloudflare.cf_client import CFClient
from models.aws_credentials import AwsCredentials
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass(frozen=True)
class OrphanEc2Instance:
    """孤儿 EC2 实例"""
    instance_id: str
    region: str
    account_id: str
    launch_time: str
    state: str
    tags: dict[str, str]


@dataclass(frozen=True)
class OrphanDnsRecord:
    """孤儿 DNS 记录"""
    record_id: str
    domain_name: str
    record_type: str
    content: str
    proxied: bool
    created_on: str


@dataclass(frozen=True)
class OrphanAssetAllocation:
    """孤儿资产分配"""
    allocation_id: int
    asset_id: int
    xboard_node_id: int
    protocol_type: str
    allocated_at: str


@dataclass(frozen=True)
class OrphanXboardNode:
    """孤儿 Xboard 节点"""
    xboard_node_id: int
    node_name: str
    node_type: str
    host: str
    show: bool


@dataclass(frozen=True)
class OrphanResourceReport:
    """孤儿资源检测报告"""
    scan_time: str
    ec2_instances: list[OrphanEc2Instance]
    dns_records: list[OrphanDnsRecord]
    asset_allocations: list[OrphanAssetAllocation]
    xboard_nodes: list[OrphanXboardNode]
    total_count: int


class OrphanResourceDetectorError(RuntimeError):
    pass


class OrphanResourceDetector:
    """孤儿资源检测器"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.orphan_resource_detector")
        self._state_repo = StateRepo(runtime_context)
        self._asset_repo = AssetRepo(runtime_context)
        self._xboard_repo = XboardRepo(runtime_context)

    def scan_all_orphan_resources(
        self,
        scan_ec2: bool = True,
        scan_dns: bool = True,
        scan_allocations: bool = True,
        scan_xboard: bool = True,
    ) -> OrphanResourceReport:
        """
        扫描所有孤儿资源

        Args:
            scan_ec2: 是否扫描 EC2 实例
            scan_dns: 是否扫描 DNS 记录
            scan_allocations: 是否扫描资产分配
            scan_xboard: 是否扫描 Xboard 节点

        Returns:
            孤儿资源报告
        """
        set_event_type("orphan_scan_started")
        self._logger.info("Starting orphan resource scan")

        orphan_ec2_instances: list[OrphanEc2Instance] = []
        orphan_dns_records: list[OrphanDnsRecord] = []
        orphan_allocations: list[OrphanAssetAllocation] = []
        orphan_xboard_nodes: list[OrphanXboardNode] = []

        try:
            if scan_ec2:
                orphan_ec2_instances = self._scan_orphan_ec2_instances()
                self._logger.info("Found %d orphan EC2 instances", len(orphan_ec2_instances))

            if scan_dns:
                orphan_dns_records = self._scan_orphan_dns_records()
                self._logger.info("Found %d orphan DNS records", len(orphan_dns_records))

            if scan_allocations:
                orphan_allocations = self._scan_orphan_asset_allocations()
                self._logger.info("Found %d orphan asset allocations", len(orphan_allocations))

            if scan_xboard:
                orphan_xboard_nodes = self._scan_orphan_xboard_nodes()
                self._logger.info("Found %d orphan Xboard nodes", len(orphan_xboard_nodes))

            total_count = (
                len(orphan_ec2_instances)
                + len(orphan_dns_records)
                + len(orphan_allocations)
                + len(orphan_xboard_nodes)
            )

            report = OrphanResourceReport(
                scan_time=datetime.utcnow().isoformat(),
                ec2_instances=orphan_ec2_instances,
                dns_records=orphan_dns_records,
                asset_allocations=orphan_allocations,
                xboard_nodes=orphan_xboard_nodes,
                total_count=total_count,
            )

            set_event_type("orphan_scan_completed")
            self._logger.info("Orphan resource scan completed: total=%d", total_count)
            return report

        except Exception as exc:
            set_event_type("orphan_scan_failed")
            self._logger.exception("Orphan resource scan failed: %s", exc)
            raise OrphanResourceDetectorError("Failed to scan orphan resources") from exc

    def _scan_orphan_ec2_instances(self) -> list[OrphanEc2Instance]:
        """扫描孤儿 EC2 实例"""
        orphan_instances: list[OrphanEc2Instance] = []

        # 获取所有活跃的 AWS 资产
        active_assets = self._asset_repo.list_assets_by_status("active")
        aws_assets = [a for a in active_assets if a.asset_type == "aws"]

        # 获取 SQLite 中所有节点的 instance_id
        all_nodes = self._state_repo.list_active_nodes()
        known_instance_ids = {
            node.aws_instance_id
            for node in all_nodes
            if node.aws_instance_id is not None
        }

        # 扫描每个 AWS 账号
        for asset in aws_assets:
            try:
                credential = AwsCredentials(
                    account_id=asset.aws_account_id or "",
                    access_key=asset.aws_access_key or "",
                    secret_key=asset.aws_secret_key or "",
                    region=asset.region or "",
                )
                ec2_client = EC2Client(
                    runtime_context=self._runtime,
                    aws_credential=credential,
                )

                # 列出所有 ShadowFleet 管理的实例（通过 tag 识别）
                instances = ec2_client.list_instances_by_tag("ManagedBy", "ShadowFleet")

                for instance in instances:
                    instance_id = instance.get("InstanceId")
                    if instance_id not in known_instance_ids:
                        # 检查实例是否是最近创建的（可能正在 provisioning）
                        launch_time_str = instance.get("LaunchTime", "")
                        if launch_time_str:
                            launch_time = datetime.fromisoformat(launch_time_str.replace("Z", "+00:00"))
                            # 如果实例创建时间超过 1 小时，认为是孤儿
                            if datetime.utcnow() - launch_time.replace(tzinfo=None) > timedelta(hours=1):
                                tags = {
                                    tag["Key"]: tag["Value"]
                                    for tag in instance.get("Tags", [])
                                }
                                orphan_instances.append(
                                    OrphanEc2Instance(
                                        instance_id=instance_id,
                                        region=asset.region or "",
                                        account_id=asset.aws_account_id or "",
                                        launch_time=launch_time_str,
                                        state=instance.get("State", {}).get("Name", "unknown"),
                                        tags=tags,
                                    )
                                )

            except Exception as exc:
                self._logger.warning(
                    "Failed to scan EC2 instances for asset_id=%s: %s",
                    asset.id,
                    exc,
                )

        return orphan_instances

    def _scan_orphan_dns_records(self) -> list[OrphanDnsRecord]:
        """扫描孤儿 DNS 记录"""
        orphan_records: list[OrphanDnsRecord] = []

        if not self._runtime.config.cloudflare.enabled:
            return orphan_records

        try:
            cf_client = CFClient(self._runtime)

            # 获取所有 ShadowFleet 管理的域名（从 SQLite）
            all_nodes = self._state_repo.list_all_nodes_with_domains()
            known_domains = {node.domain_name for node in all_nodes if node.domain_name}

            # 列出 Cloudflare 中所有以 sf- 开头的记录
            root_domain = self._runtime.config.cloudflare.root_domain
            if not root_domain:
                return orphan_records

            all_records = cf_client.list_dns_records()

            for record in all_records:
                record_name = record.get("name", "")
                # 只检查 sf- 开头的子域名
                if record_name.startswith(f"sf-") and record_name.endswith(root_domain):
                    if record_name not in known_domains:
                        orphan_records.append(
                            OrphanDnsRecord(
                                record_id=record.get("id", ""),
                                domain_name=record_name,
                                record_type=record.get("type", ""),
                                content=record.get("content", ""),
                                proxied=record.get("proxied", False),
                                created_on=record.get("created_on", ""),
                            )
                        )

        except Exception as exc:
            self._logger.warning("Failed to scan DNS records: %s", exc)

        return orphan_records

    def _scan_orphan_asset_allocations(self) -> list[OrphanAssetAllocation]:
        """扫描孤儿资产分配"""
        orphan_allocations: list[OrphanAssetAllocation] = []

        # 这个查询需要在 SQLite 中执行
        sql = """
            SELECT
                faa.id,
                faa.asset_id,
                faa.xboard_node_id,
                faa.protocol_type,
                faa.created_at
            FROM fleet_asset_allocations faa
            LEFT JOIN fleet_nodes fn ON fn.xboard_node_id = faa.xboard_node_id
            WHERE faa.allocation_status = 'allocated'
              AND (fn.id IS NULL OR fn.is_deleted = 1)
        """

        try:
            with self._runtime.sqlite_manager.connection() as connection:
                rows = connection.execute(sql).fetchall()

            for row in rows:
                orphan_allocations.append(
                    OrphanAssetAllocation(
                        allocation_id=int(row[0]),
                        asset_id=int(row[1]),
                        xboard_node_id=int(row[2]),
                        protocol_type=str(row[3]),
                        allocated_at=str(row[4]),
                    )
                )

        except Exception as exc:
            self._logger.warning("Failed to scan asset allocations: %s", exc)

        return orphan_allocations

    def _scan_orphan_xboard_nodes(self) -> list[OrphanXboardNode]:
        """扫描孤儿 Xboard 节点"""
        orphan_nodes: list[OrphanXboardNode] = []

        try:
            # 获取 Xboard 中所有 ShadowFleet 节点
            xboard_nodes = self._xboard_repo.list_all_shadowfleet_nodes()

            # 获取 SQLite 中所有节点的 xboard_node_id
            sqlite_nodes = self._state_repo.list_active_nodes()
            known_xboard_ids = {node.xboard_node_id for node in sqlite_nodes}

            for xboard_node in xboard_nodes:
                if xboard_node.node_id not in known_xboard_ids:
                    orphan_nodes.append(
                        OrphanXboardNode(
                            xboard_node_id=xboard_node.node_id,
                            node_name=xboard_node.node_name,
                            node_type=xboard_node.node_type,
                            host=xboard_node.host,
                            show=xboard_node.show,
                        )
                    )

        except Exception as exc:
            self._logger.warning("Failed to scan Xboard nodes: %s", exc)

        return orphan_nodes
