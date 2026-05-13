"""
Provisioning 流程重构 - 步骤模式

将原有的 provision_aws_node 函数（280+ 行）重构为清晰的步骤模式，
每个步骤职责单一，易于测试和维护。

核心思想：
1. 将 Provisioning 流程拆分为独立的步骤（Step）
2. 每个步骤有明确的输入和输出
3. 使用 Pipeline 模式组织步骤执行
4. 自动管理回滚
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from services.rollback_coordinator import RollbackCoordinator, RollbackPriority
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass
class ProvisioningContext:
    """Provisioning 上下文，在步骤之间传递数据"""
    # 输入参数
    request: Any  # ProvisionRequest
    runtime_context: RuntimeContext

    # 步骤输出（逐步填充）
    selection_result: Any | None = None
    registered_node_result: Any | None = None
    effective_domain_name: str | None = None
    ready_callback_registration: Any | None = None
    rendered_user_data: str | None = None
    aws_credential: Any | None = None
    ec2_client: Any | None = None
    key_name: str | None = None
    effective_instance_type: str | None = None
    launch_result: Any | None = None
    dns_sync_result: Any | None = None
    cloudflare_record_id: str | None = None
    online_result: Any | None = None

    # 回滚协调器
    rollback_coordinator: RollbackCoordinator | None = None


class ProvisioningStep(ABC):
    """Provisioning 步骤抽象基类"""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def execute(self, context: ProvisioningContext) -> None:
        """
        执行步骤

        Args:
            context: Provisioning 上下文

        Raises:
            Exception: 步骤执行失败
        """
        pass

    @abstractmethod
    def get_rollback_priority(self) -> RollbackPriority:
        """获取回滚优先级"""
        pass

    def register_rollback(self, context: ProvisioningContext) -> None:
        """
        注册回滚动作（可选）

        子类可以重写此方法来注册回滚动作
        """
        pass


class SelectAssetStep(ProvisioningStep):
    """步骤 1: 选择资产"""

    def __init__(self) -> None:
        super().__init__("SelectAsset")

    def execute(self, context: ProvisioningContext) -> None:
        from services.asset_selector_service import AssetSelectionRequest, AssetSelectorService

        asset_selector = AssetSelectorService(context.runtime_context)
        context.selection_result = asset_selector.select_asset(
            AssetSelectionRequest(
                protocol_type=context.request.protocol_type,
                asset_type=context.request.asset_type,
                region=context.request.region,
                require_cdn_proxy=context.request.require_cdn_proxy,
            )
        )

        set_event_type("provisioning_asset_selected")
        context.runtime_context.logger.info(
            "Selected asset: asset_id=%s, region=%s",
            context.selection_result.asset_id,
            context.selection_result.region,
        )

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.LOW


class RegisterNodeStep(ProvisioningStep):
    """步骤 2: 注册节点到 Xboard"""

    def __init__(self) -> None:
        super().__init__("RegisterNode")

    def execute(self, context: ProvisioningContext) -> None:
        from services.node_registry_service import NodeRegistryService
        from services.provisioning_support import build_register_node_request

        node_registry = NodeRegistryService(context.runtime_context)
        context.registered_node_result = node_registry.register_node(
            build_register_node_request(context.runtime_context, context.request)
        )

        set_event_type("provisioning_node_registered")
        context.runtime_context.logger.info(
            "Registered node: xboard_node_id=%s",
            context.registered_node_result.xboard_node_id,
        )

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.CRITICAL

    def register_rollback(self, context: ProvisioningContext) -> None:
        if context.registered_node_result is None:
            return

        from services.node_registry_service import NodeRegistryService

        xboard_node_id = context.registered_node_result.xboard_node_id
        node_registry = NodeRegistryService(context.runtime_context)

        context.rollback_coordinator.register_action(
            name="Delete registered node",
            action=lambda: node_registry.delete_node(xboard_node_id),
            priority=self.get_rollback_priority(),
            resource_type="xboard_node",
            resource_id=str(xboard_node_id),
            allow_failure=False,
        )


class AutoConfigureNodeStep(ProvisioningStep):
    """步骤 3: 自动配置节点（生成节点 ID、协议参数等）"""

    def __init__(self) -> None:
        super().__init__("AutoConfigureNode")

    def execute(self, context: ProvisioningContext) -> None:
        from services.node_auto_config_service import NodeAutoConfigService

        auto_config_service = NodeAutoConfigService(context.runtime_context)
        auto_config_service.auto_configure_node(
            xboard_node_id=context.registered_node_result.xboard_node_id,
            protocol_type=context.request.protocol_type,
            protocol_settings=context.request.protocol_settings,
            sni_domain=getattr(context.request, 'sni_domain', None),
            reality_private_key=getattr(context.request, 'reality_private_key', None),
            reality_public_key=getattr(context.request, 'reality_public_key', None),
        )

        set_event_type("provisioning_node_configured")
        context.runtime_context.logger.info(
            "Auto-configured node: xboard_node_id=%s",
            context.registered_node_result.xboard_node_id,
        )

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.MEDIUM


class AllocateDomainStep(ProvisioningStep):
    """步骤 4: 分配域名"""

    def __init__(self) -> None:
        super().__init__("AllocateDomain")

    def execute(self, context: ProvisioningContext) -> None:
        from services.provisioning_support import resolve_effective_domain_name

        context.effective_domain_name = resolve_effective_domain_name(
            runtime_context=context.runtime_context,
            request=context.request,
            selection_result=context.selection_result,
            xboard_node_id=context.registered_node_result.xboard_node_id,
        )

        if context.effective_domain_name:
            set_event_type("provisioning_domain_allocated")
            context.runtime_context.logger.info(
                "Allocated domain: %s",
                context.effective_domain_name,
            )

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.HIGH


class RegisterReadyCallbackStep(ProvisioningStep):
    """步骤 5: 注册就绪回调"""

    def __init__(self) -> None:
        super().__init__("RegisterReadyCallback")

    def execute(self, context: ProvisioningContext) -> None:
        from services.ready_callback_service import ReadyCallbackService
        from services.provisioning_support import require_task_id

        ready_callback_service = ReadyCallbackService(context.runtime_context)
        context.ready_callback_registration = ready_callback_service.register_callback(
            task_id=require_task_id(context.request),
            xboard_node_id=context.registered_node_result.xboard_node_id,
            correlation_id=context.runtime_context.correlation_id,
        )

        set_event_type("provisioning_callback_registered")
        context.runtime_context.logger.info(
            "Registered ready callback: task_id=%s",
            require_task_id(context.request),
        )

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.MEDIUM


class RenderUserDataStep(ProvisioningStep):
    """步骤 6: 渲染 User Data"""

    def __init__(self) -> None:
        super().__init__("RenderUserData")

    def execute(self, context: ProvisioningContext) -> None:
        from services.provisioning_support import build_user_data_render_request
        from utils.template_engine import render_user_data

        render_request = build_user_data_render_request(
            runtime_context=context.runtime_context,
            request=context.request,
            selection_result=context.selection_result,
            xboard_node_id=context.registered_node_result.xboard_node_id,
            ready_callback_registration=context.ready_callback_registration,
            effective_domain_name=context.effective_domain_name,
        )

        rendered = render_user_data(render_request)
        context.rendered_user_data = rendered.user_data

        set_event_type("provisioning_userdata_rendered")
        context.runtime_context.logger.info("Rendered user data")

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.LOW


class PrepareAwsCredentialsStep(ProvisioningStep):
    """步骤 7: 准备 AWS 凭证和客户端"""

    def __init__(self) -> None:
        super().__init__("PrepareAwsCredentials")

    def execute(self, context: ProvisioningContext) -> None:
        from infrastructure.aws.ec2_client import EC2Client
        from services.key_pair_manager import KeyPairManager
        from services.provisioning_support import (
            build_aws_credential,
            resolve_default_instance_spec,
        )

        context.aws_credential = build_aws_credential(context.selection_result)
        context.ec2_client = EC2Client(
            runtime_context=context.runtime_context,
            aws_credential=context.aws_credential,
        )

        # 确保 Key Pair 存在
        key_pair_manager = KeyPairManager(context.runtime_context)
        context.key_name = key_pair_manager.ensure_key_pair_for_account(
            aws_credential=context.aws_credential,
            ec2_client=context.ec2_client._ec2_client,
        )

        # 解析实例类型
        context.effective_instance_type = resolve_default_instance_spec(
            runtime_context=context.runtime_context,
            aws_credential=context.aws_credential,
            selection_result_instance_type=context.selection_result.instance_type,
            correlation_id=context.runtime_context.correlation_id,
        )

        set_event_type("provisioning_aws_prepared")
        context.runtime_context.logger.info(
            "Prepared AWS credentials: region=%s, instance_type=%s",
            context.aws_credential.region,
            context.effective_instance_type,
        )

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.LOW


class LaunchEc2InstanceStep(ProvisioningStep):
    """步骤 8: 启动 EC2 实例"""

    def __init__(self) -> None:
        super().__init__("LaunchEc2Instance")

    def execute(self, context: ProvisioningContext) -> None:
        from infrastructure.aws.ec2_client import Ec2LaunchRequest
        from services.provisioning_support import require_non_empty

        context.launch_result = context.ec2_client.launch_ipv6_instance(
            Ec2LaunchRequest(
                image_id=require_non_empty(context.selection_result.ami_id, "ami_id"),
                instance_type=context.effective_instance_type,
                subnet_id=require_non_empty(context.selection_result.subnet_id, "subnet_id"),
                security_group_id=require_non_empty(
                    context.selection_result.security_group_id,
                    "security_group_id",
                ),
                user_data=context.rendered_user_data,
                key_name=context.key_name,
                instance_name=context.request.node_name,
                associate_public_ip=False,
            )
        )

        set_event_type("provisioning_instance_launched")
        context.runtime_context.logger.info(
            "Launched EC2 instance: instance_id=%s",
            context.launch_result.instance_id,
        )

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.HIGH

    def register_rollback(self, context: ProvisioningContext) -> None:
        if context.launch_result is None:
            return

        instance_id = context.launch_result.instance_id
        ec2_client = context.ec2_client

        context.rollback_coordinator.register_action(
            name="Terminate EC2 instance",
            action=lambda: ec2_client.terminate_instance(instance_id),
            priority=self.get_rollback_priority(),
            resource_type="ec2_instance",
            resource_id=instance_id,
            allow_failure=True,  # 允许失败（可能已被手动删除）
        )


class SyncDnsRecordsStep(ProvisioningStep):
    """步骤 9: 同步 DNS 记录"""

    def __init__(self) -> None:
        super().__init__("SyncDnsRecords")

    def execute(self, context: ProvisioningContext) -> None:
        if not context.selection_result.requires_dns_record:
            context.runtime_context.logger.info("DNS record not required, skipping")
            return

        from services.provisioning_dns_service import sync_dns_records
        from services.provisioning_support import require_non_empty

        ipv6_address = (
            context.launch_result.ipv6_addresses[0]
            if context.launch_result.ipv6_addresses
            else None
        )
        ipv4_address = context.launch_result.ipv4_address

        context.dns_sync_result = sync_dns_records(
            runtime_context=context.runtime_context,
            protocol_type=context.request.protocol_type,
            domain_name=require_non_empty(context.effective_domain_name, "domain_name"),
            selection_result=context.selection_result,
            require_cdn_proxy=context.request.require_cdn_proxy,
            ipv4_address=ipv4_address,
            ipv6_address=ipv6_address,
        )

        context.cloudflare_record_id = context.dns_sync_result.primary_record_id

        set_event_type("provisioning_dns_synced")
        context.runtime_context.logger.info(
            "Synced DNS records: record_id=%s",
            context.cloudflare_record_id,
        )

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.MEDIUM

    def register_rollback(self, context: ProvisioningContext) -> None:
        if context.dns_sync_result is None:
            return

        from services.provisioning_dns_service import rollback_dns_records

        dns_sync_result = context.dns_sync_result
        runtime_context = context.runtime_context

        context.rollback_coordinator.register_action(
            name="Rollback DNS records",
            action=lambda: rollback_dns_records(runtime_context, dns_sync_result),
            priority=self.get_rollback_priority(),
            resource_type="dns_records",
            resource_id=context.cloudflare_record_id,
            allow_failure=True,
        )


class WaitForReadyCallbackStep(ProvisioningStep):
    """步骤 10: 等待就绪回调"""

    def __init__(self) -> None:
        super().__init__("WaitForReadyCallback")

    def execute(self, context: ProvisioningContext) -> None:
        from services.ready_callback_service import ReadyCallbackService
        from services.provisioning_support import require_task_id

        ready_callback_service = ReadyCallbackService(context.runtime_context)
        ready_callback_service.wait_for_ready_callback(require_task_id(context.request))

        set_event_type("provisioning_ready_callback_received")
        context.runtime_context.logger.info("Received ready callback")

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.LOW


class MarkNodeOnlineStep(ProvisioningStep):
    """步骤 11: 标记节点为在线"""

    def __init__(self) -> None:
        super().__init__("MarkNodeOnline")

    def execute(self, context: ProvisioningContext) -> None:
        from services.node_registry_service import NodeRegistryService

        node_registry = NodeRegistryService(context.runtime_context)

        ipv6_address = (
            context.launch_result.ipv6_addresses[0]
            if context.launch_result.ipv6_addresses
            else None
        )
        ipv4_address = context.launch_result.ipv4_address

        context.online_result = node_registry.mark_node_online(
            xboard_node_id=context.registered_node_result.xboard_node_id,
            host=context.effective_domain_name or context.request.node_name,
            aws_account_id=context.selection_result.aws_account_id,
            aws_region=context.selection_result.region,
            aws_instance_id=context.launch_result.instance_id,
            aws_subnet_id=context.launch_result.subnet_id,
            aws_security_group_id=context.selection_result.security_group_id,
            instance_type=context.effective_instance_type,
            cloudflare_record_id=context.cloudflare_record_id,
            domain_name=context.effective_domain_name,
            ipv4_address=ipv4_address,
            ipv6_address=ipv6_address,
            status_reason=context.request.status_reason,
        )

        set_event_type("provisioning_node_online")
        context.runtime_context.logger.info(
            "Marked node online: xboard_node_id=%s",
            context.registered_node_result.xboard_node_id,
        )

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.CRITICAL


class CreateAssetAllocationStep(ProvisioningStep):
    """步骤 12: 创建资产分配"""

    def __init__(self) -> None:
        super().__init__("CreateAssetAllocation")

    def execute(self, context: ProvisioningContext) -> None:
        from database.asset_repo import AssetAllocationCreateRequest, AssetRepo

        asset_repo = AssetRepo(context.runtime_context)
        asset_repo.create_allocation(
            AssetAllocationCreateRequest(
                asset_id=context.selection_result.asset_id,
                fleet_node_id=context.online_result.local_node_id,
                xboard_node_id=context.online_result.xboard_node_id,
                protocol_type=context.request.protocol_type,
            )
        )

        set_event_type("provisioning_allocation_created")
        context.runtime_context.logger.info(
            "Created asset allocation: asset_id=%s",
            context.selection_result.asset_id,
        )

    def get_rollback_priority(self) -> RollbackPriority:
        return RollbackPriority.HIGH


class ProvisioningPipeline:
    """Provisioning 流程管道"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.provisioning_pipeline")
        self._steps: list[ProvisioningStep] = []

    def add_step(self, step: ProvisioningStep) -> ProvisioningPipeline:
        """添加步骤"""
        self._steps.append(step)
        return self

    def execute(self, request: Any) -> ProvisioningContext:
        """
        执行 Provisioning 流程

        Args:
            request: ProvisionRequest

        Returns:
            ProvisioningContext

        Raises:
            Exception: 流程执行失败
        """
        # 创建上下文
        context = ProvisioningContext(
            request=request,
            runtime_context=self._runtime,
            rollback_coordinator=RollbackCoordinator(self._logger),
        )

        set_event_type("provisioning_pipeline_started")
        self._logger.info(
            "Starting provisioning pipeline: node=%s, protocol=%s, steps=%d",
            request.node_name,
            request.protocol_type,
            len(self._steps),
        )

        executed_steps: list[ProvisioningStep] = []

        try:
            # 执行每个步骤
            for step in self._steps:
                self._logger.info("Executing step: %s", step.name)

                # 执行步骤
                step.execute(context)
                executed_steps.append(step)

                # 注册回滚
                step.register_rollback(context)

            set_event_type("provisioning_pipeline_completed")
            self._logger.info(
                "Provisioning pipeline completed successfully: xboard_node_id=%s",
                context.registered_node_result.xboard_node_id if context.registered_node_result else None,
            )

            return context

        except Exception as exc:
            set_event_type("provisioning_pipeline_failed")
            self._logger.error(
                "Provisioning pipeline failed at step: %s (executed %d/%d steps)",
                executed_steps[-1].name if executed_steps else "N/A",
                len(executed_steps),
                len(self._steps),
            )

            # 执行回滚
            rollback_report = context.rollback_coordinator.execute_rollback()
            self._logger.info(
                "Rollback completed: succeeded=%d, failed=%d, critical_failures=%d",
                rollback_report.succeeded,
                rollback_report.failed,
                len(rollback_report.critical_failures),
            )

            raise


def create_aws_provisioning_pipeline(runtime_context: RuntimeContext) -> ProvisioningPipeline:
    """创建 AWS Provisioning 流程管道"""
    return (
        ProvisioningPipeline(runtime_context)
        .add_step(SelectAssetStep())
        .add_step(RegisterNodeStep())
        .add_step(AutoConfigureNodeStep())
        .add_step(AllocateDomainStep())
        .add_step(RegisterReadyCallbackStep())
        .add_step(RenderUserDataStep())
        .add_step(PrepareAwsCredentialsStep())
        .add_step(LaunchEc2InstanceStep())
        .add_step(SyncDnsRecordsStep())
        .add_step(WaitForReadyCallbackStep())
        .add_step(MarkNodeOnlineStep())
        .add_step(CreateAssetAllocationStep())
    )
