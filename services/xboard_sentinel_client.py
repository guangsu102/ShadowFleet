from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests

from services.monitor_models import (
    XboardServerList,
    XboardServerListItem,
    XboardSentinelMinuteStat,
    XboardSentinelNodeRuntime,
)
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import execute_with_backoff

RETRYABLE_XBOARD_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class XboardSentinelClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class XboardSentinelClient:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._logger = runtime_context.logger.getChild("services.xboard_sentinel_client")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._base_url = (
            runtime_context.config.app.xboard_sentinel_api_base_url or ""
        ).rstrip("/")
        self._api_key = runtime_context.config.app.xboard_sentinel_api_key

        if not self._base_url:
            raise ValueError("xboard_sentinel_api_base_url is required")
        if self._api_key is None:
            raise ValueError("xboard_sentinel_api_key is required")

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            }
        )

    def get_server_minute_stats(
        self,
        *,
        server_id: int,
        server_type: str,
        lookback_minutes: int,
    ) -> list[XboardSentinelMinuteStat]:
        payload = self._request(
            method="GET",
            endpoint="/api/v1/shadowfleet/server-minute-stats",
            params={
                "server_id": server_id,
                "server_type": server_type,
                "lookback_minutes": lookback_minutes,
            },
        )
        if not isinstance(payload, dict):
            raise XboardSentinelClientError("Xboard minute-stats response must be a JSON object")

        samples = payload.get("samples", [])
        if not isinstance(samples, list):
            raise XboardSentinelClientError("Xboard minute-stats response.samples must be a list")

        # Use root-level values from API response, fall back to request params
        payload_server_id = payload.get("server_id")
        resolved_server_id = int(payload_server_id) if payload_server_id is not None else server_id
        payload_server_type = payload.get("server_type")
        resolved_server_type = str(payload_server_type) if payload_server_type is not None else server_type

        records: list[XboardSentinelMinuteStat] = []
        for sample in samples:
            if not isinstance(sample, dict):
                raise XboardSentinelClientError("Xboard minute-stats sample must be an object")
            records.append(
                XboardSentinelMinuteStat(
                    server_id=resolved_server_id,
                    server_type=resolved_server_type,
                    uplink_bytes=int(sample["uplink_bytes"]),
                    downlink_bytes=int(sample["downlink_bytes"]),
                    total_bytes=int(sample["total_bytes"]),
                    active_user_count=int(sample["active_user_count"]),
                    sample_minute=int(sample["sample_minute"]),
                )
            )
        return records

    def get_server_runtime(
        self, *, server_id: int, server_type: str | None = None
    ) -> XboardSentinelNodeRuntime:
        params: dict[str, int | str] = {"server_id": server_id}
        if server_type is not None:
            params["server_type"] = server_type
        payload = self._request(
            method="GET",
            endpoint="/api/v1/shadowfleet/server-runtime",
            params=params,
        )
        if not isinstance(payload, dict):
            raise XboardSentinelClientError("Xboard server-runtime response must be a JSON object")
        return XboardSentinelNodeRuntime(
            node_id=int(payload["id"]),
            node_type=str(payload["type"]),
            host=str(payload["host"]),
            port=str(payload["port"]),
            server_port=int(payload["server_port"]),
            show=bool(payload["show"]),
        )

    def get_server_list(self) -> XboardServerList:
        """
        Get all ShadowFleet nodes with online status from Xboard.
        Requires Bearer token authentication (xboard_sentinel_api_key).
        """
        payload = self._request(
            method="GET",
            endpoint="/api/v1/shadowfleet/server-list",
        )
        if not isinstance(payload, dict):
            raise XboardSentinelClientError("Xboard server-list response must be a JSON object")

        servers_data = payload.get("servers")
        if not isinstance(servers_data, list):
            raise XboardSentinelClientError("Xboard server-list response.servers must be a list")

        servers: list[XboardServerListItem] = []
        for item in servers_data:
            if not isinstance(item, dict):
                raise XboardSentinelClientError("Xboard server-list item must be an object")
            servers.append(
                XboardServerListItem(
                    id=int(item["id"]),
                    name=str(item["name"]),
                    type=str(item["type"]),
                    host=str(item["host"]),
                    port=str(item["port"]),
                    server_port=int(item["server_port"]),
                    show=bool(item["show"]),
                    last_check_at=int(item["last_check_at"]) if item.get("last_check_at") is not None else None,
                    last_push_at=int(item["last_push_at"]) if item.get("last_push_at") is not None else None,
                    is_online=int(item["is_online"]),
                    available_status=str(item["available_status"]),
                )
            )
        return XboardServerList(servers=servers)

    def _request(
        self,
        *,
        method: str,
        endpoint: str,
        params: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
    ) -> Any:
        url = f"{self._base_url}{endpoint}"

        def _send_request() -> Any:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                json=payload,
                timeout=self._request_timeout_seconds,
            )
            return self._validate_response(response)

        request_func: Callable[[], Any] = _send_request
        try:
            return execute_with_backoff(
                operation_name=f"xboard_sentinel_{method.lower()}_{endpoint}",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="xboard_api",
                func=request_func,
                should_retry=self._should_retry_exception,
            )
        except (XboardSentinelClientError, requests.ConnectionError, requests.Timeout):
            set_event_type("xboard_api_failed")
            self._logger.exception(
                "Xboard Sentinel API request failed: method=%s endpoint=%s",
                method,
                endpoint,
            )
            raise

    @staticmethod
    def _validate_response(response: requests.Response) -> Any:
        if response.status_code == 204:
            return {}
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise XboardSentinelClientError("Xboard Sentinel API returned non-JSON response") from exc

        if response.status_code >= 400:
            detail = response_payload if isinstance(response_payload, dict) else None
            raise XboardSentinelClientError(
                XboardSentinelClient._build_error_message(
                    status_code=response.status_code,
                    payload=detail,
                ),
                status_code=response.status_code,
            )
        return response_payload

    @staticmethod
    def _build_error_message(status_code: int, payload: dict[str, Any] | None) -> str:
        if payload is None:
            return f"Xboard Sentinel API error {status_code}"
        message = payload.get("message") or payload.get("detail")
        if isinstance(message, str) and message.strip():
            return f"Xboard Sentinel API error {status_code}: {message.strip()}"
        return f"Xboard Sentinel API error {status_code}"

    @staticmethod
    def _should_retry_exception(exc: BaseException) -> bool:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
        if isinstance(exc, XboardSentinelClientError):
            return exc.status_code in RETRYABLE_XBOARD_STATUS_CODES
        return False
