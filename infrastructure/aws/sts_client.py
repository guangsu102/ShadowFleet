"""AWS STS client for identity resolution."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


@dataclass(frozen=True)
class StsIdentity:
    """Result of STS GetCallerIdentity."""

    account_id: str
    arn: str
    user_id: str


class StsClientError(RuntimeError):
    """Raised when STS GetCallerIdentity fails."""


def resolve_aws_account_id(
    *,
    aws_access_key: str,
    aws_secret_key: str,
    aws_region: str,
    request_timeout_seconds: int = 10,
    max_retries: int = 3,
) -> StsIdentity:
    """
    Resolve AWS Account ID via STS GetCallerIdentity using explicit credentials.

    Returns StsIdentity with account_id, arn, and user_id.
    Raises StsClientError on credential validation failure.
    """
    logger = logging.getLogger("infrastructure.aws.sts")

    boto_config = Config(
        connect_timeout=request_timeout_seconds,
        read_timeout=request_timeout_seconds,
        retries={"max_attempts": max_retries, "mode": "standard"},
        region_name=aws_region or "us-east-1",
    )

    client = boto3.client(
        service_name="sts",
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        config=boto_config,
    )

    try:
        response = client.get_caller_identity()
        identity = StsIdentity(
            account_id=str(response["Account"]),
            arn=str(response["Arn"]),
            user_id=str(response["UserId"]),
        )
        logger.info(
            "STS GetCallerIdentity succeeded: account_id=%s user_id=%s",
            identity.account_id,
            identity.user_id,
        )
        return identity
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        error_message = exc.response.get("Error", {}).get("Message", str(exc))
        logger.error(
            "STS GetCallerIdentity failed: error_code=%s error_message=%s",
            error_code,
            error_message,
        )
        raise StsClientError(
            f"AWS 凭证验证失败 (STS): [{error_code}] {error_message}"
        ) from exc
