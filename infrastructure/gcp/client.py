from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import time
from typing import Any

import requests

from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import execute_with_backoff


COMPUTE_SCOPE = "https://www.googleapis.com/auth/compute"
DEFAULT_COMPUTE_BASE_URL = "https://compute.googleapis.com/compute/v1"
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
MANAGED_LABEL_KEY = "managed-by"
MANAGED_LABEL_VALUE = "shadowfleet"
CREATED_AT_LABEL = "shadowfleet-created-at"


class GCPClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class GCPCredentials:
    project_id: str
    client_email: str
    private_key: str
    private_key_id: str | None = None
    client_id: str | None = None
    token_uri: str = "https://oauth2.googleapis.com/token"

    @classmethod
    def from_service_account_json(
        cls,
        value: str | dict[str, object],
        *,
        project_id: str | None = None,
    ) -> "GCPCredentials":
        try:
            payload = json.loads(value) if isinstance(value, str) else dict(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("GCP service_account_json must be valid JSON") from exc
        if payload.get("type") not in (None, "service_account"):
            raise ValueError("GCP credentials must be a service account key")
        return cls(
            project_id=_required_text(project_id or payload.get("project_id"), "project_id"),
            client_email=_required_text(payload.get("client_email"), "client_email"),
            private_key=_required_text(payload.get("private_key"), "private_key"),
            private_key_id=_optional_text(payload.get("private_key_id")),
            client_id=_optional_text(payload.get("client_id")),
            token_uri=_optional_text(payload.get("token_uri"))
            or "https://oauth2.googleapis.com/token",
        )

    def to_service_account_info(self) -> dict[str, str]:
        info = {
            "type": "service_account",
            "project_id": self.project_id,
            "client_email": self.client_email,
            "private_key": self.private_key,
            "token_uri": self.token_uri,
        }
        if self.private_key_id:
            info["private_key_id"] = self.private_key_id
        if self.client_id:
            info["client_id"] = self.client_id
        return info


@dataclass(frozen=True)
class GCPProvisioningTarget:
    zone: str
    region: str
    machine_type: str
    source_image: str
    network: str
    subnetwork: str | None
    architecture: str
    guest_cpus: int | None


@dataclass(frozen=True)
class GCPInstanceLaunchRequest:
    name: str
    zone: str
    machine_type: str
    source_image: str
    network: str
    subnetwork: str | None
    ssh_username: str
    ssh_public_key: str
    startup_script: str
    labels: dict[str, str] | None = None
    network_tags: tuple[str, ...] = ("shadowfleet",)


@dataclass(frozen=True)
class GCPInstanceLaunchResult:
    instance_id: str
    name: str
    zone: str
    machine_type: str
    network_interface: str
    ipv4_address: str | None
    ipv6_address: str | None


class GCPClient:
    """Compute Engine REST adapter authenticated with a service account."""

    def __init__(
        self,
        runtime_context: RuntimeContext,
        credentials: GCPCredentials,
        *,
        session: Any | None = None,
        compute_base_url: str = DEFAULT_COMPUTE_BASE_URL,
    ) -> None:
        self._credentials = _validate_credentials(credentials)
        self._project_id = self._credentials.project_id
        self._logger = runtime_context.logger.getChild("infrastructure.gcp")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._base_url = compute_base_url.rstrip("/")
        self._session = session or _build_authorized_session(self._credentials)
        self._created_instance_name: str | None = None
        self._created_instance_zone: str | None = None

    @property
    def project_id(self) -> str:
        return self._project_id

    @property
    def created_instance_name(self) -> str | None:
        return self._created_instance_name

    @property
    def created_instance_zone(self) -> str | None:
        return self._created_instance_zone

    def validate_project(self) -> dict[str, Any]:
        project = self._require_object(
            self._request("GET", f"/projects/{self._project_id}"),
            "project",
        )
        if str(project.get("name") or "") != self._project_id:
            raise GCPClientError("GCP project validation returned an unexpected project")
        return project

    def list_zones(self) -> list[dict[str, Any]]:
        return self._list_collection(f"/projects/{self._project_id}/zones")

    def list_machine_types(self, zone: str) -> list[dict[str, Any]]:
        return self._list_collection(
            f"/projects/{self._project_id}/zones/{_required_text(zone, 'zone')}/machineTypes"
        )

    def list_images(
        self,
        image_project: str = "ubuntu-os-cloud",
        *,
        family_prefix: str | None = "ubuntu-",
    ) -> list[dict[str, Any]]:
        images = self._list_collection(
            f"/projects/{_required_text(image_project, 'image_project')}/global/images",
            params={"orderBy": "creationTimestamp desc"},
        )
        if family_prefix:
            prefix = family_prefix.casefold()
            images = [
                image
                for image in images
                if str(image.get("family") or "").casefold().startswith(prefix)
            ]
        return images

    def list_networks(self) -> list[dict[str, Any]]:
        return self._list_collection(f"/projects/{self._project_id}/global/networks")

    def list_subnetworks(self, region: str) -> list[dict[str, Any]]:
        return self._list_collection(
            f"/projects/{self._project_id}/regions/{_required_text(region, 'region')}/subnetworks"
        )

    def get_zone(self, zone: str) -> dict[str, Any]:
        return self._require_object(
            self._request("GET", f"/projects/{self._project_id}/zones/{zone}"),
            "zone",
        )

    def get_machine_type(self, zone: str, machine_type: str) -> dict[str, Any]:
        name = _resource_name(machine_type)
        return self._require_object(
            self._request(
                "GET",
                f"/projects/{self._project_id}/zones/{zone}/machineTypes/{name}",
            ),
            "machine type",
        )

    def get_image(self, source_image: str) -> dict[str, Any]:
        return self._require_object(
            self._request("GET", f"/{_normalize_image_path(source_image)}"),
            "image",
        )

    def get_network(self, network: str) -> dict[str, Any]:
        name = _resource_name(network)
        return self._require_object(
            self._request("GET", f"/projects/{self._project_id}/global/networks/{name}"),
            "network",
        )

    def get_subnetwork(self, region: str, subnetwork: str) -> dict[str, Any]:
        name = _resource_name(subnetwork)
        return self._require_object(
            self._request(
                "GET",
                f"/projects/{self._project_id}/regions/{region}/subnetworks/{name}",
            ),
            "subnetwork",
        )

    def validate_provisioning_target(
        self,
        *,
        zone: str,
        machine_type: str,
        source_image: str,
        network: str,
        subnetwork: str | None = None,
    ) -> GCPProvisioningTarget:
        zone_item = self.get_zone(_required_text(zone, "zone"))
        if str(zone_item.get("status") or "UP").upper() != "UP":
            raise GCPClientError(f"GCP zone is not available: {zone}")
        region = _resource_name(_required_text(zone_item.get("region"), "zone.region"))
        machine = self.get_machine_type(zone, _required_text(machine_type, "machine_type"))
        image = self.get_image(_required_text(source_image, "source_image"))
        if str(image.get("status") or "READY").upper() != "READY":
            raise GCPClientError(f"GCP image is not ready: {source_image}")
        network_item = self.get_network(_required_text(network, "network"))
        network_link = _required_text(network_item.get("selfLink"), "network.selfLink")
        subnet_link: str | None = None
        if subnetwork and subnetwork.strip():
            subnet = self.get_subnetwork(region, subnetwork)
            if _resource_name(str(subnet.get("network") or "")) != _resource_name(network_link):
                raise GCPClientError("GCP subnetwork does not belong to the selected network")
            subnet_link = _required_text(subnet.get("selfLink"), "subnetwork.selfLink")
        elif not bool(network_item.get("autoCreateSubnetworks")):
            raise GCPClientError("GCP custom-mode network requires a subnetwork")
        architecture = str(image.get("architecture") or "X86_64").lower().replace("_", "")
        return GCPProvisioningTarget(
            zone=zone,
            region=region,
            machine_type=_resource_name(_required_text(machine.get("name"), "machineType.name")),
            source_image=_required_text(image.get("selfLink"), "image.selfLink"),
            network=network_link,
            subnetwork=subnet_link,
            architecture="arm64" if architecture in {"arm64", "aarch64"} else "x64",
            guest_cpus=_optional_int(machine.get("guestCpus")),
        )

    def ensure_firewall_ports(
        self,
        *,
        network: str,
        inbound_ports: tuple[int, ...],
        rule_name: str = "shadowfleet-ingress",
        target_tag: str = "shadowfleet",
    ) -> str:
        ports = tuple(sorted(set(inbound_ports)))
        if not ports or any(port <= 0 or port > 65535 for port in ports):
            raise ValueError("GCP inbound ports must be between 1 and 65535")
        path = f"/projects/{self._project_id}/global/firewalls/{rule_name}"
        payload: dict[str, object] = {
            "name": rule_name,
            "description": "ShadowFleet managed inbound TCP",
            "network": network,
            "direction": "INGRESS",
            "priority": 1000,
            "sourceRanges": ["0.0.0.0/0", "::/0"],
            "targetTags": [target_tag],
            "allowed": [{"IPProtocol": "tcp", "ports": [str(port) for port in ports]}],
        }
        try:
            existing = self._require_object(self._request("GET", path), "firewall")
        except GCPClientError as exc:
            if exc.status_code != 404:
                raise
            operation = self._request(
                "POST",
                f"/projects/{self._project_id}/global/firewalls",
                payload=payload,
            )
            self.wait_for_global_operation(_required_text(operation.get("name"), "operation.name"))
            set_event_type("gcp_firewall_created")
            return rule_name
        existing_network = _resource_name(str(existing.get("network") or ""))
        requested_network = _resource_name(network)
        if existing_network and existing_network != requested_network:
            raise GCPClientError(
                f"GCP firewall rule {rule_name} belongs to network "
                f"{existing_network}, not {requested_network}"
            )
        existing_ports = _firewall_tcp_ports(existing)
        if set(ports).issubset(existing_ports):
            return rule_name
        payload["allowed"] = [{
            "IPProtocol": "tcp",
            "ports": [str(port) for port in sorted(existing_ports | set(ports))],
        }]
        operation = self._request("PUT", path, payload=payload)
        self.wait_for_global_operation(_required_text(operation.get("name"), "operation.name"))
        set_event_type("gcp_firewall_updated")
        return rule_name

    def launch_instance(
        self,
        request: GCPInstanceLaunchRequest,
        *,
        wait_timeout_seconds: int = 600,
        poll_interval_seconds: float = 5.0,
    ) -> GCPInstanceLaunchResult:
        _validate_launch_request(request)
        labels = {
            **(request.labels or {}),
            MANAGED_LABEL_KEY: MANAGED_LABEL_VALUE,
            CREATED_AT_LABEL: datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        }
        interface: dict[str, object] = {
            "network": request.network,
            "accessConfigs": [{
                "name": "External NAT",
                "type": "ONE_TO_ONE_NAT",
                "networkTier": "PREMIUM",
            }],
            "stackType": "IPV4_ONLY",
        }
        if request.subnetwork:
            interface["subnetwork"] = request.subnetwork
        payload = {
            "name": request.name,
            "machineType": _machine_type_path(
                self._project_id,
                request.zone,
                request.machine_type,
            ),
            "disks": [{
                "boot": True,
                "autoDelete": True,
                "initializeParams": {"sourceImage": request.source_image},
            }],
            "networkInterfaces": [interface],
            "metadata": {"items": [
                {
                    "key": "ssh-keys",
                    "value": f"{request.ssh_username}:{request.ssh_public_key}",
                },
                {"key": "startup-script", "value": request.startup_script},
            ]},
            "labels": _normalize_labels(labels),
            "tags": {"items": list(dict.fromkeys(request.network_tags))},
            "scheduling": {"automaticRestart": True, "onHostMaintenance": "MIGRATE"},
        }
        self._created_instance_name = request.name
        self._created_instance_zone = request.zone
        operation = self._request(
            "POST",
            f"/projects/{self._project_id}/zones/{request.zone}/instances",
            payload=payload,
        )
        self.wait_for_zone_operation(
            request.zone,
            _required_text(operation.get("name"), "operation.name"),
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        instance = self.wait_for_instance_running(
            request.zone,
            request.name,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        set_event_type("gcp_instance_created")
        return self._to_launch_result(instance, request.zone)

    def get_instance(self, zone: str, instance_name: str) -> dict[str, Any]:
        return self._require_object(
            self._request(
                "GET",
                f"/projects/{self._project_id}/zones/{zone}/instances/{instance_name}",
            ),
            "instance",
        )

    def list_instances(self, zone: str) -> list[dict[str, Any]]:
        return self._list_collection(
            f"/projects/{self._project_id}/zones/{_required_text(zone, 'zone')}/instances"
        )

    def wait_for_instance_running(
        self,
        zone: str,
        instance_name: str,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            instance = self.get_instance(zone, instance_name)
            status = str(instance.get("status") or "").upper()
            if status == "RUNNING":
                return instance
            if status in {"TERMINATED", "SUSPENDED"}:
                raise GCPClientError(f"GCP instance entered {status}: {instance_name}")
            time.sleep(poll_interval_seconds)
        raise GCPClientError(f"Timed out waiting for GCP instance: {instance_name}")

    def delete_instance(self, zone: str, instance_name: str) -> None:
        try:
            operation = self._request(
                "DELETE",
                f"/projects/{self._project_id}/zones/{zone}/instances/{instance_name}",
            )
        except GCPClientError as exc:
            if exc.status_code == 404:
                return
            raise
        self.wait_for_zone_operation(
            zone,
            _required_text(operation.get("name"), "operation.name"),
        )
        set_event_type("gcp_instance_deleted")

    def rotate_external_ipv4(
        self,
        zone: str,
        instance_name: str,
        *,
        interface_name: str = "nic0",
        access_config_name: str = "External NAT",
    ) -> str:
        base = f"/projects/{self._project_id}/zones/{zone}/instances/{instance_name}"
        operation = self._request(
            "POST",
            f"{base}/deleteAccessConfig",
            params={
                "networkInterface": interface_name,
                "accessConfig": access_config_name,
            },
        )
        self.wait_for_zone_operation(
            zone,
            _required_text(operation.get("name"), "operation.name"),
        )
        operation = self._request(
            "POST",
            f"{base}/addAccessConfig",
            params={"networkInterface": interface_name},
            payload={
                "name": access_config_name,
                "type": "ONE_TO_ONE_NAT",
                "networkTier": "PREMIUM",
            },
        )
        self.wait_for_zone_operation(
            zone,
            _required_text(operation.get("name"), "operation.name"),
        )
        instance = self.get_instance(zone, instance_name)
        ipv4, _ = _instance_public_addresses(instance)
        if ipv4 is None:
            raise GCPClientError(
                f"GCP instance has no external IPv4 after rotation: {instance_name}"
            )
        set_event_type("gcp_ipv4_rotated")
        return ipv4

    def wait_for_zone_operation(
        self,
        zone: str,
        operation_name: str,
        *,
        timeout_seconds: int = 600,
        poll_interval_seconds: float = 2.0,
    ) -> dict[str, Any]:
        return self._wait_for_operation(
            f"/projects/{self._project_id}/zones/{zone}/operations/{operation_name}",
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    def wait_for_global_operation(
        self,
        operation_name: str,
        *,
        timeout_seconds: int = 600,
        poll_interval_seconds: float = 2.0,
    ) -> dict[str, Any]:
        return self._wait_for_operation(
            f"/projects/{self._project_id}/global/operations/{operation_name}",
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    def _wait_for_operation(
        self,
        path: str,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            operation = self._require_object(self._request("GET", path), "operation")
            if str(operation.get("status") or "").upper() == "DONE":
                if operation.get("error"):
                    raise GCPClientError(
                        f"GCP operation failed: {_error_detail(operation['error'])}"
                    )
                return operation
            time.sleep(poll_interval_seconds)
        raise GCPClientError(
            f"Timed out waiting for GCP operation: {path.rsplit('/', 1)[-1]}"
        )

    def _list_collection(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            page_params = dict(params or {})
            if page_token:
                page_params["pageToken"] = page_token
            payload = self._require_object(
                self._request("GET", path, params=page_params),
                "collection",
            )
            raw_items = payload.get("items")
            if isinstance(raw_items, list):
                items.extend(item for item in raw_items if isinstance(item, dict))
            page_token = _optional_text(payload.get("nextPageToken"))
            if page_token is None:
                return items

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
    ) -> Any:
        normalized_method = method.upper()

        def perform_request() -> Any:
            try:
                response = self._session.request(
                    method=normalized_method,
                    url=f"{self._base_url}{path}",
                    json=payload,
                    params=params,
                    timeout=self._request_timeout_seconds,
                )
            except requests.RequestException as exc:
                raise GCPClientError(f"GCP request failed: {exc}") from exc
            try:
                body = response.json() if response.content else {}
            except ValueError as exc:
                raise GCPClientError(
                    f"GCP returned invalid JSON (HTTP {response.status_code})",
                    response.status_code,
                ) from exc
            if response.status_code != 200:
                raise GCPClientError(
                    f"GCP API error (HTTP {response.status_code}): {_error_detail(body)}",
                    response.status_code,
                )
            return body

        try:
            return execute_with_backoff(
                operation_name=f"gcp_{normalized_method.lower()}_{path.rsplit('/', 1)[-1]}",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="gcp",
                func=perform_request,
                should_retry=lambda exc: isinstance(exc, GCPClientError)
                and exc.status_code in RETRYABLE_STATUS_CODES,
            )
        except GCPClientError:
            set_event_type("gcp_request_failed")
            raise

    @staticmethod
    def _require_object(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise GCPClientError(f"GCP {label} response must be an object")
        return value

    @staticmethod
    def _to_launch_result(
        instance: dict[str, Any],
        zone: str,
    ) -> GCPInstanceLaunchResult:
        interfaces = instance.get("networkInterfaces")
        interface = (
            next((item for item in interfaces if isinstance(item, dict)), {})
            if isinstance(interfaces, list)
            else {}
        )
        ipv4, ipv6 = _instance_public_addresses(instance)
        return GCPInstanceLaunchResult(
            instance_id=str(instance.get("id") or instance.get("name") or ""),
            name=_required_text(instance.get("name"), "instance.name"),
            zone=zone,
            machine_type=_resource_name(str(instance.get("machineType") or "")),
            network_interface=str(interface.get("name") or "nic0"),
            ipv4_address=ipv4,
            ipv6_address=ipv6,
        )


def instance_created_at(instance: dict[str, Any]) -> str:
    return str(instance.get("creationTimestamp") or "").strip()


def instance_labels(instance: dict[str, Any]) -> dict[str, str]:
    labels = instance.get("labels")
    if not isinstance(labels, dict):
        return {}
    return {str(key): str(value) for key, value in labels.items()}


def _build_authorized_session(credentials: GCPCredentials) -> Any:
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError as exc:
        raise GCPClientError(
            "google-auth is required for GCP support; install project dependencies"
        ) from exc
    google_credentials = service_account.Credentials.from_service_account_info(
        credentials.to_service_account_info(),
        scopes=[COMPUTE_SCOPE],
    )
    return AuthorizedSession(google_credentials)


def _validate_credentials(credentials: GCPCredentials) -> GCPCredentials:
    for value, name in (
        (credentials.project_id, "project_id"),
        (credentials.client_email, "client_email"),
        (credentials.private_key, "private_key"),
        (credentials.token_uri, "token_uri"),
    ):
        _required_text(value, name)
    if "BEGIN PRIVATE KEY" not in credentials.private_key:
        raise ValueError("GCP private_key must be a PEM private key")
    return credentials


def _validate_launch_request(request: GCPInstanceLaunchRequest) -> None:
    for value, name in (
        (request.name, "name"),
        (request.zone, "zone"),
        (request.machine_type, "machine_type"),
        (request.source_image, "source_image"),
        (request.network, "network"),
        (request.ssh_username, "ssh_username"),
        (request.ssh_public_key, "ssh_public_key"),
        (request.startup_script, "startup_script"),
    ):
        _required_text(value, name)
    normalized = request.name.strip()
    if len(normalized) > 63 or not normalized[0].isalpha():
        raise ValueError(
            "GCP instance name must start with a letter and be at most 63 characters"
        )
    if any(
        not (char.islower() or char.isdigit() or char == "-")
        for char in normalized
    ):
        raise ValueError(
            "GCP instance name may contain lowercase letters, digits and hyphens only"
        )


def _instance_public_addresses(
    instance: dict[str, Any],
) -> tuple[str | None, str | None]:
    ipv4: str | None = None
    ipv6: str | None = None
    interfaces = instance.get("networkInterfaces")
    if not isinstance(interfaces, list):
        return None, None
    for interface in interfaces:
        if not isinstance(interface, dict):
            continue
        for key in ("accessConfigs", "ipv6AccessConfigs"):
            configs = interface.get(key)
            if not isinstance(configs, list):
                continue
            for config in configs:
                if not isinstance(config, dict):
                    continue
                address = _optional_text(
                    config.get("natIP") or config.get("externalIpv6")
                )
                if not address:
                    continue
                try:
                    parsed = ipaddress.ip_address(address)
                except ValueError:
                    continue
                if parsed.version == 4 and ipv4 is None:
                    ipv4 = str(parsed)
                elif parsed.version == 6 and ipv6 is None:
                    ipv6 = str(parsed)
    return ipv4, ipv6


def _normalize_image_path(value: str) -> str:
    text = _required_text(value, "source_image")
    marker = "/compute/v1/"
    if marker in text:
        text = text.split(marker, 1)[1]
    return text.strip("/")


def _machine_type_path(project_id: str, zone: str, value: str) -> str:
    if "/machineTypes/" in value:
        return value
    return (
        f"projects/{project_id}/zones/{zone}/machineTypes/{_resource_name(value)}"
    )


def _resource_name(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1]


def _normalize_labels(values: dict[str, str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for key, value in values.items():
        normalized_key = str(key).strip().lower().replace("_", "-")[:63]
        normalized_value = str(value).strip().lower().replace("_", "-")[:63]
        if normalized_key:
            labels[normalized_key] = normalized_value
    return labels


def _firewall_tcp_ports(firewall: dict[str, Any]) -> set[int]:
    ports: set[int] = set()
    allowed = firewall.get("allowed")
    if not isinstance(allowed, list):
        return ports
    for entry in allowed:
        if (
            not isinstance(entry, dict)
            or str(entry.get("IPProtocol") or "").lower() != "tcp"
        ):
            continue
        raw_ports = entry.get("ports")
        if not isinstance(raw_ports, list):
            continue
        for raw in raw_ports:
            text = str(raw)
            if "-" in text:
                start, _, end = text.partition("-")
                try:
                    ports.update(range(int(start), int(end) + 1))
                except ValueError:
                    continue
            else:
                try:
                    ports.add(int(text))
                except ValueError:
                    continue
    return ports


def _error_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if error and error is not payload:
            return _error_detail(error)
        errors = payload.get("errors")
        if isinstance(errors, list):
            return "; ".join(_error_detail(item) for item in errors)
        for key in ("message", "status", "code"):
            if payload.get(key):
                return str(payload[key])
    return str(payload)


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _required_text(value: object, name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"GCP {name} must not be empty")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
