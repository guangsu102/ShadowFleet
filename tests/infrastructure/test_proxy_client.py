from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.aws.proxy_client import (
    AwsProxyClientError,
    _build_decodo_proxy_query_params,
    _build_evomi_password,
    build_aws_boto_proxies,
)
from models.config_models import AwsProxyConfig


def _make_runtime_context(config: AwsProxyConfig) -> SimpleNamespace:
    logger = MagicMock(spec=logging.Logger)
    logger.getChild.return_value = logger
    return SimpleNamespace(
        logger=logger,
        config=SimpleNamespace(
            app=SimpleNamespace(
                request_timeout_seconds=10,
                max_retries=0,
                retry_backoff_seconds=1.0,
            ),
            aws_proxy=config,
        ),
    )


class _MockResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


def test_build_evomi_password_with_sticky_session_and_adblock() -> None:
    config = AwsProxyConfig(
        enabled=True,
        provider="evomi",
        api_key="evm_key",
        session_type="sticky",
        session_duration=10,
        adblock_enabled=True,
    )

    password = _build_evomi_password(
        base_password="proxy_password",
        config=config,
        country="US",
        session_id="Ab12Cd34",
    )

    assert password == (
        "proxy_password_country-US_session-Ab12Cd34_lifetime-10_adblock-1"
    )


def test_build_decodo_query_params_uses_region_country_mapping() -> None:
    config = AwsProxyConfig(
        enabled=True,
        provider="decodo",
        authorization="auth",
        username="user",
        password="pass",
        location="random",
    )

    params = _build_decodo_proxy_query_params(config, required_country="JP")

    assert params["location"] == "jp"


def test_build_decodo_query_params_rejects_non_country_location_with_region_lock() -> None:
    config = AwsProxyConfig(
        enabled=True,
        provider="decodo",
        authorization="auth",
        username="user",
        password="pass",
        location="tokyo",
    )

    with pytest.raises(AwsProxyClientError, match="must be 'random' or a two-letter country code"):
        _build_decodo_proxy_query_params(config, required_country="JP")


def test_build_aws_boto_proxies_evomi_uses_aws_region_country() -> None:
    config = AwsProxyConfig(
        enabled=True,
        provider="evomi",
        api_key="evm_key",
        session_type="sticky",
        session_duration=10,
        adblock_enabled=True,
    )
    runtime_context = _make_runtime_context(config)
    response = _MockResponse(
        200,
        {
            "success": True,
            "products": {
                "rp": {
                    "username": "proxy_user",
                    "password": "proxy_password",
                    "endpoint": "premium-residential.evomi.com",
                    "ports": {"http": 1000, "socks5": 1002},
                }
            },
        },
    )

    with patch("requests.Session.request", return_value=response):
        proxies = build_aws_boto_proxies(runtime_context, aws_region="ap-northeast-1")

    assert proxies is not None
    assert proxies["http"].startswith("http://proxy_user:proxy_password_country-JP_")
    assert "@premium-residential.evomi.com:1000" in proxies["http"]
    assert proxies["https"] == proxies["http"]


def test_build_aws_boto_proxies_evomi_rejects_conflicting_country() -> None:
    config = AwsProxyConfig(
        enabled=True,
        provider="evomi",
        api_key="evm_key",
        country="US",
    )
    runtime_context = _make_runtime_context(config)

    with pytest.raises(AwsProxyClientError, match="conflicts with the AWS region country mapping"):
        build_aws_boto_proxies(runtime_context, aws_region="eu-west-1")
