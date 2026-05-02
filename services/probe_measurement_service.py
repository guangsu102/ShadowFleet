from __future__ import annotations

from dataclasses import dataclass
import time
from typing import TYPE_CHECKING

from database.probe_models import (
    JsonValue,
    ProbeMeasurementCreateRequest,
    ProbeMeasurementRecord,
    ProbeMeasurementResultCreateRequest,
)
from database.probe_measurement_repo import ProbeMeasurementRepo
from services.monitor_models import MonitorCandidate, ProbeMeasurementSummary, ProbeResult
from utils.logger import generate_correlation_id, set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class ProbeMeasurementServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class MeasurementFinalizeInput:
    candidate: MonitorCandidate
    measurement_record: ProbeMeasurementRecord
    control_plane_result: ProbeResult
    remote_results: list[dict[str, JsonValue]]


@dataclass(frozen=True)
class RemoteResultWaitResult:
    timed_out: bool
    results: list[dict[str, JsonValue]]


class ProbeMeasurementService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._repo = ProbeMeasurementRepo(runtime_context)
        self._logger = runtime_context.logger.getChild("services.probe_measurement")

    def create_measurement(
        self,
        *,
        candidate: MonitorCandidate,
        correlation_id: str,
        control_plane_result: ProbeResult,
    ) -> ProbeMeasurementRecord:
        measurement_id = generate_correlation_id()
        return self._repo.create_measurement(
            ProbeMeasurementCreateRequest(
                measurement_id=measurement_id,
                xboard_node_id=candidate.xboard_node_id,
                correlation_id=correlation_id,
                final_status="collecting",
                reason="collecting_remote_probe_results",
                control_plane_result=self._serialize_probe_result(control_plane_result),
            )
        )

    def record_remote_result(
        self,
        *,
        measurement_id: str,
        probe_id: str,
        result_payload: dict[str, JsonValue],
    ) -> None:
        probe_status = str(result_payload.get("status") or "probe_inconclusive")
        self._repo.create_measurement_result(
            ProbeMeasurementResultCreateRequest(
                measurement_id=measurement_id,
                probe_id=probe_id,
                probe_status=probe_status,
                failure_stage=self._to_optional_text(result_payload.get("failure_stage")),
                resolved_ip=self._to_optional_text(result_payload.get("resolved_ip")),
                latency_ms=self._to_optional_int(result_payload.get("latency_ms")),
                result=result_payload,
            )
        )

    def wait_for_remote_results(
        self,
        *,
        measurement_id: str,
        minimum_result_count: int,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> RemoteResultWaitResult:
        if minimum_result_count <= 0:
            return RemoteResultWaitResult(timed_out=False, results=[])
        deadline = time.monotonic() + timeout_seconds
        while True:
            results = self.list_remote_results(measurement_id)
            if len(results) >= minimum_result_count:
                return RemoteResultWaitResult(timed_out=False, results=results)
            if time.monotonic() >= deadline:
                return RemoteResultWaitResult(timed_out=True, results=results)
            time.sleep(poll_interval_seconds)

    def list_remote_results(self, measurement_id: str) -> list[dict[str, JsonValue]]:
        result_records = self._repo.list_measurement_results(measurement_id)
        return [record.result for record in result_records]

    def list_recent_measurements(self, limit: int = 20) -> list[ProbeMeasurementRecord]:
        return self._repo.list_recent_measurements(limit=limit)

    def list_recent_measurements_for_node(
        self,
        xboard_node_id: int,
        limit: int = 10,
    ) -> list[ProbeMeasurementRecord]:
        return self._repo.list_recent_measurements_for_node(xboard_node_id=xboard_node_id, limit=limit)

    def count_recent_confirmed_blocked_cycles(
        self,
        xboard_node_id: int,
        limit: int,
    ) -> int:
        recent_measurements = self.list_recent_measurements_for_node(xboard_node_id, limit=limit)
        confirmed_cycle_count = 0
        for record in recent_measurements:
            if record.final_status != "confirmed_blocked_by_gfw":
                break
            confirmed_cycle_count += 1
        return confirmed_cycle_count

    def finalize_measurement(
        self,
        *,
        candidate: MonitorCandidate,
        measurement_record: ProbeMeasurementRecord,
        control_plane_result: ProbeResult,
        remote_results: list[dict[str, JsonValue]],
    ) -> ProbeMeasurementSummary:
        app_config = self._runtime_context.config.app
        minimum_probe_count = app_config.sentinel_probe_min_cn_probe_count
        failure_count = sum(
            1
            for result in remote_results
            if str(result.get("status")) != "reachable"
        )
        total_count = len(remote_results)
        failure_ratio = (failure_count / total_count) if total_count > 0 else 0.0
        final_status = "probe_inconclusive"
        reason = "国内探针样本不足"

        if candidate.node_type == "Hysteria2" and not app_config.sentinel_probe_allow_auto_heal_hy2:
            final_status = "probe_inconclusive"
            reason = "Hysteria2 当前仅支持人工复核，不自动确诊或自愈"
        elif app_config.sentinel_probe_mode == "local_active_probe":
            if control_plane_result.status == "reachable":
                final_status = "healthy"
                reason = "控制面本地主动探测成功"
            elif control_plane_result.status in {
                "dns_failed",
                "origin_unreachable",
                "tls_failed",
                "application_unreachable",
            }:
                final_status = "origin_fault"
                reason = "仅控制面探测时判定为源站或接入链路故障"
            else:
                final_status = "probe_inconclusive"
                reason = "仅控制面探测无法确认阻断"
        elif total_count >= minimum_probe_count:
            if control_plane_result.status == "reachable":
                if failure_count == 0:
                    final_status = "healthy"
                    reason = "国内探针均可达"
                elif (
                    failure_count >= minimum_probe_count
                    and failure_ratio >= app_config.sentinel_probe_required_success_ratio
                ):
                    final_status = "confirmed_blocked_by_gfw"
                    reason = "海外可达且国内多探针连续失败"
                else:
                    final_status = "suspected_blocked"
                    reason = "海外可达但国内探针存在失败"
            elif control_plane_result.status in {"origin_unreachable", "tls_failed", "application_unreachable"}:
                final_status = "origin_fault"
                reason = "海外控制面探测已失败，更像源站故障"
            elif control_plane_result.status == "dns_failed":
                final_status = "origin_fault"
                reason = "海外控制面 DNS 解析失败"

        finalized_record = self._repo.finalize_measurement(
            measurement_id=measurement_record.measurement_id,
            final_status=final_status,
            reason=reason,
            control_plane_result=self._serialize_probe_result(control_plane_result),
        )
        set_event_type("probe_measurement_finalized")
        self._logger.info(
            "Finalized probe measurement measurement_id=%s status=%s remote_results=%s",
            finalized_record.measurement_id,
            final_status,
            total_count,
        )
        return ProbeMeasurementSummary(
            measurement_id=finalized_record.measurement_id,
            xboard_node_id=finalized_record.xboard_node_id,
            final_status=finalized_record.final_status,
            reason=finalized_record.reason,
            control_plane_result=finalized_record.control_plane_result,
            probe_result_count=total_count,
            created_at=finalized_record.created_at,
            finished_at=finalized_record.finished_at,
        )

    @staticmethod
    def _serialize_probe_result(result: ProbeResult) -> dict[str, JsonValue]:
        return {
            "provider": result.provider,
            "status": result.status,
            "reason": result.reason,
            "success_region_count": result.success_region_count,
            "failed_region_count": result.failed_region_count,
            "failure_stage": result.failure_stage,
            "resolved_ip": result.resolved_ip,
            "latency_ms": result.latency_ms,
            "raw_payload": result.raw_payload,
        }

    @staticmethod
    def _to_optional_text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _to_optional_int(value: object) -> int | None:
        if value is None:
            return None
        return int(value)
