from __future__ import annotations

from collections.abc import Callable
from typing import Any

from botocore.client import BaseClient
from botocore.exceptions import ClientError


class EC2VpcClient:
    """EC2 VPC/Subnet/SecurityGroup operations, delegating to the shared boto client."""

    def __init__(self, ec2_client: BaseClient, execute_ec2_call: Callable[..., Any]) -> None:
        self._ec2_client = ec2_client
        self._execute_ec2_call = execute_ec2_call

    # ------------------------------------------------------------------ VPC
    def find_or_create_vpc(self, vpc_cidr: str = "10.88.0.0/16") -> str:
        response = self._execute_ec2_call(
            operation_name="find_vpc",
            func=lambda: self._ec2_client.describe_vpcs(
                Filters=[{"Name": "cidr-block-association.cidr-block", "Values": [vpc_cidr]}]
            ),
        )
        vpcs = response.get("Vpcs", [])
        for vpc in vpcs:
            vpc_id = vpc.get("VpcId")
            if vpc_id:
                return vpc_id

        response = self._execute_ec2_call(
            operation_name="create_vpc",
            func=lambda: self._ec2_client.create_vpc(CidrBlock=vpc_cidr),
            is_write=True,
        )
        vpc_id = response.get("Vpc", {}).get("VpcId")
        if not vpc_id:
            raise RuntimeError(f"AWS create_vpc returned no VpcId for CIDR {vpc_cidr}")

        self._execute_ec2_call(
            operation_name="enable_vpc_dns",
            func=lambda: self._ec2_client.modify_vpc_attribute(
                VpcId=vpc_id, EnableDnsHostnames={"Value": True}
            ),
            is_write=True,
        )
        return vpc_id

    # ----------------------------------------------------------- IPv6 on VPC
    def ensure_vpc_ipv6_enabled(self, vpc_id: str) -> str:
        """Enable IPv6 on VPC if not already; returns the VPC's IPv6 CIDR prefix."""
        response = self._execute_ec2_call(
            operation_name="describe_vpc_ipv6",
            func=lambda: self._ec2_client.describe_vpcs(VpcIds=[vpc_id]),
        )
        vpcs = response.get("Vpcs", [])
        if not vpcs:
            raise ValueError(f"VPC not found: {vpc_id}")
        ipv6_blocks = vpcs[0].get("Ipv6CidrBlockAssociationSet", [])
        for assoc in ipv6_blocks:
            state = assoc.get("Ipv6CidrBlockState", {}).get("State")
            if state == "associated":
                return assoc.get("Ipv6CidrBlock", "")
        self._execute_ec2_call(
            operation_name="associate_vpc_ipv6",
            func=lambda: self._ec2_client.associate_vpc_cidr_block(
                VpcId=vpc_id, AmazonProvidedIpv6CidrBlock=True
            ),
            is_write=True,
        )
        desc = self._execute_ec2_call(
            operation_name="describe_vpc_after_assign",
            func=lambda: self._ec2_client.describe_vpcs(VpcIds=[vpc_id]),
        )
        vpcs2 = desc.get("Vpcs", [])
        for assoc in vpcs2[0].get("Ipv6CidrBlockAssociationSet", []):
            if assoc.get("Ipv6CidrBlockState", {}).get("State") == "associated":
                return assoc.get("Ipv6CidrBlock", "")
        raise RuntimeError("Failed to associate IPv6 CIDR to VPC")

    @staticmethod
    def _subnet_ipv6_from_vpc(vpc_ipv6_cidr: str, subnet_index: int = 0) -> str:
        parts = vpc_ipv6_cidr.rstrip("/").split(":")
        if len(parts) < 4:
            raise ValueError(f"Unexpected VPC IPv6 CIDR format: {vpc_ipv6_cidr}")
        net_prefix = ":".join(parts[:4])
        return f"{net_prefix}:{subnet_index:02x}00::/64"

    # ---------------------------------------------------------------- Subnet
    def find_or_create_subnet_with_ipv6(
        self,
        vpc_id: str,
        availability_zone: str | None = None,
        subnet_cidr: str = "10.88.1.0/24",
    ) -> tuple[str, str]:
        az_filter: list[dict[str, Any]] = [{"Name": "vpc-id", "Values": [vpc_id]}]
        if availability_zone:
            az_filter.append({"Name": "availability-zone", "Values": [availability_zone]})

        response = self._execute_ec2_call(
            operation_name="find_subnet",
            func=lambda: self._ec2_client.describe_subnets(Filters=az_filter),
        )
        subnets = response.get("Subnets", [])
        candidate_subnet_id: str | None = None
        candidate_az: str = ""
        for subnet in subnets:
            subnet_id = subnet.get("SubnetId")
            if subnet_id:
                candidate_subnet_id = subnet_id
                candidate_az = subnet.get("AvailabilityZone", "")
                if subnet.get("Ipv6CidrBlock"):
                    return subnet_id, candidate_az

        if not availability_zone:
            response = self._execute_ec2_call(
                operation_name="list_azs",
                func=lambda: self._ec2_client.describe_availability_zones(
                    Filters=[{"Name": "state", "Values": ["available"]}]
                ),
            )
            azs = response.get("AvailabilityZones", [])
            if not azs:
                raise RuntimeError("No available availability zones")
            availability_zone = azs[0].get("ZoneName", "us-east-1a")

        if candidate_subnet_id:
            subnet_id = candidate_subnet_id
            found_az = candidate_az
            vpc_ipv6_cidr = self.ensure_vpc_ipv6_enabled(vpc_id)
            subnet_ipv6_cidr = self._subnet_ipv6_from_vpc(vpc_ipv6_cidr)
            self._execute_ec2_call(
                operation_name="associate_subnet_ipv6",
                func=lambda: self._ec2_client.associate_subnet_cidr_block(
                    SubnetId=subnet_id, Ipv6CidrBlock=subnet_ipv6_cidr
                ),
                is_write=True,
            )
        else:
            vpc_ipv6_cidr = self.ensure_vpc_ipv6_enabled(vpc_id)
            subnet_ipv6_cidr = self._subnet_ipv6_from_vpc(vpc_ipv6_cidr)
            response = self._execute_ec2_call(
                operation_name="create_subnet",
                func=lambda: self._ec2_client.create_subnet(
                    VpcId=vpc_id,
                    CidrBlock=subnet_cidr,
                    AvailabilityZone=availability_zone,
                ),
                is_write=True,
            )
            subnet_id = response.get("Subnet", {}).get("SubnetId")
            if not subnet_id:
                raise RuntimeError("AWS create_subnet returned no SubnetId")
            found_az = response.get("Subnet", {}).get("AvailabilityZone", availability_zone)

            self._execute_ec2_call(
                operation_name="associate_subnet_ipv6",
                func=lambda: self._ec2_client.associate_subnet_cidr_block(
                    SubnetId=subnet_id, Ipv6CidrBlock=subnet_ipv6_cidr
                ),
                is_write=True,
            )

        self._execute_ec2_call(
            operation_name="enable_subnet_ipv6",
            func=lambda: self._ec2_client.modify_subnet_attribute(
                SubnetId=subnet_id, AssignIpv6AddressOnCreation={"Value": True}
            ),
            is_write=True,
        )
        return subnet_id, found_az

    def describe_subnet_ipv6_cidr(self, subnet_id: str) -> str:
        response = self._execute_ec2_call(
            operation_name="describe_subnet_ipv6_cidr",
            func=lambda: self._ec2_client.describe_subnets(SubnetIds=[subnet_id]),
        )
        subnets = response.get("Subnets", [])
        if not subnets:
            raise ValueError(f"Subnet not found: {subnet_id}")

        for association in subnets[0].get("Ipv6CidrBlockAssociationSet", []):
            state = association.get("Ipv6CidrBlockState", {}).get("State")
            ipv6_cidr_block = association.get("Ipv6CidrBlock")
            if state == "associated" and ipv6_cidr_block:
                return ipv6_cidr_block

        raise ValueError(f"Subnet does not have an associated IPv6 CIDR block: {subnet_id}")

    # -------------------------------------------------------- Security Group
    def create_security_group_with_rules(
        self,
        vpc_id: str,
        group_name: str,
        description: str,
        port_rules: tuple[tuple[int, str], ...],
    ) -> str:
        response = self._execute_ec2_call(
            operation_name="create_sg",
            func=lambda: self._ec2_client.create_security_group(
                GroupName=group_name,
                Description=description,
                VpcId=vpc_id,
            ),
            is_write=True,
        )
        sg_id = response.get("GroupId")
        if not sg_id:
            raise RuntimeError(f"AWS create_security_group returned no GroupId for {group_name}")

        ip_permissions: list[dict[str, Any]] = [
            {
                "IpProtocol": protocol,
                "FromPort": port,
                "ToPort": port,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": f"ShadowFleet port {port}"}],
            }
            for port, protocol in port_rules
        ]

        if ip_permissions:
            self._execute_ec2_call(
                operation_name="authorize_sg_rules",
                func=lambda: self._ec2_client.authorize_security_group_ingress(
                    GroupId=sg_id, IpPermissions=ip_permissions
                ),
                is_write=True,
            )

        return sg_id

    def describe_security_group(self, security_group_id: str) -> dict[str, Any]:
        response = self._execute_ec2_call(
            operation_name="describe_security_group",
            func=lambda: self._ec2_client.describe_security_groups(GroupIds=[security_group_id]),
        )
        groups = response.get("SecurityGroups", [])
        if not groups:
            raise ValueError(f"Security group not found: {security_group_id}")
        return groups[0]

    def authorize_security_group_ingress(
        self,
        security_group_id: str,
        ip_permissions: list[dict[str, Any]],
    ) -> None:
        try:
            self._execute_ec2_call(
                operation_name="authorize_security_group_ingress",
                func=lambda: self._ec2_client.authorize_security_group_ingress(
                    GroupId=security_group_id,
                    IpPermissions=ip_permissions,
                ),
                is_write=True,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "InvalidPermission.Duplicate":
                raise
