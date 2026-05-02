from __future__ import annotations

from services.local_probe_executor import LocalProbeExecutor
from services.monitor_models import MonitorCandidate, ProbeResult
from services.runtime_service import RuntimeContext


class ProbeClientError(RuntimeError):
    pass


class ProbeClient:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.probe_client")
        self._provider = runtime_context.config.app.sentinel_probe_provider
        self._local_executor = LocalProbeExecutor(runtime_context)

    @property
    def provider(self) -> str:
        return self._provider

    def probe_node(self, candidate: MonitorCandidate) -> ProbeResult:
        try:
            if self._provider == "local_active_probe":
                return self._local_executor.probe_node(candidate)
            raise ProbeClientError(
                f"Unsupported sentinel_probe_provider: {self._provider!r}. "
                f"Only 'local_active_probe' is currently implemented."
            )
        except ProbeClientError:
            raise
        except Exception as exc:
            self._logger.exception(
                "Probe failed xboard_node_id=%s node_type=%s provider=%s",
                candidate.xboard_node_id,
                candidate.node_type,
                self._provider,
            )
            raise ProbeClientError(str(exc)) from exc
