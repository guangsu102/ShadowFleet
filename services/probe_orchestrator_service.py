from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from services.monitor_models import MonitorCandidate, ProbeMeasurementSummary, ProbeResult
from services.probe_command_service import ProbeCommandService
from services.probe_measurement_service import ProbeMeasurementService
from services.probe_registry_service import ProbeRegistryService

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class ProbeOrchestratorServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProbeOrchestrationResult:
    measurement_summary: ProbeMeasurementSummary
    selected_probe_ids: tuple[str, ...]


class ProbeOrchestratorService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._registry_service = ProbeRegistryService(runtime_context)
        self._command_service = ProbeCommandService(runtime_context)
        self._measurement_service = ProbeMeasurementService(runtime_context)
        self._logger = runtime_context.logger.getChild("services.probe_orchestrator")

    def measure_candidate(
        self,
        *,
        candidate: MonitorCandidate,
        control_plane_result: ProbeResult,
        correlation_id: str,
    ) -> ProbeOrchestrationResult:
        app_config = self._runtime_context.config.app
        measurement_record = self._measurement_service.create_measurement(
            candidate=candidate,
            correlation_id=correlation_id,
            control_plane_result=control_plane_result,
        )
        selected_probe_ids: list[str] = []
        remote_results = []
        if app_config.sentinel_probe_mode == "cn_probe_mesh":
            selected_probe_ids = self._select_probe_ids()
            for probe_id in selected_probe_ids:
                self._command_service.enqueue_command(
                    probe_id=probe_id,
                    command_type="run_connectivity_probe",
                    correlation_id=correlation_id,
                    payload={
                        "measurement_id": measurement_record.measurement_id,
                        "xboard_node_id": candidate.xboard_node_id,
                        "node_name": candidate.node_name,
                        "node_type": candidate.node_type,
                        "asset_type": candidate.asset_type,
                        "domain_name": candidate.domain_name,
                        "host": candidate.host,
                        "port": candidate.port,
                        "server_port": candidate.server_port,
                        "timeout_seconds": app_config.sentinel_probe_timeout_seconds,
                    },
                )

            wait_result = self._measurement_service.wait_for_remote_results(
                measurement_id=measurement_record.measurement_id,
                minimum_result_count=len(selected_probe_ids),
                timeout_seconds=app_config.sentinel_probe_result_wait_timeout_seconds,
                poll_interval_seconds=app_config.probe_poll_interval_seconds,
            )
            if wait_result.timed_out:
                self._logger.warning(
                    "Probe result collection timed out measurement_id=%s expected=%s got=%s",
                    measurement_record.measurement_id,
                    len(selected_probe_ids),
                    len(wait_result.results),
                )
            remote_results = wait_result.results
        measurement_summary = self._measurement_service.finalize_measurement(
            candidate=candidate,
            measurement_record=measurement_record,
            control_plane_result=control_plane_result,
            remote_results=remote_results,
        )
        return ProbeOrchestrationResult(
            measurement_summary=measurement_summary,
            selected_probe_ids=tuple(selected_probe_ids),
        )

    def list_recent_measurements(self, limit: int = 20):
        return self._measurement_service.list_recent_measurements(limit=limit)

    def count_recent_confirmed_blocked_cycles(
        self,
        *,
        xboard_node_id: int,
        limit: int,
    ) -> int:
        return self._measurement_service.count_recent_confirmed_blocked_cycles(
            xboard_node_id=xboard_node_id,
            limit=limit,
        )

    def _select_probe_ids(self) -> list[str]:
        probe_records = self._registry_service.list_probes()
        active_probe_ids = [probe.probe_id for probe in probe_records if probe.status == "active"]
        minimum_probe_count = self._runtime_context.config.app.sentinel_probe_min_cn_probe_count
        if len(active_probe_ids) < minimum_probe_count:
            raise ProbeOrchestratorServiceError("active cn probes are insufficient for measurement")
        return active_probe_ids[: max(minimum_probe_count, 3)]
