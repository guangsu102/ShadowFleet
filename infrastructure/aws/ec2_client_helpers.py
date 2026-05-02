from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import logging
import secrets
from collections.abc import Callable
from typing import Any

from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    ConnectionClosedError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from utils.logger import set_event_type
from utils.resilience import TokenBucketRateLimiter, execute_with_backoff


DEFAULT_WRITE_TOKENS_PER_SECOND = 1.0
DEFAULT_WRITE_BURST_CAPACITY = 2
DEFAULT_IPV6_INGRESS_PORTS = (80, 443)
MIN_RANDOM_HOST_OFFSET = 16
MAX_IPV6_GENERATION_ATTEMPTS = 16
RETRYABLE_AWS_ERROR_CODES = {
    "RequestLimitExceeded",
    "Throttling",
    "ThrottlingException",
    "RequestThrottled",
    "ServiceUnavailable",
    "InternalError",
}
RETRYABLE_IPV6_CANDIDATE_ERROR_CODES = {
    "InvalidIpv6Address.Malformed",
    "InvalidIpv6Address.InUse",
}


@dataclass(frozen=True)
class Ec2LaunchRequest:
    image_id: str
    instance_type: str
    subnet_id: str
    security_group_id: str
    user_data: str
    ipv6_address_count: int = 1
    associate_public_ip: bool = False
    key_name: str | None = None
    iam_instance_profile_name: str | None = None
    instance_name: str | None = None


@dataclass(frozen=True)
class Ec2InstanceLaunchResult:
    instance_id: str
    subnet_id: str
    state: str
    network_interface_id: str | None
    ipv6_addresses: list[str]


def execute_ec2_call(
    *,
    logger: logging.Logger,
    region: str,
    max_retries: int,
    retry_backoff_seconds: float,
    rate_limiter: TokenBucketRateLimiter,
    operation_name: str,
    func: Callable[[], Any],
    is_write: bool = False,
) -> Any:
    request_func = rate_limited(rate_limiter, func) if is_write else func
    try:
        return execute_with_backoff(
            operation_name=operation_name,
            max_retries=max_retries,
            base_delay_seconds=retry_backoff_seconds,
            logger=logger,
            event_type_prefix="aws",
            func=request_func,
            should_retry=should_retry_exception,
        )
    except ClientError as exc:
        set_event_type("aws_request_failed")
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        logger.exception(
            "AWS EC2 operation failed: operation=%s region=%s error_code=%s",
            operation_name,
            region,
            error_code,
        )
        raise
    except (
        ConnectTimeoutError,
        ConnectionClosedError,
        EndpointConnectionError,
        ReadTimeoutError,
    ):
        set_event_type("aws_request_failed")
        logger.exception(
            "AWS EC2 operation failed due to a network error: operation=%s region=%s",
            operation_name,
            region,
        )
        raise


def should_retry_exception(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            ConnectTimeoutError,
            ConnectionClosedError,
            EndpointConnectionError,
            ReadTimeoutError,
        ),
    ):
        return True
    if isinstance(exc, ClientError):
        return is_retryable_client_error(exc)
    return False


def is_retryable_client_error(exc: ClientError) -> bool:
    error_code = exc.response.get("Error", {}).get("Code", "")
    return error_code in RETRYABLE_AWS_ERROR_CODES


def is_retryable_ipv6_candidate_error(exc: ClientError) -> bool:
    error_code = exc.response.get("Error", {}).get("Code", "")
    error_message = exc.response.get("Error", {}).get("Message", "").lower()
    if error_code in RETRYABLE_IPV6_CANDIDATE_ERROR_CODES:
        return True
    return error_code == "InvalidParameterValue" and "ipv6" in error_message


def rate_limited(
    rate_limiter: TokenBucketRateLimiter,
    func: Callable[[], Any],
) -> Callable[[], Any]:
    def _wrapped() -> Any:
        rate_limiter.acquire()
        return func()

    return _wrapped


def generate_random_ipv6_address(
    subnet_network: ipaddress.IPv6Network,
    tried_addresses: set[str],
) -> str:
    host_bits = 128 - subnet_network.prefixlen
    if host_bits <= 0:
        raise ValueError(f"Subnet {subnet_network} does not allow host address randomization")

    max_offset = subnet_network.num_addresses - 1
    minimum_offset = min(MIN_RANDOM_HOST_OFFSET, max_offset)
    if max_offset <= minimum_offset:
        raise ValueError(f"Subnet {subnet_network} is too small for randomized IPv6 assignment")

    for _ in range(MAX_IPV6_GENERATION_ATTEMPTS):
        candidate_offset = secrets.randbits(host_bits)
        if candidate_offset <= minimum_offset or candidate_offset > max_offset:
            continue

        candidate_address = str(
            ipaddress.IPv6Address(int(subnet_network.network_address) + candidate_offset)
        )
        if candidate_address in tried_addresses:
            continue

        tried_addresses.add(candidate_address)
        return candidate_address

    raise RuntimeError(f"Failed to generate a unique randomized IPv6 in subnet {subnet_network}")


def find_missing_ipv6_ingress_ports(
    security_group: dict[str, Any],
    expected_ports: tuple[int, ...],
) -> list[int]:
    existing_ports: set[int] = set()
    for permission in security_group.get("IpPermissions", []):
        if permission.get("IpProtocol") != "tcp":
            continue

        from_port = permission.get("FromPort")
        to_port = permission.get("ToPort")
        if not isinstance(from_port, int) or not isinstance(to_port, int):
            continue

        has_global_ipv6_rule = any(
            ipv6_range.get("CidrIpv6") == "::/0"
            for ipv6_range in permission.get("Ipv6Ranges", [])
        )
        if not has_global_ipv6_rule:
            continue

        for port in range(from_port, to_port + 1):
            existing_ports.add(port)

    return [port for port in expected_ports if port not in existing_ports]


def validate_launch_request(logger: logging.Logger, launch_request: Ec2LaunchRequest) -> None:
    if launch_request.ipv6_address_count <= 0:
        raise ValueError("ipv6_address_count must be greater than 0")
    instance_family = launch_request.instance_type.split(".", maxsplit=1)[0]
    if not instance_family.endswith("g"):
        logger.warning(
            "Launching a non-Graviton instance type may violate ARM64 requirements: %s",
            launch_request.instance_type,
        )


def build_launch_result(
    instance_payload: dict[str, Any],
    subnet_id: str,
) -> Ec2InstanceLaunchResult:
    network_interfaces = instance_payload.get("NetworkInterfaces", [])
    primary_network_interface_id: str | None = None
    ipv6_addresses: list[str] = []

    if network_interfaces:
        primary_network_interface = min(
            network_interfaces,
            key=lambda item: item.get("Attachment", {}).get("DeviceIndex", 0),
        )
        primary_network_interface_id = primary_network_interface.get("NetworkInterfaceId")
        ipv6_addresses = [
            address["Ipv6Address"]
            for address in primary_network_interface.get("Ipv6Addresses", [])
            if address.get("Ipv6Address")
        ]

    instance_id = instance_payload.get("InstanceId")
    if not instance_id:
        raise RuntimeError("AWS instance launch response missing InstanceId")

    state = instance_payload.get("State", {}).get("Name", "pending")
    return Ec2InstanceLaunchResult(
        instance_id=instance_id,
        subnet_id=subnet_id,
        state=state,
        network_interface_id=primary_network_interface_id,
        ipv6_addresses=ipv6_addresses,
    )
