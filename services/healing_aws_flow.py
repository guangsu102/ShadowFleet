from __future__ import annotations

from database.asset_repo import AssetRepo
from database.state_repo import FleetNodeEventCreateRequest, FleetNodeRecord, StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.aws.ec2_client import EC2Client
from infrastructure.cloudflare.cf_client import CFClient
from models.aws_credentials import AwsCredentials
from services.healing_models import HealRequest, HealResult, HealerServiceError
from services.healing_notifier import notify_healing_success
from services.healing_support import get_duration_ms
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


def heal_aws_node(
    *,
    runtime_context: RuntimeContext,
    asset_repo: AssetRepo,
    state_repo: StateRepo,
    xboard_repo: XboardRepo,
    node_record: FleetNodeRecord,
    request: HealRequest,
    started_monotonic: float,
) -> HealResult:
    if node_record.aws_account_id is None or node_record.aws_region is None:
        raise HealerServiceError("AWS node runtime metadata is incomplete")
    if node_record.domain_name is None:
        raise HealerServiceError("AWS node domain_name is required for IPv6 healing")

    asset_record = _resolve_aws_asset(
        asset_repo=asset_repo,
        aws_account_id=node_record.aws_account_id,
        aws_region=node_record.aws_region,
    )
    ec2_client = EC2Client(
        runtime_context=runtime_context,
        aws_credential=AwsCredentials(
            account_id=node_record.aws_account_id,
            access_key=asset_record.aws_access_key,
            secret_key=asset_record.aws_secret_key,
            region=node_record.aws_region,
        ),
    )
    old_ipv6_address, new_ipv6_address = ec2_client.rotate_instance_ipv6(
        instance_id=node_record.aws_instance_id,
        subnet_id=node_record.aws_subnet_id,
    )

    if not runtime_context.config.cloudflare.enabled:
        raise HealerServiceError("Cloudflare must be enabled for AWS IPv6 healing")
    cf_client = CFClient(runtime_context)
    cloudflare_record_id = cf_client.sync_aaaa_record(
        record_name=node_record.domain_name,
        ipv6_address=new_ipv6_address,
        proxied=False,
    )

    xboard_repo.update_node_host(node_record.xboard_node_id, node_record.domain_name)
    xboard_repo.mark_node_online(node_record.xboard_node_id)
    state_repo.update_node_runtime_metadata(
        xboard_node_id=node_record.xboard_node_id,
        cloudflare_record_id=cloudflare_record_id,
        domain_name=node_record.domain_name,
        ipv6_address=new_ipv6_address,
        last_known_host=node_record.domain_name,
    )
    state_repo.update_node_status(
        xboard_node_id=node_record.xboard_node_id,
        status="online",
        status_reason=None,
        last_error=None,
    )
    duration_ms = get_duration_ms(started_monotonic)
    state_repo.create_event(
        FleetNodeEventCreateRequest(
            node_id=node_record.id,
            xboard_node_id=node_record.xboard_node_id,
            event_type="healing_completed",
            correlation_id=runtime_context.correlation_id,
            from_status="healing",
            to_status="online",
            message="AWS IPv6 hot-swap healing completed.",
            payload={
                "strategy": "aws_ipv6_rotate",
                "reason": request.reason,
                "source": request.source,
                "old_ipv6_address": old_ipv6_address,
                "new_ipv6_address": new_ipv6_address,
                "domain_name": node_record.domain_name,
                "cloudflare_record_id": cloudflare_record_id,
                "duration_ms": duration_ms,
                "measurement_payload": request.measurement_payload,
            },
        )
    )

    set_event_type("healing_completed")
    result = HealResult(
        xboard_node_id=node_record.xboard_node_id,
        node_name=node_record.node_name,
        node_type=node_record.node_type,
        asset_type="aws",
        strategy="aws_ipv6_rotate",
        success=True,
        old_ipv6_address=old_ipv6_address,
        new_ipv6_address=new_ipv6_address,
        domain_name=node_record.domain_name,
        cloudflare_record_id=cloudflare_record_id,
        proxied_enabled=False,
        duration_ms=duration_ms,
        message="AWS IPv6 热切换自愈成功",
        correlation_id=runtime_context.correlation_id,
    )
    notify_healing_success(runtime_context, result)
    return result


def _resolve_aws_asset(
    *,
    asset_repo: AssetRepo,
    aws_account_id: str,
    aws_region: str,
):
    assets = asset_repo.list_assets_by_aws_account_id(aws_account_id)
    for asset in assets:
        if asset.region == aws_region:
            if asset.aws_access_key is None or asset.aws_secret_key is None:
                raise HealerServiceError(
                    f"AWS asset credentials are missing for aws_account_id={aws_account_id}"
                )
            return asset
    if not assets:
        raise HealerServiceError(f"AWS asset not found for aws_account_id={aws_account_id}")
    fallback_asset = assets[0]
    if fallback_asset.aws_access_key is None or fallback_asset.aws_secret_key is None:
        raise HealerServiceError(
            f"AWS asset credentials are missing for aws_account_id={aws_account_id}"
        )
    return fallback_asset
