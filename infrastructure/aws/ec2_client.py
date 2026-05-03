from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Callable
from typing import Any

from botocore.client import BaseClient

from infrastructure.aws.ec2_client_helpers import (
    DEFAULT_IPV6_INGRESS_PORTS,
    DEFAULT_WRITE_BURST_CAPACITY,
    DEFAULT_WRITE_TOKENS_PER_SECOND,
    Ec2InstanceLaunchResult,
    Ec2LaunchRequest,
    build_launch_result,
    execute_ec2_call,
    find_missing_ipv6_ingress_ports,
    validate_launch_request,
)
from infrastructure.aws.ec2_ipv6 import EC2Ipv6Client
from infrastructure.aws.ec2_vpc import EC2VpcClient
from infrastructure.aws.proxy_client import build_aws_boto_proxies
from models.aws_credentials import AwsCredentials
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import TokenBucketRateLimiter

__all__ = [
    "EC2Client",
    "Ec2InstanceLaunchResult",
    "Ec2LaunchRequest",
    "InstanceTypeSpec",
]


@dataclass(frozen=True)
class InstanceTypeSpec:
    """Arm64 instance type with specs, ordered by priority for default selection."""
    vcpu: int
    memory_gb: float
    series_priority: int
    instance_type: str

    @property
    def series_name(self) -> str:
        if self.instance_type.startswith("c6g"):
            return "c6g"
        if self.instance_type.startswith("m6g"):
            return "m6g"
        if self.instance_type.startswith("t4g"):
            return "t4g"
        return "other"


class EC2Client:
    def __init__(
        self,
        runtime_context: RuntimeContext,
        aws_credential: AwsCredentials,
    ) -> None:
        self._runtime_context = runtime_context
        self._aws_credential = aws_credential
        self._logger = runtime_context.logger.getChild(
            f"infrastructure.aws.ec2.{aws_credential.account_id}"
        )
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._write_rate_limiter = TokenBucketRateLimiter(
            tokens_per_second=DEFAULT_WRITE_TOKENS_PER_SECOND,
            burst_capacity=DEFAULT_WRITE_BURST_CAPACITY,
        )
        self._ec2_client = _build_ec2_service_client(
            runtime_context=runtime_context,
            aws_credential=aws_credential,
        )
        self._execute_ec2_call = self._build_execute_call()
        self.vpc = EC2VpcClient(self._ec2_client, self._execute_ec2_call, self._logger)
        self.ipv6 = EC2Ipv6Client(self._ec2_client, self._execute_ec2_call)

    @property
    def region(self) -> str:
        return self._aws_credential.region

    # ------------------------------------------------------------------ Helpers
    def _build_execute_call(self) -> Callable[..., Any]:
        def _call(
            operation_name: str,
            func: Callable[[], Any],
            is_write: bool = False,
        ) -> Any:
            return execute_ec2_call(
                logger=self._logger,
                region=self.region,
                max_retries=self._max_retries,
                retry_backoff_seconds=self._retry_backoff_seconds,
                rate_limiter=self._write_rate_limiter,
                operation_name=operation_name,
                func=func,
                is_write=is_write,
            )
        return _call

    # ---------------------------------------------------------- IPv6 SG rules
    def ensure_ipv6_ingress_rules(
        self,
        security_group_id: str,
        ports: tuple[int, ...] = DEFAULT_IPV6_INGRESS_PORTS,
    ) -> None:
        sg = self.vpc.describe_security_group(security_group_id)
        missing_ports = find_missing_ipv6_ingress_ports(
            security_group=sg,
            expected_ports=ports,
        )
        if not missing_ports:
            set_event_type("aws_security_group_verified")
            self._logger.info(
                "IPv6 ingress rules already present for security group %s",
                security_group_id,
            )
            return

        ip_permissions = [
            {
                "IpProtocol": "tcp",
                "FromPort": port,
                "ToPort": port,
                "Ipv6Ranges": [
                    {"CidrIpv6": "::/0", "Description": "ShadowFleet IPv6 ingress"},
                ],
            }
            for port in missing_ports
        ]
        self.vpc.authorize_security_group_ingress(security_group_id, ip_permissions)
        set_event_type("aws_security_group_updated")
        self._logger.info(
            "Ensured IPv6 ingress rules for security group %s on ports %s",
            security_group_id,
            missing_ports,
        )

    # ---------------------------------------------------------- Instance lifecycle
    def launch_ipv6_instance(
        self,
        launch_request: Ec2LaunchRequest,
    ) -> Ec2InstanceLaunchResult:
        validate_launch_request(self._logger, launch_request)
        self.ensure_ipv6_ingress_rules(launch_request.security_group_id)

        payload: dict[str, Any] = {
            "ImageId": launch_request.image_id,
            "InstanceType": launch_request.instance_type,
            "MinCount": 1,
            "MaxCount": 1,
            "UserData": launch_request.user_data,
            "NetworkInterfaces": [
                {
                    "DeviceIndex": 0,
                    "SubnetId": launch_request.subnet_id,
                    "Groups": [launch_request.security_group_id],
                    "AssociatePublicIpAddress": launch_request.associate_public_ip,
                    "DeleteOnTermination": True,
                    "Ipv6AddressCount": launch_request.ipv6_address_count,
                }
            ],
        }
        if launch_request.key_name:
            payload["KeyName"] = launch_request.key_name
        if launch_request.iam_instance_profile_name:
            payload["IamInstanceProfile"] = {"Name": launch_request.iam_instance_profile_name}
        if launch_request.instance_name:
            payload["TagSpecifications"] = [
                {
                    "ResourceType": "instance",
                    "Tags": [{"Key": "Name", "Value": launch_request.instance_name}],
                }
            ]

        response = self._execute_ec2_call(
            operation_name="launch_ipv6_instance",
            func=lambda: self._ec2_client.run_instances(**payload),
            is_write=True,
        )
        instances = response.get("Instances", [])
        if not instances:
            raise RuntimeError("AWS run_instances returned no Instances payload")

        launch_result = build_launch_result(
            instance_payload=instances[0],
            subnet_id=launch_request.subnet_id,
        )
        set_event_type("aws_instance_launched")
        self._logger.info(
            "Launched instance %s in subnet %s associate_public_ip=%s",
            launch_result.instance_id,
            launch_request.subnet_id,
            launch_request.associate_public_ip,
        )
        return launch_result

    def get_instance_state(self, instance_id: str) -> str:
        response = self._execute_ec2_call(
            operation_name="get_instance_state",
            func=lambda: self._ec2_client.describe_instances(InstanceIds=[instance_id]),
        )
        reservations = response.get("Reservations", [])
        if not reservations or not reservations[0].get("Instances"):
            raise ValueError(f"Instance not found: {instance_id}")

        state = reservations[0]["Instances"][0].get("State", {}).get("Name")
        if not state:
            raise ValueError(f"Instance state missing: {instance_id}")
        return state

    def start_instance(self, instance_id: str) -> None:
        self._execute_ec2_call(
            operation_name="start_instance",
            func=lambda: self._ec2_client.start_instances(InstanceIds=[instance_id]),
            is_write=True,
        )
        set_event_type("aws_instance_started")
        self._logger.info("Started instance %s", instance_id)

    def stop_instance(self, instance_id: str) -> None:
        self._execute_ec2_call(
            operation_name="stop_instance",
            func=lambda: self._ec2_client.stop_instances(InstanceIds=[instance_id]),
            is_write=True,
        )
        set_event_type("aws_instance_stopped")
        self._logger.info("Stopped instance %s", instance_id)

    def terminate_instance(self, instance_id: str) -> None:
        self._execute_ec2_call(
            operation_name="terminate_instance",
            func=lambda: self._ec2_client.terminate_instances(InstanceIds=[instance_id]),
            is_write=True,
        )
        set_event_type("aws_instance_terminated")
        self._logger.info("Terminated instance %s", instance_id)

    # ------------------------------------------------------ Network interfaces
    def get_primary_network_interface_id(self, instance_id: str) -> str:
        response = self._execute_ec2_call(
            operation_name="get_primary_network_interface_id",
            func=lambda: self._ec2_client.describe_instances(InstanceIds=[instance_id]),
        )
        reservations = response.get("Reservations", [])
        if not reservations or not reservations[0].get("Instances"):
            raise ValueError(f"Instance not found: {instance_id}")

        instance = reservations[0]["Instances"][0]
        network_interfaces = instance.get("NetworkInterfaces", [])
        if not network_interfaces:
            raise ValueError(f"Instance has no network interface: {instance_id}")

        primary_nic = min(
            network_interfaces,
            key=lambda item: item.get("Attachment", {}).get("DeviceIndex", 0),
        )
        network_interface_id = primary_nic.get("NetworkInterfaceId")
        if not network_interface_id:
            raise ValueError(f"Primary network interface id missing: {instance_id}")
        return network_interface_id

    def rotate_instance_ipv6(
        self,
        instance_id: str,
        subnet_id: str,
    ) -> tuple[str | None, str]:
        network_interface_id = self.get_primary_network_interface_id(instance_id)
        subnet_ipv6_cidr = self.vpc.describe_subnet_ipv6_cidr(subnet_id)
        old_address, new_address = self.ipv6.rotate_ipv6(
            network_interface_id=network_interface_id,
            subnet_ipv6_cidr=subnet_ipv6_cidr,
        )
        self._logger.info(
            "Rotated IPv6 for instance %s: old=%s new=%s",
            instance_id,
            old_address,
            new_address,
        )
        return old_address, new_address

    # ---------------------------------------------------- Instance type listing
    def list_arm64_instance_types_with_specs(self) -> list[InstanceTypeSpec]:
        response = self._execute_ec2_call(
            operation_name="describe_instance_types",
            func=lambda: self._ec2_client.describe_instance_types(
                Filters=[{"Name": "processor-info.supported-architecture", "Values": ["arm64"]}]
            ),
        )
        specs: list[InstanceTypeSpec] = []
        for t in response.get("InstanceTypes", []):
            name = t.get("InstanceType", "")
            if not name:
                continue

            vcpu_info = t.get("VCpuInfo", {})
            mem_info = t.get("MemoryInfo", {})
            default_cores = vcpu_info.get("DefaultCores", 0)
            memory_mib = mem_info.get("SizeInMiB", 0)
            if default_cores == 0 or memory_mib == 0:
                continue

            if name.startswith("t4g"):
                priority = 1
            elif name.startswith("c6g"):
                priority = 2
            elif name.startswith("m6g"):
                priority = 3
            else:
                priority = 9

            specs.append(InstanceTypeSpec(
                vcpu=default_cores,
                memory_gb=round(memory_mib / 1024, 1),
                series_priority=priority,
                instance_type=name,
            ))

        specs.sort(key=lambda s: (s.vcpu, abs(s.memory_gb - 2.0), s.series_priority, s.instance_type))
        return specs

    def list_arm64_amis(
        self,
        owners: tuple[str, ...] = ("amazon",),
        filters: dict[str, str] | None = None,
        name_filter: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, str]]:
        def _debian_version_key(name: str) -> tuple[int, str]:
            m = re.search(r"debian[_-]?(\d+)", name, re.IGNORECASE)
            return (int(m.group(1)) if m else -1, name)

        def _is_stable(name: str) -> bool:
            lower = re.sub(r"\s*\(ami-[^)]+\)", "", name.lower()).strip()
            parts = lower.split("-")
            if len(parts) < 3 or parts[0] != "debian" or "arm64" not in parts:
                return False
            try:
                int(parts[1])
            except ValueError:
                return False
            idx = parts.index("arm64")
            return all(part.isdigit() for part in parts[2:idx])

        query_filters: list[dict[str, Any]] = [
            {"Name": "architecture", "Values": ["arm64"]},
            {"Name": "state", "Values": ["available"]},
        ]
        if filters:
            query_filters.extend({"Name": k, "Values": [v]} for k, v in filters.items())
        if name_filter:
            query_filters.append({"Name": "name", "Values": [f"*{name_filter}*"]})

        response = self._execute_ec2_call(
            operation_name="list_arm64_amis",
            func=lambda: self._ec2_client.describe_images(
                Owners=list(owners),
                Filters=query_filters,
            ),
        )
        images = sorted(
            response.get("Images", []),
            key=lambda x: _debian_version_key(x.get("Name", "")),
            reverse=True,
        )
        return [
            {
                "ImageId": img.get("ImageId", ""),
                "Name": img.get("Name", ""),
                "Description": img.get("Description", ""),
                "OwnerId": img.get("OwnerId", ""),
            }
            for img in images[:limit]
            if img.get("ImageId") and _is_stable(img.get("Name", ""))
        ]


def _build_ec2_service_client(
    runtime_context: RuntimeContext,
    aws_credential: AwsCredentials,
) -> BaseClient:
    import boto3
    from botocore.config import Config as BotoConfig

    session = boto3.session.Session(
        aws_access_key_id=aws_credential.access_key,
        aws_secret_access_key=aws_credential.secret_key,
        region_name=aws_credential.region,
    )
    kwargs: dict[str, object] = {
        "connect_timeout": runtime_context.config.app.request_timeout_seconds,
        "read_timeout": runtime_context.config.app.request_timeout_seconds,
    }
    proxies = build_aws_boto_proxies(runtime_context)
    if proxies is not None:
        kwargs["proxies"] = proxies
    return session.client("ec2", config=BotoConfig(**kwargs))
