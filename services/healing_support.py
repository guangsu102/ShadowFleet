from __future__ import annotations

import time
from dataclasses import dataclass

from botocore.exceptions import ClientError

from database.state_models import FleetOperationLockRequest
from database.state_repo import FleetNodeRecord
from services.healing_models import AwsAccountBannedError, HealRequest, HealerServiceError, InstanceNotFoundError, ManualReviewRequiredError
from services.monitor_support import infer_node_asset_type

AWS_HEALABLE_PROTOCOLS = {"AnyTLS", "Trojan", "vless", "vmess"}
AZURE_HEALABLE_PROTOCOLS = AWS_HEALABLE_PROTOCOLS
DIGITALOCEAN_HEALABLE_PROTOCOLS = AWS_HEALABLE_PROTOCOLS
GCP_HEALABLE_PROTOCOLS = AWS_HEALABLE_PROTOCOLS
KAMATERA_HEALABLE_PROTOCOLS = AWS_HEALABLE_PROTOCOLS
VULTR_HEALABLE_PROTOCOLS = AWS_HEALABLE_PROTOCOLS
OCI_HEALABLE_PROTOCOLS = AWS_HEALABLE_PROTOCOLS
SELF_HOSTED_PROXY_PROTOCOLS = {"Trojan", "vless", "vmess"}
AWS_ACCOUNT_BANNED_ERROR_CODES = {
    "AuthFailure",
    "UnauthorizedOperation",
    "InvalidClientTokenId",
}
HEAL_LOCK_EXPIRY_SECONDS = 120
AZURE_HEAL_LOCK_EXPIRY_SECONDS = 2100
DIGITALOCEAN_HEAL_LOCK_EXPIRY_SECONDS = 3600


@dataclass(frozen=True)
class HealingContext:
    request: HealRequest
    node_record: FleetNodeRecord
    previous_status: str
    started_monotonic: float


def build_healing_context(request: HealRequest, node_record: FleetNodeRecord) -> HealingContext:
    if request.xboard_node_id <= 0:
        raise ValueError("xboard_node_id must be greater than 0")
    if not request.reason or not request.reason.strip():
        raise ValueError("reason must not be empty")
    return HealingContext(
        request=request,
        node_record=node_record,
        previous_status=node_record.status,
        started_monotonic=time.monotonic(),
    )


def determine_heal_strategy(node_record: FleetNodeRecord, request: HealRequest) -> str:
    if request.force_strategy is not None:
        asset_type = infer_node_asset_type(node_record)
        expected_strategy = {
            "aws": "aws_ipv6_rotate",
            "azure": "azure_ipv6_rotate",
            "digitalocean": "digitalocean_instance_replace",
            "gcp": "gcp_ipv4_rotate",
            "kamatera": "kamatera_instance_replace",
            "oci": "oci_ipv6_rotate",
            "vultr": "vultr_instance_replace",
            "self_hosted": "cloudflare_enable_proxy",
        }.get(asset_type)
        if request.force_strategy != expected_strategy:
            raise ManualReviewRequiredError(
                f"{asset_type} node does not support forced healing strategy: "
                f"{request.force_strategy}"
            )
        return request.force_strategy
    asset_type = infer_node_asset_type(node_record)
    if asset_type == "aws" and node_record.node_type in AWS_HEALABLE_PROTOCOLS:
        return "aws_ipv6_rotate"
    if asset_type == "azure" and node_record.node_type in AZURE_HEALABLE_PROTOCOLS:
        return "azure_ipv6_rotate"
    if (
        asset_type == "digitalocean"
        and node_record.node_type in DIGITALOCEAN_HEALABLE_PROTOCOLS
    ):
        return "digitalocean_instance_replace"
    if asset_type == "gcp" and node_record.node_type in GCP_HEALABLE_PROTOCOLS:
        return "gcp_ipv4_rotate"
    if asset_type == "kamatera" and node_record.node_type in KAMATERA_HEALABLE_PROTOCOLS:
        return "kamatera_instance_replace"
    if asset_type == "oci" and node_record.node_type in OCI_HEALABLE_PROTOCOLS:
        return "oci_ipv6_rotate"
    if asset_type == "vultr" and node_record.node_type in VULTR_HEALABLE_PROTOCOLS:
        return "vultr_instance_replace"
    if asset_type == "self_hosted" and node_record.node_type in SELF_HOSTED_PROXY_PROTOCOLS:
        return "cloudflare_enable_proxy"
    return "manual_review_required"


def ensure_aws_healing_eligible(node_record: FleetNodeRecord) -> None:
    if infer_node_asset_type(node_record) != "aws":
        raise ManualReviewRequiredError("AWS healing received a non-AWS node")
    if node_record.node_type not in AWS_HEALABLE_PROTOCOLS:
        raise ManualReviewRequiredError(
            f"AWS node type is not supported for IPv6 healing: {node_record.node_type}"
        )
    if node_record.aws_account_id is None:
        raise ManualReviewRequiredError("AWS node is missing aws_account_id")
    if node_record.aws_region is None:
        raise ManualReviewRequiredError("AWS node is missing aws_region")
    if node_record.aws_instance_id is None:
        raise ManualReviewRequiredError("AWS node is missing aws_instance_id")
    if node_record.aws_subnet_id is None:
        raise ManualReviewRequiredError("AWS node is missing aws_subnet_id")
    if node_record.domain_name is None or not node_record.domain_name.strip():
        raise ManualReviewRequiredError("AWS node is missing domain_name")


def ensure_azure_healing_eligible(node_record: FleetNodeRecord) -> None:
    if infer_node_asset_type(node_record) != "azure":
        raise ManualReviewRequiredError("Azure healing received a non-Azure node")
    if node_record.node_type not in AZURE_HEALABLE_PROTOCOLS:
        raise ManualReviewRequiredError(
            f"Azure node type is not supported for IPv6 healing: {node_record.node_type}"
        )
    if not node_record.aws_instance_id:
        raise ManualReviewRequiredError("Azure node is missing VM resource ID")
    if node_record.domain_name is None or not node_record.domain_name.strip():
        raise ManualReviewRequiredError("Azure node is missing domain_name")


def ensure_gcp_healing_eligible(node_record: FleetNodeRecord) -> None:
    if infer_node_asset_type(node_record) != "gcp":
        raise ManualReviewRequiredError("GCP healing received a non-GCP node")
    if node_record.node_type not in GCP_HEALABLE_PROTOCOLS:
        raise ManualReviewRequiredError(
            f"GCP node type is not supported for IPv4 healing: {node_record.node_type}"
        )
    if not node_record.aws_instance_id:
        raise ManualReviewRequiredError("GCP node is missing instance name")
    if not node_record.aws_region:
        raise ManualReviewRequiredError("GCP node is missing zone")
    if node_record.domain_name is None or not node_record.domain_name.strip():
        raise ManualReviewRequiredError("GCP node is missing domain_name")


def ensure_oci_healing_eligible(node_record: FleetNodeRecord) -> None:
    if infer_node_asset_type(node_record) != "oci":
        raise ManualReviewRequiredError("OCI healing received a non-OCI node")
    if node_record.node_type not in OCI_HEALABLE_PROTOCOLS:
        raise ManualReviewRequiredError(
            f"OCI node type is not supported for IPv6 healing: {node_record.node_type}"
        )
    if not node_record.aws_instance_id:
        raise ManualReviewRequiredError("OCI node is missing instance ID")
    if node_record.domain_name is None or not node_record.domain_name.strip():
        raise ManualReviewRequiredError("OCI node is missing domain_name")


def ensure_digitalocean_healing_eligible(node_record: FleetNodeRecord) -> None:
    if infer_node_asset_type(node_record) != "digitalocean":
        raise ManualReviewRequiredError(
            "DigitalOcean healing received a non-DigitalOcean node"
        )
    if node_record.node_type not in DIGITALOCEAN_HEALABLE_PROTOCOLS:
        raise ManualReviewRequiredError(
            "DigitalOcean node type is not supported for replacement healing: "
            f"{node_record.node_type}"
        )
    if not node_record.aws_instance_id:
        raise ManualReviewRequiredError("DigitalOcean node is missing Droplet ID")
    if node_record.domain_name is None or not node_record.domain_name.strip():
        raise ManualReviewRequiredError("DigitalOcean node is missing domain_name")


def ensure_vultr_healing_eligible(node_record: FleetNodeRecord) -> None:
    if infer_node_asset_type(node_record) != "vultr":
        raise ManualReviewRequiredError(
            "Vultr healing received a non-Vultr node"
        )
    if node_record.node_type not in VULTR_HEALABLE_PROTOCOLS:
        raise ManualReviewRequiredError(
            f"Vultr node type is not supported for replacement healing: "
            f"{node_record.node_type}"
        )
    if not node_record.aws_instance_id:
        raise ManualReviewRequiredError("Vultr node is missing instance ID")
    if node_record.domain_name is None or not node_record.domain_name.strip():
        raise ManualReviewRequiredError("Vultr node is missing domain_name")


def ensure_kamatera_healing_eligible(node_record: FleetNodeRecord) -> None:
    if infer_node_asset_type(node_record) != "kamatera":
        raise ManualReviewRequiredError("Kamatera healing received a non-Kamatera node")
    if node_record.node_type not in KAMATERA_HEALABLE_PROTOCOLS:
        raise ManualReviewRequiredError(
            f"Kamatera node type is not supported for replacement healing: {node_record.node_type}"
        )
    if not node_record.aws_instance_id:
        raise ManualReviewRequiredError("Kamatera node is missing server ID")
    if node_record.domain_name is None or not node_record.domain_name.strip():
        raise ManualReviewRequiredError("Kamatera node is missing domain_name")


def ensure_self_hosted_healing_eligible(node_record: FleetNodeRecord) -> None:
    asset_type = infer_node_asset_type(node_record)
    if asset_type not in {"self_hosted", "vultr", "azure"}:
        raise HealerServiceError("Cloudflare proxy healing received an unsupported node")
    if node_record.node_type not in SELF_HOSTED_PROXY_PROTOCOLS:
        raise ManualReviewRequiredError(
            f"{asset_type} node type is not supported for Cloudflare fallback: {node_record.node_type}"
        )
    if node_record.domain_name is None or not node_record.domain_name.strip():
        raise ManualReviewRequiredError(f"{asset_type} node is missing domain_name")


def build_heal_lock(
    node_record: FleetNodeRecord,
    correlation_id: str,
    strategy: str | None = None,
) -> FleetOperationLockRequest:
    if strategy == "digitalocean_instance_replace":
        expires_in_seconds = DIGITALOCEAN_HEAL_LOCK_EXPIRY_SECONDS
    elif strategy in {
        "azure_ipv6_rotate",
        "gcp_ipv4_rotate",
        "oci_ipv6_rotate",
        "vultr_instance_replace",
        "kamatera_instance_replace",
    }:
        expires_in_seconds = AZURE_HEAL_LOCK_EXPIRY_SECONDS
    else:
        expires_in_seconds = HEAL_LOCK_EXPIRY_SECONDS
    return FleetOperationLockRequest(
        lock_key=build_heal_lock_key(node_record.xboard_node_id),
        node_id=node_record.id,
        operation_type="healing",
        correlation_id=correlation_id,
        expires_in_seconds=expires_in_seconds,
    )


def build_heal_lock_key(xboard_node_id: int) -> str:
    return f"healing:{xboard_node_id}"


def build_failure_message(error: BaseException) -> str:
    message = str(error).strip()
    if message:
        return message
    return error.__class__.__name__


def get_duration_ms(started_monotonic: float) -> int:
    duration = int((time.monotonic() - started_monotonic) * 1000)
    return max(0, duration)  # Ensure non-negative


def classify_aws_client_error(error: BaseException, aws_account_id: str | None) -> BaseException:
    # Handle InstanceNotFoundError (ValueError from EC2 client)
    if isinstance(error, ValueError):
        error_message = str(error).strip()
        if "Instance not found" in error_message:
            # Extract instance_id from error message: "Instance not found: i-xxxxx"
            instance_id = None
            if ": " in error_message:
                instance_id = error_message.split(": ", 1)[1].strip()
            return InstanceNotFoundError(
                instance_id=instance_id or "unknown",
                aws_account_id=aws_account_id,
            )

        # Instance has no network interface (usually means instance is terminating or damaged)
        if "Instance has no network interface" in error_message:
            # Extract instance_id from error message: "Instance has no network interface: i-xxxxx"
            instance_id = None
            if ": " in error_message:
                instance_id = error_message.split(": ", 1)[1].strip()
            return InstanceNotFoundError(
                instance_id=instance_id or "unknown",
                aws_account_id=aws_account_id,
            )

    if not isinstance(error, ClientError) or aws_account_id is None:
        return error
    error_code = error.response.get("Error", {}).get("Code", "Unknown")
    if error_code not in AWS_ACCOUNT_BANNED_ERROR_CODES:
        return error
    message = error.response.get("Error", {}).get("Message", str(error))
    return AwsAccountBannedError(
        aws_account_id=aws_account_id,
        error_code=error_code,
        message=message,
    )
