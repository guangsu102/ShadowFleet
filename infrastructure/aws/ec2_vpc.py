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
            response = self._execute_ec2_call(
                operation_name="describe_subnet_for_ipv6",
                func=lambda: self._ec2_client.describe_subnets(SubnetIds=[subnet_id]),
            )
            subnets_checked = response.get("Subnets", [])
            if subnets_checked and subnets_checked[0].get("Ipv6CidrBlock"):
                return subnet_id, found_az
            subnet_ipv6_cidr = self._subnet_ipv6_from_vpc(vpc_ipv6_cidr)
            try:
                self._execute_ec2_call(
                    operation_name="associate_subnet_ipv6",
                    func=lambda: self._ec2_client.associate_subnet_cidr_block(
                        SubnetId=subnet_id, Ipv6CidrBlock=subnet_ipv6_cidr
                    ),
                    is_write=True,
                )
            except ClientError as e:
                if e.response["Error"]["Code"] == "InvalidSubnet.Conflict":
                    try:
                        existing = self.describe_subnet_ipv6_cidr(subnet_id)
                        self._logger.debug(
                            "IPv6 CIDR already associated after conflict: subnet=%s cidr=%s",
                            subnet_id, existing,
                        )
                    except Exception:
                        self._logger.debug(
                            "IPv6 CIDR conflict for subnet=%s but could not retrieve existing CIDR",
                            subnet_id,
                        )
                    return subnet_id, found_az
                raise
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

            try:
                self._execute_ec2_call(
                    operation_name="associate_subnet_ipv6",
                    func=lambda: self._ec2_client.associate_subnet_cidr_block(
                        SubnetId=subnet_id, Ipv6CidrBlock=subnet_ipv6_cidr
                    ),
                    is_write=True,
                )
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code == "InvalidSubnet.Conflict":
                    self._logger.debug(
                        "IPv6 CIDR already associated after conflict during subnet creation: subnet=%s",
                        subnet_id,
                    )
                else:
                    self._logger.error(
                        "associate_subnet_ipv6 failed with non-conflict error: code=%s subnet=%s",
                        error_code,
                        subnet_id,
                    )
                    raise
            except Exception as e:
                self._logger.error(
                    "associate_subnet_ipv6 failed with unexpected exception: type=%s subnet=%s",
                    type(e).__name__,
                    subnet_id,
                )
                raise

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

    # ----------------------------------------------------------- Internet Gateway
    def ensure_internet_gateway(self, vpc_id: str) -> str:
        """Find or create an Internet Gateway attached to the VPC."""
        response = self._execute_ec2_call(
            operation_name="describe_igw",
            func=lambda: self._ec2_client.describe_internet_gateways(
                Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
            ),
        )
        igws = response.get("InternetGateways", [])
        if igws:
            return igws[0]["InternetGatewayId"]
        response = self._execute_ec2_call(
            operation_name="create_igw",
            func=lambda: self._ec2_client.create_internet_gateway(),
            is_write=True,
        )
        igw_id = response.get("InternetGateway", {}).get("InternetGatewayId")
        if not igw_id:
            raise RuntimeError("AWS create_internet_gateway returned no InternetGatewayId")
        self._execute_ec2_call(
            operation_name="attach_igw",
            func=lambda: self._ec2_client.attach_internet_gateway(
                InternetGatewayId=igw_id, VpcId=vpc_id
            ),
            is_write=True,
        )
        return igw_id

    # ------------------------------------------------------------- Route Tables
    def find_or_create_public_route_table(self, vpc_id: str, subnet_id: str) -> str:
        """Find a route table associated with the subnet; if none, associate with main route table and add IGW route."""
        rt_response = self._execute_ec2_call(
            operation_name="describe_rt_for_subnet",
            func=lambda: self._ec2_client.describe_route_tables(
                Filters=[
                    {"Name": "association.subnet-id", "Values": [subnet_id]},
                    {"Name": "vpc-id", "Values": [vpc_id]},
                ]
            ),
        )
        route_tables = rt_response.get("RouteTables", [])
        if route_tables:
            return route_tables[0]["RouteTableId"]

        main_rt_response = self._execute_ec2_call(
            operation_name="describe_main_rt",
            func=lambda: self._ec2_client.describe_route_tables(
                Filters=[
                    {"Name": "association.main", "Values": ["true"]},
                    {"Name": "vpc-id", "Values": [vpc_id]},
                ]
            ),
        )
        main_tables = main_rt_response.get("RouteTables", [])
        if not main_tables:
            raise RuntimeError(f"No main route table found for VPC {vpc_id}")
        rt_id = main_tables[0]["RouteTableId"]
        self._execute_ec2_call(
            operation_name="associate_subnet_rt",
            func=lambda: self._ec2_client.associate_route_table(
                RouteTableId=rt_id, SubnetId=subnet_id
            ),
            is_write=True,
        )
        return rt_id

    def ensure_igw_route(self, route_table_id: str) -> None:
        """Add 0.0.0.0/0 -> IGW route if not already present."""
        response = self._execute_ec2_call(
            operation_name="describe_routes",
            func=lambda: self._ec2_client.describe_route_tables(
                RouteTableIds=[route_table_id]
            ),
        )
        routes = response["RouteTables"][0]["Routes"]
        for route in routes:
            if route.get("DestinationCidrBlock") == "0.0.0.0/0" and route.get("GatewayId"):
                return
        igw_id = self._get_igw_for_vpc(route_table_id)
        self._execute_ec2_call(
            operation_name="create_igw_route",
            func=lambda: self._ec2_client.create_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock="0.0.0.0/0",
                GatewayId=igw_id,
            ),
            is_write=True,
        )

    def _get_igw_for_vpc(self, route_table_id: str) -> str:
        """Look up the IGW attached to the VPC owning this route table."""
        response = self._execute_ec2_call(
            operation_name="get_rt_vpc",
            func=lambda: self._ec2_client.describe_route_tables(RouteTableIds=[route_table_id]),
        )
        vpc_id = response["RouteTables"][0]["VpcId"]
        igw_response = self._execute_ec2_call(
            operation_name="find_igw",
            func=lambda: self._ec2_client.describe_internet_gateways(
                Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
            ),
        )
        igws = igw_response.get("InternetGateways", [])
        if not igws:
            raise RuntimeError(f"No Internet Gateway found for VPC {vpc_id}")
        return igws[0]["InternetGatewayId"]

    # ------------------------------------------------------------ NAT Gateway
    def find_or_create_nat_gateway(
        self,
        subnet_id: str,
        eip_allocation_id: str,
    ) -> str:
        """Create a NAT Gateway in the public subnet; reuses if already exists."""
        response = self._execute_ec2_call(
            operation_name="describe_nat",
            func=lambda: self._ec2_client.describe_nat_gateways(
                Filters=[{"Name": "subnet-id", "Values": [subnet_id]}]
            ),
        )
        nats = response.get("NatGateways", [])
        for nat in nats:
            if nat.get("State") not in ("deleted", "deleting"):
                return nat["NatGatewayId"]
        response = self._execute_ec2_call(
            operation_name="create_nat",
            func=lambda: self._ec2_client.create_nat_gateway(
                SubnetId=subnet_id,
                ConnectivityType="public",
                AllocationId=eip_allocation_id,
            ),
            is_write=True,
        )
        nat_id = response.get("NatGateway", {}).get("NatGatewayId")
        if not nat_id:
            raise RuntimeError("AWS create_nat_gateway returned no NatGatewayId")
        self._wait_for_nat_available(nat_id)
        return nat_id

    def _wait_for_nat_available(self, nat_id: str) -> None:
        import time

        for _ in range(30):
            response = self._execute_ec2_call(
                operation_name="wait_nat",
                func=lambda: self._ec2_client.describe_nat_gateways(NatGatewayIds=[nat_id]),
            )
            state = response["NatGateways"][0]["State"]
            if state == "available":
                return
            if state in ("failed", "deleting"):
                raise RuntimeError(f"NAT Gateway {nat_id} entered state: {state}")
            time.sleep(5)
        raise RuntimeError(f"NAT Gateway {nat_id} did not become available in time")

    def allocate_elastic_ip(self) -> str:
        """Allocate a new Elastic IP; returns AllocationId."""
        response = self._execute_ec2_call(
            operation_name="allocate_eip",
            func=lambda: self._ec2_client.allocate_address(Domain="vpc"),
            is_write=True,
        )
        alloc_id = response.get("AllocationId")
        if not alloc_id:
            raise RuntimeError("AWS allocate_address returned no AllocationId")
        return alloc_id

    def release_elastic_ip(self, allocation_id: str) -> None:
        try:
            self._execute_ec2_call(
                operation_name="release_eip",
                func=lambda: self._ec2_client.release_address(AllocationId=allocation_id),
                is_write=True,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in (
                "InvalidAllocationID.NotFound",
                "AuthFailure",
            ):
                raise

    def associate_eip_with_nat(self, nat_gateway_id: str, allocation_id: str) -> None:
        """Wait for NAT to be available, then associate EIP with it."""
        self._wait_for_nat_available(nat_gateway_id)
        try:
            self._execute_ec2_call(
                operation_name="assoc_eip_nat",
                func=lambda: self._ec2_client.associate_address(
                    AllocationId=allocation_id,
                    NatGatewayId=nat_gateway_id,
                ),
                is_write=True,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "InvalidAssociationID.NotFound":
                raise

    def ensure_nat_route(self, route_table_id: str, nat_gateway_id: str) -> None:
        """Add 0.0.0.0/0 -> NAT Gateway route if not already present."""
        response = self._execute_ec2_call(
            operation_name="describe_nat_routes",
            func=lambda: self._ec2_client.describe_route_tables(RouteTableIds=[route_table_id]),
        )
        routes = response["RouteTables"][0]["Routes"]
        for route in routes:
            if route.get("DestinationCidrBlock") == "0.0.0.0/0" and route.get("NatGatewayId"):
                return
        self._execute_ec2_call(
            operation_name="create_nat_route",
            func=lambda: self._ec2_client.create_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock="0.0.0.0/0",
                NatGatewayId=nat_gateway_id,
            ),
            is_write=True,
        )
