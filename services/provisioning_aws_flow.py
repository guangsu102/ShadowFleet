from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from database.asset_repo import AssetAllocationCreateRequest, AssetEventCreateRequest, AssetRepo
from infrastructure.aws.ec2_client import EC2Client, Ec2LaunchRequest
from services.key_pair_manager import KeyPairManager
from services.provisioning_dns_service import sync_dns_records
from services.provisioning_failure_handler import handle_provision_failure
from services.provisioning_models import DnsSyncResult, ProvisionRequest, ProvisionResult
from services.provisioning_notifier import notify_success
from services.provisioning_support import (
    ProvisioningDependencies,
    build_aws_credential,
    build_register_node_request,
    build_user_data_render_request,
    require_non_empty,
    require_task_id,
    resolve_default_instance_spec,
    resolve_effective_domain_name,
    select_asset,
)
from utils.logger import set_event_type
from utils.template_engine import render_user_data


@dataclass
class _PublicNetworkResources:
    """Resources created for outbound public internet access from private subnet."""

    subnet_id: str
    route_table_id: str
    nat_gateway_id: str | None
    eip_allocation_id: str | None


def _is_daemon_reachable(runtime_context: ProvisioningDependencies) -> bool:
    """Return True if Daemon has a publicly reachable artifact base URL (IPv6 or override)."""
    return bool(runtime_context.runtime_context.daemon_artifact_base_url)


def provision_aws_node(
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
) -> ProvisionResult:
    set_event_type("provisioning_started")
    dependencies.logger.info(
        "Starting AWS provisioning for node=%s protocol=%s region=%s",
        request.node_name,
        request.protocol_type,
        request.region,
    )

    daemon_reachable = _is_daemon_reachable(dependencies)
    dependencies.logger.info(
        "Daemon reachability check: daemon_artifact_base_url=%s -> reachable=%s",
        dependencies.runtime_context.daemon_artifact_base_url,
        daemon_reachable,
    )

    selection_result = select_asset(dependencies.asset_selector, request)
    asset_repo.create_asset_event(
        AssetEventCreateRequest(
            asset_id=selection_result.asset_id,
            event_type="provisioning_selected",
            correlation_id=dependencies.runtime_context.correlation_id,
            message="Asset selected for provisioning.",
            payload={
                "protocol_type": request.protocol_type,
                "node_name": request.node_name,
                "region": selection_result.region,
            },
        )
    )

    registered_node_result = None
    dns_sync_result: DnsSyncResult | None = None
    ready_callback_registration = None
    cloudflare_record_id: str | None = None
    launch_result = None
    ec2_client: EC2Client | None = None
    effective_domain_name: str | None = None
    public_net_resources: _PublicNetworkResources | None = None
    associate_public_ip = False

    try:
        registered_node_result = dependencies.node_registry.register_node(
            build_register_node_request(dependencies.runtime_context, request)
        )

        # 自动配置节点（生成节点ID、配置协议参数）
        from services.node_auto_config_service import NodeAutoConfigService
        auto_config_service = NodeAutoConfigService(dependencies.runtime_context)
        auto_config_service.auto_configure_node(
            xboard_node_id=registered_node_result.xboard_node_id,
            protocol_type=request.protocol_type,
            protocol_settings=request.protocol_settings,
            sni_domain=getattr(request, 'sni_domain', None),
            reality_private_key=getattr(request, 'reality_private_key', None),
            reality_public_key=getattr(request, 'reality_public_key', None),
        )

        effective_domain_name = resolve_effective_domain_name(
            runtime_context=dependencies.runtime_context,
            request=request,
            selection_result=selection_result,
            xboard_node_id=registered_node_result.xboard_node_id,
        )
        ready_callback_registration = dependencies.ready_callback_service.register_callback(
            task_id=require_task_id(request),
            xboard_node_id=registered_node_result.xboard_node_id,
            correlation_id=dependencies.runtime_context.correlation_id,
        )
        rendered_user_data = render_user_data(
            build_user_data_render_request(
                runtime_context=dependencies.runtime_context,
                request=request,
                selection_result=selection_result,
                xboard_node_id=registered_node_result.xboard_node_id,
                ready_callback_registration=ready_callback_registration,
                effective_domain_name=effective_domain_name,
            )
        )
        aws_credential = build_aws_credential(selection_result)
        ec2_client = EC2Client(
            runtime_context=dependencies.runtime_context,
            aws_credential=aws_credential,
        )
        key_pair_manager = KeyPairManager(dependencies.runtime_context)
        key_name = key_pair_manager.ensure_key_pair_for_account(
            aws_credential=aws_credential,
            ec2_client=ec2_client._ec2_client,
        )
        effective_instance_type = resolve_default_instance_spec(
            runtime_context=dependencies.runtime_context,
            aws_credential=aws_credential,
            selection_result_instance_type=selection_result.instance_type,
            correlation_id=dependencies.runtime_context.correlation_id,
        )

        # Daemon unreachable -> instance needs a public IP to reach GitHub / Daemon.
        if not daemon_reachable:
            public_net_resources = _ensure_public_network_access(
                ec2_client=ec2_client,
                subnet_id=require_non_empty(selection_result.subnet_id, "subnet_id"),
                dependencies=dependencies,
            )
            associate_public_ip = True

        launch_result = ec2_client.launch_ipv6_instance(
            Ec2LaunchRequest(
                image_id=require_non_empty(selection_result.ami_id, "ami_id"),
                instance_type=effective_instance_type,
                subnet_id=require_non_empty(selection_result.subnet_id, "subnet_id"),
                security_group_id=require_non_empty(
                    selection_result.security_group_id,
                    "security_group_id",
                ),
                user_data=rendered_user_data.user_data,
                key_name=key_name,
                instance_name=request.node_name,
                associate_public_ip=associate_public_ip,
            )
        )
        ipv6_address = launch_result.ipv6_addresses[0] if launch_result.ipv6_addresses else None
        ipv4_address = launch_result.ipv4_address

        if selection_result.requires_dns_record:
            dns_sync_result = sync_dns_records(
                runtime_context=dependencies.runtime_context,
                protocol_type=request.protocol_type,
                domain_name=require_non_empty(effective_domain_name, "domain_name"),
                selection_result=selection_result,
                require_cdn_proxy=request.require_cdn_proxy,
                ipv4_address=ipv4_address,
                ipv6_address=ipv6_address,
            )
            cloudflare_record_id = dns_sync_result.primary_record_id

        dependencies.ready_callback_service.wait_for_ready_callback(require_task_id(request))
        online_result = dependencies.node_registry.mark_node_online(
            xboard_node_id=registered_node_result.xboard_node_id,
            host=effective_domain_name or request.node_name,
            aws_account_id=selection_result.aws_account_id,
            aws_region=selection_result.region,
            aws_instance_id=launch_result.instance_id,
            aws_subnet_id=launch_result.subnet_id,
            aws_security_group_id=selection_result.security_group_id,
            instance_type=effective_instance_type,
            cloudflare_record_id=cloudflare_record_id,
            domain_name=effective_domain_name,
            ipv4_address=ipv4_address,
            ipv6_address=ipv6_address,
            status_reason=request.status_reason,
        )
        dependencies.ready_callback_service.mark_callback_completed(require_task_id(request))
        asset_repo.create_allocation(
            AssetAllocationCreateRequest(
                asset_id=selection_result.asset_id,
                fleet_node_id=online_result.local_node_id,
                xboard_node_id=online_result.xboard_node_id,
                protocol_type=request.protocol_type,
            )
        )
        asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=selection_result.asset_id,
                event_type="provisioning_succeeded",
                correlation_id=dependencies.runtime_context.correlation_id,
                message="Provisioning completed successfully.",
                payload={
                    "xboard_node_id": online_result.xboard_node_id,
                    "instance_id": launch_result.instance_id,
                    "ipv4_address": ipv4_address,
                    "ipv6_address": ipv6_address,
                    "domain_name": effective_domain_name,
                    "cloudflare_record_id": cloudflare_record_id,
                    "cloudflare_a_record_id": (
                        dns_sync_result.a_record_id if dns_sync_result is not None else None
                    ),
                    "cloudflare_aaaa_record_id": (
                        dns_sync_result.aaaa_record_id if dns_sync_result is not None else None
                    ),
                },
            )
        )
        notify_success(
            runtime_context=dependencies.runtime_context,
            request=request,
            selection_result=selection_result,
            online_result=online_result,
            instance_id=launch_result.instance_id,
            ipv6_address=ipv6_address,
            domain_name=effective_domain_name,
            cloudflare_record_id=cloudflare_record_id,
        )
        set_event_type("provisioning_completed")
        dependencies.logger.info(
            "Completed AWS provisioning xboard_node_id=%s instance_id=%s ipv4=%s ipv6=%s",
            online_result.xboard_node_id,
            launch_result.instance_id,
            ipv4_address,
            ipv6_address,
        )
        return ProvisionResult(
            local_node_id=online_result.local_node_id,
            xboard_node_id=online_result.xboard_node_id,
            asset_id=selection_result.asset_id,
            asset_type=selection_result.asset_type,
            protocol_type=request.protocol_type,
            node_name=request.node_name,
            status=online_result.status,
            aws_account_id=selection_result.aws_account_id,
            region=selection_result.region,
            instance_id=launch_result.instance_id,
            network_interface_id=launch_result.network_interface_id,
            ipv4_address=ipv4_address,
            ipv6_address=ipv6_address,
            domain_name=effective_domain_name,
            cloudflare_record_id=cloudflare_record_id,
            cloudflare_a_record_id=(
                dns_sync_result.a_record_id if dns_sync_result is not None else None
            ),
            cloudflare_aaaa_record_id=(
                dns_sync_result.aaaa_record_id if dns_sync_result is not None else None
            ),
        )
    except Exception as exc:
        handle_provision_failure(
            runtime_context=dependencies.runtime_context,
            asset_repo=asset_repo,
            node_registry=dependencies.node_registry,
            logger_name=dependencies.logger.name,
            request=request,
            selection_result=selection_result,
            registered_node_result=registered_node_result,
            launch_result=launch_result,
            ec2_client=ec2_client,
            dns_sync_result=dns_sync_result,
            cloudflare_record_id=cloudflare_record_id,
            public_net_resources=public_net_resources,
            error=exc,
        )
        raise


def _ensure_public_network_access(
    ec2_client: EC2Client,
    subnet_id: str,
    dependencies: ProvisioningDependencies,
) -> _PublicNetworkResources:
    """
    Set up outbound internet access for the instance subnet.
    Creates an Internet Gateway, public route table entry, NAT Gateway + EIP
    so the instance (even without a public IP) can reach GitHub/Daemon.
    """
    logger = dependencies.logger.getChild("public_network_setup")
    vpc_client = ec2_client.vpc

    # 1. Find the VPC owning the subnet
    subnet_info = ec2_client._ec2_client.describe_subnets(SubnetIds=[subnet_id])["Subnets"][0]
    vpc_id = subnet_info["VpcId"]

    # 2. Ensure Internet Gateway is attached
    igw_id = vpc_client.ensure_internet_gateway(vpc_id)
    logger.info("Internet Gateway %s attached to VPC %s", igw_id, vpc_id)

    # 3. Get route table for the subnet
    rt_id = vpc_client.find_or_create_public_route_table(vpc_id, subnet_id)

    # 4. Add IGW route so instances WITH public IPs can reach the internet
    vpc_client.ensure_igw_route(rt_id)
    logger.info("IGW route added to route table %s", rt_id)

    # 5. For instances WITHOUT a public IP, set up NAT Gateway on this public subnet
    #    so they can still reach the internet outbound.
    existing_nat = vpc_client.find_existing_nat_gateway(subnet_id)
    if existing_nat:
        nat_gateway_id, eip_allocation_id = existing_nat
        logger.info("Reusing existing NAT Gateway %s in subnet %s", nat_gateway_id, subnet_id)
    else:
        eip_allocation_id = vpc_client.allocate_elastic_ip()
        nat_gateway_id = vpc_client.find_or_create_nat_gateway(subnet_id, eip_allocation_id)
        logger.info("NAT Gateway %s created in subnet %s", nat_gateway_id, subnet_id)

    # 6. NAT route is already on the main route table; add it if not present
    vpc_client.ensure_nat_route(rt_id, nat_gateway_id)
    logger.info("NAT route added to route table %s", rt_id)

    return _PublicNetworkResources(
        subnet_id=subnet_id,
        route_table_id=rt_id,
        nat_gateway_id=nat_gateway_id,
        eip_allocation_id=eip_allocation_id,
    )
