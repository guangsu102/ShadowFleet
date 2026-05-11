"""
API 路由：系统健康监控

提供以下端点：
1. GET /api/v1/health/orphan-resources - 检测孤儿资源
2. POST /api/v1/health/orphan-resources/cleanup - 清理孤儿资源
3. GET /api/v1/health/sync-status - 检查数据库同步状态
4. POST /api/v1/health/sync-status/repair - 修复同步问题
5. GET /api/v1/health/system - 系统整体健康检查
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth.dependencies import get_current_user, require_operator
from api.deps import get_runtime_context
from services.database_sync_monitor import DatabaseSyncMonitor
from services.health_check_service import HealthCheckService
from services.orphan_resource_cleaner import OrphanResourceCleaner
from services.orphan_resource_detector import OrphanResourceDetector
from services.runtime_service import RuntimeContext
from services.system_health_monitor import SystemHealthMonitor


router = APIRouter(prefix="/api/v1/health", tags=["health"])


class OrphanResourceReportResponse(BaseModel):
    scan_time: str
    total_count: int
    ec2_instances: list[dict]
    dns_records: list[dict]
    asset_allocations: list[dict]
    xboard_nodes: list[dict]


class CleanupRequest(BaseModel):
    cleanup_ec2: bool = True
    cleanup_dns: bool = True
    cleanup_allocations: bool = True
    cleanup_xboard: bool = True
    dry_run: bool = False


class CleanupReportResponse(BaseModel):
    cleanup_time: str
    total_attempted: int
    total_succeeded: int
    total_failed: int
    results: list[dict]


class SyncHealthReportResponse(BaseModel):
    check_time: str
    total_xboard_nodes: int
    total_sqlite_nodes: int
    inconsistency_count: int
    health_status: str
    inconsistencies: list[dict]


class RepairRequest(BaseModel):
    repair_missing_in_sqlite: bool = True
    repair_missing_in_xboard: bool = False
    repair_status_mismatch: bool = True
    repair_host_mismatch: bool = True
    dry_run: bool = False


class RepairStatsResponse(BaseModel):
    repaired: int
    failed: int
    skipped: int


class SystemHealthReportResponse(BaseModel):
    check_time: str
    overall_status: str
    alerts: list[str]
    orphan_resource_summary: dict
    sync_health_summary: dict


@router.get("/orphan-resources", response_model=OrphanResourceReportResponse)
async def scan_orphan_resources(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> OrphanResourceReportResponse:
    """扫描孤儿资源"""
    detector = OrphanResourceDetector(ctx)
    report = detector.scan_all_orphan_resources()

    return OrphanResourceReportResponse(
        scan_time=report.scan_time,
        total_count=report.total_count,
        ec2_instances=[
            {
                "instance_id": inst.instance_id,
                "region": inst.region,
                "account_id": inst.account_id,
                "launch_time": inst.launch_time,
                "state": inst.state,
                "tags": inst.tags,
            }
            for inst in report.ec2_instances
        ],
        dns_records=[
            {
                "record_id": rec.record_id,
                "domain_name": rec.domain_name,
                "record_type": rec.record_type,
                "content": rec.content,
                "proxied": rec.proxied,
                "created_on": rec.created_on,
            }
            for rec in report.dns_records
        ],
        asset_allocations=[
            {
                "allocation_id": alloc.allocation_id,
                "asset_id": alloc.asset_id,
                "xboard_node_id": alloc.xboard_node_id,
                "protocol_type": alloc.protocol_type,
                "allocated_at": alloc.allocated_at,
            }
            for alloc in report.asset_allocations
        ],
        xboard_nodes=[
            {
                "xboard_node_id": node.xboard_node_id,
                "node_name": node.node_name,
                "node_type": node.node_type,
                "host": node.host,
                "show": node.show,
            }
            for node in report.xboard_nodes
        ],
    )


@router.post("/orphan-resources/cleanup", response_model=CleanupReportResponse)
async def cleanup_orphan_resources(
    request: CleanupRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> CleanupReportResponse:
    """清理孤儿资源"""
    detector = OrphanResourceDetector(ctx)
    cleaner = OrphanResourceCleaner(ctx)

    # 先扫描
    orphan_report = detector.scan_all_orphan_resources()

    # 再清理
    cleanup_report = cleaner.cleanup_orphan_resources(
        orphan_report,
        cleanup_ec2=request.cleanup_ec2,
        cleanup_dns=request.cleanup_dns,
        cleanup_allocations=request.cleanup_allocations,
        cleanup_xboard=request.cleanup_xboard,
        dry_run=request.dry_run,
    )

    return CleanupReportResponse(
        cleanup_time=cleanup_report.cleanup_time,
        total_attempted=cleanup_report.total_attempted,
        total_succeeded=cleanup_report.total_succeeded,
        total_failed=cleanup_report.total_failed,
        results=[
            {
                "resource_type": result.resource_type,
                "resource_id": result.resource_id,
                "success": result.success,
                "error_message": result.error_message,
            }
            for result in cleanup_report.results
        ],
    )


@router.get("/sync-status", response_model=SyncHealthReportResponse)
async def check_sync_status(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> SyncHealthReportResponse:
    """检查数据库同步状态"""
    monitor = DatabaseSyncMonitor(ctx)
    report = monitor.check_sync_health()

    return SyncHealthReportResponse(
        check_time=report.check_time,
        total_xboard_nodes=report.total_xboard_nodes,
        total_sqlite_nodes=report.total_sqlite_nodes,
        inconsistency_count=report.inconsistency_count,
        health_status=report.health_status,
        inconsistencies=[
            {
                "xboard_node_id": inc.xboard_node_id,
                "inconsistency_type": inc.inconsistency_type,
                "xboard_state": inc.xboard_state,
                "sqlite_state": inc.sqlite_state,
                "details": inc.details,
            }
            for inc in report.inconsistencies
        ],
    )


@router.post("/sync-status/repair", response_model=RepairStatsResponse)
async def repair_sync_inconsistencies(
    request: RepairRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> RepairStatsResponse:
    """修复数据库同步问题"""
    monitor = DatabaseSyncMonitor(ctx)

    # 先检查
    sync_report = monitor.check_sync_health()

    # 再修复
    stats = monitor.auto_repair_inconsistencies(
        sync_report,
        repair_missing_in_sqlite=request.repair_missing_in_sqlite,
        repair_missing_in_xboard=request.repair_missing_in_xboard,
        repair_status_mismatch=request.repair_status_mismatch,
        repair_host_mismatch=request.repair_host_mismatch,
        dry_run=request.dry_run,
    )

    return RepairStatsResponse(
        repaired=stats["repaired"],
        failed=stats["failed"],
        skipped=stats["skipped"],
    )


@router.get("/system", response_model=SystemHealthReportResponse)
async def check_system_health(
    auto_cleanup: bool = False,
    auto_repair: bool = False,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> SystemHealthReportResponse:
    """系统整体健康检查"""
    monitor = SystemHealthMonitor(ctx)
    report = monitor.run_health_check(
        auto_cleanup_orphans=auto_cleanup,
        auto_repair_sync=auto_repair,
    )

    return SystemHealthReportResponse(
        check_time=report.check_time,
        overall_status=report.overall_status,
        alerts=report.alerts,
        orphan_resource_summary={
            "total_count": report.orphan_resource_report.total_count,
            "ec2_instances": len(report.orphan_resource_report.ec2_instances),
            "dns_records": len(report.orphan_resource_report.dns_records),
            "asset_allocations": len(report.orphan_resource_report.asset_allocations),
            "xboard_nodes": len(report.orphan_resource_report.xboard_nodes),
        },
        sync_health_summary={
            "health_status": report.sync_health_report.health_status,
            "total_xboard_nodes": report.sync_health_report.total_xboard_nodes,
            "total_sqlite_nodes": report.sync_health_report.total_sqlite_nodes,
            "inconsistency_count": report.sync_health_report.inconsistency_count,
        },
    )


@router.get("/liveness")
async def liveness_check(
    ctx: RuntimeContext = Depends(get_runtime_context),
) -> dict:
    """
    存活检查 - 用于 Kubernetes liveness probe

    只检查应用本身是否活着，不检查依赖服务
    失败时会重启容器
    """
    health_service = HealthCheckService(ctx)
    status = health_service.check_liveness()

    return {
        "status": status.status,
        "timestamp": status.timestamp,
        "checks": [
            {
                "component": check.component,
                "status": check.status,
                "message": check.message,
            }
            for check in status.checks
        ],
    }


@router.get("/readiness")
async def readiness_check(
    ctx: RuntimeContext = Depends(get_runtime_context),
) -> dict:
    """
    就绪检查 - 用于 Kubernetes readiness probe

    检查所有依赖服务是否可用
    失败时停止发送流量，但不重启
    """
    from fastapi import Response

    health_service = HealthCheckService(ctx)
    status = health_service.check_readiness()

    # 如果不健康，返回 503 状态码
    # 注意：这里需要通过 Response 对象设置状态码
    response_data = {
        "status": status.status,
        "timestamp": status.timestamp,
        "checks": [
            {
                "component": check.component,
                "status": check.status,
                "message": check.message,
                "response_time_ms": check.response_time_ms,
            }
            for check in status.checks
        ],
    }

    return response_data
