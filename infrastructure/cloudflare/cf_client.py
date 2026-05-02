from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests

from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import TokenBucketRateLimiter, execute_with_backoff


DEFAULT_WRITE_TOKENS_PER_SECOND = 1.0
DEFAULT_WRITE_BURST_CAPACITY = 2
RETRYABLE_CF_STATUS_CODES = {429, 500, 502, 503, 504}


class CloudflareApiError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors or []


class CFClient:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        cloudflare_config = runtime_context.config.cloudflare
        if not cloudflare_config.enabled:
            raise ValueError("Cloudflare client requires cloudflare.enabled=true")
        if not cloudflare_config.api_token or not cloudflare_config.zone_id:
            raise ValueError("Cloudflare client requires api_token and zone_id")

        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("infrastructure.cloudflare")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._zone_id = cloudflare_config.zone_id
        self._base_url = cloudflare_config.base_url.rstrip("/")
        self._write_rate_limiter = TokenBucketRateLimiter(
            tokens_per_second=DEFAULT_WRITE_TOKENS_PER_SECOND,
            burst_capacity=DEFAULT_WRITE_BURST_CAPACITY,
        )

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {cloudflare_config.api_token}",
                "Content-Type": "application/json",
            }
        )

    def get_dns_record(
        self,
        record_name: str,
        record_type: str,
    ) -> dict[str, object] | None:
        response_payload = self._request(
            method="GET",
            endpoint=f"/zones/{self._zone_id}/dns_records",
            params={
                "name": record_name,
                "type": record_type,
                "per_page": 1,
            },
        )
        results = response_payload.get("result", [])
        if not isinstance(results, list) or not results:
            return None

        first_record = results[0]
        if not isinstance(first_record, dict):
            return None
        return first_record

    def get_dns_record_by_id(self, record_id: str) -> dict[str, object]:
        response_payload = self._request(
            method="GET",
            endpoint=f"/zones/{self._zone_id}/dns_records/{record_id}",
        )
        record = response_payload.get("result")
        if not isinstance(record, dict):
            raise CloudflareApiError(500, "Cloudflare get-by-id response missing result payload")
        return record

    def delete_dns_record(self, record_id: str) -> None:
        self._request(
            method="DELETE",
            endpoint=f"/zones/{self._zone_id}/dns_records/{record_id}",
            is_write=True,
        )
        set_event_type("cf_dns_record_deleted")
        self._logger.info("Cloudflare DNS record deleted: record_id=%s", record_id)

    def upsert_dns_record(
        self,
        record_name: str,
        record_type: str,
        content: str,
        proxied: bool,
        ttl: int = 1,
    ) -> str:
        existing_record = self.get_dns_record(
            record_name=record_name,
            record_type=record_type,
        )
        if existing_record is None:
            created_record = self._create_dns_record(
                record_name=record_name,
                record_type=record_type,
                content=content,
                proxied=proxied,
                ttl=ttl,
            )
            record_id = str(created_record["id"])
            self._assert_record_state(
                record_id=record_id,
                expected_content=content,
                expected_proxied=proxied,
            )
            return record_id

        record_id = str(existing_record["id"])
        updates: dict[str, object] = {}

        if existing_record.get("content") != content:
            updates["content"] = content
        if existing_record.get("proxied") is not proxied:
            updates["proxied"] = proxied

        if updates:
            self._patch_dns_record(record_id=record_id, payload=updates)
            self._assert_record_state(
                record_id=record_id,
                expected_content=content,
                expected_proxied=proxied,
            )

        return record_id

    def update_record_content(
        self,
        record_id: str,
        content: str,
    ) -> None:
        self._patch_dns_record(
            record_id=record_id,
            payload={"content": content},
        )
        record = self.get_dns_record_by_id(record_id)
        actual_content = record.get("content")
        if actual_content != content:
            raise CloudflareApiError(
                status_code=409,
                message=f"Cloudflare DNS content mismatch after update: record_id={record_id}",
            )

    def set_record_proxied(
        self,
        record_id: str,
        proxied: bool,
    ) -> None:
        self._patch_dns_record(
            record_id=record_id,
            payload={"proxied": proxied},
        )
        record = self.get_dns_record_by_id(record_id)
        actual_proxied = record.get("proxied")
        if actual_proxied is not proxied:
            raise CloudflareApiError(
                status_code=409,
                message=f"Cloudflare DNS proxied state mismatch after update: record_id={record_id}",
            )

    def sync_aaaa_record(
        self,
        record_name: str,
        ipv6_address: str,
        proxied: bool,
    ) -> str:
        record_id = self.upsert_dns_record(
            record_name=record_name,
            record_type="AAAA",
            content=ipv6_address,
            proxied=proxied,
            ttl=1,
        )
        set_event_type("cf_dns_synced")
        self._logger.info(
            "Cloudflare AAAA record synchronized: name=%s proxied=%s",
            record_name,
            proxied,
        )
        return record_id

    def sync_a_record(
        self,
        record_name: str,
        ipv4_address: str,
        proxied: bool,
    ) -> str:
        record_id = self.upsert_dns_record(
            record_name=record_name,
            record_type="A",
            content=ipv4_address,
            proxied=proxied,
            ttl=1,
        )
        set_event_type("cf_dns_synced")
        self._logger.info(
            "Cloudflare A record synchronized: name=%s proxied=%s",
            record_name,
            proxied,
        )
        return record_id

    def _create_dns_record(
        self,
        record_name: str,
        record_type: str,
        content: str,
        proxied: bool,
        ttl: int,
    ) -> dict[str, Any]:
        response_payload = self._request(
            method="POST",
            endpoint=f"/zones/{self._zone_id}/dns_records",
            payload={
                "type": record_type,
                "name": record_name,
                "content": content,
                "proxied": proxied,
                "ttl": ttl,
            },
            is_write=True,
        )
        created_record = response_payload.get("result")
        if not isinstance(created_record, dict):
            raise CloudflareApiError(500, "Cloudflare create response missing result payload")

        set_event_type("cf_dns_record_created")
        self._logger.info(
            "Cloudflare DNS record created: name=%s type=%s proxied=%s",
            record_name,
            record_type,
            proxied,
        )
        return created_record

    def _patch_dns_record(
        self,
        record_id: str,
        payload: dict[str, object],
    ) -> None:
        self._request(
            method="PATCH",
            endpoint=f"/zones/{self._zone_id}/dns_records/{record_id}",
            payload=payload,
            is_write=True,
        )
        set_event_type("cf_dns_record_updated")
        self._logger.info(
            "Cloudflare DNS record updated: record_id=%s fields=%s",
            record_id,
            sorted(payload.keys()),
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
        is_write: bool = False,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{endpoint}"

        def _send_request() -> dict[str, Any]:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                json=payload,
                timeout=self._request_timeout_seconds,
            )
            return self._validate_response(response)

        if is_write:
            request_func: Callable[[], dict[str, Any]] = self._rate_limited(_send_request)
        else:
            request_func = _send_request

        try:
            return execute_with_backoff(
                operation_name=f"cloudflare_{method.lower()}_{endpoint}",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="cf",
                func=request_func,
                should_retry=self._should_retry_exception,
            )
        except (CloudflareApiError, requests.ConnectionError, requests.Timeout):
            set_event_type("cf_request_failed")
            self._logger.exception(
                "Cloudflare request failed: method=%s endpoint=%s",
                method,
                endpoint,
            )
            raise

    def _validate_response(self, response: requests.Response) -> dict[str, Any]:
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise CloudflareApiError(
                status_code=response.status_code,
                message="Cloudflare returned a non-JSON response",
            ) from exc

        success = response_payload.get("success")
        if response.status_code >= 400 or success is False:
            errors = response_payload.get("errors", [])
            message = self._build_error_message(
                status_code=response.status_code,
                errors=errors,
            )
            raise CloudflareApiError(
                status_code=response.status_code,
                message=message,
                errors=errors if isinstance(errors, list) else None,
            )

        if not isinstance(response_payload, dict):
            raise CloudflareApiError(
                status_code=response.status_code,
                message="Cloudflare response payload must be a JSON object",
            )

        return response_payload

    def _should_retry_exception(self, exc: BaseException) -> bool:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
        if isinstance(exc, CloudflareApiError):
            return exc.status_code in RETRYABLE_CF_STATUS_CODES
        return False

    def _rate_limited(self, func: Callable[[], dict[str, Any]]) -> Callable[[], dict[str, Any]]:
        def _wrapped() -> dict[str, Any]:
            self._write_rate_limiter.acquire()
            return func()

        return _wrapped

    def _build_error_message(
        self,
        status_code: int,
        errors: Any,
    ) -> str:
        if isinstance(errors, list) and errors:
            first_error = errors[0]
            if isinstance(first_error, dict):
                error_code = first_error.get("code", "unknown")
                error_message = first_error.get("message", "unknown error")
                return f"Cloudflare API error {status_code}: {error_code} {error_message}"

        return f"Cloudflare API error {status_code}"

    def _assert_record_state(
        self,
        record_id: str,
        expected_content: str,
        expected_proxied: bool,
    ) -> None:
        record = self.get_dns_record_by_id(record_id)
        actual_content = record.get("content")
        actual_proxied = record.get("proxied")
        if actual_content != expected_content or actual_proxied is not expected_proxied:
            raise CloudflareApiError(
                status_code=409,
                message=(
                    "Cloudflare DNS record state mismatch after update: "
                    f"record_id={record_id}"
                ),
            )
