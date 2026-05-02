from __future__ import annotations


from database.asset_models import AssetCreateRequest, AssetEventCreateRequest, AssetProtocolConfigRequest
from database.asset_repo import AssetRepo
from infrastructure.aws.ec2_client import EC2Client
from infrastructure.aws.sts_client import StsClientError, resolve_aws_account_id
from infrastructure.self_hosted.ssh_client import SelfHostedSshClient, SelfHostedSshConfig
from models.aws_credentials import AwsCredentials
from services.asset_application_models import (
    AssetRegistrationRequest,
    AssetRegistrationResult,
    SelfHostedAssetRegistrationRequest,
)
from services.runtime_service import RuntimeContext


class AssetApplicationService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._asset_repo = AssetRepo(runtime_context)
        self._logger = runtime_context.logger.getChild("services.asset_application")

    def register_aws_asset(self, request: AssetRegistrationRequest) -> AssetRegistrationResult:
        self._validate_registration_request(request)
        resolved_account_id = self._resolve_account_id(request)

        vpc_id = self._normalize_optional_text(request.vpc_id)
        subnet_id = self._normalize_optional_text(request.subnet_id)
        security_group_id = self._normalize_optional_text(request.security_group_id)

        if request.auto_create_security_group and not security_group_id:
            self._logger.info(
                "Auto-creating VPC/Subnet/SG for asset=%s region=%s",
                request.asset_name,
                request.region,
            )
            ec2_client = self._build_ec2_client(
                aws_account_id=resolved_account_id,
                aws_region=request.region.strip(),
                aws_access_key=request.aws_access_key.strip(),
                aws_secret_key=request.aws_secret_key.strip(),
            )
            vpc_id = ec2_client.vpc.find_or_create_vpc()
            subnet_id, _ = ec2_client.vpc.find_or_create_subnet_with_ipv6(vpc_id=vpc_id)
            sg_name = request.security_group_name or f"shadowfleet-{request.asset_name}"
            sg_description = f"ShadowFleet asset: {request.asset_name}"
            port_rules: tuple[tuple[int, str], ...] = tuple(
                (port, "tcp") for port in request.security_group_ports
            )
            if not port_rules:
                port_rules = ((443, "tcp"), (22, "tcp"))
            security_group_id = ec2_client.vpc.create_security_group_with_rules(
                vpc_id=vpc_id,
                group_name=sg_name,
                description=sg_description,
                port_rules=port_rules,
            )
            self._logger.info(
                "Auto-created SG=%s Subnet=%s VPC=%s for asset=%s",
                security_group_id,
                subnet_id,
                vpc_id,
                request.asset_name,
            )

        asset_id = self._asset_repo.create_asset(
            AssetCreateRequest(
                asset_type="aws",
                asset_name=request.asset_name.strip(),
                region=request.region.strip(),
                aws_account_id=resolved_account_id,
                aws_access_key=request.aws_access_key.strip(),
                aws_secret_key=request.aws_secret_key.strip(),
                default_instance_type=self._normalize_optional_text(request.default_instance_type),
                default_vcpu=request.default_vcpu,
                account_total_vcpu=request.account_total_vcpu,
                default_architecture=self._normalize_optional_text(request.default_architecture),
                remarks=self._normalize_optional_text(request.remarks),
            )
        )
        normalized_default_inst = self._normalize_optional_text(request.default_instance_type)
        ami_id_for_insert = self._normalize_optional_text(request.ami_id)

        all_protocol_types = [request.protocol_type] + list(request.additional_protocol_types)
        all_protocol_types = [p for p in all_protocol_types if p]

        first_protocol_config_id: int | None = None
        for idx, proto_type in enumerate(all_protocol_types):
            is_first = (idx == 0)
            proto_config_id = self._asset_repo.upsert_asset_protocol_config(
                AssetProtocolConfigRequest(
                    asset_id=asset_id,
                    protocol_type=proto_type,
                    target_count=request.target_count,
                    max_count=request.max_count,
                    priority=request.priority if is_first else request.priority + idx,
                    allow_cdn_proxy=request.allow_cdn_proxy,
                    instance_type=normalized_default_inst,
                    vcpu=request.default_vcpu,
                    architecture="arm64",
                    ami_id=ami_id_for_insert,
                    subnet_id=subnet_id,
                    security_group_id=security_group_id,
                )
            )
            if is_first:
                first_protocol_config_id = proto_config_id

        self._asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=asset_id,
                event_type="asset_registered_from_dashboard",
                correlation_id=self._runtime_context.correlation_id,
                message="AWS asset registered from Streamlit dashboard.",
                payload={
                    "asset_name": request.asset_name.strip(),
                    "region": request.region.strip(),
                    "aws_account_id": resolved_account_id,
                    "protocol_type": request.protocol_type,
                },
            )
        )
        self._logger.info(
            "Registered AWS asset id=%s name=%s region=%s account_id=%s",
            asset_id,
            request.asset_name,
            request.region,
            resolved_account_id,
        )
        return AssetRegistrationResult(
            asset_id=asset_id,
            asset_name=request.asset_name.strip(),
            protocol_config_id=first_protocol_config_id,
        )

    @staticmethod
    def _validate_registration_request(request: AssetRegistrationRequest) -> None:
        if not request.asset_name or not request.asset_name.strip():
            raise ValueError("资产名称不能为空")
        if not request.region or not request.region.strip():
            raise ValueError("区域不能为空")
        if not request.aws_access_key or not request.aws_access_key.strip():
            raise ValueError("AWS Access Key 不能为空")
        if not request.aws_secret_key or not request.aws_secret_key.strip():
            raise ValueError("AWS Secret Key 不能为空")
        if request.default_vcpu is not None and request.default_vcpu <= 0:
            raise ValueError("默认 vCPU 必须大于 0")
        if request.protocol_type is not None:
            if request.target_count < 0:
                raise ValueError("target_count 不能小于 0")
            if request.max_count < 0:
                raise ValueError("max_count 不能小于 0")
            if request.max_count > 0 and request.target_count > request.max_count:
                raise ValueError("target_count 不能大于 max_count")

    def _resolve_account_id(self, request: AssetRegistrationRequest) -> str:
        """Resolve AWS Account ID: use provided value or auto-fetch via STS."""
        if request.aws_account_id and request.aws_account_id.strip():
            return request.aws_account_id.strip()
        if not request.aws_access_key or not request.aws_secret_key:
            raise StsClientError("需要 AK/SK 才能自动获取 AWS 账号 ID")
        identity = resolve_aws_account_id(
            aws_access_key=request.aws_access_key.strip(),
            aws_secret_key=request.aws_secret_key.strip(),
            aws_region=request.region.strip(),
            request_timeout_seconds=self._runtime_context.config.app.request_timeout_seconds,
            max_retries=self._runtime_context.config.app.max_retries,
        )
        self._logger.info(
            "Auto-resolved AWS account_id=%s from STS for asset=%s",
            identity.account_id,
            request.asset_name,
        )
        return identity.account_id

    def resolve_account_id(
        self,
        aws_access_key: str,
        aws_secret_key: str,
        aws_region: str,
    ) -> str:
        """Public endpoint for UI layer to resolve AWS account ID via STS."""
        identity = resolve_aws_account_id(
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
            aws_region=aws_region,
            request_timeout_seconds=self._runtime_context.config.app.request_timeout_seconds,
            max_retries=self._runtime_context.config.app.max_retries,
        )
        self._logger.info("Resolved AWS account_id=%s via UI action", identity.account_id)
        return identity.account_id

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def query_arm64_amis(
        self,
        aws_access_key: str,
        aws_secret_key: str,
        aws_region: str,
        name_filter: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, str]]:
        """Query arm64 AMIs visible in the given account/region."""
        ec2_client = self._build_ec2_client(
            aws_account_id="query",
            aws_region=aws_region,
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
        )
        self._logger.info(
            "Querying arm64 AMIs in region=%s name_filter=%s limit=%d",
            aws_region,
            name_filter,
            limit,
        )
        return ec2_client.list_arm64_amis(name_filter=name_filter, limit=limit)

    def _build_ec2_client(
        self,
        aws_account_id: str,
        aws_region: str,
        aws_access_key: str,
        aws_secret_key: str,
    ) -> EC2Client:
        credential = AwsCredentials(
            account_id=aws_account_id,
            access_key=aws_access_key,
            secret_key=aws_secret_key,
            region=aws_region,
        )
        return EC2Client(
            runtime_context=self._runtime_context,
            aws_credential=credential,
        )

    @staticmethod
    def _validate_self_hosted_request(request: SelfHostedAssetRegistrationRequest) -> None:
        if not request.asset_name or not request.asset_name.strip():
            raise ValueError("资产名称不能为空")
        if not request.host or not request.host.strip():
            raise ValueError("主机地址不能为空")
        if request.ssh_port <= 0 or request.ssh_port > 65535:
            raise ValueError("SSH 端口必须在 1-65535 之间")
        if not request.ssh_username or not request.ssh_username.strip():
            raise ValueError("SSH 用户名不能为空")
        if not request.ssh_password and not request.ssh_private_key:
            raise ValueError("必须提供 SSH 密码或私钥之一")
        if request.target_count < 0:
            raise ValueError("target_count 不能小于 0")
        if request.max_count < 0:
            raise ValueError("max_count 不能小于 0")
        if request.max_count > 0 and request.target_count > request.max_count:
            raise ValueError("target_count 不能大于 max_count")

    def probe_self_hosted_hardware(
        self,
        host: str,
        ssh_port: int,
        ssh_username: str,
        ssh_password: str | None,
        ssh_private_key: str | None,
    ) -> tuple[int, float]:
        """Connect to a self-hosted machine via SSH and detect CPU/memory specs."""
        ssh_config = SelfHostedSshConfig(
            host=host,
            port=ssh_port,
            username=ssh_username,
            password=ssh_password,
            private_key=ssh_private_key,
        )
        client = SelfHostedSshClient(
            runtime_context=self._runtime_context,
            ssh_config=ssh_config,
        )
        spec = client.detect_hardware()
        self._logger.info(
            "Self-hosted hardware probe success host=%s cpu_cores=%s memory_gb=%s",
            host,
            spec.cpu_cores,
            spec.memory_gb,
        )
        return spec.cpu_cores, spec.memory_gb

    def register_self_hosted_asset(
        self, request: SelfHostedAssetRegistrationRequest
    ) -> AssetRegistrationResult:
        """Register a self-hosted (自建) asset with automatic hardware probing via SSH."""
        self._validate_self_hosted_request(request)

        cpu_cores = request.cpu_cores
        memory_gb = request.memory_gb
        if cpu_cores is None or memory_gb is None:
            try:
                cpu_cores, memory_gb = self.probe_self_hosted_hardware(
                    host=request.host,
                    ssh_port=request.ssh_port,
                    ssh_username=request.ssh_username,
                    ssh_password=request.ssh_password,
                    ssh_private_key=request.ssh_private_key,
                )
            except Exception as exc:
                self._logger.warning(
                    "Hardware probe failed for host=%s: %s. Proceeding with null hardware fields.",
                    request.host,
                    exc,
                )

        asset_id = self._asset_repo.create_asset(
            AssetCreateRequest(
                asset_type="self_hosted",
                asset_name=request.asset_name.strip(),
                region=request.region.strip() if request.region else None,
                ssh_host=request.host.strip(),
                ssh_port=request.ssh_port,
                ssh_username=request.ssh_username.strip(),
                ssh_password=request.ssh_password.strip() if request.ssh_password else None,
                ssh_private_key=request.ssh_private_key.strip() if request.ssh_private_key else None,
                cpu_cores=cpu_cores,
                memory_gb=memory_gb,
                remarks=self._normalize_optional_text(request.remarks),
            )
        )

        protocol_config_ids: list[int] = []
        all_protocols: tuple[str, ...] = ()
        if request.protocol_type is not None:
            all_protocols = (request.protocol_type,) + request.additional_protocol_types
            for proto in all_protocols:
                config_id = self._asset_repo.upsert_asset_protocol_config(
                    AssetProtocolConfigRequest(
                        asset_id=asset_id,
                        protocol_type=proto,  # type: ignore[arg-type]
                        target_count=request.target_count,
                        max_count=request.max_count,
                        priority=request.priority,
                        allow_cdn_proxy=False,
                        requires_domain=("anytls" in proto.lower()),
                        requires_dns_record=("anytls" in proto.lower()),
                        supports_cdn_proxy=True,
                    )
                )
                if config_id is not None:
                    protocol_config_ids.append(config_id)

        self._asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=asset_id,
                event_type="asset_registered_from_dashboard",
                correlation_id=self._runtime_context.correlation_id,
                message="Self-hosted asset registered from Streamlit dashboard.",
                payload={
                    "asset_name": request.asset_name.strip(),
                    "region": request.region.strip() if request.region else None,
                    "host": request.host.strip(),
                    "protocol_types": list(all_protocols),
                    "cpu_cores": cpu_cores,
                    "memory_gb": memory_gb,
                },
            )
        )

        self._logger.info(
            "Registered self-hosted asset id=%s name=%s host=%s cpu=%s mem=%sGB protocols=%s",
            asset_id,
            request.asset_name,
            request.host,
            cpu_cores,
            memory_gb,
            list(all_protocols),
        )

        return AssetRegistrationResult(
            asset_id=asset_id,
            asset_name=request.asset_name.strip(),
            protocol_config_id=protocol_config_ids[0] if protocol_config_ids else None,
        )

    def delete_asset(self, asset_id: int) -> None:
        """Delete an asset after checking it has no active allocations."""
        active_count = self._asset_repo.get_active_allocations_count(asset_id)
        if active_count > 0:
            raise ValueError(
                f"资产 {asset_id} 仍有 {active_count} 个活跃分配记录，请先释放节点后再删除。"
            )
        asset = self._asset_repo.get_asset_by_id(asset_id)
        self._asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=asset_id,
                event_type="asset_deleted_from_dashboard",
                correlation_id=self._runtime_context.correlation_id,
                message="Asset deleted from Streamlit dashboard.",
                payload={
                    "asset_name": asset.asset_name,
                    "asset_type": asset.asset_type,
                    "region": asset.region,
                },
            )
        )
        self._asset_repo.delete_asset(asset_id)
        self._logger.info("Deleted asset id=%s name=%s", asset_id, asset.asset_name)
