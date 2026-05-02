from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import TYPE_CHECKING

from database.probe_models import ProbeConfigRecord, ProbeConfigUpsertRequest, ProbeCreateRequest, ProbeRecord
from database.probe_repo import ProbeRepo
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext

TOKEN_BYTES = 24
PROBE_ID_BYTES = 12


class ProbeRegistryServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProbeRegistrationResult:
    probe_id: str
    probe_name: str
    auth_token: str
    config_version: int
    config: dict[str, object]


class ProbeRegistryService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._repo = ProbeRepo(runtime_context)
        self._logger = runtime_context.logger.getChild("services.probe_registry")

    def register_probe(
        self,
        *,
        bootstrap_token: str,
        probe_name: str,
        machine_fingerprint: str,
        public_ip: str | None,
        region: str | None,
        isp: str | None,
        tags: list[str] | None,
        capabilities: dict[str, object] | None,
    ) -> ProbeRegistrationResult:
        if not self._runtime_context.config.app.probe_server_enabled:
            raise ProbeRegistryServiceError("probe server is disabled by configuration")
        normalized_token = bootstrap_token.strip()
        if normalized_token not in self._runtime_context.config.app.probe_bootstrap_tokens:
            raise ProbeRegistryServiceError("invalid probe bootstrap token")
        normalized_probe_name = probe_name.strip()
        if not normalized_probe_name:
            raise ValueError("probe_name must not be empty")
        normalized_fingerprint = machine_fingerprint.strip()
        if not normalized_fingerprint:
            raise ValueError("machine_fingerprint must not be empty")

        existing_probe = self._repo.get_probe_by_machine_fingerprint(normalized_fingerprint)
        if existing_probe is not None:
            config_record = self._ensure_probe_config(
                existing_probe.probe_id,
                existing_probe.config_version,
            )
            set_event_type("probe_registered_existing")
            self._logger.info(
                "Probe re-registered probe_id=%s probe_name=%s",
                existing_probe.probe_id,
                existing_probe.probe_name,
            )
            return ProbeRegistrationResult(
                probe_id=existing_probe.probe_id,
                probe_name=existing_probe.probe_name,
                auth_token=existing_probe.auth_token,
                config_version=config_record.config_version,
                config=config_record.config,
            )

        probe_id = f"probe-{secrets.token_urlsafe(PROBE_ID_BYTES)}"
        auth_token = secrets.token_urlsafe(TOKEN_BYTES)
        created_probe = self._repo.create_probe(
            ProbeCreateRequest(
                probe_id=probe_id,
                probe_name=normalized_probe_name,
                auth_token=auth_token,
                machine_fingerprint=normalized_fingerprint,
                public_ip=public_ip,
                region=region.strip() if region else None,
                isp=isp.strip() if isp else None,
                tags=tags or [],
                capabilities=capabilities or {},
            )
        )
        config_record = self._ensure_probe_config(created_probe.probe_id, created_probe.config_version)
        set_event_type("probe_registered")
        self._logger.info(
            "Registered new probe probe_id=%s probe_name=%s",
            created_probe.probe_id,
            created_probe.probe_name,
        )
        return ProbeRegistrationResult(
            probe_id=created_probe.probe_id,
            probe_name=created_probe.probe_name,
            auth_token=created_probe.auth_token,
            config_version=config_record.config_version,
            config=config_record.config,
        )

    def authenticate_probe(self, *, probe_id: str, auth_token: str) -> ProbeRecord:
        if not self._runtime_context.config.app.probe_server_enabled:
            raise ProbeRegistryServiceError("probe server is disabled by configuration")
        probe_record = self._repo.get_probe_by_probe_id(probe_id)
        if probe_record.auth_token != auth_token.strip():
            raise ProbeRegistryServiceError("invalid probe token")
        if probe_record.status == "disabled":
            raise ProbeRegistryServiceError("probe is disabled")
        return probe_record

    def record_heartbeat(
        self,
        *,
        probe_id: str,
        auth_token: str,
        public_ip: str | None,
        agent_version: str | None,
        capabilities: dict[str, object] | None,
        runtime_metrics: dict[str, object] | None,
    ) -> tuple[ProbeRecord, int]:
        probe_record = self.authenticate_probe(probe_id=probe_id, auth_token=auth_token)
        self._repo.record_heartbeat(
            probe_id=probe_record.probe_id,
            public_ip=public_ip,
            agent_version=agent_version,
            capabilities=capabilities,
            runtime_metrics=runtime_metrics,
        )
        updated_probe = self._repo.get_probe_by_probe_id(probe_record.probe_id)
        return updated_probe, updated_probe.config_version

    def get_probe_config(
        self,
        *,
        probe_id: str,
        auth_token: str,
    ) -> ProbeConfigRecord:
        probe_record = self.authenticate_probe(probe_id=probe_id, auth_token=auth_token)
        config_record = self._repo.get_latest_probe_config(probe_record.probe_id)
        if config_record is None:
            return self._ensure_probe_config(probe_record.probe_id, probe_record.config_version)
        return config_record

    def list_probes(self) -> list[ProbeRecord]:
        self._repo.mark_stale_probes_offline(
            timeout_seconds=self._runtime_context.config.app.probe_heartbeat_timeout_seconds
        )
        return self._repo.list_probes(include_inactive=True)

    def _ensure_probe_config(self, probe_id: str, config_version: int) -> ProbeConfigRecord:
        config_record = self._repo.get_latest_probe_config(probe_id)
        if config_record is not None:
            return config_record
        default_config = self._build_default_probe_config()
        return self._repo.upsert_probe_config(
            ProbeConfigUpsertRequest(
                probe_id=probe_id,
                config_version=config_version,
                config=default_config,
            )
        )

    def _build_default_probe_config(self) -> dict[str, object]:
        app_config = self._runtime_context.config.app
        return {
            "poll_interval_seconds": app_config.probe_poll_interval_seconds,
            "probe_timeout_seconds": app_config.sentinel_probe_timeout_seconds,
            "result_wait_timeout_seconds": app_config.sentinel_probe_result_wait_timeout_seconds,
            "allow_http_probe": True,
            "allow_tls_probe": True,
            "allow_udp_probe": False,
        }
