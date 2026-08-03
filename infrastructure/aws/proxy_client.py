from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import secrets
import string
from typing import Any
from urllib.parse import quote, urlsplit

import requests

from models.config_models import AwsProxyConfig
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import execute_with_backoff

RETRYABLE_PROXY_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_DECODO_BASE_URL = "https://api.decodo.com/v2"
DEFAULT_EVOMI_BASE_URL = "https://api.evomi.com"

AWS_REGION_COUNTRY_MAP: dict[str, str] = {
    "af-south-1": "ZA",
    "ap-east-1": "HK",
    "ap-northeast-1": "JP",
    "ap-northeast-2": "KR",
    "ap-northeast-3": "JP",
    "ap-south-1": "IN",
    "ap-south-2": "IN",
    "ap-southeast-1": "SG",
    "ap-southeast-2": "AU",
    "ap-southeast-3": "ID",
    "ap-southeast-4": "AU",
    "ap-southeast-5": "MY",
    "ap-southeast-6": "NZ",
    "ap-southeast-7": "TH",
    "ca-central-1": "CA",
    "ca-west-1": "CA",
    "cn-north-1": "CN",
    "cn-northwest-1": "CN",
    "eu-central-1": "DE",
    "eu-central-2": "CH",
    "eu-north-1": "SE",
    "eu-south-1": "IT",
    "eu-south-2": "ES",
    "eu-west-1": "IE",
    "eu-west-2": "GB",
    "eu-west-3": "FR",
    "il-central-1": "IL",
    "me-central-1": "AE",
    "me-south-1": "BH",
    "mx-central-1": "MX",
    "sa-east-1": "BR",
    "us-east-1": "US",
    "us-east-2": "US",
    "us-gov-east-1": "US",
    "us-gov-west-1": "US",
    "us-west-1": "US",
    "us-west-2": "US",
}


@dataclass(frozen=True)
class ProxyResolutionContext:
    aws_region: str | None = None


class AwsProxyClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _BaseAwsProxyClient:
    def __init__(
        self,
        runtime_context: RuntimeContext,
        resolution_context: ProxyResolutionContext | None = None,
    ) -> None:
        self._logger = runtime_context.logger.getChild("infrastructure.aws.proxy")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._config = runtime_context.config.aws_proxy
        self._resolution_context = resolution_context or ProxyResolutionContext()

        if not self._config.enabled:
            raise ValueError("AWS proxy client requires aws_proxy.enabled=true")

        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, object] | None = None,
    ) -> Any:
        url = f"{self._resolve_base_url().rstrip('/')}{endpoint}"

        def _send_request() -> Any:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                timeout=self._request_timeout_seconds,
            )
            return self._validate_response(response)

        try:
            return execute_with_backoff(
                operation_name=f"aws_proxy_{self._config.provider}_{method.lower()}_{endpoint}",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="aws_proxy",
                func=_send_request,
                should_retry=self._should_retry_exception,
            )
        except (AwsProxyClientError, requests.ConnectionError, requests.Timeout):
            set_event_type("aws_proxy_request_failed")
            self._logger.exception(
                "AWS proxy request failed: provider=%s method=%s endpoint=%s",
                self._config.provider,
                method,
                endpoint,
            )
            raise

    def _resolve_required_country(self) -> str | None:
        aws_region = self._resolution_context.aws_region
        if aws_region is None:
            return self._config.country
        normalized_region = aws_region.strip().lower()
        country = AWS_REGION_COUNTRY_MAP.get(normalized_region)
        if country is None:
            raise AwsProxyClientError(
                f"Unsupported AWS region for proxy country mapping: {aws_region}"
            )
        configured_country = self._config.country
        if configured_country is not None and configured_country.upper() != country:
            raise AwsProxyClientError(
                "aws_proxy.country conflicts with the AWS region country mapping "
                f"(region={aws_region}, expected_country={country}, configured_country={configured_country})"
            )
        return country

    def _resolve_base_url(self) -> str:
        if self._config.provider == "decodo" and self._config.base_url == DEFAULT_EVOMI_BASE_URL:
            return DEFAULT_DECODO_BASE_URL
        if self._config.provider == "evomi" and self._config.base_url == DEFAULT_DECODO_BASE_URL:
            return DEFAULT_EVOMI_BASE_URL
        return self._config.base_url

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


class DecodoAwsProxyClient(_BaseAwsProxyClient):
    def __init__(
        self,
        runtime_context: RuntimeContext,
        resolution_context: ProxyResolutionContext | None = None,
    ) -> None:
        super().__init__(runtime_context, resolution_context)
        self._session.headers.update({"Authorization": self._config.authorization or ""})

    def resolve_proxy_url(self) -> str:
        response_payload = self._request(
            method="GET",
            endpoint="/endpoints-custom",
            params=_build_decodo_proxy_query_params(
                self._config,
                self._resolve_required_country(),
            ),
        )
        if not isinstance(response_payload, list) or not response_payload:
            raise AwsProxyClientError("Proxy API returned an empty endpoint list")

        first_proxy = response_payload[0]
        if not isinstance(first_proxy, str) or not first_proxy.strip():
            raise AwsProxyClientError("Proxy API returned an invalid proxy endpoint")

        proxy_url = first_proxy.strip()
        _validate_proxy_url(proxy_url)

        parsed_proxy = urlsplit(proxy_url)
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


class EvomiAwsProxyClient(_BaseAwsProxyClient):
    def __init__(
        self,
        runtime_context: RuntimeContext,
        resolution_context: ProxyResolutionContext | None = None,
    ) -> None:
        super().__init__(runtime_context, resolution_context)
        self._session.headers.update({"x-apikey": self._config.api_key or ""})

    def resolve_proxy_url(self) -> str:
        required_country = self._resolve_required_country()
        response_payload = self._request(method="GET", endpoint="/public")
        if not isinstance(response_payload, dict) or response_payload.get("success") is not True:
            raise AwsProxyClientError("Evomi API returned an unsuccessful proxy data response")

        products = response_payload.get("products")
        if not isinstance(products, dict):
            raise AwsProxyClientError("Evomi API returned an invalid products payload")

        product_payload = products.get(self._config.product)
        if not isinstance(product_payload, dict):
            raise AwsProxyClientError(
                f"Evomi API response does not contain product={self._config.product}"
            )

        username = _require_string(product_payload, "username")
        password = _require_string(product_payload, "password")
        endpoint = _require_string(product_payload, "endpoint")
        port = _resolve_evomi_port(product_payload, self._config)
        session_id = _resolve_session_id(self._config)
        proxy_scheme = "http"
        proxy_password = _build_evomi_password(
            base_password=password,
            config=self._config,
            country=required_country,
            session_id=session_id,
        )
        proxy_url = (
            f"{proxy_scheme}://{quote(username, safe='')}:{quote(proxy_password, safe='')}"
            f"@{endpoint}:{port}"
        )
        _validate_proxy_url(proxy_url)

        set_event_type("aws_proxy_resolved")
        self._logger.info(
            "Resolved AWS proxy endpoint via Evomi: provider=%s product=%s aws_region=%s country=%s host=%s port=%s",
            self._config.provider,
            self._config.product,
            self._resolution_context.aws_region,
            required_country,
            endpoint,
            port,
        )
        return proxy_url

def build_aws_boto_proxies(
    runtime_context: RuntimeContext,
    aws_region: str | None = None,
) -> dict[str, str] | None:
    if not runtime_context.config.aws_proxy.enabled:
        return None

    resolution_context = ProxyResolutionContext(aws_region=aws_region)
    if runtime_context.config.aws_proxy.provider == "decodo":
        proxy_url = DecodoAwsProxyClient(runtime_context, resolution_context).resolve_proxy_url()
    elif runtime_context.config.aws_proxy.provider == "evomi":
        proxy_url = EvomiAwsProxyClient(runtime_context, resolution_context).resolve_proxy_url()
    else:
        raise AwsProxyClientError(
            f"Unsupported aws_proxy.provider: {runtime_context.config.aws_proxy.provider}"
        )

    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def _build_decodo_proxy_query_params(
    config: AwsProxyConfig,
    required_country: str | None,
) -> dict[str, object]:
    location = config.location
    if required_country is not None:
        if location == "random":
            location = required_country.lower()
        elif len(location) == 2:
            if location.upper() != required_country:
                raise AwsProxyClientError(
                    "aws_proxy.location conflicts with the AWS region country mapping "
                    f"(expected_country={required_country}, configured_location={config.location})"
                )
        else:
            raise AwsProxyClientError(
                "aws_proxy.location must be 'random' or a two-letter country code when "
                f"an AWS region is provided (region_country={required_country}, configured_location={config.location})"
            )

    return {
        "proxyType": config.proxy_type,
        "authType": config.auth_type,
        "username": config.username,
        "password": config.password,
        "sessionType": "sticky" if config.session_type == "hard" else config.session_type,
        "sessionDuration": config.session_duration_minutes,
        "location": location,
        "outputFormat": config.output_format,
        "count": config.count,
        "page": config.page,
        "responseType": config.response_type,
        "domain": config.domain,
    }


def _build_evomi_password(
    base_password: str,
    config: AwsProxyConfig,
    country: str | None,
    session_id: str | None,
) -> str:
    suffixes: list[str] = []
    if country is not None:
        suffixes.append(f"country-{country}")
    if config.region is not None:
        suffixes.append(f"region-{_normalize_evomi_geo_token(config.region)}")
    if config.city is not None:
        suffixes.append(f"city-{_normalize_evomi_geo_token(config.city)}")
    if session_id is not None:
        if config.session_type == "hard":
            suffixes.append(f"hardsession-{session_id}")
        elif config.session_type == "sticky":
            suffixes.append(f"session-{session_id}")
            suffixes.append(f"lifetime-{config.session_duration_minutes}")
    if config.adblock_enabled:
        suffixes.append("adblock-1")
    if not suffixes:
        return base_password
    return f"{base_password}_{'_'.join(suffixes)}"


def _normalize_evomi_geo_token(value: str) -> str:
    return value.strip().lower().replace(" ", ".")


def _resolve_evomi_port(product_payload: dict[str, Any], config: AwsProxyConfig) -> int:
    ports = product_payload.get("ports")
    if not isinstance(ports, dict):
        raise AwsProxyClientError("Evomi API returned an invalid ports payload")

    port_key = "http" if config.protocol in {"http", "https"} else config.protocol
    port_value = ports.get(port_key)
    if port_value is None and config.protocol == "https":
        port_value = ports.get("http")
    if not isinstance(port_value, int):
        raise AwsProxyClientError(
            f"Evomi API response does not contain a valid port for protocol={config.protocol}"
        )
    return port_value


def _resolve_session_id(config: AwsProxyConfig) -> str | None:
    if config.session_type == "random":
        return None
    if config.session_id is not None:
        return config.session_id
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AwsProxyClientError(f"Evomi API returned an invalid {key} field")
    return value.strip()


def _validate_proxy_url(proxy_url: str) -> None:
    parsed_proxy = urlsplit(proxy_url)
    if not parsed_proxy.scheme or not parsed_proxy.hostname or parsed_proxy.port is None:
        raise AwsProxyClientError("Proxy API returned a malformed proxy URL")
