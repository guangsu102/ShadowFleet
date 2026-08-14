from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


AzureNetworkResourceType = Literal[
    "azure_network_interface",
    "azure_public_ip_address",
    "azure_network_security_group",
]


@dataclass(frozen=True)
class AzureNetworkResourceSpec:
    resource_type: AzureNetworkResourceType
    name_suffixes: tuple[str, ...]


AZURE_HEALING_PUBLIC_IP_MARKER = "-ipv6-heal-"


AZURE_NETWORK_RESOURCE_SPECS = (
    AzureNetworkResourceSpec("azure_network_interface", ("-nic",)),
    AzureNetworkResourceSpec("azure_public_ip_address", ("-ipv4", "-ipv6")),
    AzureNetworkResourceSpec("azure_network_security_group", ("-nsg",)),
)
AZURE_NETWORK_RESOURCE_TYPES = frozenset(
    spec.resource_type for spec in AZURE_NETWORK_RESOURCE_SPECS
)


def azure_resource_tags(resource: dict[str, Any]) -> dict[str, str]:
    raw_tags = resource.get("tags")
    if not isinstance(raw_tags, dict):
        return {}
    return {str(key): str(value) for key, value in raw_tags.items()}


def is_shadowfleet_azure_resource(resource: dict[str, Any]) -> bool:
    return azure_resource_tags(resource).get("shadowfleet", "").casefold() == "true"


def azure_resource_created_at(resource: dict[str, Any]) -> str:
    return azure_resource_tags(resource).get("shadowfleet_created_at", "").strip()


def azure_vm_name(resource: dict[str, Any]) -> str:
    name = str(resource.get("name") or "").strip()
    if name:
        return name
    resource_id = str(resource.get("id") or "").strip().rstrip("/")
    return resource_id.rsplit("/", 1)[-1] if resource_id else ""


def azure_parent_vm_name(
    resource_type: AzureNetworkResourceType,
    resource_name: str,
) -> str | None:
    normalized_name = resource_name.strip()
    if not normalized_name:
        return None
    spec = next(
        (
            candidate
            for candidate in AZURE_NETWORK_RESOURCE_SPECS
            if candidate.resource_type == resource_type
        ),
        None,
    )
    if spec is None:
        return None
    lowered_name = normalized_name.casefold()
    if (
        resource_type == "azure_public_ip_address"
        and AZURE_HEALING_PUBLIC_IP_MARKER in lowered_name
    ):
        marker_index = lowered_name.rfind(AZURE_HEALING_PUBLIC_IP_MARKER)
        return normalized_name[:marker_index] or None
    for suffix in spec.name_suffixes:
        if lowered_name.endswith(suffix) and len(normalized_name) > len(suffix):
            return normalized_name[: -len(suffix)]
    return None


def azure_parent_vm_name_from_resource(
    resource_type: AzureNetworkResourceType,
    resource: dict[str, Any],
) -> str | None:
    tagged_parent = azure_resource_tags(resource).get(
        "shadowfleet_parent_vm", ""
    ).strip()
    if tagged_parent:
        return tagged_parent
    return azure_parent_vm_name(
        resource_type,
        str(resource.get("name") or ""),
    )


def is_azure_healing_public_ip(resource: dict[str, Any]) -> bool:
    name = str(resource.get("name") or "").casefold()
    return AZURE_HEALING_PUBLIC_IP_MARKER in name


def azure_public_ip_is_attached(resource: dict[str, Any]) -> bool:
    properties = resource.get("properties")
    if not isinstance(properties, dict):
        return False
    ip_configuration = properties.get("ipConfiguration")
    return isinstance(ip_configuration, dict) and bool(
        str(ip_configuration.get("id") or "").strip()
    )


def azure_parent_vm_is_live(
    parent_vm_name: str,
    live_vm_names: set[str],
    *,
    healing_public_ip: bool,
) -> bool:
    normalized_parent = parent_vm_name.casefold()
    if normalized_parent in live_vm_names:
        return True
    if not healing_public_ip:
        return False
    return any(
        live_vm_name[:42] == normalized_parent
        for live_vm_name in live_vm_names
    )
