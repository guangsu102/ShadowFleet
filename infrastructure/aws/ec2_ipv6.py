from __future__ import annotations

import ipaddress
from collections.abc import Callable
from typing import Any

from botocore.exceptions import ClientError

from infrastructure.aws.ec2_client_helpers import (
    MAX_IPV6_GENERATION_ATTEMPTS,
    generate_random_ipv6_address,
    is_retryable_client_error,
    is_retryable_ipv6_candidate_error,
)
from utils.logger import set_event_type


class EC2Ipv6Client:
    """EC2 IPv6 address management operations."""

    def __init__(self, ec2_client: Any, execute_ec2_call: Callable[..., Any]) -> None:
        self._ec2_client = ec2_client
        self._execute_ec2_call = execute_ec2_call

    def get_bound_ipv6_addresses(self, network_interface_id: str) -> list[str]:
        response = self._execute_ec2_call(
            operation_name="get_bound_ipv6_addresses",
            func=lambda: self._ec2_client.describe_network_interfaces(
                NetworkInterfaceIds=[network_interface_id],
            ),
        )
        interfaces = response.get("NetworkInterfaces", [])
        if not interfaces:
            raise ValueError(f"Network interface not found: {network_interface_id}")

        ipv6_addresses = interfaces[0].get("Ipv6Addresses", [])
        return [
            addr["Ipv6Address"]
            for addr in ipv6_addresses
            if addr.get("Ipv6Address")
        ]

    def unassign_ipv6_addresses(
        self,
        network_interface_id: str,
        ipv6_addresses: list[str],
    ) -> None:
        if not ipv6_addresses:
            return

        self._execute_ec2_call(
            operation_name="unassign_ipv6_addresses",
            func=lambda: self._ec2_client.unassign_ipv6_addresses(
                NetworkInterfaceId=network_interface_id,
                Ipv6Addresses=ipv6_addresses,
            ),
            is_write=True,
        )
        set_event_type("aws_ipv6_unassigned")

    def assign_ipv6_addresses(
        self,
        network_interface_id: str,
        ipv6_addresses: list[str],
    ) -> None:
        self._execute_ec2_call(
            operation_name="assign_ipv6_addresses",
            func=lambda: self._ec2_client.assign_ipv6_addresses(
                NetworkInterfaceId=network_interface_id,
                Ipv6Addresses=ipv6_addresses,
            ),
            is_write=True,
        )
        set_event_type("aws_ipv6_assigned")

    def assign_random_ipv6_address(
        self,
        network_interface_id: str,
        subnet_ipv6_cidr: str,
        tried_addresses: set[str] | None = None,
    ) -> str:
        subnet_network = ipaddress.IPv6Network(subnet_ipv6_cidr, strict=True)
        tried: set[str] = tried_addresses or set()

        for _ in range(MAX_IPV6_GENERATION_ATTEMPTS):
            candidate_address = generate_random_ipv6_address(
                subnet_network=subnet_network,
                tried_addresses=tried,
            )

            try:
                self.assign_ipv6_addresses(network_interface_id, [candidate_address])
                set_event_type("aws_ipv6_assigned")
                return candidate_address
            except ClientError as exc:
                if is_retryable_client_error(exc):
                    raise
                if not is_retryable_ipv6_candidate_error(exc):
                    raise

        raise RuntimeError(
            f"Failed to assign randomized IPv6 address for network interface {network_interface_id}"
        )

    def rotate_ipv6(
        self,
        network_interface_id: str,
        subnet_ipv6_cidr: str,
    ) -> tuple[str | None, str]:
        old_addresses = self.get_bound_ipv6_addresses(network_interface_id)
        old_address = old_addresses[0] if old_addresses else None

        self.unassign_ipv6_addresses(network_interface_id, old_addresses)

        new_address = self.assign_random_ipv6_address(
            network_interface_id=network_interface_id,
            subnet_ipv6_cidr=subnet_ipv6_cidr,
        )
        set_event_type("aws_ipv6_rotated")
        return old_address, new_address
