from __future__ import annotations

from database.monitor_repo import MonitorRepo
from database.state_repo import FleetNodeEventCreateRequest, StateRepo
from services.healer_service import HealerService
from services.healing_models import HealRequest
from services.monitor_models import (
    MonitorCandidate,
    MonitorCycleResult,
    MonitorServiceError,
    ProbeResult,
)
from services.monitor_support import is_in_heal_cooldown, should_flag_zero_uplink, to_monitor_candidate, utcnow
from services.probe_client import ProbeClient, ProbeClientError
from services.probe_orchestrator_service import ProbeOrchestratorService, ProbeOrchestratorServiceError
from services.runtime_service import RuntimeContext
from services.xboard_sentinel_client import XboardSentinelClient, XboardSentinelClientError
from utils.logger import generate_correlation_id, set_correlation_id, set_event_type


class MonitorService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.monitor")
        self._state_repo = StateRepo(runtime_context)
        self._xboard_client = XboardSentinelClient(runtime_context)
        self._monitor_repo = MonitorRepo(runtime_context)
        self._probe_client = ProbeClient(runtime_context)
        self._probe_orchestrator = ProbeOrchestratorService(runtime_context)
        self._healer_service = HealerService(runtime_context)

    def run_scan_cycle(self) -> MonitorCycleResult:
        correlation_id = generate_correlation_id()
        original_correlation_id = self._runtime_context.correlation_id
        set_correlation_id(correlation_id)
        cycle_id = self._monitor_repo.create_cycle(correlation_id)
        candidate_count = 0
        confirmed_count = 0
        healed_count = 0
        failed_count = 0

        try:
            set_event_type("monitor_cycle_started")
            candidates = self.collect_suspicious_nodes(cycle_id=cycle_id)
            candidate_count = len(candidates)
            for candidate in candidates:
                try:
                    probe_result = self._probe_candidate(candidate, cycle_id=cycle_id)
                except ProbeClientError as exc:
                    failed_count += 1
                    self._record_detection(
                        cycle_id=cycle_id,
                        candidate=candidate,
                        detection_type="probe",
                        detection_status="failed",
                        reason=str(exc),
                        payload=None,
                    )
                    continue

                try:
                    orchestration_result = self._probe_orchestrator.measure_candidate(
                        candidate=candidate,
                        control_plane_result=probe_result,
                        correlation_id=self._runtime_context.correlation_id,
                    )
                except ProbeOrchestratorServiceError as exc:
                    failed_count += 1
                    self._record_detection(
                        cycle_id=cycle_id,
                        candidate=candidate,
                        detection_type="probe_measurement",
                        detection_status="failed",
                        reason=str(exc),
                        payload=self._serialize_probe_result(probe_result),
                    )
                    continue

                measurement_summary = orchestration_result.measurement_summary
                self._record_detection(
                    cycle_id=cycle_id,
                    candidate=candidate,
                    detection_type="probe_measurement",
                    detection_status=measurement_summary.final_status,
                    reason=measurement_summary.reason,
                    payload={
                        "measurement_id": measurement_summary.measurement_id,
                        "control_plane_result": self._serialize_probe_result(probe_result),
                        "selected_probe_ids": list(orchestration_result.selected_probe_ids),
                        "probe_result_count": measurement_summary.probe_result_count,
                    },
                )

                # Determine if we should trigger healing based on mode and final_status
                should_heal = measurement_summary.final_status == "confirmed_blocked_by_gfw"
                if not should_heal and self._runtime_context.config.app.sentinel_probe_mode == "local_active_probe":
                    should_heal = measurement_summary.final_status == "origin_fault"

                if not should_heal:
                    continue

                confirmed_count += 1
                confirm_cycles = self._runtime_context.config.app.sentinel_probe_confirm_cycles
                if (
                    self._runtime_context.config.app.sentinel_probe_mode == "local_active_probe"
                    and measurement_summary.final_status == "origin_fault"
                ):
                    # local_active_probe 模式：统计 origin_fault 周期数
                    confirmed_cycles = self._probe_orchestrator.count_recent_failed_cycles(
                        xboard_node_id=candidate.xboard_node_id,
                        limit=confirm_cycles,
                        status_filter="origin_fault",
                    )
                else:
                    # cn_probe_mesh 模式：统计 confirmed_blocked_by_gfw 周期数
                    confirmed_cycles = self._probe_orchestrator.count_recent_confirmed_blocked_cycles(
                        xboard_node_id=candidate.xboard_node_id,
                        limit=confirm_cycles,
                    )
                if confirmed_cycles < confirm_cycles:
                    node_record = self._state_repo.get_node_by_xboard_node_id(candidate.xboard_node_id)
                    if node_record is None:
                        raise MonitorServiceError(
                            f"Fleet node not found during confirm-cycle accumulation: "
                            f"xboard_node_id={candidate.xboard_node_id}"
                        )
                    self._state_repo.create_event(
                        FleetNodeEventCreateRequest(
                            node_id=node_record.id,
                            xboard_node_id=candidate.xboard_node_id,
                            event_type="monitor_confirm_cycle_accumulating",
                            correlation_id=self._runtime_context.correlation_id,
                            from_status=node_record.status,
                            to_status=node_record.status,
                            message=(
                                f"已确认阻断周期数={confirmed_cycles}/{confirm_cycles}，"
                                "尚未达到自动自愈阈值"
                            ),
                            payload={"measurement_id": measurement_summary.measurement_id},
                        )
                    )
                    continue
                try:
                    heal_reason = (
                        "sentinel_local_origin_fault"
                        if self._runtime_context.config.app.sentinel_probe_mode == "local_active_probe"
                        and measurement_summary.final_status == "origin_fault"
                        else "sentinel_cn_probe_confirmed_blocked"
                    )
                    self._healer_service.heal_node(
                        HealRequest(
                            xboard_node_id=candidate.xboard_node_id,
                            reason=heal_reason,
                            source="sentinel",
                            measurement_payload={
                                "measurement_id": measurement_summary.measurement_id,
                                "final_status": measurement_summary.final_status,
                                "reason": measurement_summary.reason,
                                "control_plane_result": self._serialize_probe_result(probe_result),
                            },
                        )
                    )
                    healed_count += 1
                except Exception:
                    failed_count += 1
                    self._logger.exception(
                        "Healing triggered by monitor failed xboard_node_id=%s",
                        candidate.xboard_node_id,
                    )

            self._monitor_repo.finalize_cycle(
                cycle_id=cycle_id,
                status="succeeded",
                candidate_count=candidate_count,
                confirmed_count=confirmed_count,
                healed_count=healed_count,
                failed_count=failed_count,
            )
            set_event_type("monitor_cycle_completed")
            self._logger.info(
                "Monitor cycle completed cycle_id=%s candidates=%s confirmed=%s healed=%s failed=%s",
                cycle_id,
                candidate_count,
                confirmed_count,
                healed_count,
                failed_count,
            )
            self._monitor_repo.prune_successful_detections(keep_count=30)
            return MonitorCycleResult(
                cycle_id=cycle_id,
                candidate_count=candidate_count,
                confirmed_count=confirmed_count,
                healed_count=healed_count,
                failed_count=failed_count,
            )
        except Exception as exc:
            self._monitor_repo.finalize_cycle(
                cycle_id=cycle_id,
                status="failed",
                candidate_count=candidate_count,
                confirmed_count=confirmed_count,
                healed_count=healed_count,
                failed_count=failed_count + 1,
                error_message=str(exc),
            )
            set_event_type("monitor_cycle_failed")
            self._logger.exception("Monitor cycle failed cycle_id=%s", cycle_id)
            raise
        finally:
            set_correlation_id(original_correlation_id)
            set_event_type("general")

    def collect_suspicious_nodes(self, *, cycle_id: int) -> list[MonitorCandidate]:
        now_utc = utcnow()
        config = self._runtime_context.config.app
        lookback_minutes = config.sentinel_suspicious_lookback_minutes
        zero_window_minutes = config.sentinel_zero_uplink_window_minutes
        candidates: list[MonitorCandidate] = []

        for node_record in self._state_repo.list_monitorable_nodes():
            if is_in_heal_cooldown(
                node_record,
                now_utc=now_utc,
                cooldown_seconds=config.sentinel_heal_cooldown_seconds,
            ):
                continue
            try:
                stats = self._xboard_client.get_server_minute_stats(
                    server_id=node_record.xboard_node_id,
                    server_type=node_record.node_type,
                    lookback_minutes=lookback_minutes,
                )
            except XboardSentinelClientError:
                self._logger.exception(
                    "Failed to load Xboard minute stats via API xboard_node_id=%s",
                    node_record.xboard_node_id,
                )
                raise

            if not stats:
                continue
            recent_total_positive = any(sample.total_bytes > 0 for sample in stats)
            recent_zero_uplink_count = sum(
                1
                for sample in stats[-zero_window_minutes:]
                if sample.uplink_bytes == 0
            )
            if not should_flag_zero_uplink(
                recent_total_positive=recent_total_positive,
                recent_zero_uplink_count=recent_zero_uplink_count,
                expected_zero_window_minutes=zero_window_minutes,
            ):
                continue

            try:
                xboard_runtime = self._xboard_client.get_server_runtime(
                    server_id=node_record.xboard_node_id
                )
            except XboardSentinelClientError:
                self._logger.exception(
                    "Failed to load Xboard runtime metadata via API xboard_node_id=%s",
                    node_record.xboard_node_id,
                )
                raise

            candidate = to_monitor_candidate(node_record, xboard_runtime)
            candidates.append(candidate)

            # Calculate aggregate traffic from the last N minutes
            recent_samples = stats[-zero_window_minutes:] if len(stats) >= zero_window_minutes else stats
            total_uplink = sum(s.uplink_bytes for s in recent_samples)
            total_downlink = sum(s.downlink_bytes for s in recent_samples)
            total_bytes = sum(s.total_bytes for s in recent_samples)

            self._record_detection(
                cycle_id=cycle_id,
                candidate=candidate,
                detection_type="traffic_anomaly",
                detection_status="candidate",
                reason="历史活跃且最近窗口内上行流量归零",
                payload={
                    "recent_total_positive": recent_total_positive,
                    "recent_zero_uplink_count": recent_zero_uplink_count,
                    "zero_window_minutes": zero_window_minutes,
                    "uplink_bytes": total_uplink,
                    "downlink_bytes": total_downlink,
                    "total_bytes": total_bytes,
                    "sample_count": len(recent_samples),
                },
            )
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=node_record.xboard_node_id,
                    event_type="monitor_candidate_detected",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=node_record.status,
                    to_status=node_record.status,
                    message="Sentinel detected a suspicious traffic pattern.",
                    payload={
                        "recent_zero_uplink_count": recent_zero_uplink_count,
                        "zero_window_minutes": zero_window_minutes,
                    },
                )
            )
        return candidates

    def _probe_candidate(self, candidate: MonitorCandidate, *, cycle_id: int) -> ProbeResult:
        set_event_type("monitor_probe_started")
        result = self._probe_client.probe_node(candidate)
        set_event_type("monitor_probe_completed")
        return result

    @staticmethod
    def _serialize_probe_result(result: ProbeResult) -> dict[str, object]:
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

    def _record_detection(
        self,
        *,
        cycle_id: int,
        candidate: MonitorCandidate,
        detection_type: str,
        detection_status: str,
        reason: str | None,
        payload: dict[str, object] | None,
    ) -> None:
        self._monitor_repo.create_detection(
            cycle_id=cycle_id,
            xboard_node_id=candidate.xboard_node_id,
            detection_type=detection_type,
            detection_status=detection_status,
            reason=reason,
            probe_provider=self._probe_client.provider,
            payload=payload,
        )
