from __future__ import annotations

import time
from dataclasses import dataclass

from botocore.exceptions import ClientError

from database.state_models import FleetOperationLockRequest
from database.state_repo import FleetNodeRecord
from services.healing_models import AwsAccountBannedError, HealRequest, HealerServiceError, InstanceNotFoundError, ManualReviewRequiredError

AWS_HEALABLE_PROTOCOLS = {"AnyTLS", "Trojan", "vless", "vmess"}
SELF_HOSTED_PROXY_PROTOCOLS = {"Trojan", "vless", "vmess"}
AWS_ACCOUNT_BANNED_ERROR_CODES = {
    "AuthFailure",
    "UnauthorizedOperation",
    "InvalidClientTokenId",
}
HEAL_LOCK_EXPIRY_SECONDS = 120


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
        return request.force_strategy
    if node_record.aws_account_id is not None and node_record.node_type in AWS_HEALABLE_PROTOCOLS:
        return "aws_ipv6_rotate"
    if node_record.aws_account_id is None and node_record.node_type in SELF_HOSTED_PROXY_PROTOCOLS:
        return "cloudflare_enable_proxy"
    return "manual_review_required"


def ensure_aws_healing_eligible(node_record: FleetNodeRecord) -> None:
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


def ensure_self_hosted_healing_eligible(node_record: FleetNodeRecord) -> None:
    if node_record.aws_account_id is not None:
        raise HealerServiceError("Self-hosted healing received an AWS-backed node")
    if node_record.node_type not in SELF_HOSTED_PROXY_PROTOCOLS:
        raise ManualReviewRequiredError(
            f"Self-hosted node type is not supported for Cloudflare fallback: {node_record.node_type}"
        )
    if node_record.domain_name is None or not node_record.domain_name.strip():
        raise ManualReviewRequiredError("Self-hosted node is missing domain_name")


def build_heal_lock(node_record: FleetNodeRecord, correlation_id: str) -> FleetOperationLockRequest:
    return FleetOperationLockRequest(
        lock_key=build_heal_lock_key(node_record.xboard_node_id),
        node_id=node_record.id,
        operation_type="healing",
        correlation_id=correlation_id,
        expires_in_seconds=HEAL_LOCK_EXPIRY_SECONDS,
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
