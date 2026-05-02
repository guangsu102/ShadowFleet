from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from database.probe_models import JsonValue, ProbeCommandCreateRequest, ProbeCommandRecord
from database.probe_command_repo import ProbeCommandRepo
from services.probe_measurement_service import ProbeMeasurementService
from services.probe_registry_service import ProbeRegistryService
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class ProbeCommandServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProbeCommandSubmitResult:
    command_id: str
    status: str


class ProbeCommandService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._command_repo = ProbeCommandRepo(runtime_context)
        self._registry_service = ProbeRegistryService(runtime_context)
        self._measurement_service = ProbeMeasurementService(runtime_context)
        self._logger = runtime_context.logger.getChild("services.probe_command")

    def enqueue_command(
        self,
        *,
        probe_id: str,
        command_type: str,
        payload: dict[str, JsonValue],
        correlation_id: str,
        max_attempts: int | None = None,
    ) -> ProbeCommandSubmitResult:
        command_record = self._command_repo.create_command(
            ProbeCommandCreateRequest(
                probe_id=probe_id.strip(),
                command_type=command_type,
                payload=payload,
                correlation_id=correlation_id.strip(),
                max_attempts=max_attempts or (self._runtime_context.config.app.max_retries + 1),
            )
        )
        return ProbeCommandSubmitResult(command_id=command_record.command_id, status=command_record.status)

    def poll_commands(
        self,
        *,
        probe_id: str,
        auth_token: str,
        lease_owner: str,
        max_commands: int,
    ) -> list[ProbeCommandRecord]:
        self._registry_service.authenticate_probe(probe_id=probe_id, auth_token=auth_token)
        return self._command_repo.claim_commands(
            probe_id=probe_id,
            lease_owner=lease_owner,
            limit=max_commands,
        )

    def submit_command_result(
        self,
        *,
        probe_id: str,
        auth_token: str,
        command_id: str,
        status: str,
        result_payload: dict[str, JsonValue] | None,
        last_error: str | None,
    ) -> ProbeCommandRecord:
        self._registry_service.authenticate_probe(probe_id=probe_id, auth_token=auth_token)
        command_record = self._command_repo.get_command_by_command_id(command_id)
        if command_record.probe_id != probe_id.strip():
            raise ProbeCommandServiceError("command does not belong to probe")
        if status == "succeeded":
            updated_record = self._command_repo.mark_command_succeeded(
                command_id=command_id,
                result=result_payload,
            )
            if command_record.command_type == "run_connectivity_probe" and result_payload is not None:
                measurement_id = result_payload.get("measurement_id")
                if isinstance(measurement_id, str) and measurement_id.strip():
                    self._measurement_service.record_remote_result(
                        measurement_id=measurement_id,
                        probe_id=probe_id,
                        result_payload=result_payload,
                    )
            set_event_type("probe_command_result_submitted")
            return updated_record
        updated_record = self._command_repo.mark_command_failed(
            command_id=command_id,
            last_error=(last_error or "probe command failed"),
        )
        set_event_type("probe_command_result_submitted")
        return updated_record

    def list_recent_commands(self, limit: int = 20) -> list[ProbeCommandRecord]:
        return self._command_repo.list_recent_commands(limit=limit)
