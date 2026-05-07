from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import ipaddress
import logging
import re
import socket
from typing import Literal

from infrastructure.self_hosted.ssh_client import RemoteCommandResult, SelfHostedSshClientError, SelfHostedSshConfig
from models.aws_credentials import AwsCredentials
from services.asset_selector_service import (
    AssetSelectionError,
    AssetSelectionRequest,
    AssetSelectionResult,
    AssetSelectorService,
)
from services.node_registry_service import NodeRegistryService, RegisterNodeRequest
from services.provisioning_models import DnsRecordSnapshot, ProvisionRequest
from services.ready_callback_service import ReadyCallbackRegistration, ReadyCallbackService
from services.runtime_service import RuntimeContext
from utils.template_engine import UserDataRenderRequest, V2bxCertConfig

CACHED_ARTIFACT_VERSION_PATH = "/var/www/shadowfleet-artifacts/.v2bx_version"


def _load_cached_v2bx_version(config_app) -> str | None:
    """Load V2bx version from daemon's artifact cache without importing daemon module."""
    from pathlib import Path

    version_file = Path(config_app.artifact_cache_dir) / ".v2bx_version"
    if not version_file.exists():
        return None
    return version_file.read_text().strip() or None


class ProvisionerServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProvisioningDependencies:
    runtime_context: RuntimeContext
    logger: logging.Logger
    asset_selector: AssetSelectorService
    node_registry: NodeRegistryService
    ready_callback_service: ReadyCallbackService


def validate_request(request: ProvisionRequest) -> None:
    if not request.node_name or not request.node_name.strip():
        raise ValueError("node_name must not be empty")
    if not request.port or not request.port.strip():
        raise ValueError("port must not be empty")
    # self-hosted: server_port <= 0 means auto-allocate (40000-60000)
    if request.asset_type != "self_hosted" and request.server_port <= 0:
        raise ValueError("server_port must be greater than 0")
    if request.rate <= Decimal("0"):
        raise ValueError("rate must be greater than 0")
    if request.asset_type == "aws" and request.protocol_type == "Hysteria2":
        raise ProvisionerServiceError("Hysteria2 is not allowed on AWS assets")
    if request.require_cdn_proxy and request.protocol_type == "AnyTLS":
        raise ProvisionerServiceError("AnyTLS supports DNS linkage but must not use CDN proxy")


def select_asset(
    asset_selector: AssetSelectorService,
    request: ProvisionRequest,
) -> AssetSelectionResult:
    try:
        return asset_selector.select_asset(
            AssetSelectionRequest(
                protocol_type=request.protocol_type,
                asset_type=request.asset_type,
                region=request.region,
                require_cdn_proxy=request.require_cdn_proxy,
            )
        )
    except AssetSelectionError as exc:
        raise ProvisionerServiceError("Failed to select a provisioning asset") from exc


def build_register_node_request(request: ProvisionRequest) -> RegisterNodeRequest:
    host = request.domain_name or request.node_name
    return RegisterNodeRequest(
        node_type=request.protocol_type,
        node_name=request.node_name,
        host=host,
        port=request.port,
        server_port=request.server_port,
        rate=request.rate,
        code=request.code,
        parent_id=request.parent_id,
        group_ids=request.group_ids,
        route_ids=request.route_ids,
        tags=request.tags,
        protocol_settings=request.protocol_settings,
        show=request.show,
        sort=request.sort,
        rate_time_enable=request.rate_time_enable,
        rate_time_ranges=request.rate_time_ranges,
        status_reason=request.status_reason,
        domain_name=request.domain_name,
    )


def build_user_data_render_request(
    runtime_context: RuntimeContext,
    request: ProvisionRequest,
    selection_result: AssetSelectionResult,
    xboard_node_id: int,
    ready_callback_registration: ReadyCallbackRegistration,
    effective_domain_name: str | None,
    nginx_internal_port: int | None = None,
) -> UserDataRenderRequest:
    xboard_cfg = runtime_context.config.xboard
    if xboard_cfg is None or xboard_cfg.v2bx_api_host is None or xboard_cfg.v2bx_api_key is None:
        raise ProvisionerServiceError(
            "xboard.v2bx_api_host and xboard.v2bx_api_key must be configured in config.yaml"
        )
    cert_config = V2bxCertConfig(
        cert_mode="dns",
        cert_domain=require_non_empty(effective_domain_name, "domain_name"),
        email=runtime_context.config.cloudflare.acme_email,
        provider="cloudflare",
        dns_env={"CF_DNS_API_TOKEN": runtime_context.config.cloudflare.api_token},
    )
    server_host = effective_domain_name or (
        selection_result.ssh_host if selection_result.asset_type == "self_hosted" else request.node_name
    )
    return UserDataRenderRequest(
        asset_provider=selection_result.asset_type,
        protocol_type=request.protocol_type,
        node_name=request.node_name,
        xboard_api_host=xboard_cfg.v2bx_api_host,
        xboard_api_key=xboard_cfg.v2bx_api_key,
        xboard_node_id=xboard_node_id,
        server_host=require_non_empty(server_host, "server_host"),
        correlation_id=runtime_context.correlation_id,
        ready_callback_url=ready_callback_registration.callback_url,
        ready_callback_token=ready_callback_registration.callback_token,
        domain_name=effective_domain_name,
        enable_cdn_proxy=request.require_cdn_proxy and effective_domain_name is not None,
        cert_config=cert_config,
        listen_port=request.server_port,
        nginx_internal_port=nginx_internal_port if nginx_internal_port is not None else 5105,
        daemon_artifact_base_url=runtime_context.daemon_artifact_base_url,
        cached_v2bx_version=_load_cached_v2bx_version(runtime_context.config.app),
        daemon_ipv6=runtime_context.daemon_ipv6,
    )


def build_aws_credential(selection_result: AssetSelectionResult) -> AwsCredentials:
    return AwsCredentials(
        account_id=require_non_empty(selection_result.aws_account_id, "aws_account_id"),
        access_key=require_non_empty(selection_result.aws_access_key, "aws_access_key"),
        secret_key=require_non_empty(selection_result.aws_secret_key, "aws_secret_key"),
        region=require_non_empty(selection_result.region, "region"),
    )


def resolve_effective_domain_name(
    runtime_context: RuntimeContext,
    request: ProvisionRequest,
    selection_result: AssetSelectionResult,
    xboard_node_id: int,
) -> str | None:
    if request.domain_name is not None and request.domain_name.strip():
        return request.domain_name.strip()
    if not selection_result.requires_dns_record:
        return None

    cloudflare_config = runtime_context.config.cloudflare
    if not cloudflare_config.enabled:
        raise ProvisionerServiceError(
            "Cloudflare must be enabled when protocol requires automatic domain allocation"
        )
    if cloudflare_config.root_domain is None:
        raise ProvisionerServiceError(
            "cloudflare.root_domain is required for automatic subdomain allocation"
        )

    protocol_slug = re.sub(r"[^a-z0-9]+", "-", request.protocol_type.lower()).strip("-")
    region_slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        (selection_result.region or "global").lower(),
    ).strip("-")
    prefix_slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        cloudflare_config.auto_subdomain_prefix.lower(),
    ).strip("-")
    label = f"{prefix_slug}-{protocol_slug}-{region_slug}-{xboard_node_id}"
    return f"{label[:63].strip('-')}.{cloudflare_config.root_domain}"


def build_self_hosted_ssh_config(selection_result: AssetSelectionResult) -> SelfHostedSshConfig:
    return SelfHostedSshConfig(
        host=require_non_empty(selection_result.ssh_host, "ssh_host"),
        port=selection_result.ssh_port or 22,
        username=require_non_empty(selection_result.ssh_username, "ssh_username"),
        password=selection_result.ssh_password,
        private_key=selection_result.ssh_private_key,
    )


def resolve_self_hosted_ip_addresses(host: str) -> tuple[str | None, str | None]:
    normalized_host = host.strip()
    if not normalized_host:
        raise ProvisionerServiceError("ssh_host must not be empty for self-hosted provisioning")

    try:
        ip_object = ipaddress.ip_address(normalized_host)
    except ValueError:
        ip_object = None

    if ip_object is not None:
        if ip_object.version == 4:
            return str(ip_object), None
        return None, str(ip_object)

    try:
        address_infos = socket.getaddrinfo(normalized_host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ProvisionerServiceError(
            f"Failed to resolve self-hosted asset address: host={normalized_host}"
        ) from exc

    ipv4_address: str | None = None
    ipv6_address: str | None = None
    for family, _, _, _, sockaddr in address_infos:
        if family == socket.AF_INET and ipv4_address is None:
            ipv4_address = str(sockaddr[0])
        elif family == socket.AF_INET6 and ipv6_address is None:
            ipv6_address = str(sockaddr[0])

    if ipv4_address is None and ipv6_address is None:
        raise ProvisionerServiceError(
            f"No routable IP address resolved for self-hosted asset: host={normalized_host}"
        )
    return ipv4_address, ipv6_address


def build_remote_execution_payload(
    stage: str,
    command_result: RemoteCommandResult | None = None,
    error: SelfHostedSshClientError | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"stage": stage}
    if command_result is not None:
        payload["exit_status"] = command_result.exit_status
        payload["stdout"] = truncate_text(command_result.stdout)
        payload["stderr"] = truncate_text(command_result.stderr)
    if error is not None:
        payload["error_message"] = str(error)
        payload["error_stage"] = error.stage
        if error.exit_status is not None:
            payload["error_exit_status"] = error.exit_status
        if error.stdout is not None:
            payload["error_stdout"] = truncate_text(error.stdout)
        if error.stderr is not None:
            payload["error_stderr"] = truncate_text(error.stderr)
    return payload


def truncate_text(value: str | None, limit: int = 8000) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n...[truncated]..."


def require_non_empty(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise ProvisionerServiceError(f"{field_name} is required for provisioning")
    return value.strip()


def resolve_default_instance_spec(
    runtime_context: RuntimeContext,
    aws_credential: AwsCredentials,
    selection_result_instance_type: str | None,
    correlation_id: str,
) -> str:
    """
    Resolve instance type for AWS provisioning when not explicitly specified.

    Priority:
      1. User-specified instance_type (protocol config or asset default) -> use as-is
      2. Dynamic fallback: query available arm64 types in region, pick best match:
         - Prefer 2 vCPU + ~2 GB; fallback to 2 vCPU + ~4 GB
         - Within same spec: c6g > m6g > t4g > other series
    """
    if selection_result_instance_type is not None and selection_result_instance_type.strip():
        return selection_result_instance_type.strip()

    from infrastructure.aws.ec2_client import EC2Client

    ec2_client = EC2Client(runtime_context=runtime_context, aws_credential=aws_credential)
    specs = ec2_client.list_arm64_instance_types_with_specs()

    two_core_specs = [s for s in specs if s.vcpu == 2]
    if not two_core_specs:
        raise ProvisionerServiceError(
            f"[{correlation_id}] No arm64 instance with 2 vCPU available in region {aws_credential.region}. "
            "Please specify an instance type manually."
        )

    # Priority: 2GB -> 4GB -> 8GB -> 1GB (fallback)
    two_gb = [s for s in two_core_specs if abs(s.memory_gb - 2.0) < 0.5]
    four_gb = [s for s in two_core_specs if abs(s.memory_gb - 4.0) < 0.5]
    eight_gb = [s for s in two_core_specs if abs(s.memory_gb - 8.0) < 0.5]
    one_gb = [s for s in two_core_specs if abs(s.memory_gb - 1.0) < 0.5]

    for candidates in [two_gb, four_gb, eight_gb, one_gb]:
        if candidates:
            best = candidates[0]
            break
    else:
        raise ProvisionerServiceError(
            f"[{correlation_id}] No suitable 2 vCPU arm64 instance in region {aws_credential.region}. "
            "Please specify an instance type manually."
        )

    # Determine priority tier for logging
    if abs(best.memory_gb - 2.0) < 0.5:
        tier = "2GB"
    elif abs(best.memory_gb - 4.0) < 0.5:
        tier = "4GB"
    elif abs(best.memory_gb - 8.0) < 0.5:
        tier = "8GB"
    else:
        tier = "1GB"

    runtime_context.logger.info(
        "[%s] No instance_type specified, auto-resolved to %s (vcpu=%d, memory=%.1fGB, series=%s, tier=%s)",
        correlation_id,
        best.instance_type,
        best.vcpu,
        best.memory_gb,
        best.series_name,
        tier,
    )
    return best.instance_type


def require_task_id(request: ProvisionRequest) -> int:
    if request.provisioning_task_id is None or request.provisioning_task_id <= 0:
        raise ProvisionerServiceError(
            "provisioning_task_id is required for phone-home ready confirmation"
        )
    return request.provisioning_task_id


def build_dns_snapshot(
    record_type: Literal["A", "AAAA"],
    existing_record: dict[str, object] | None,
) -> DnsRecordSnapshot:
    if existing_record is None:
        return DnsRecordSnapshot(
            record_type=record_type,
            record_id=None,
            existed=False,
            content=None,
            proxied=False,
        )
    return DnsRecordSnapshot(
        record_type=record_type,
        record_id=str(existing_record["id"]) if existing_record.get("id") else None,
        existed=True,
        content=str(existing_record["content"]) if existing_record.get("content") is not None else None,
        proxied=bool(existing_record.get("proxied", False)),
    )
