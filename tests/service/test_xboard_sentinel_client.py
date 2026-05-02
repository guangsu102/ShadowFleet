"""Unit tests for XboardSentinelClient (services/xboard_sentinel_client.py).

Covers:
- Initialization validation
- get_server_minute_stats() happy-path and all error codes
- get_server_runtime() with optional server_type
- _validate_response error semantics (401/403/404/422/503)
- _should_retry_exception retry logic
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from services.monitor_models import XboardSentinelMinuteStat, XboardSentinelNodeRuntime
from services.xboard_sentinel_client import (
    RETRYABLE_XBOARD_STATUS_CODES,
    XboardSentinelClient,
    XboardSentinelClientError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_runtime_context(
    base_url: str = "https://xboard.example.com",
    api_key: str = "test-api-key",
    request_timeout: int = 10,
    max_retries: int = 3,
    retry_backoff: float = 1.0,
) -> MagicMock:
    ctx = MagicMock()
    ctx.correlation_id = "test-correlation"
    ctx.logger = MagicMock(spec=logging.Logger)
    ctx.logger.getChild.return_value = ctx.logger

    app_cfg = MagicMock()
    app_cfg.xboard_sentinel_api_base_url = base_url
    app_cfg.xboard_sentinel_api_key = api_key
    app_cfg.request_timeout_seconds = request_timeout
    app_cfg.max_retries = max_retries
    app_cfg.retry_backoff_seconds = retry_backoff

    ctx.config = MagicMock()
    ctx.config.app = app_cfg
    return ctx


def _build_response_mock(
    status_code: int,
    json_data: Any,
    raise_json_error: bool = False,
) -> MagicMock:
    """Factory for requests.Response mocks."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = status_code
    if raise_json_error:
        mock_resp.json.side_effect = ValueError("not json")
    else:
        mock_resp.json.return_value = json_data
    return mock_resp


# ---------------------------------------------------------------------------
# Tests: XboardSentinelClient.__init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_missing_base_url_raises_value_error(self) -> None:
        ctx = _make_runtime_context(base_url=None)
        ctx.config.app.xboard_sentinel_api_base_url = None

        with pytest.raises(ValueError, match="xboard_sentinel_api_base_url is required"):
            XboardSentinelClient(ctx)

    def test_missing_api_key_raises_value_error(self) -> None:
        ctx = _make_runtime_context(api_key=None)
        ctx.config.app.xboard_sentinel_api_key = None

        with pytest.raises(ValueError, match="xboard_sentinel_api_key is required"):
            XboardSentinelClient(ctx)

    def test_valid_init_sets_bearer_header(self) -> None:
        ctx = _make_runtime_context(api_key="my-secret-key")

        with patch("services.xboard_sentinel_client.requests.Session") as mock_session_cls:
            client = XboardSentinelClient(ctx)

            assert client._base_url == "https://xboard.example.com"
            assert client._api_key == "my-secret-key"
            mock_session_cls.return_value.headers.update.assert_called_once()
            call_args = mock_session_cls.return_value.headers.update.call_args
            assert call_args[0][0]["Authorization"] == "Bearer my-secret-key"
            assert call_args[0][0]["Accept"] == "application/json"


# ---------------------------------------------------------------------------
# Tests: get_server_minute_stats
# ---------------------------------------------------------------------------

class TestGetServerMinuteStats:
    def _call(
        self,
        runtime_ctx: MagicMock,
        response: MagicMock,
    ) -> list[XboardSentinelMinuteStat]:
        with patch(
            "services.xboard_sentinel_client.requests.Session"
        ) as mock_session_cls, patch(
            "services.xboard_sentinel_client.execute_with_backoff"
        ):
            mock_session = mock_session_cls.return_value
            mock_session.request.return_value = response
            client = XboardSentinelClient(runtime_ctx)
            return client.get_server_minute_stats(
                server_id=123,
                server_type="Trojan",
                lookback_minutes=5,
            )

    def test_200_returns_list_of_minute_stats(self) -> None:
        stats_payload = {
            "server_id": 123,
            "server_type": "Trojan",
            "samples": [
                {
                    "sample_minute": 1742947200,
                    "uplink_bytes": 1024,
                    "downlink_bytes": 2048,
                    "total_bytes": 3072,
                    "active_user_count": 2,
                },
                {
                    "sample_minute": 1742947260,
                    "uplink_bytes": 0,
                    "downlink_bytes": 0,
                    "total_bytes": 0,
                    "active_user_count": 0,
                },
            ],
        }
        response = _build_response_mock(200, stats_payload)
        result = self._call(_make_runtime_context(), response)

        assert len(result) == 2
        assert result[0].uplink_bytes == 1024
        assert result[0].downlink_bytes == 2048
        assert result[0].total_bytes == 3072
        assert result[0].active_user_count == 2
        assert result[0].sample_minute == 1742947200
        assert result[1].total_bytes == 0

    def test_200_empty_samples_returns_empty_list(self) -> None:
        response = _build_response_mock(200, {"server_id": 123, "server_type": "AnyTLS", "samples": []})
        result = self._call(_make_runtime_context(), response)
        assert result == []

    def test_404_raises_xboard_sentinel_client_error(self) -> None:
        response = _build_response_mock(404, {"message": "server not found"})

        with pytest.raises(XboardSentinelClientError) as exc_info:
            self._call(_make_runtime_context(), response)

        assert exc_info.value.status_code == 404
        assert "server not found" in str(exc_info.value)

    def test_401_missing_token_raises_with_401_code(self) -> None:
        response = _build_response_mock(401, {"message": "missing bearer token"})

        with pytest.raises(XboardSentinelClientError) as exc_info:
            self._call(_make_runtime_context(), response)

        assert exc_info.value.status_code == 401
        assert "missing bearer token" in str(exc_info.value)

    def test_403_invalid_token_raises_with_403_code(self) -> None:
        response = _build_response_mock(403, {"message": "invalid bearer token"})

        with pytest.raises(XboardSentinelClientError) as exc_info:
            self._call(_make_runtime_context(), response)

        assert exc_info.value.status_code == 403
        assert "invalid bearer token" in str(exc_info.value)

    def test_422_invalid_params_raises_with_422_code(self) -> None:
        response = _build_response_mock(422, {"message": "server_type is required"})

        with pytest.raises(XboardSentinelClientError) as exc_info:
            self._call(_make_runtime_context(), response)

        assert exc_info.value.status_code == 422
        assert "server_type is required" in str(exc_info.value)

    def test_503_api_not_configured_raises_with_503_code(self) -> None:
        response = _build_response_mock(503, {"message": "shadowfleet api key not configured"})

        with pytest.raises(XboardSentinelClientError) as exc_info:
            self._call(_make_runtime_context(), response)

        assert exc_info.value.status_code == 503

    def test_non_json_response_raises_error(self) -> None:
        response = _build_response_mock(500, None, raise_json_error=True)

        with pytest.raises(XboardSentinelClientError, match="non-JSON"):
            self._call(_make_runtime_context(), response)

    def test_non_dict_response_payload_raises_error(self) -> None:
        response = MagicMock(spec=requests.Response)
        response.status_code = 200
        response.json.return_value = ["not", "a", "dict"]

        with pytest.raises(XboardSentinelClientError, match="must be a JSON object"):
            self._call(_make_runtime_context(), response)

    def test_non_list_samples_raises_error(self) -> None:
        response = _build_response_mock(200, {"server_id": 123, "server_type": "AnyTLS", "samples": "not a list"})

        with pytest.raises(XboardSentinelClientError, match="samples must be a list"):
            self._call(_make_runtime_context(), response)

    def test_non_dict_sample_raises_error(self) -> None:
        response = _build_response_mock(200, {
            "server_id": 123,
            "server_type": "AnyTLS",
            "samples": [{"uplink_bytes": 100, "downlink_bytes": 200, "total_bytes": 300, "active_user_count": 1, "sample_minute": 1742947200}, "not a dict"],
        })

        with pytest.raises(XboardSentinelClientError, match="sample must be an object"):
            self._call(_make_runtime_context(), response)


# ---------------------------------------------------------------------------
# Tests: get_server_runtime
# ---------------------------------------------------------------------------

class TestGetServerRuntime:
    def _call(
        self,
        runtime_ctx: MagicMock,
        response: MagicMock,
        *,
        server_type: str | None = None,
    ) -> XboardSentinelNodeRuntime:
        with patch(
            "services.xboard_sentinel_client.requests.Session"
        ) as mock_session_cls, patch(
            "services.xboard_sentinel_client.execute_with_backoff"
        ):
            mock_session = mock_session_cls.return_value
            mock_session.request.return_value = response
            client = XboardSentinelClient(runtime_ctx)
            return client.get_server_runtime(server_id=123, server_type=server_type)

    def test_200_returns_node_runtime(self) -> None:
        runtime_payload = {
            "id": 123,
            "type": "Trojan",
            "host": "jp-1.example.com",
            "port": "443",
            "server_port": 443,
            "show": True,
        }
        response = _build_response_mock(200, runtime_payload)
        result = self._call(_make_runtime_context(), response)

        assert result.node_id == 123
        assert result.node_type == "Trojan"
        assert result.host == "jp-1.example.com"
        assert result.port == "443"
        assert result.server_port == 443
        assert result.show is True

    def test_200_show_false(self) -> None:
        runtime_payload = {
            "id": 456,
            "type": "AnyTLS",
            "host": "us-1.example.com",
            "port": "8443",
            "server_port": 8443,
            "show": False,
        }
        response = _build_response_mock(200, runtime_payload)
        result = self._call(_make_runtime_context(), response)

        assert result.show is False

    def test_200_with_optional_server_type_param(self) -> None:
        runtime_payload = {
            "id": 789,
            "type": "vless",
            "host": "sg-1.example.com",
            "port": "443",
            "server_port": 443,
            "show": True,
        }
        response = _build_response_mock(200, runtime_payload)

        with patch(
            "services.xboard_sentinel_client.requests.Session"
        ) as mock_session_cls, patch(
            "services.xboard_sentinel_client.execute_with_backoff"
        ):
            mock_session = mock_session_cls.return_value
            mock_session.request.return_value = response
            client = XboardSentinelClient(_make_runtime_context())

            # Pass optional server_type
            client.get_server_runtime(server_id=789, server_type="VLESS")

            # Verify server_type was included in request params
            mock_session.request.assert_called_once()
            call_kwargs = mock_session.request.call_args.kwargs
            assert call_kwargs["params"]["server_id"] == 789
            assert call_kwargs["params"]["server_type"] == "VLESS"

    def test_without_server_type_only_sends_server_id(self) -> None:
        runtime_payload = {
            "id": 999,
            "type": "Hysteria2",
            "host": "de-1.example.com",
            "port": "443",
            "server_port": 443,
            "show": True,
        }
        response = _build_response_mock(200, runtime_payload)

        with patch(
            "services.xboard_sentinel_client.requests.Session"
        ) as mock_session_cls, patch(
            "services.xboard_sentinel_client.execute_with_backoff"
        ):
            mock_session = mock_session_cls.return_value
            mock_session.request.return_value = response
            client = XboardSentinelClient(_make_runtime_context())

            # No server_type passed
            client.get_server_runtime(server_id=999)

            call_kwargs = mock_session.request.call_args.kwargs
            assert call_kwargs["params"] == {"server_id": 999}

    def test_404_raises_xboard_sentinel_client_error(self) -> None:
        response = _build_response_mock(404, {"message": "server not found"})

        with pytest.raises(XboardSentinelClientError) as exc_info:
            self._call(_make_runtime_context(), response)

        assert exc_info.value.status_code == 404
        assert "server not found" in str(exc_info.value)

    def test_422_raises_xboard_sentinel_client_error(self) -> None:
        response = _build_response_mock(422, {"message": "server_id is required"})

        with pytest.raises(XboardSentinelClientError) as exc_info:
            self._call(_make_runtime_context(), response)

        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Tests: _validate_response
# ---------------------------------------------------------------------------

class TestValidateResponse:
    def test_204_returns_empty_dict(self) -> None:
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.status_code = 204
        mock_resp.json.return_value = {}

        result = XboardSentinelClient._validate_response(mock_resp)
        assert result == {}

    def test_200_returns_json(self) -> None:
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": "value"}

        result = XboardSentinelClient._validate_response(mock_resp)
        assert result == {"key": "value"}

    def test_error_with_message_field_uses_message(self) -> None:
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"message": "missing bearer token"}

        with pytest.raises(XboardSentinelClientError) as exc:
            XboardSentinelClient._validate_response(mock_resp)

        assert "missing bearer token" in str(exc.value)

    def test_error_with_detail_field_uses_detail(self) -> None:
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"detail": "forbidden"}

        with pytest.raises(XboardSentinelClientError) as exc:
            XboardSentinelClient._validate_response(mock_resp)

        assert "forbidden" in str(exc.value)

    def test_error_with_non_string_message_falls_back(self) -> None:
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"message": None, "code": "INTERNAL"}

        with pytest.raises(XboardSentinelClientError) as exc:
            XboardSentinelClient._validate_response(mock_resp)

        assert "Xboard Sentinel API error 500" in str(exc.value)


# ---------------------------------------------------------------------------
# Tests: _should_retry_exception
# ---------------------------------------------------------------------------

class TestShouldRetryException:
    def test_connection_error_retries(self) -> None:
        exc = requests.ConnectionError("connection refused")
        assert XboardSentinelClient._should_retry_exception(exc) is True

    def test_timeout_retries(self) -> None:
        exc = requests.Timeout("timed out")
        assert XboardSentinelClient._should_retry_exception(exc) is True

    def test_client_error_with_retryable_status_retries(self) -> None:
        for code in RETRYABLE_XBOARD_STATUS_CODES:
            exc = XboardSentinelClientError("error", status_code=code)
            assert XboardSentinelClient._should_retry_exception(exc) is True, f"code {code} should retry"

    def test_401_does_not_retry(self) -> None:
        exc = XboardSentinelClientError("unauthorized", status_code=401)
        assert XboardSentinelClient._should_retry_exception(exc) is False

    def test_403_does_not_retry(self) -> None:
        exc = XboardSentinelClientError("forbidden", status_code=403)
        assert XboardSentinelClient._should_retry_exception(exc) is False

    def test_404_does_not_retry(self) -> None:
        exc = XboardSentinelClientError("not found", status_code=404)
        assert XboardSentinelClient._should_retry_exception(exc) is False

    def test_422_does_not_retry(self) -> None:
        exc = XboardSentinelClientError("unprocessable", status_code=422)
        assert XboardSentinelClient._should_retry_exception(exc) is False

    def test_unknown_exception_type_does_not_retry(self) -> None:
        exc = RuntimeError("unexpected")
        assert XboardSentinelClient._should_retry_exception(exc) is False


# ---------------------------------------------------------------------------
# Tests: retry logic integration (execute_with_backoff called)
# ---------------------------------------------------------------------------

class TestRetryIntegration:
    def test_execute_with_backoff_is_called_on_request(self) -> None:
        """Verify execute_with_backoff is invoked so retries actually happen."""
        response = _build_response_mock(200, {"server_id": 1, "server_type": "AnyTLS", "samples": []})

        with patch(
            "services.xboard_sentinel_client.requests.Session"
        ) as mock_session_cls, patch(
            "services.xboard_sentinel_client.execute_with_backoff"
        ) as mock_backoff:
            mock_session = mock_session_cls.return_value
            mock_session.request.return_value = response
            mock_backoff.return_value = []

            client = XboardSentinelClient(_make_runtime_context())
            client.get_server_minute_stats(server_id=1, server_type="AnyTLS", lookback_minutes=5)

            mock_backoff.assert_called_once()
            call_kwargs = mock_backoff.call_args.kwargs
            assert call_kwargs["max_retries"] == 3
            assert call_kwargs["base_delay_seconds"] == 1.0
            assert call_kwargs["operation_name"] == "xboard_sentinel_get_/api/v1/shadowfleet/server-minute-stats"
