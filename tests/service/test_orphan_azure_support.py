from __future__ import annotations

from services.orphan_azure_support import (
    azure_parent_vm_is_live,
    azure_parent_vm_name,
    azure_parent_vm_name_from_resource,
    azure_public_ip_is_attached,
    is_azure_healing_public_ip,
)


def test_healing_public_ip_name_resolves_parent_vm() -> None:
    assert (
        azure_parent_vm_name(
            "azure_public_ip_address",
            "sf-azure-ipv6-heal-deadbeef",
        )
        == "sf-azure"
    )


def test_parent_vm_tag_preserves_untruncated_vm_name() -> None:
    resource = {
        "name": "very-long-shadowfleet-name-ipv6-heal-deadbeef",
        "tags": {"shadowfleet_parent_vm": "very-long-shadowfleet-name-full"},
    }

    assert (
        azure_parent_vm_name_from_resource(
            "azure_public_ip_address",
            resource,
        )
        == "very-long-shadowfleet-name-full"
    )


def test_healing_public_ip_attachment_is_detected() -> None:
    resource = {
        "name": "sf-azure-ipv6-heal-deadbeef",
        "properties": {
            "ipConfiguration": {
                "id": "/subscriptions/sub/resourceGroups/rg/providers/"
                "Microsoft.Network/networkInterfaces/nic/ipConfigurations/ipv6"
            }
        },
    }

    assert is_azure_healing_public_ip(resource) is True
    assert azure_public_ip_is_attached(resource) is True
    assert azure_public_ip_is_attached(
        {"name": resource["name"], "properties": {}}
    ) is False


def test_truncated_healing_parent_matches_live_vm() -> None:
    full_name = "a" * 50
    assert azure_parent_vm_is_live(
        full_name[:42],
        {full_name},
        healing_public_ip=True,
    )
    assert not azure_parent_vm_is_live(
        full_name[:42],
        {full_name},
        healing_public_ip=False,
    )
