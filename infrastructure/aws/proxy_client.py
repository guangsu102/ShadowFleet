from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import requests

from models.config_models import AwsProxyConfig
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import execute_with_backoff

RETRYABLE_PROXY_STATUS_CODES = {429, 500, 502, 503, 504}


class AwsProxyClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DecodoAwsProxyClient:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._logger = runtime_context.logger.getChild("infrastructure.aws.proxy")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._config = runtime_context.config.aws_proxy

        if not self._config.enabled:
            raise ValueError("AWS proxy client requires aws_proxy.enabled=true")

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Authorization": self._config.authorization or "",
            }
        )

    def resolve_proxy_url(self) -> str:
        response_payload = self._request(
            method="GET",
            endpoint="/endpoints-custom",
            params=_build_proxy_query_params(self._config),
        )
        if not isinstance(response_payload, list) or not response_payload:
            raise AwsProxyClientError("Proxy API returned an empty endpoint list")

        first_proxy = response_payload[0]
        if not isinstance(first_proxy, str) or not first_proxy.strip():
            raise AwsProxyClientError("Proxy API returned an invalid proxy endpoint")

        proxy_url = first_proxy.strip()
        parsed_proxy = urlsplit(proxy_url)
        if not parsed_proxy.scheme or not parsed_proxy.hostname or parsed_proxy.port is None:
            raise AwsProxyClientError("Proxy API returned a malformed proxy URL")

        set_event_type("aws_proxy_resolved")
        self._logger.info(
            "Resolved AWS proxy endpoint via Decodo: provider=%s session_type=%s location=%s host=%s port=%s",
            self._config.provider,
            self._config.session_type,
            self._config.location,
            parsed_proxy.hostname,
            parsed_proxy.port,
        )
        return proxy_url

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, object] | None = None,
    ) -> Any:
        url = f"{self._config.base_url.rstrip('/')}{endpoint}"

        def _send_request() -> Any:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                timeout=self._request_timeout_seconds,
            )
            return self._validate_response(response)

        request_func: Callable[[], Any] = _send_request
        try:
            return execute_with_backoff(
                operation_name=f"aws_proxy_{method.lower()}_{endpoint}",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="aws_proxy",
                func=request_func,
                should_retry=self._should_retry_exception,
            )
        except (AwsProxyClientError, requests.ConnectionError, requests.Timeout):
            set_event_type("aws_proxy_request_failed")
            self._logger.exception(
                "AWS proxy request failed: method=%s endpoint=%s",
                method,
                endpoint,
            )
            raise

    def _validate_response(self, response: requests.Response) -> Any:
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise AwsProxyClientError("Proxy API returned a non-JSON response") from exc

        if response.status_code >= 400:
            raise AwsProxyClientError(
                f"Proxy API request failed with status {response.status_code}",
                status_code=response.status_code,
            )
        return response_payload

    def _should_retry_exception(self, exc: BaseException) -> bool:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
        if isinstance(exc, AwsProxyClientError):
            return exc.status_code in RETRYABLE_PROXY_STATUS_CODES
        return False


def build_aws_boto_proxies(runtime_context: RuntimeContext) -> dict[str, str] | None:
    if not runtime_context.config.aws_proxy.enabled:
        return None

    proxy_url = DecodoAwsProxyClient(runtime_context).resolve_proxy_url()
    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def _build_proxy_query_params(config: AwsProxyConfig) -> dict[str, object]:
    return {
        "proxyType": config.proxy_type,
        "authType": config.auth_type,
        "username": config.username,
        "password": config.password,
        "sessionType": config.session_type,
        "sessionDuration": config.session_duration_minutes,
        "location": config.location,
        "outputFormat": config.output_format,
        "count": config.count,
        "page": config.page,
        "responseType": config.response_type,
        "domain": config.domain,
    }
