from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from database.asset_models import AssetRecord
from database.asset_repo import AssetEventCreateRequest, AssetRepo
from infrastructure.gcp import GCPClientError
from infrastructure.kamatera import KamateraClientError
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


ProviderType = Literal["gcp", "kamatera"]
_EXPLICIT_CREDENTIAL_ERROR_HINTS = (
    "authentication failed",
    "credential has been revoked",
    "credentials have been revoked",
    "invalid client",
    "invalid credential",
    "invalid grant",
    "invalid secret",
    "invalid_grant",
    "unauthorized client",
)


@dataclass(frozen=True)
class ProviderAccountQuarantineResult:
    provider: ProviderType
    account_id: str | None
    asset_count: int


def is_terminal_provider_account_error(
    provider: ProviderType,
    error: BaseException,
) -> bool:
    message = str(error).casefold()
    status_code = getattr(error, "status_code", None)
    if getattr(error, "retryable", False):
        return False
    if status_code in {403, 408, 429} or (
        isinstance(status_code, int) and status_code >= 500
    ):
        return False

    if provider == "gcp":
        if not isinstance(error, GCPClientError):
            return False
    elif provider == "kamatera":
        if not isinstance(error, KamateraClientError):
            return False
    else:
        return False

    if status_code == 401:
        return True
    return any(hint in message for hint in _EXPLICIT_CREDENTIAL_ERROR_HINTS)


def quarantine_terminal_provider_error(
    *,
    runtime_context: RuntimeContext,
    asset_repo: AssetRepo,
    provider: ProviderType,
    account_id: str | None,
    source_asset_id: int,
    error: BaseException,
) -> ProviderAccountQuarantineResult | None:
    if not is_terminal_provider_account_error(provider, error):
        return None

    normalized_account_id = str(account_id or "").strip() or None
    assets = _account_assets(
        asset_repo,
        provider=provider,
        account_id=normalized_account_id,
        source_asset_id=source_asset_id,
    )
    status_code = getattr(error, "status_code", None)
    error_code = str(status_code) if status_code is not None else type(error).__name__
    changed_assets = [asset for asset in assets if asset.status != "banned"]

    for asset in changed_assets:
        asset_repo.update_asset_status(asset.id, "banned")
        asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=asset.id,
                event_type="provider_account_quarantined",
                correlation_id=runtime_context.correlation_id,
                message=str(error),
                payload={
                    "provider": provider,
                    "account_id": normalized_account_id,
                    "error_code": error_code,
                    "source_asset_id": source_asset_id,
                },
            )
        )

    if changed_assets:
        set_event_type("provider_account_quarantined")
        runtime_context.logger.getChild("services.provider_account_health").error(
            "Quarantined provider account provider=%s account_id=%s assets=%s error_code=%s",
            provider,
            normalized_account_id,
            len(changed_assets),
            error_code,
        )

    return ProviderAccountQuarantineResult(
        provider=provider,
        account_id=normalized_account_id,
        asset_count=len(changed_assets),
    )


def _account_assets(
    asset_repo: AssetRepo,
    *,
    provider: ProviderType,
    account_id: str | None,
    source_asset_id: int,
) -> list[AssetRecord]:
    assets = (
        asset_repo.list_assets_by_aws_account_id(account_id)
        if account_id is not None
        else [asset_repo.get_asset_by_id(source_asset_id)]
    )
    matching_assets = [asset for asset in assets if asset.asset_type == provider]
    if not matching_assets:
        source_asset = asset_repo.get_asset_by_id(source_asset_id)
        if source_asset.asset_type == provider:
            matching_assets = [source_asset]
    return matching_assets
