from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
import time
from typing import Any

import requests

from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import execute_with_backoff


DEFAULT_BASE_URL = "https://cloudcli.cloudwm.com"
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class KamateraClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class KamateraServerLaunchRequest:
    name: str
    datacenter: str
    image: str
    cpu: str
    ram_mb: int
    disk_sizes_gb: tuple[int, ...]
    startup_script: str
    ssh_public_key: str
    billing_cycle: str = "hourly"
    monthly_package: str | None = None
    daily_backup: bool = False
    managed: bool = False
    tags: tuple[str, ...] = ()
    password: str = "__generate__"


@dataclass(frozen=True)
class KamateraServerCloneRequest:
    source_id: str
    name: str
    ssh_public_key: str = ""
    startup_script: str = ""
    tags: tuple[str, ...] = ()
    password: str = "__generate__"


@dataclass(frozen=True)
class KamateraServerLaunchResult:
    instance_id: str
    name: str
    datacenter: str
    cpu: str | None
    ram_mb: int | None
    ipv4_address: str | None
    ipv6_address: str | None
    networks: tuple[dict[str, Any], ...]


class KamateraClient:
    """Adapter for Kamatera's CloudCLI JSON API."""

    def __init__(
        self,
        runtime_context: RuntimeContext,
        client_id: str,
        secret: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        if not client_id or not client_id.strip():
            raise ValueError("Kamatera Client ID must not be empty")
        if not secret or not secret.strip():
            raise ValueError("Kamatera API secret must not be empty")

        self._logger = runtime_context.logger.getChild("infrastructure.kamatera")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._base_url = base_url.rstrip("/")
        self._created_server_id: str | None = None
        self._created_server_name: str | None = None
        self._session = requests.Session()
        self._session.headers.update(
            {
                "AuthClientId": client_id.strip(),
                "AuthSecret": secret.strip(),
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    @property
    def created_server_id(self) -> str | None:
        return self._created_server_id

    @property
    def created_server_name(self) -> str | None:
        return self._created_server_name

    def validate_account(self) -> None:
        self.list_datacenters()

    def list_datacenters(self) -> list[dict[str, Any]]:
        return self._as_object_list(
            self._request("GET", "/service/server/options/datacenters"),
            "datacenters",
        )

    def list_images(self, datacenter: str) -> list[dict[str, Any]]:
        return self._as_object_list(
            self._request(
                "POST",
                "/service/server/options/images",
                payload={"datacenter": _required_text(datacenter, "datacenter")},
            ),
            "images",
        )

    def get_capabilities(self, datacenter: str) -> dict[str, Any]:
        payload = self._request(
            "GET",
            "/service/server",
            params={
                "capabilities": 1,
                "datacenter": _required_text(datacenter, "datacenter"),
            },
        )
        if not isinstance(payload, dict):
            raise KamateraClientError("Kamatera capabilities response must be an object")
        return payload

    def list_servers(self) -> list[dict[str, Any]]:
        return self._as_object_list(
            self._request("GET", "/service/servers"),
            "servers",
        )

    def get_server(self, server_id: str) -> dict[str, Any]:
        servers = self._as_object_list(
            self._request(
                "POST",
                "/service/server/info",
                payload={"id": _required_text(server_id, "server_id")},
            ),
            "server info",
        )
        if len(servers) != 1:
            raise KamateraClientError(f"Kamatera server not found: {server_id}", 404)
        return servers[0]

    def get_server_by_name(self, name: str) -> dict[str, Any]:
        normalized_name = _required_text(name, "name")
        servers = self._as_object_list(
            self._request(
                "POST",
                "/service/server/info",
                payload={"name": normalized_name},
            ),
            "server info",
        )
        exact = [server for server in servers if str(server.get("name") or "") == normalized_name]
        if len(exact) != 1:
            raise KamateraClientError(f"Kamatera server not found: {normalized_name}", 404)
        return exact[0]

    def list_server_tags(self, server_id: str) -> tuple[str, ...]:
        payload = self._request(
            "POST",
            "/server/tags",
            payload={"id": _required_text(server_id, "server_id")},
        )
        values = payload if isinstance(payload, list) else payload.get("tags", []) if isinstance(payload, dict) else []
        tags: list[str] = []
        if isinstance(values, list):
            for value in values:
                raw = value.get("tagName") if isinstance(value, dict) else value
                text = str(raw or "").strip()
                if text:
                    tags.append(text)
        return tuple(dict.fromkeys(tags))

    def validate_provisioning_target(
        self,
        *,
        datacenter: str,
        image: str,
    ) -> None:
        datacenter_id = _required_text(datacenter, "datacenter")
        image_id = _required_text(image, "image")
        datacenters = self.list_datacenters()
        if not any(str(item.get("id") or "") == datacenter_id for item in datacenters):
            raise KamateraClientError(f"Kamatera datacenter is not available: {datacenter_id}")
        images = self.list_images(datacenter_id)
        if not any(str(item.get("id") or "") == image_id for item in images):
            raise KamateraClientError(
                f"Kamatera image is not available in {datacenter_id}: {image_id}"
            )

    def launch_server(
        self,
        request: KamateraServerLaunchRequest,
        *,
        wait_timeout_seconds: int = 2400,
        poll_interval_seconds: float = 2.0,
    ) -> KamateraServerLaunchResult:
        self._validate_launch_request(request)
        tags = tuple(dict.fromkeys(("shadowfleet", *request.tags)))
        password = request.password.strip() or "__generate__"
        payload: dict[str, Any] = {
            "name": request.name.strip(),
            "password": password,
            "passwordValidate": password,
            "ssh-key": request.ssh_public_key.strip(),
            "datacenter": request.datacenter.strip(),
            "image": request.image.strip(),
            "cpu": request.cpu.strip(),
            "ram": request.ram_mb,
            "disk": " ".join(f"size={size}" for size in request.disk_sizes_gb),
            "dailybackup": "yes" if request.daily_backup else "no",
            "managed": "yes" if request.managed else "no",
            "network": "name=wan,ip=auto",
            "quantity": "1",
            "billingcycle": request.billing_cycle,
            "poweronaftercreate": "yes",
            "script-file": request.startup_script,
            "tag": list(tags),
        }
        if request.monthly_package:
            payload["monthlypackage"] = request.monthly_package.strip()

        self._created_server_name = request.name.strip()
        response = self._request("POST", "/service/server", payload=payload)
        command_id = self._extract_command_id(response)
        command = self.wait_for_command(
            command_id,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        server_name = self._server_name_from_command(command) or self._created_server_name
        server = self.get_server_by_name(server_name)
        self._created_server_id = _required_text(server.get("id"), "server.id")
        set_event_type("kamatera_server_created")
        return self._to_launch_result(server)

    def clone_server(
        self,
        request: KamateraServerCloneRequest,
        *,
        wait_timeout_seconds: int = 2400,
        poll_interval_seconds: float = 2.0,
    ) -> KamateraServerLaunchResult:
        if not request.source_id.strip():
            raise ValueError("Kamatera clone source_id must not be empty")
        if len(request.name.strip()) < 4:
            raise ValueError("Kamatera server name must contain at least 4 characters")
        password = request.password.strip() or "__generate__"
        payload: dict[str, Any] = {
            "source-id": request.source_id.strip(),
            "name": request.name.strip(),
            "password": password,
            "passwordValidate": password,
            "network": "name=wan,ip=auto",
            "poweronaftercreate": "yes",
            "tag": list(dict.fromkeys(("shadowfleet", *request.tags))),
        }
        if request.ssh_public_key.strip():
            payload["ssh-key"] = request.ssh_public_key.strip()
        if request.startup_script:
            payload["script-file"] = request.startup_script

        self._created_server_name = request.name.strip()
        response = self._request("POST", "/service/cloneServer", payload=payload)
        command = self.wait_for_command(
            self._extract_command_id(response),
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        server_name = self._server_name_from_command(command) or self._created_server_name
        server = self.get_server_by_name(server_name)
        self._created_server_id = _required_text(server.get("id"), "server.id")
        set_event_type("kamatera_server_cloned")
        return self._to_launch_result(server)

    def delete_server(
        self,
        server_id: str | None = None,
        *,
        name: str | None = None,
        wait_timeout_seconds: int = 2400,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        normalized_id = _optional_text(server_id)
        normalized_name = _optional_text(name)
        if normalized_id is None and normalized_name is None:
            raise ValueError("Kamatera server_id or name is required")
        payload: dict[str, Any] = {"force": True}
        if normalized_id:
            payload["id"] = normalized_id
        else:
            payload["name"] = normalized_name
        try:
            response = self._request("POST", "/service/server/terminate", payload=payload)
        except KamateraClientError as exc:
            if exc.status_code == 404 or _looks_not_found(str(exc)):
                return
            raise
        for command_id in self._extract_command_ids(response):
            self.wait_for_command(
                command_id,
                timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        set_event_type("kamatera_server_deleted")

    def wait_for_command(
        self,
        command_id: str,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            commands = self._as_object_list(
                self._request(
                    "GET",
                    "/service/queue",
                    params={"id": command_id},
                ),
                "queue",
            )
            if len(commands) != 1:
                raise KamateraClientError(
                    "Kamatera queue response must contain exactly one command"
                )
            command = commands[0]
            status = str(command.get("status") or "").lower()
            if status == "complete":
                return command
            if status == "error":
                detail = str(command.get("log") or command.get("description") or command)
                raise KamateraClientError(f"Kamatera command failed: {detail}")
            time.sleep(poll_interval_seconds)
        raise KamateraClientError(
            f"Timed out waiting for Kamatera command: {command_id}"
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        normalized_method = method.upper()

        def perform_request() -> Any:
            try:
                response = self._session.request(
                    method=normalized_method,
                    url=f"{self._base_url}{endpoint}",
                    json=payload,
                    params=params,
                    timeout=self._request_timeout_seconds,
                )
            except requests.RequestException as exc:
                raise KamateraClientError(f"Kamatera request failed: {exc}") from exc

            try:
                body = response.json()
            except ValueError as exc:
                raise KamateraClientError(
                    f"Kamatera returned invalid JSON (HTTP {response.status_code})",
                    response.status_code,
                ) from exc
            if response.status_code != 200:
                raise KamateraClientError(
                    f"Kamatera API error (HTTP {response.status_code}): {_error_detail(body)}",
                    response.status_code,
                )
            embedded_error = _embedded_error(body)
            if embedded_error is not None:
                status_code = 404 if _looks_not_found(embedded_error) else response.status_code
                raise KamateraClientError(
                    f"Kamatera API error: {embedded_error}",
                    status_code,
                )
            return body

        try:
            return execute_with_backoff(
                operation_name=f"kamatera_{normalized_method.lower()}_{endpoint}",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="kamatera",
                func=perform_request,
                should_retry=lambda exc: isinstance(exc, KamateraClientError)
                and exc.status_code in RETRYABLE_STATUS_CODES,
            )
        except KamateraClientError:
            set_event_type("kamatera_request_failed")
            raise

    @staticmethod
    def _extract_command_ids(payload: Any) -> tuple[str, ...]:
        values: Any
        if isinstance(payload, dict):
            values = payload.get("commandIds") or payload.get("command_ids")
        else:
            values = payload
        if isinstance(values, (str, int, float)):
            values = [values]
        if not isinstance(values, list):
            raise KamateraClientError("Kamatera response is missing command IDs")
        command_ids = tuple(str(value).strip() for value in values if str(value).strip())
        if not command_ids:
            raise KamateraClientError("Kamatera response is missing command IDs")
        return command_ids

    @classmethod
    def _extract_command_id(cls, payload: Any) -> str:
        command_ids = cls._extract_command_ids(payload)
        if len(command_ids) != 1:
            raise KamateraClientError("Kamatera response returned an unexpected command count")
        return command_ids[0]

    @staticmethod
    def _server_name_from_command(command: dict[str, Any]) -> str | None:
        server = command.get("server")
        if isinstance(server, dict):
            name = _optional_text(server.get("name"))
            if name:
                return name
        log = str(command.get("log") or "")
        match = re.search(r"(?m)^Name:\s*(.+?)\s*$", log)
        return match.group(1).strip() if match else None

    @staticmethod
    def _as_object_list(payload: Any, resource_name: str) -> list[dict[str, Any]]:
        values = payload
        if isinstance(payload, dict):
            for key in (resource_name, "items", "data", "servers", "images", "datacenters"):
                if isinstance(payload.get(key), list):
                    values = payload[key]
                    break
        if not isinstance(values, list):
            raise KamateraClientError(
                f"Kamatera {resource_name} response must be a list"
            )
        return [value for value in values if isinstance(value, dict)]

    @staticmethod
    def _validate_launch_request(request: KamateraServerLaunchRequest) -> None:
        if len(request.name.strip()) < 4:
            raise ValueError("Kamatera server name must contain at least 4 characters")
        for value, field_name in (
            (request.datacenter, "datacenter"),
            (request.image, "image"),
            (request.cpu, "cpu"),
            (request.ssh_public_key, "ssh_public_key"),
        ):
            _required_text(value, field_name)
        if request.ram_mb < 256:
            raise ValueError("Kamatera ram_mb must be at least 256")
        if not request.disk_sizes_gb or len(request.disk_sizes_gb) > 4:
            raise ValueError("Kamatera requires between one and four disks")
        if any(size <= 0 for size in request.disk_sizes_gb):
            raise ValueError("Kamatera disk sizes must be greater than 0")
        if request.billing_cycle not in {"hourly", "monthly"}:
            raise ValueError("Kamatera billing_cycle must be hourly or monthly")
        if request.billing_cycle == "monthly" and not _optional_text(request.monthly_package):
            raise ValueError("Kamatera monthly_package is required for monthly billing")

    @staticmethod
    def _to_launch_result(server: dict[str, Any]) -> KamateraServerLaunchResult:
        networks_raw = server.get("networks")
        networks = tuple(
            network for network in networks_raw if isinstance(network, dict)
        ) if isinstance(networks_raw, list) else ()
        ipv4, ipv6 = _public_ip_addresses(networks)
        ram_value = server.get("ram")
        try:
            ram_mb = int(ram_value) if ram_value is not None else None
        except (TypeError, ValueError):
            ram_mb = None
        return KamateraServerLaunchResult(
            instance_id=_required_text(server.get("id"), "server.id"),
            name=_required_text(server.get("name"), "server.name"),
            datacenter=_required_text(server.get("datacenter"), "server.datacenter"),
            cpu=_optional_text(server.get("cpu")),
            ram_mb=ram_mb,
            ipv4_address=ipv4,
            ipv6_address=ipv6,
            networks=networks,
        )


def _public_ip_addresses(
    networks: tuple[dict[str, Any], ...],
) -> tuple[str | None, str | None]:
    ipv4: str | None = None
    ipv6: str | None = None
    for network in networks:
        network_name = str(network.get("network") or network.get("name") or "").lower()
        if network_name and not (network_name == "wan" or network_name.startswith("wan-")):
            continue
        raw_ips = network.get("ips")
        if not isinstance(raw_ips, list):
            continue
        for raw_ip in raw_ips:
            value = raw_ip.get("ip") if isinstance(raw_ip, dict) else raw_ip
            text = str(value or "").split("/")[0].strip()
            try:
                parsed = ipaddress.ip_address(text)
            except ValueError:
                continue
            if parsed.version == 4 and ipv4 is None:
                ipv4 = str(parsed)
            elif parsed.version == 6 and ipv6 is None:
                ipv6 = str(parsed)
    return ipv4, ipv6


def server_created_at(server: dict[str, Any]) -> str:
    for key in ("created", "createdAt", "creationDate", "dateCreated", "date_created"):
        value = _optional_text(server.get(key))
        if value:
            return value
    return ""


def server_tags(server: dict[str, Any]) -> tuple[str, ...]:
    raw = server.get("tags") or server.get("tag")
    if not isinstance(raw, list):
        return ()
    values: list[str] = []
    for item in raw:
        value = item.get("tagName") if isinstance(item, dict) else item
        text = str(value or "").strip()
        if text:
            values.append(text)
    return tuple(dict.fromkeys(values))


def _embedded_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    errors = payload.get("errors")
    error = payload.get("error")
    if errors:
        return _error_detail(errors)
    if error is True:
        return _error_detail(payload.get("message") or payload.get("description") or payload)
    if isinstance(error, (str, dict, list)) and error:
        return _error_detail(error)
    return None


def _error_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("message", "description", "detail", "error"):
            if payload.get(key):
                return _error_detail(payload[key])
    if isinstance(payload, list):
        return "; ".join(_error_detail(item) for item in payload)
    return str(payload)


def _looks_not_found(message: str) -> bool:
    normalized = message.casefold()
    return "not found" in normalized or "failed to find server" in normalized


def _required_text(value: object, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"Kamatera {field_name} must not be empty")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
