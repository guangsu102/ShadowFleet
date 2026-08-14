from __future__ import annotations

import base64
from dataclasses import dataclass
from ipaddress import ip_network
from datetime import datetime, timezone
import time
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import requests

from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import execute_with_backoff


DEFAULT_MANAGEMENT_URL = "https://management.azure.com"
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
LEGACY_DEFAULT_VNET_NAME = "shadowfleet-vnet"


def resolve_azure_vnet_name(location: str, configured_name: str | None = None) -> str:
    requested_name = (configured_name or "").strip()
    if requested_name and requested_name.casefold() != LEGACY_DEFAULT_VNET_NAME:
        return requested_name
    region_suffix = _resource_name(location.strip()).lower()
    return _resource_name(f"{LEGACY_DEFAULT_VNET_NAME}-{region_suffix}").lower()


class AzureClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AzureCredentials:
    tenant_id: str
    client_id: str
    client_secret: str
    subscription_id: str


@dataclass(frozen=True)
class AzureVmLaunchRequest:
    name: str
    location: str
    resource_group: str
    vm_size: str
    admin_username: str
    ssh_public_key: str
    user_data: str
    image_publisher: str = "Canonical"
    image_offer: str = "0001-com-ubuntu-server-jammy"
    image_sku: str = "22_04-lts-gen2"
    image_version: str = "latest"
    vnet_name: str = "shadowfleet-vnet"
    subnet_name: str = "default"
    tags: tuple[str, ...] = ()
    inbound_ports: tuple[int, ...] = (22, 443)


@dataclass(frozen=True)
class AzureVmLaunchResult:
    instance_id: str
    vm_name: str
    location: str
    vm_size: str
    network_interface_id: str
    subnet_id: str
    network_security_group_id: str
    ipv4_address: str | None
    ipv6_address: str | None


@dataclass(frozen=True)
class _AzureIpv6RotationContext:
    vm_name: str
    nic_id: str
    ip_configuration: dict[str, Any]
    old_public_ip_id: str
    old_public_ip: dict[str, Any]
    old_ipv6_address: str
    temporary_public_ip_id: str


class AzureClient:
    """Azure Resource Manager adapter using service-principal credentials."""

    def __init__(
        self,
        runtime_context: RuntimeContext,
        credentials: AzureCredentials,
        management_url: str = DEFAULT_MANAGEMENT_URL,
        authority_url: str = "https://login.microsoftonline.com",
    ) -> None:
        for field_name, value in (
            ("tenant_id", credentials.tenant_id),
            ("client_id", credentials.client_id),
            ("client_secret", credentials.client_secret),
            ("subscription_id", credentials.subscription_id),
        ):
            if not value or not value.strip():
                raise ValueError(f"Azure {field_name} must not be empty")

        self._credentials = credentials
        self._subscription_id = credentials.subscription_id.strip()
        self._management_url = management_url.rstrip("/")
        self._authority_url = authority_url.rstrip("/")
        self._logger = runtime_context.logger.getChild("infrastructure.azure")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._session = requests.Session()
        self._access_token: str | None = None
        self._created_resource_ids: list[str] = []

    @property
    def created_resource_ids(self) -> tuple[str, ...]:
        return tuple(self._created_resource_ids)

    def validate_subscription(self) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"/subscriptions/{self._subscription_id}",
            api_version="2020-01-01",
        )
        if not payload.get("subscriptionId"):
            raise AzureClientError("Azure subscription response missing subscriptionId")
        return payload

    def list_locations(self) -> list[dict[str, Any]]:
        return self._list_collection(
            f"/subscriptions/{self._subscription_id}/locations",
            api_version="2020-01-01",
            name="Azure locations",
        )

    def list_vm_sizes(self, location: str) -> list[dict[str, Any]]:
        return self._list_collection(
            (
                f"/subscriptions/{self._subscription_id}/providers/Microsoft.Compute/"
                f"locations/{quote(location, safe='')}/vmSizes"
            ),
            api_version="2023-09-01",
            name="Azure VM sizes",
        )

    def validate_provisioning_target(
        self,
        *,
        location: str,
        vm_size: str,
        resource_group: str,
        vnet_name: str,
        subnet_name: str,
    ) -> str:
        normalized_location = location.strip().casefold()
        locations = self.list_locations()
        if not any(
            normalized_location
            in {
                str(item.get("name") or "").strip().casefold(),
                str(item.get("displayName") or "").strip().casefold(),
            }
            for item in locations
        ):
            raise AzureClientError(
                f"Azure location was not found or is not accessible: {location}"
            )

        normalized_vm_size = vm_size.strip().casefold()
        if not any(
            str(item.get("name") or "").strip().casefold()
            == normalized_vm_size
            for item in self.list_vm_sizes(location)
        ):
            raise AzureClientError(
                f"Azure VM size {vm_size!r} is not available in {location!r}"
            )

        self.ensure_resource_group(resource_group, location)
        return self.ensure_network(
            resource_group,
            location,
            resolve_azure_vnet_name(location, vnet_name),
            subnet_name,
        )

    def list_virtual_machines(self, resource_group: str) -> list[dict[str, Any]]:
        return self._list_collection(
            self._resource_path(resource_group, "Microsoft.Compute", "virtualMachines"),
            api_version="2024-03-01",
            name="Azure virtual machines",
        )

    def list_network_interfaces(self, resource_group: str) -> list[dict[str, Any]]:
        return self._list_collection(
            self._resource_path(resource_group, "Microsoft.Network", "networkInterfaces"),
            api_version="2023-09-01",
            name="Azure network interfaces",
        )

    def list_public_ip_addresses(self, resource_group: str) -> list[dict[str, Any]]:
        return self._list_collection(
            self._resource_path(resource_group, "Microsoft.Network", "publicIPAddresses"),
            api_version="2023-09-01",
            name="Azure public IP addresses",
        )

    def list_network_security_groups(self, resource_group: str) -> list[dict[str, Any]]:
        return self._list_collection(
            self._resource_path(
                resource_group,
                "Microsoft.Network",
                "networkSecurityGroups",
            ),
            api_version="2023-09-01",
            name="Azure network security groups",
        )

    def launch_vm(
        self,
        request: AzureVmLaunchRequest,
        wait_timeout_seconds: int = 600,
        poll_interval_seconds: float = 5.0,
    ) -> AzureVmLaunchResult:
        self._created_resource_ids = []
        self.ensure_resource_group(request.resource_group, request.location)
        subnet_id = self.ensure_network(
            request.resource_group,
            request.location,
            resolve_azure_vnet_name(request.location, request.vnet_name),
            request.subnet_name,
        )

        base_name = _resource_name(request.name)
        nsg_id = self._resource_id(
            request.resource_group, "Microsoft.Network", "networkSecurityGroups", f"{base_name}-nsg"
        )
        ipv4_id = self._resource_id(
            request.resource_group, "Microsoft.Network", "publicIPAddresses", f"{base_name}-ipv4"
        )
        ipv6_id = self._resource_id(
            request.resource_group, "Microsoft.Network", "publicIPAddresses", f"{base_name}-ipv6"
        )
        nic_id = self._resource_id(
            request.resource_group, "Microsoft.Network", "networkInterfaces", f"{base_name}-nic"
        )
        vm_id = self._resource_id(
            request.resource_group, "Microsoft.Compute", "virtualMachines", base_name
        )

        self._put_and_wait(
            nsg_id,
            "2023-09-01",
            self._nsg_payload(request.location, request.inbound_ports, request.tags),
            wait_timeout_seconds,
            poll_interval_seconds,
            track_created=True,
        )
        for public_ip_id, version in ((ipv4_id, "IPv4"), (ipv6_id, "IPv6")):
            self._put_and_wait(
                public_ip_id,
                "2023-09-01",
                self._public_ip_payload(request.location, version, request.tags),
                wait_timeout_seconds,
                poll_interval_seconds,
                track_created=True,
            )

        self._put_and_wait(
            nic_id,
            "2023-09-01",
            self._nic_payload(request.location, subnet_id, nsg_id, ipv4_id, ipv6_id, request.tags),
            wait_timeout_seconds,
            poll_interval_seconds,
            track_created=True,
        )

        self._request(
            "PUT",
            vm_id,
            api_version="2024-03-01",
            payload=self._vm_payload(request, nic_id),
            expected_status={200, 201, 202},
        )
        self._remember_created(vm_id)
        set_event_type("azure_vm_created")
        self._logger.info("Created Azure VM id=%s", vm_id)
        self.wait_for_vm_running(
            vm_id,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        ipv4_address = self._get_public_ip(ipv4_id)
        ipv6_address = self._get_public_ip(ipv6_id)
        return AzureVmLaunchResult(
            instance_id=vm_id,
            vm_name=base_name,
            location=request.location,
            vm_size=request.vm_size,
            network_interface_id=nic_id,
            subnet_id=subnet_id,
            network_security_group_id=nsg_id,
            ipv4_address=ipv4_address,
            ipv6_address=ipv6_address,
        )

    def get_vm(self, vm_id: str) -> dict[str, Any]:
        return self._request("GET", vm_id, api_version="2024-03-01")

    def get_vm_power_state(self, vm_id: str) -> str | None:
        payload = self._request(
            "GET",
            f"{vm_id}/instanceView",
            api_version="2024-03-01",
        )
        statuses = payload.get("statuses", [])
        if not isinstance(statuses, list):
            return None
        for status in statuses:
            if isinstance(status, dict) and str(status.get("code", "")).startswith("PowerState/"):
                return str(status["code"]).split("/", 1)[1]
        return None

    def wait_for_vm_running(
        self,
        vm_id: str,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                if self.get_vm_power_state(vm_id) == "running":
                    return
            except AzureClientError as exc:
                if exc.status_code not in {404, 409}:
                    raise
            time.sleep(poll_interval_seconds)
        raise AzureClientError(f"Timed out waiting for Azure VM to become running: {vm_id}")

    def delete_vm(self, vm_id: str, delete_dependencies: bool = True) -> None:
        parsed = _parse_vm_resource_id(vm_id)
        dependencies: list[tuple[str, str]] = []
        if parsed is not None:
            resource_group, vm_name = parsed
            dependencies = [
                (self._resource_id(resource_group, "Microsoft.Network", "networkInterfaces", f"{vm_name}-nic"), "2023-09-01"),
                (self._resource_id(resource_group, "Microsoft.Network", "publicIPAddresses", f"{vm_name}-ipv4"), "2023-09-01"),
                (self._resource_id(resource_group, "Microsoft.Network", "publicIPAddresses", f"{vm_name}-ipv6"), "2023-09-01"),
                (self._resource_id(resource_group, "Microsoft.Network", "networkSecurityGroups", f"{vm_name}-nsg"), "2023-09-01"),
            ]
            healing_prefix = f"{vm_name[:42]}-ipv6-heal-".casefold()
            try:
                for public_ip in self.list_public_ip_addresses(resource_group):
                    name = str(public_ip.get("name") or "").casefold()
                    tags = public_ip.get("tags")
                    if (
                        name.startswith(healing_prefix)
                        and isinstance(tags, dict)
                        and str(tags.get("shadowfleet") or "").casefold() == "true"
                    ):
                        resource_id = str(public_ip.get("id") or "").strip()
                        if resource_id:
                            dependencies.insert(
                                -1,
                                (resource_id, "2023-09-01"),
                            )
            except Exception:
                self._logger.exception(
                    "Failed to enumerate Azure healing Public IPs for VM=%s",
                    vm_name,
                )
        self._delete_resource(vm_id, "2024-03-01")
        if delete_dependencies:
            for resource_id, api_version in dependencies:
                self._delete_resource(resource_id, api_version)
        set_event_type("azure_vm_deleted")
        self._logger.info("Deleted Azure VM id=%s", vm_id)

    def delete_network_interface(self, resource_id: str) -> None:
        self._delete_resource(resource_id, "2023-09-01")
        set_event_type("azure_network_interface_deleted")

    def delete_public_ip_address(self, resource_id: str) -> None:
        self._delete_resource(resource_id, "2023-09-01")
        set_event_type("azure_public_ip_address_deleted")

    def rotate_vm_ipv6_public_ip(
        self,
        vm_id: str,
        wait_timeout_seconds: int = 300,
        poll_interval_seconds: float = 2.0,
    ) -> tuple[str, str]:
        rotation = self._build_ipv6_rotation_context(vm_id)
        return self._complete_ipv6_rotation(
            rotation,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    def delete_network_security_group(self, resource_id: str) -> None:
        self._delete_resource(resource_id, "2023-09-01")
        set_event_type("azure_network_security_group_deleted")

    def rollback_created_resources(self) -> None:
        for resource_id in reversed(self._created_resource_ids):
            api_version = "2024-03-01" if "/Microsoft.Compute/virtualMachines/" in resource_id else "2023-09-01"
            try:
                self._delete_resource(resource_id, api_version)
            except Exception:
                self._logger.exception("Failed to rollback Azure resource id=%s", resource_id)

    def _complete_ipv6_rotation(
        self,
        rotation: _AzureIpv6RotationContext,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> tuple[str, str]:
        temporary_ipv6_address = self._activate_temporary_ipv6_public_ip(
            rotation,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        try:
            self._delete_resource(rotation.old_public_ip_id, "2023-09-01")
        except Exception:
            self._rollback_ipv6_attachment(
                rotation,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            raise
        new_ipv6_address = self._restore_canonical_ipv6_public_ip(
            rotation,
            temporary_ipv6_address=temporary_ipv6_address,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        set_event_type("azure_ipv6_rotated")
        self._logger.info(
            "Rotated Azure VM IPv6 Public IP old=%s new=%s",
            rotation.old_ipv6_address,
            new_ipv6_address,
        )
        return rotation.old_ipv6_address, new_ipv6_address

    def _build_ipv6_rotation_context(
        self, vm_id: str
    ) -> _AzureIpv6RotationContext:
        vm = self.get_vm(vm_id)
        nic_id = self._primary_network_interface_id(vm)
        nic = self._request("GET", nic_id, api_version="2023-09-01")
        ip_configuration = self._ipv6_ip_configuration(nic)
        old_public_ip_id = self._ip_configuration_public_ip_id(ip_configuration)
        old_public_ip = self._request(
            "GET", old_public_ip_id, api_version="2023-09-01"
        )
        old_ipv6_address = self._public_ip_address(old_public_ip)
        if old_ipv6_address is None:
            raise AzureClientError(
                f"Azure IPv6 Public IP has no assigned address: {old_public_ip_id}"
            )
        location = str(old_public_ip.get("location") or nic.get("location") or "").strip()
        if not location:
            raise AzureClientError("Azure IPv6 Public IP response is missing location")
        old_public_ip["location"] = location

        vm_name = str(vm.get("name") or "shadowfleet").strip()
        temporary_name = _resource_name(
            f"{vm_name[:42]}-ipv6-heal-{uuid4().hex[:8]}"
        )
        temporary_public_ip_id = (
            f"{old_public_ip_id.rsplit('/', 1)[0]}/{temporary_name}"
        )
        return _AzureIpv6RotationContext(
            vm_name=vm_name,
            nic_id=nic_id,
            ip_configuration=ip_configuration,
            old_public_ip_id=old_public_ip_id,
            old_public_ip=old_public_ip,
            old_ipv6_address=old_ipv6_address,
            temporary_public_ip_id=temporary_public_ip_id,
        )

    def _activate_temporary_ipv6_public_ip(
        self,
        rotation: _AzureIpv6RotationContext,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> str:
        try:
            temporary_payload = self._rotation_public_ip_payload(
                rotation.old_public_ip,
                preserve_dns_settings=False,
            )
            temporary_tags = temporary_payload.get("tags")
            if not isinstance(temporary_tags, dict):
                temporary_tags = {}
            temporary_payload["tags"] = {
                **temporary_tags,
                "shadowfleet": "true",
                "shadowfleet_parent_vm": rotation.vm_name,
            }
            self._put_and_wait(
                rotation.temporary_public_ip_id,
                "2023-09-01",
                temporary_payload,
                timeout_seconds,
                poll_interval_seconds,
            )
            temporary_address = self._get_public_ip(
                rotation.temporary_public_ip_id
            )
            if not temporary_address:
                raise AzureClientError(
                    "Azure temporary IPv6 Public IP has no assigned address"
                )
            if temporary_address == rotation.old_ipv6_address:
                raise AzureClientError(
                    "Azure allocated the same IPv6 address during rotation"
                )
            self._attach_public_ip_to_configuration(
                nic_id=rotation.nic_id,
                ip_configuration=rotation.ip_configuration,
                public_ip_id=rotation.temporary_public_ip_id,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            return temporary_address
        except Exception:
            self._rollback_ipv6_attachment(
                rotation,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            raise

    def _rollback_ipv6_attachment(
        self,
        rotation: _AzureIpv6RotationContext,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        try:
            self._attach_public_ip_to_configuration(
                nic_id=rotation.nic_id,
                ip_configuration=rotation.ip_configuration,
                public_ip_id=rotation.old_public_ip_id,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        except Exception:
            self._logger.exception(
                "Failed to restore Azure IPv6 Public IP attachment id=%s",
                rotation.old_public_ip_id,
            )
            return
        self._delete_resource_best_effort(
            rotation.temporary_public_ip_id, "2023-09-01"
        )

    def _delete_resource_best_effort(
        self, resource_id: str, api_version: str
    ) -> None:
        try:
            self._delete_resource(resource_id, api_version)
        except Exception:
            self._logger.exception(
                "Failed to delete superseded Azure resource id=%s", resource_id
            )

    def _restore_canonical_ipv6_public_ip(
        self,
        rotation: _AzureIpv6RotationContext,
        *,
        temporary_ipv6_address: str,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> str:
        try:
            new_address = self._create_and_attach_canonical_ipv6_public_ip(
                rotation,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        except Exception:
            # The temporary address is already live. Keep it as a durable fallback
            # so the caller can update DNS and finish healing.
            self._logger.exception(
                "Failed to restore canonical Azure IPv6 Public IP; "
                "keeping temporary address id=%s",
                rotation.temporary_public_ip_id,
            )
            self._attach_public_ip_to_configuration(
                nic_id=rotation.nic_id,
                ip_configuration=rotation.ip_configuration,
                public_ip_id=rotation.temporary_public_ip_id,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            self._delete_resource_best_effort(
                rotation.old_public_ip_id, "2023-09-01"
            )
            set_event_type("azure_ipv6_rotated_temporary_fallback")
            return temporary_ipv6_address
        self._delete_resource_best_effort(
            rotation.temporary_public_ip_id, "2023-09-01"
        )
        return new_address

    def _create_and_attach_canonical_ipv6_public_ip(
        self,
        rotation: _AzureIpv6RotationContext,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> str:
        self._put_and_wait(
            rotation.old_public_ip_id,
            "2023-09-01",
            self._rotation_public_ip_payload(
                rotation.old_public_ip,
                preserve_dns_settings=True,
            ),
            timeout_seconds,
            poll_interval_seconds,
        )
        self._attach_public_ip_to_configuration(
            nic_id=rotation.nic_id,
            ip_configuration=rotation.ip_configuration,
            public_ip_id=rotation.old_public_ip_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        new_address = self._get_public_ip(rotation.old_public_ip_id)
        if not new_address or new_address == rotation.old_ipv6_address:
            raise AzureClientError(
                "Azure canonical Public IP did not receive a new IPv6 address"
            )
        return new_address

    def _attach_public_ip_to_configuration(
        self,
        *,
        nic_id: str,
        ip_configuration: dict[str, Any],
        public_ip_id: str,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        name = str(ip_configuration.get("name") or "").strip()
        properties = ip_configuration.get("properties")
        if not name or not isinstance(properties, dict):
            raise AzureClientError(
                "Azure IPv6 IP configuration is missing name or properties"
            )
        mutable_property_names = {
            "applicationGatewayBackendAddressPools",
            "applicationSecurityGroups",
            "gatewayLoadBalancer",
            "loadBalancerBackendAddressPools",
            "loadBalancerInboundNatRules",
            "primary",
            "privateIPAddress",
            "privateIPAddressVersion",
            "privateIPAllocationMethod",
            "privateLinkConnectionProperties",
            "subnet",
            "virtualNetworkTaps",
        }
        payload_properties = {
            key: value
            for key, value in properties.items()
            if key in mutable_property_names
        }
        payload_properties["privateIPAddressVersion"] = "IPv6"
        payload_properties["publicIPAddress"] = {"id": public_ip_id}
        self._put_and_wait(
            f"{nic_id}/ipConfigurations/{quote(name, safe='')}",
            "2023-09-01",
            {"properties": payload_properties},
            timeout_seconds,
            poll_interval_seconds,
        )

    def ensure_resource_group(self, resource_group: str, location: str) -> None:
        resource_id = f"/subscriptions/{self._subscription_id}/resourcegroups/{resource_group}"
        try:
            self._request("GET", resource_id, api_version="2021-04-01")
            return
        except AzureClientError as exc:
            if exc.status_code != 404:
                raise
        self._request(
            "PUT",
            resource_id,
            api_version="2021-04-01",
            payload={"location": location, "tags": {"shadowfleet": "true"}},
            expected_status={200, 201},
        )

    def ensure_network(
        self,
        resource_group: str,
        location: str,
        vnet_name: str,
        subnet_name: str,
    ) -> str:
        vnet_id = self._resource_id(
            resource_group, "Microsoft.Network", "virtualNetworks", vnet_name
        )
        subnet_id = f"{vnet_id}/subnets/{subnet_name}"
        try:
            existing_vnet = self._request("GET", vnet_id, api_version="2023-09-01")
        except AzureClientError as exc:
            if exc.status_code != 404:
                raise
            self._put_and_wait(
                vnet_id,
                "2023-09-01",
                {
                    "location": location,
                    "tags": {"shadowfleet": "true"},
                    "properties": {
                        "addressSpace": {"addressPrefixes": ["10.42.0.0/16", "fd42:42::/48"]},
                    },
                },
                300,
                2.0,
            )
        else:
            existing_location = str(existing_vnet.get("location") or "").strip()
            if not existing_location:
                raise AzureClientError(
                    f"Azure VNet response is missing location: {vnet_id}"
                )
            if existing_location.casefold() != location.strip().casefold():
                raise AzureClientError(
                    f"Azure VNet {vnet_name!r} is in {existing_location!r}, "
                    f"but the VM location is {location!r}. Use one VNet per Azure region.",
                    status_code=409,
                )
            try:
                existing_subnet = self._request(
                    "GET",
                    subnet_id,
                    api_version="2023-09-01",
                )
                _validate_dual_stack_subnet(existing_subnet, subnet_id)
                return subnet_id
            except AzureClientError as exc:
                if exc.status_code != 404:
                    raise
                raise AzureClientError(
                    f"Azure VNet {vnet_name!r} already exists, but subnet "
                    f"{subnet_name!r} was not found. Create a dual-stack subnet "
                    "inside the VNet or use a dedicated ShadowFleet VNet name.",
                    status_code=409,
                ) from exc

        self._put_and_wait(
            subnet_id,
            "2023-09-01",
            {"properties": {"addressPrefixes": ["10.42.0.0/24", "fd42:42::/64"]}},
            300,
            2.0,
        )
        return subnet_id

    def _get_access_token(self, force_refresh: bool = False) -> str:
        if self._access_token and not force_refresh:
            return self._access_token
        url = (
            f"{self._authority_url}/{quote(self._credentials.tenant_id.strip(), safe='')}"
            "/oauth2/v2.0/token"
        )
        response = self._session.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._credentials.client_id.strip(),
                "client_secret": self._credentials.client_secret.strip(),
                "scope": "https://management.azure.com/.default",
            },
            timeout=self._request_timeout_seconds,
        )
        if response.status_code != 200:
            raise self._build_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AzureClientError("Azure token endpoint returned non-JSON response") from exc
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            raise AzureClientError("Azure token response missing access_token")
        self._access_token = str(token)
        return self._access_token

    def _request(
        self,
        method: str,
        resource_id: str,
        *,
        api_version: str,
        payload: dict[str, object] | None = None,
        expected_status: set[int] | None = None,
    ) -> dict[str, Any]:
        expected = expected_status or {200}
        url = resource_id if resource_id.startswith("http") else f"{self._management_url}{resource_id}"
        params = None if "api-version=" in url.lower() else {"api-version": api_version}

        def _send() -> dict[str, Any]:
            response = self._session.request(
                method,
                url,
                params=params,
                json=payload,
                headers={"Authorization": f"Bearer {self._get_access_token()}"},
                timeout=self._request_timeout_seconds,
            )
            if response.status_code == 401:
                response = self._session.request(
                    method,
                    url,
                    params=params,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._get_access_token(force_refresh=True)}"},
                    timeout=self._request_timeout_seconds,
                )
            if response.status_code not in expected:
                raise self._build_error(response)
            if response.status_code == 204 or not response.content:
                return {}
            try:
                parsed = response.json()
            except ValueError as exc:
                raise AzureClientError(
                    f"Azure returned a non-JSON response: status={response.status_code}",
                    status_code=response.status_code,
                ) from exc
            if not isinstance(parsed, dict):
                raise AzureClientError("Azure response payload must be a JSON object")
            return parsed

        try:
            return execute_with_backoff(
                operation_name=f"azure_{method.lower()}_{resource_id}",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="azure",
                func=_send,
                should_retry=self._should_retry_exception,
            )
        except (AzureClientError, requests.ConnectionError, requests.Timeout):
            set_event_type("azure_request_failed")
            self._logger.exception("Azure request failed: method=%s resource=%s", method, resource_id)
            raise

    def _put_and_wait(
        self,
        resource_id: str,
        api_version: str,
        payload: dict[str, object],
        timeout_seconds: int,
        poll_interval_seconds: float,
        *,
        track_created: bool = False,
    ) -> dict[str, Any]:
        result = self._request(
            "PUT",
            resource_id,
            api_version=api_version,
            payload=payload,
            expected_status={200, 201, 202},
        )
        if track_created:
            self._remember_created(resource_id)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                current = self._request("GET", resource_id, api_version=api_version)
            except AzureClientError as exc:
                if exc.status_code not in {404, 409}:
                    raise
                time.sleep(poll_interval_seconds)
                continue
            properties = current.get("properties")
            state = properties.get("provisioningState") if isinstance(properties, dict) else None
            if state in (None, "Succeeded"):
                return current
            if state in ("Failed", "Canceled"):
                raise AzureClientError(f"Azure resource provisioning {state}: {resource_id}")
            time.sleep(poll_interval_seconds)
        raise AzureClientError(f"Timed out waiting for Azure resource: {resource_id}")

    def _list_collection(
        self,
        resource_id: str,
        *,
        api_version: str,
        name: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_resource_id: str | None = resource_id
        while next_resource_id:
            payload = self._request(
                "GET",
                next_resource_id,
                api_version=api_version,
            )
            items.extend(self._collection(payload, name))
            next_link = payload.get("nextLink")
            if next_link is not None and not isinstance(next_link, str):
                raise AzureClientError(f"{name} nextLink must be a string")
            next_resource_id = next_link or None
        return items

    def _delete_resource(self, resource_id: str, api_version: str) -> None:
        try:
            self._request(
                "DELETE",
                resource_id,
                api_version=api_version,
                expected_status={200, 202, 204, 404},
            )
        except AzureClientError as exc:
            if exc.status_code != 404:
                raise
            return
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                self._request("GET", resource_id, api_version=api_version)
            except AzureClientError as exc:
                if exc.status_code == 404:
                    return
                raise
            time.sleep(2.0)
        raise AzureClientError(f"Timed out waiting for Azure resource deletion: {resource_id}")

    def _get_public_ip(self, resource_id: str) -> str | None:
        payload = self._request("GET", resource_id, api_version="2023-09-01")
        properties = payload.get("properties")
        if not isinstance(properties, dict):
            return None
        value = properties.get("ipAddress")
        return str(value).strip() if value else None

    @staticmethod
    def _primary_network_interface_id(vm: dict[str, Any]) -> str:
        properties = vm.get("properties")
        network_profile = (
            properties.get("networkProfile") if isinstance(properties, dict) else None
        )
        interfaces = (
            network_profile.get("networkInterfaces")
            if isinstance(network_profile, dict)
            else None
        )
        if not isinstance(interfaces, list) or not interfaces:
            raise AzureClientError("Azure VM has no network interface")
        primary = next(
            (
                item
                for item in interfaces
                if isinstance(item, dict)
                and isinstance(item.get("properties"), dict)
                and item["properties"].get("primary") is True
            ),
            interfaces[0],
        )
        nic_id = primary.get("id") if isinstance(primary, dict) else None
        if not isinstance(nic_id, str) or not nic_id.strip():
            raise AzureClientError("Azure VM network interface is missing id")
        return nic_id.strip()

    @staticmethod
    def _ipv6_ip_configuration(nic: dict[str, Any]) -> dict[str, Any]:
        properties = nic.get("properties")
        configurations = (
            properties.get("ipConfigurations") if isinstance(properties, dict) else None
        )
        if not isinstance(configurations, list):
            raise AzureClientError("Azure NIC response is missing IP configurations")
        for configuration in configurations:
            if not isinstance(configuration, dict):
                continue
            config_properties = configuration.get("properties")
            version = (
                config_properties.get("privateIPAddressVersion")
                if isinstance(config_properties, dict)
                else None
            )
            if str(version or "").casefold() == "ipv6":
                return configuration
        raise AzureClientError("Azure NIC has no IPv6 IP configuration")

    @staticmethod
    def _ip_configuration_public_ip_id(
        ip_configuration: dict[str, Any]
    ) -> str:
        properties = ip_configuration.get("properties")
        public_ip = (
            properties.get("publicIPAddress") if isinstance(properties, dict) else None
        )
        resource_id = public_ip.get("id") if isinstance(public_ip, dict) else None
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise AzureClientError(
                "Azure IPv6 IP configuration has no Public IP attachment"
            )
        return resource_id.strip()

    @staticmethod
    def _public_ip_address(public_ip: dict[str, Any]) -> str | None:
        properties = public_ip.get("properties")
        value = properties.get("ipAddress") if isinstance(properties, dict) else None
        return str(value).strip() if value else None

    def _resource_id(self, resource_group: str, namespace: str, resource_type: str, name: str) -> str:
        return (
            f"/subscriptions/{self._subscription_id}/resourceGroups/{resource_group}/"
            f"providers/{namespace}/{resource_type}/{name}"
        )

    def _resource_path(self, resource_group: str, namespace: str, resource_type: str) -> str:
        return (
            f"/subscriptions/{self._subscription_id}/resourceGroups/{resource_group}/"
            f"providers/{namespace}/{resource_type}"
        )

    def _remember_created(self, resource_id: str) -> None:
        if resource_id not in self._created_resource_ids:
            self._created_resource_ids.append(resource_id)

    @staticmethod
    def _collection(payload: dict[str, Any], name: str) -> list[dict[str, Any]]:
        value = payload.get("value", [])
        if not isinstance(value, list):
            raise AzureClientError(f"{name} response must contain a list")
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _should_retry_exception(exc: BaseException) -> bool:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
        return isinstance(exc, AzureClientError) and exc.status_code in RETRYABLE_STATUS_CODES

    @staticmethod
    def _build_error(response: requests.Response) -> AzureClientError:
        message = response.text.strip()
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or error.get("code") or message)
            elif payload.get("error_description"):
                message = str(payload["error_description"])
        return AzureClientError(
            f"Azure API error {response.status_code}: {message}",
            status_code=response.status_code,
        )

    @staticmethod
    def _tag_map(tags: tuple[str, ...]) -> dict[str, str]:
        tag_map = {
            tag: "true"
            for tag in dict.fromkeys(("shadowfleet", *tags))
            if tag.strip()
        }
        tag_map["shadowfleet_created_at"] = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        return tag_map

    @classmethod
    def _nsg_payload(
        cls, location: str, ports: tuple[int, ...], tags: tuple[str, ...]
    ) -> dict[str, object]:
        rules = []
        for index, port in enumerate(dict.fromkeys(port for port in ports if 0 < port <= 65535)):
            rules.append(
                {
                    "name": f"allow-tcp-{port}",
                    "properties": {
                        "priority": 100 + index,
                        "access": "Allow",
                        "direction": "Inbound",
                        "protocol": "Tcp",
                        "sourcePortRange": "*",
                        "destinationPortRange": str(port),
                        "sourceAddressPrefix": "*",
                        "destinationAddressPrefix": "*",
                    },
                }
            )
        return {"location": location, "tags": cls._tag_map(tags), "properties": {"securityRules": rules}}

    @classmethod
    def _public_ip_payload(
        cls, location: str, version: str, tags: tuple[str, ...]
    ) -> dict[str, object]:
        return {
            "location": location,
            "tags": cls._tag_map(tags),
            "sku": {"name": "Standard"},
            "properties": {
                "publicIPAllocationMethod": "Static",
                "publicIPAddressVersion": version,
                "idleTimeoutInMinutes": 30,
            },
        }

    @staticmethod
    def _rotation_public_ip_properties(
        public_ip: dict[str, Any],
        *,
        preserve_dns_settings: bool,
    ) -> dict[str, object]:
        existing = public_ip.get("properties")
        if not isinstance(existing, dict):
            existing = {}
        mutable_names = {
            "ddosSettings",
            "deleteOption",
            "idleTimeoutInMinutes",
            "ipTags",
        }
        properties: dict[str, object] = {
            key: value for key, value in existing.items() if key in mutable_names
        }
        if preserve_dns_settings and "dnsSettings" in existing:
            properties["dnsSettings"] = existing["dnsSettings"]
        if preserve_dns_settings and "publicIPPrefix" in existing:
            properties["publicIPPrefix"] = existing["publicIPPrefix"]
        properties["publicIPAllocationMethod"] = "Static"
        properties["publicIPAddressVersion"] = "IPv6"
        properties.setdefault("idleTimeoutInMinutes", 30)
        return properties

    @staticmethod
    def _rotation_public_ip_tags(public_ip: dict[str, Any]) -> dict[str, str]:
        existing = public_ip.get("tags")
        tags = (
            {str(key): str(value) for key, value in existing.items()}
            if isinstance(existing, dict)
            else {}
        )
        tags["shadowfleet"] = "true"
        tags["shadowfleet_created_at"] = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        return tags

    @staticmethod
    def _rotation_public_ip_payload(
        public_ip: dict[str, Any],
        *,
        preserve_dns_settings: bool,
    ) -> dict[str, object]:
        location = str(public_ip.get("location") or "").strip()
        if not location:
            raise AzureClientError("Azure IPv6 Public IP response is missing location")
        payload: dict[str, object] = {
            "location": location,
            "tags": AzureClient._rotation_public_ip_tags(public_ip),
            "sku": public_ip.get("sku") or {"name": "Standard"},
            "properties": AzureClient._rotation_public_ip_properties(
                public_ip,
                preserve_dns_settings=preserve_dns_settings,
            ),
        }
        for field_name in ("zones", "extendedLocation"):
            field_value = public_ip.get(field_name)
            if field_value is not None:
                payload[field_name] = field_value
        return payload

    @classmethod
    def _nic_payload(
        cls,
        location: str,
        subnet_id: str,
        nsg_id: str,
        ipv4_id: str,
        ipv6_id: str,
        tags: tuple[str, ...],
    ) -> dict[str, object]:
        return {
            "location": location,
            "tags": cls._tag_map(tags),
            "properties": {
                "networkSecurityGroup": {"id": nsg_id},
                "ipConfigurations": [
                    {
                        "name": "ipv4",
                        "properties": {
                            "primary": True,
                            "privateIPAllocationMethod": "Dynamic",
                            "privateIPAddressVersion": "IPv4",
                            "subnet": {"id": subnet_id},
                            "publicIPAddress": {"id": ipv4_id},
                        },
                    },
                    {
                        "name": "ipv6",
                        "properties": {
                            "privateIPAllocationMethod": "Dynamic",
                            "privateIPAddressVersion": "IPv6",
                            "subnet": {"id": subnet_id},
                            "publicIPAddress": {"id": ipv6_id},
                        },
                    },
                ],
            },
        }

    @classmethod
    def _vm_payload(cls, request: AzureVmLaunchRequest, nic_id: str) -> dict[str, object]:
        custom_data = base64.b64encode(request.user_data.encode("utf-8")).decode("ascii")
        return {
            "location": request.location,
            "tags": cls._tag_map(request.tags),
            "properties": {
                "hardwareProfile": {"vmSize": request.vm_size},
                "storageProfile": {
                    "imageReference": {
                        "publisher": request.image_publisher,
                        "offer": request.image_offer,
                        "sku": request.image_sku,
                        "version": request.image_version,
                    },
                    "osDisk": {
                        "createOption": "FromImage",
                        "deleteOption": "Delete",
                        "managedDisk": {"storageAccountType": "Standard_LRS"},
                    },
                },
                "osProfile": {
                    "computerName": request.name[:64],
                    "adminUsername": request.admin_username,
                    "customData": custom_data,
                    "linuxConfiguration": {
                        "disablePasswordAuthentication": True,
                        "ssh": {
                            "publicKeys": [
                                {
                                    "path": f"/home/{request.admin_username}/.ssh/authorized_keys",
                                    "keyData": request.ssh_public_key,
                                }
                            ]
                        },
                    },
                },
                "networkProfile": {
                    "networkInterfaces": [{"id": nic_id, "properties": {"primary": True}}]
                },
            },
        }


def _validate_dual_stack_subnet(
    subnet: dict[str, Any],
    subnet_id: str,
) -> None:
    properties = subnet.get("properties")
    if not isinstance(properties, dict):
        raise AzureClientError(
            f"Azure subnet response is missing properties: {subnet_id}",
            status_code=409,
        )
    raw_prefixes = properties.get("addressPrefixes")
    if isinstance(raw_prefixes, list):
        prefixes = [
            str(prefix).strip()
            for prefix in raw_prefixes
            if str(prefix).strip()
        ]
    else:
        single_prefix = str(properties.get("addressPrefix") or "").strip()
        prefixes = [single_prefix] if single_prefix else []

    versions: set[int] = set()
    try:
        versions = {
            ip_network(prefix, strict=False).version
            for prefix in prefixes
        }
    except ValueError as exc:
        raise AzureClientError(
            f"Azure subnet has an invalid address prefix: {subnet_id}",
            status_code=409,
        ) from exc
    if versions != {4, 6}:
        raise AzureClientError(
            f"Azure subnet must be dual-stack (IPv4 and IPv6): {subnet_id}",
            status_code=409,
        )


def _resource_name(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_" else "-" for character in value)
    cleaned = cleaned.strip("-")[:64]
    if not cleaned:
        raise ValueError("Azure VM name must contain at least one valid character")
    return cleaned


def _parse_vm_resource_id(resource_id: str) -> tuple[str, str] | None:
    parts = [part for part in resource_id.strip("/").split("/") if part]
    lowered = [part.lower() for part in parts]
    try:
        group_index = lowered.index("resourcegroups")
        vm_index = lowered.index("virtualmachines")
        return parts[group_index + 1], parts[vm_index + 1]
    except (ValueError, IndexError):
        return None
