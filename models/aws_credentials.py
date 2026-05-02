"""AWS credentials data structure used across infrastructure and service layers.

AK/SK are stored per-account in the SQLite fleet_assets table, NOT in config.yaml.
This module provides a plain immutable dataclass for passing credentials to
boto3 clients and AWS operations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AwsCredentials:
    """Immutable AWS credential holder for a single account/region pair."""

    account_id: str
    access_key: str
    secret_key: str
    region: str
