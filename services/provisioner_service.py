from __future__ import annotations

from database.asset_repo import AssetRepo
from services.asset_selector_service import AssetSelectorService
from services.node_registry_service import NodeRegistryService
from services.provisioning_aws_flow import provision_aws_node
from services.provisioning_models import DnsRecordSnapshot, DnsSyncResult, ProvisionRequest, ProvisionResult
from services.provisioning_self_hosted_flow import provision_self_hosted_node
from services.provisioning_support import ProvisionerServiceError, ProvisioningDependencies, validate_request
from services.ready_callback_service import ReadyCallbackService
from services.runtime_service import RuntimeContext

__all__ = [
    "DnsRecordSnapshot",
    "DnsSyncResult",
    "ProvisionRequest",
    "ProvisionResult",
    "ProvisionerServiceError",
    "ProvisionerService",
]


class ProvisionerService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.provisioner")
        self._asset_selector = AssetSelectorService(runtime_context)
        self._asset_repo = AssetRepo(runtime_context)
        self._node_registry = NodeRegistryService(runtime_context)
        self._ready_callback_service = ReadyCallbackService(runtime_context)

    def provision_node(self, request: ProvisionRequest) -> ProvisionResult:
        validate_request(request)
        dependencies = ProvisioningDependencies(
            runtime_context=self._runtime_context,
            logger=self._logger,
            asset_selector=self._asset_selector,
            node_registry=self._node_registry,
            ready_callback_service=self._ready_callback_service,
        )
        if request.asset_type == "self_hosted":
            return provision_self_hosted_node(dependencies, self._asset_repo, request)
        return provision_aws_node(dependencies, self._asset_repo, request)
