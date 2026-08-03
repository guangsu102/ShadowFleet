from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import requests

from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import execute_with_backoff


DEFAULT_BASE_URL = "https://api.digitalocean.com/v2"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class DigitalOceanClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class DigitalOceanDropletLaunchRequest:
    name: str
    region: str
    size: str
    image: str
    user_data: str
    ssh_keys: tuple[str | int, ...] = ()
    vpc_uuid: str | None = None
    tags: tuple[str, ...] = ()
    ipv6: bool = True
    monitoring: bool = True


@dataclass(frozen=True)
class DigitalOceanDropletLaunchResult:
    instance_id: str
    droplet_id: int
    name: str
    region: str
    size: str
    image: str
    ipv4_address: str | None
    ipv6_addresses: tuple[str, ...]
    network_interface_id: str | None = None
    subnet_id: str | None = None


class DigitalOceanClient:
    def __init__(
        self,
        runtime_context: RuntimeContext,
        api_token: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        if not api_token or not api_token.strip():
            raise ValueError("DigitalOcean API token must not be empty")

        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("infrastructure.digitalocean")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_token.strip()}",
                "Content-Type": "application/json",
            }
        )

    def validate_account(self) -> dict[str, Any]:
        payload = self._request("GET", "/account")
        account = payload.get("account")
        if not isinstance(account, dict):
            raise DigitalOceanClientError("DigitalOcean account response missing account payload")
        return account

    def list_images(self, image_type: str = "distribution", per_page: int = 100) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            "/images",
            params={"type": image_type, "per_page": per_page},
        )
        images = payload.get("images", [])
        if not isinstance(images, list):
            raise DigitalOceanClientError("DigitalOcean images response must be a list")
        return [image for image in images if isinstance(image, dict)]

    def list_sizes(self, per_page: int = 200) -> list[dict[str, Any]]:
        payload = self._request("GET", "/sizes", params={"per_page": per_page})
        sizes = payload.get("sizes", [])
        if not isinstance(sizes, list):
            raise DigitalOceanClientError("DigitalOcean sizes response must be a list")
        return [size for size in sizes if isinstance(size, dict)]

    def launch_droplet(
        self,
        request: DigitalOceanDropletLaunchRequest,
        wait_timeout_seconds: int = 300,
        poll_interval_seconds: float = 5.0,
    ) -> DigitalOceanDropletLaunchResult:
        if len(request.user_data.encode("utf-8")) > 64 * 1024:
            raise DigitalOceanClientError("DigitalOcean user_data must be 64 KiB or smaller")

        payload: dict[str, Any] = {
            "name": request.name,
            "region": request.region,
            "size": request.size,
            "image": request.image,
            "ssh_keys": list(request.ssh_keys),
            "backups": False,
            "ipv6": request.ipv6,
            "monitoring": request.monitoring,
            "tags": list(request.tags),
            "user_data": request.user_data,
        }
        if request.vpc_uuid:
            payload["vpc_uuid"] = request.vpc_uuid

        response_payload = self._request("POST", "/droplets", payload=payload, expected_status={202})
        droplet = response_payload.get("droplet")
        if not isinstance(droplet, dict) or droplet.get("id") is None:
            raise DigitalOceanClientError("DigitalOcean create droplet response missing droplet.id")

        droplet_id = int(droplet["id"])
        set_event_type("do_droplet_created")
        self._logger.info("Created DigitalOcean droplet id=%s name=%s", droplet_id, request.name)

        final_droplet = self.wait_for_droplet_active(
            droplet_id=droplet_id,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        return self._map_launch_result(final_droplet, request)

    def get_droplet(self, droplet_id: int | str) -> dict[str, Any]:
        payload = self._request("GET", f"/droplets/{droplet_id}")
        droplet = payload.get("droplet")
        if not isinstance(droplet, dict):
            raise DigitalOceanClientError(f"DigitalOcean droplet not found: {droplet_id}")
        return droplet

    def wait_for_droplet_active(
        self,
        droplet_id: int,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            droplet = self.get_droplet(droplet_id)
            if droplet.get("status") == "active":
                return droplet
            time.sleep(poll_interval_seconds)
        raise DigitalOceanClientError(
            f"Timed out waiting for DigitalOcean droplet to become active: {droplet_id}"
        )

    def delete_droplet(self, droplet_id: int | str) -> None:
        self._request("DELETE", f"/droplets/{droplet_id}", expected_status={204})
        set_event_type("do_droplet_deleted")
        self._logger.info("Deleted DigitalOcean droplet id=%s", droplet_id)

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
        expected_status: set[int] | None = None,
    ) -> dict[str, Any]:
        expected = expected_status or {200}
        url = f"{self._base_url}{endpoint}"

        def _send_request() -> dict[str, Any]:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                json=payload,
                timeout=self._request_timeout_seconds,
            )
            if response.status_code not in expected:
                raise self._build_error(response)
            if response.status_code == 204 or not response.content:
                return {}
            try:
                parsed = response.json()
            except ValueError as exc:
                raise DigitalOceanClientError(
                    f"DigitalOcean returned a non-JSON response: status={response.status_code}",
                    status_code=response.status_code,
                ) from exc
            if not isinstance(parsed, dict):
                raise DigitalOceanClientError("DigitalOcean response payload must be a JSON object")
            return parsed

        try:
            return execute_with_backoff(
                operation_name=f"digitalocean_{method.lower()}_{endpoint}",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="digitalocean",
                func=_send_request,
                should_retry=self._should_retry_exception,
            )
        except (DigitalOceanClientError, requests.ConnectionError, requests.Timeout):
            set_event_type("do_request_failed")
            self._logger.exception("DigitalOcean request failed: method=%s endpoint=%s", method, endpoint)
            raise

    @staticmethod
    def _should_retry_exception(exc: BaseException) -> bool:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
        if isinstance(exc, DigitalOceanClientError) and exc.status_code in RETRYABLE_STATUS_CODES:
            return True
        return False

    @staticmethod
    def _build_error(response: requests.Response) -> DigitalOceanClientError:
        message = response.text.strip()
        try:
            parsed = response.json()
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            error_message = parsed.get("message") or parsed.get("error")
            if error_message:
                message = str(error_message)
        return DigitalOceanClientError(
            f"DigitalOcean API error {response.status_code}: {message}",
            status_code=response.status_code,
        )

    @staticmethod
    def _map_launch_result(
        droplet: dict[str, Any],
        request: DigitalOceanDropletLaunchRequest,
    ) -> DigitalOceanDropletLaunchResult:
        networks = droplet.get("networks")
        ipv4_address: str | None = None
        ipv6_addresses: list[str] = []
        if isinstance(networks, dict):
            for network in networks.get("v4", []):
                if isinstance(network, dict) and network.get("type") == "public":
                    ipv4_address = str(network.get("ip_address"))
                    break
            for network in networks.get("v6", []):
                if isinstance(network, dict) and network.get("type") == "public":
                    ip_address = network.get("ip_address")
                    if ip_address:
                        ipv6_addresses.append(str(ip_address))

        droplet_id = int(droplet["id"])
        image = droplet.get("image")
        image_slug = request.image
        if isinstance(image, dict) and image.get("slug"):
            image_slug = str(image["slug"])

        size = droplet.get("size_slug") or request.size
        return DigitalOceanDropletLaunchResult(
            instance_id=str(droplet_id),
            droplet_id=droplet_id,
            name=str(droplet.get("name") or request.name),
            region=request.region,
            size=str(size),
            image=image_slug,
            ipv4_address=ipv4_address,
            ipv6_addresses=tuple(ipv6_addresses),
            subnet_id=request.vpc_uuid,
        )
