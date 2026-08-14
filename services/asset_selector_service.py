from __future__ import annotations

from dataclasses import dataclass

from database.asset_repo import (
    AssetRepo,
    AssetSelectionCandidate,
    AssetType,
    ProtocolType,
)
from utils.logger import set_event_type

from services.runtime_service import RuntimeContext


class AssetSelectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssetSelectionRequest:
    protocol_type: ProtocolType
    asset_type: AssetType | None = None
    region: str | None = None
    require_cdn_proxy: bool = False


@dataclass(frozen=True)
class AssetSelectionResult:
    asset_id: int
    asset_type: AssetType
    asset_name: str
    protocol_type: ProtocolType
    region: str | None
    aws_account_id: str | None
    aws_access_key: str | None
    aws_secret_key: str | None
    ssh_host: str | None
    ssh_port: int | None
    ssh_username: str | None
    ssh_password: str | None
    ssh_private_key: str | None
    instance_type: str | None
    vcpu: int | None
    architecture: str | None
    ami_id: str | None
    subnet_id: str | None
    security_group_id: str | None
    allow_cdn_proxy: bool
    requires_domain: bool
    requires_dns_record: bool
    current_allocated_count: int
    current_allocated_vcpu: int
    target_count: int
    max_count: int
    provider_config: dict[str, object] | None = None


class AssetSelectorService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.asset_selector")
        self._asset_repo = AssetRepo(runtime_context)

    def select_asset(self, request: AssetSelectionRequest) -> AssetSelectionResult:
        self._validate_request(request)
        set_event_type("asset_selection_started")
        self._logger.info(
            "Selecting asset for protocol=%s asset_type=%s region=%s",
            request.protocol_type,
            request.asset_type,
            request.region,
        )

        candidates = self._asset_repo.list_selection_candidates(
            protocol_type=request.protocol_type,
            asset_type=request.asset_type,
            region=request.region,
            require_cdn_proxy=request.require_cdn_proxy,
        )
        if not candidates:
            raise AssetSelectionError(
                "No active asset matches the requested protocol, region, and capability filters"
            )

        selected_candidate = self._pick_best_candidate(candidates)
        set_event_type("asset_selection_completed")
        self._logger.info(
            "Selected asset id=%s name=%s protocol=%s current_allocations=%s",
            selected_candidate.asset.id,
            selected_candidate.asset.asset_name,
            request.protocol_type,
            selected_candidate.current_allocated_count,
        )
        return self._build_selection_result(selected_candidate)

    @staticmethod
    def _pick_best_candidate(
        candidates: list[AssetSelectionCandidate],
    ) -> AssetSelectionCandidate:
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.protocol_config.priority,
                candidate.current_allocated_count,
                candidate.asset.id,
            ),
        )[0]

    @staticmethod
    def _build_selection_result(candidate: AssetSelectionCandidate) -> AssetSelectionResult:
        asset = candidate.asset
        protocol_config = candidate.protocol_config
        return AssetSelectionResult(
            asset_id=asset.id,
            asset_type=asset.asset_type,
            asset_name=asset.asset_name,
            protocol_type=protocol_config.protocol_type,
            region=asset.region,
            aws_account_id=asset.aws_account_id,
            aws_access_key=asset.aws_access_key,
            aws_secret_key=asset.aws_secret_key,
            ssh_host=asset.ssh_host,
            ssh_port=asset.ssh_port,
            ssh_username=asset.ssh_username,
            ssh_password=asset.ssh_password,
            ssh_private_key=asset.ssh_private_key,
            instance_type=protocol_config.instance_type or asset.default_instance_type,
            vcpu=protocol_config.vcpu or asset.default_vcpu,
            architecture=protocol_config.architecture or asset.default_architecture,
            ami_id=protocol_config.ami_id,
            subnet_id=protocol_config.subnet_id,
            security_group_id=protocol_config.security_group_id,
            allow_cdn_proxy=protocol_config.allow_cdn_proxy,
            requires_domain=protocol_config.requires_domain,
            requires_dns_record=protocol_config.requires_dns_record,
            current_allocated_count=candidate.current_allocated_count,
            current_allocated_vcpu=candidate.current_allocated_vcpu,
            target_count=protocol_config.target_count,
            max_count=protocol_config.max_count,
            provider_config=asset.provider_config,
        )

    @staticmethod
    def _validate_request(request: AssetSelectionRequest) -> None:
        if request.asset_type in ("aws", "azure", "digitalocean", "oci", "vultr") and request.protocol_type == "Hysteria2":
            raise AssetSelectionError("Hysteria2 is not allowed on cloud assets")
        if request.require_cdn_proxy and request.protocol_type == "AnyTLS":
            raise AssetSelectionError("AnyTLS supports DNS linkage but must not use CDN proxy")
