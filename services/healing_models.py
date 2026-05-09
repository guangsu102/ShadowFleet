from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


HealStrategy = Literal[
    "aws_ipv6_rotate",
    "cloudflare_enable_proxy",
    "manual_review_required",
    "aws_account_abandoned",
    "cooldown_blocked",
]


@dataclass(frozen=True)
class HealRequest:
    xboard_node_id: int
    reason: str
    source: str = "sentinel"
    measurement_payload: dict[str, object] | None = None
    force_strategy: HealStrategy | None = None


@dataclass(frozen=True)
class HealResult:
    xboard_node_id: int
    node_name: str
    node_type: str
    asset_type: str
    strategy: HealStrategy
    success: bool
    old_ipv6_address: str | None
    new_ipv6_address: str | None
    domain_name: str | None
    cloudflare_record_id: str | None
    proxied_enabled: bool | None
    duration_ms: int
    message: str
    correlation_id: str


class HealerServiceError(RuntimeError):
    pass


class ManualReviewRequiredError(HealerServiceError):
    pass


class AwsAccountBannedError(HealerServiceError):
    def __init__(
        self,
        aws_account_id: str,
        error_code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.aws_account_id = aws_account_id
        self.error_code = error_code


class InstanceNotFoundError(HealerServiceError):
    def __init__(
        self,
        instance_id: str,
        aws_region: str | None = None,
        aws_account_id: str | None = None,
    ) -> None:
        message = f"Instance not found: {instance_id}"
        if aws_region:
            message += f" (region={aws_region})"
        super().__init__(message)
        self.instance_id = instance_id
        self.aws_region = aws_region
        self.aws_account_id = aws_account_id
