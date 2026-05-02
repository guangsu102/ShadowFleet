from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from database.ready_callback_repo import (
    JsonValue,
    ReadyCallbackCreateRequest,
    ReadyCallbackRecord,
    ReadyCallbackRepo,
)
from utils.logger import set_correlation_id, set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


READY_CALLBACK_PATH = "/api/v1/provisioning/ready"


class ReadyCallbackServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReadyCallbackRegistration:
    task_id: int
    xboard_node_id: int
    callback_token: str
    callback_url: str


class ReadyCallbackService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.ready_callback")
        self._repo = ReadyCallbackRepo(runtime_context)

    def register_callback(
        self,
        task_id: int,
        xboard_node_id: int,
        correlation_id: str,
    ) -> ReadyCallbackRegistration:
        callback_record = self._repo.create_callback(
            ReadyCallbackCreateRequest(
                task_id=task_id,
                xboard_node_id=xboard_node_id,
                correlation_id=correlation_id,
            )
        )
        return ReadyCallbackRegistration(
            task_id=callback_record.task_id,
            xboard_node_id=callback_record.xboard_node_id,
            callback_token=callback_record.callback_token,
            callback_url=self._build_callback_url(),
        )

    def wait_for_ready_callback(self, task_id: int) -> ReadyCallbackRecord:
        app_config = self._runtime_context.config.app
        return self._repo.wait_until_received(
            task_id=task_id,
            timeout_seconds=app_config.phone_home_ready_timeout_seconds,
            poll_interval_seconds=app_config.phone_home_poll_interval_seconds,
        )

    def mark_callback_completed(self, task_id: int) -> ReadyCallbackRecord:
        return self._repo.mark_completed(task_id=task_id)

    def record_ready_callback(
        self,
        callback_token: str,
        payload: JsonValue | None,
    ) -> ReadyCallbackRecord:
        callback_record = self._repo.get_by_token(callback_token)
        original_correlation_id = self._runtime_context.correlation_id
        set_correlation_id(callback_record.correlation_id)
        try:
            if callback_record.status == "completed":
                return callback_record
            if isinstance(payload, dict):
                payload_xboard_node_id = payload.get("xboard_node_id")
                if payload_xboard_node_id is not None and int(payload_xboard_node_id) != callback_record.xboard_node_id:
                    raise ReadyCallbackServiceError(
                        "Ready callback xboard_node_id does not match registered callback"
                    )

            updated_record = self._repo.mark_received(callback_token=callback_token, payload=payload)
            set_event_type("ready_callback_recorded")
            self._logger.info(
                "Recorded ready callback task_id=%s xboard_node_id=%s",
                updated_record.task_id,
                updated_record.xboard_node_id,
            )
            return updated_record
        finally:
            set_correlation_id(original_correlation_id)
            set_event_type("general")

    def _build_callback_url(self) -> str:
        base_url = self._runtime_context.config.app.phone_home_base_url
        if base_url is None or not base_url.strip():
            raise ReadyCallbackServiceError(
                "app.phone_home_base_url is required for provisioning ready callbacks"
            )
        base_url = base_url.strip()
        runtime = self._runtime_context
        if runtime.daemon_ipv6:
            # Daemon has public IPv6: AWS IPv6-capable instances can reach it directly.
            import re
            if re.match(r"^https?://\d+\.\d+\.\d+\.\d+:", base_url):
                base_url = re.sub(
                    r"^https?://\d+\.\d+\.\d+\.\d+:",
                    f"http://[{runtime.daemon_ipv6}]:",
                    base_url,
                )
        # If daemon has no IPv6, callback URL stays as-is (IPv4 from phone_home_base_url).
        return f"{base_url.rstrip('/')}{READY_CALLBACK_PATH}"
