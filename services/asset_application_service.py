from __future__ import annotations

import hashlib


from database.asset_models import AssetCreateRequest, AssetEventCreateRequest, AssetProtocolConfigRequest
from database.asset_repo import AssetRepo
from infrastructure.aws.ec2_client import EC2Client
from infrastructure.aws.sts_client import StsClientError, resolve_aws_account_id
from infrastructure.azure import AzureClient, AzureCredentials, resolve_azure_vnet_name
from infrastructure.digitalocean import DigitalOceanClient
from infrastructure.oci import OCIClient, OCICredentials
from infrastructure.vultr import VultrClient
from infrastructure.self_hosted.ssh_client import SelfHostedSshClient, SelfHostedSshConfig
from models.aws_credentials import AwsCredentials
from services.asset_application_models import (
    AssetRegistrationRequest,
    AssetRegistrationResult,
    AzureAssetRegistrationRequest,
    DigitalOceanAssetRegistrationRequest,
    OCIAssetRegistrationRequest,
    SelfHostedAssetRegistrationRequest,
    VultrAssetRegistrationRequest,
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

    def register_digitalocean_asset(
        self,
        request: DigitalOceanAssetRegistrationRequest,
    ) -> AssetRegistrationResult:
        self._validate_digitalocean_registration_request(request)

        client = self._build_digitalocean_client(request.digitalocean_token)
        account = client.validate_account()
        account_id = self._normalize_optional_text(str(account.get("uuid") or "")) or "digitalocean"

        tags = tuple(tag.strip() for tag in request.tags if tag and tag.strip())
        provider_config: dict[str, object] = {
            "ssh_keys": [key.strip() for key in request.ssh_keys if key and key.strip()],
            "tags": list(dict.fromkeys(("shadowfleet", *tags))),
        }
        vpc_uuid = self._normalize_optional_text(request.vpc_uuid)
        if vpc_uuid:
            provider_config["vpc_uuid"] = vpc_uuid

        asset_id = self._asset_repo.create_asset(
            AssetCreateRequest(
                asset_type="digitalocean",
                asset_name=request.asset_name.strip(),
                region=request.region.strip(),
                aws_account_id=account_id,
                aws_access_key=request.digitalocean_token.strip(),
                default_instance_type=request.default_size.strip(),
                default_vcpu=request.default_vcpu,
                default_architecture="x64",
                provider_config=provider_config,
                remarks=self._normalize_optional_text(request.remarks),
            )
        )

        all_protocol_types = [request.protocol_type] + list(request.additional_protocol_types)
        all_protocol_types = [p for p in all_protocol_types if p]

        first_protocol_config_id: int | None = None
        for idx, proto_type in enumerate(all_protocol_types):
            is_first = idx == 0
            protocol_config_id = self._asset_repo.upsert_asset_protocol_config(
                AssetProtocolConfigRequest(
                    asset_id=asset_id,
                    protocol_type=proto_type,
                    target_count=request.target_count,
                    max_count=request.max_count,
                    priority=request.priority if is_first else request.priority + idx,
                    allow_cdn_proxy=request.allow_cdn_proxy,
                    instance_type=request.default_size.strip(),
                    vcpu=request.default_vcpu,
                    architecture="x64",
                    ami_id=request.default_image.strip(),
                    subnet_id=vpc_uuid,
                )
            )
            if is_first:
                first_protocol_config_id = protocol_config_id

        self._asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=asset_id,
                event_type="asset_registered_from_dashboard",
                correlation_id=self._runtime_context.correlation_id,
                message="DigitalOcean asset registered from dashboard.",
                payload={
                    "asset_name": request.asset_name.strip(),
                    "region": request.region.strip(),
                    "account_id": account_id,
                    "protocol_type": request.protocol_type,
                },
            )
        )
        self._logger.info(
            "Registered DigitalOcean asset id=%s name=%s region=%s account_id=%s",
            asset_id,
            request.asset_name,
            request.region,
            account_id,
        )
        return AssetRegistrationResult(
            asset_id=asset_id,
            asset_name=request.asset_name.strip(),
            protocol_config_id=first_protocol_config_id,
        )

    def register_vultr_asset(
        self,
        request: VultrAssetRegistrationRequest,
    ) -> AssetRegistrationResult:
        self._validate_vultr_registration_request(request)
        vultr_client = self._build_vultr_client(request.vultr_token)
        vultr_client.validate_account()
        provider_account_id = self._vultr_provider_account_id(request.vultr_token)

        tags = tuple(tag.strip() for tag in request.tags if tag and tag.strip())
        provider_config: dict[str, object] = {
            "ssh_key_ids": [key.strip() for key in request.ssh_key_ids if key and key.strip()],
            "tags": list(dict.fromkeys(("shadowfleet", *tags))),
        }
        vpc_ids = tuple(
            dict.fromkeys(vpc_id.strip() for vpc_id in request.vpc_ids if vpc_id and vpc_id.strip())
        )
        legacy_vpc_id = self._normalize_optional_text(request.vpc2)
        if not vpc_ids and legacy_vpc_id:
            vpc_ids = (legacy_vpc_id,)
        firewall_group_id = self._normalize_optional_text(request.firewall_group_id)
        vultr_client.validate_provisioning_target(
            region=request.region.strip(),
            plan=request.default_plan.strip(),
            os_id=request.default_os_id,
            ssh_key_ids=tuple(provider_config["ssh_key_ids"]),
            vpc_ids=vpc_ids,
            firewall_group_id=firewall_group_id,
        )
        if vpc_ids:
            provider_config["vpc_ids"] = list(vpc_ids)
        if firewall_group_id:
            provider_config["firewall_group_id"] = firewall_group_id

        asset_id = self._asset_repo.create_asset(
            AssetCreateRequest(
                asset_type="vultr",
                asset_name=request.asset_name.strip(),
                region=request.region.strip(),
                aws_account_id=provider_account_id,
                aws_access_key=request.vultr_token.strip(),
                default_instance_type=request.default_plan.strip(),
                default_vcpu=request.default_vcpu,
                default_architecture="x64",
                provider_config=provider_config,
                remarks=self._normalize_optional_text(request.remarks),
            )
        )
        all_protocol_types = [request.protocol_type] + list(request.additional_protocol_types)
        all_protocol_types = [protocol for protocol in all_protocol_types if protocol]

        first_protocol_config_id: int | None = None
        for index, protocol_type in enumerate(all_protocol_types):
            is_first = index == 0
            protocol_config_id = self._asset_repo.upsert_asset_protocol_config(
                AssetProtocolConfigRequest(
                    asset_id=asset_id,
                    protocol_type=protocol_type,
                    target_count=request.target_count,
                    max_count=request.max_count,
                    priority=request.priority if is_first else request.priority + index,
                    allow_cdn_proxy=request.allow_cdn_proxy,
                    instance_type=request.default_plan.strip(),
                    vcpu=request.default_vcpu,
                    architecture="x64",
                    ami_id=str(request.default_os_id),
                    subnet_id=vpc_ids[0] if vpc_ids else None,
                    security_group_id=firewall_group_id,
                )
            )
            if is_first:
                first_protocol_config_id = protocol_config_id

        self._asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=asset_id,
                event_type="asset_registered_from_dashboard",
                correlation_id=self._runtime_context.correlation_id,
                message="Vultr asset registered from dashboard.",
                payload={
                    "asset_name": request.asset_name.strip(),
                    "region": request.region.strip(),
                    "protocol_type": request.protocol_type,
                },
            )
        )
        self._logger.info(
            "Registered Vultr asset id=%s name=%s region=%s",
            asset_id,
            request.asset_name,
            request.region,
        )
        return AssetRegistrationResult(
            asset_id=asset_id,
            asset_name=request.asset_name.strip(),
            protocol_config_id=first_protocol_config_id,
        )

    def register_azure_asset(
        self,
        request: AzureAssetRegistrationRequest,
    ) -> AssetRegistrationResult:
        self._validate_azure_registration_request(request)
        credentials = AzureCredentials(
            tenant_id=request.tenant_id.strip(),
            client_id=request.client_id.strip(),
            client_secret=request.client_secret.strip(),
            subscription_id=request.subscription_id.strip(),
        )
        azure_client = self._build_azure_client(credentials)
        azure_client.validate_subscription()
        provider_account_id = f"azure:{request.subscription_id.strip().lower()}"
        tags = tuple(tag.strip() for tag in request.tags if tag and tag.strip())
        vnet_name = resolve_azure_vnet_name(request.region, request.vnet_name)
        azure_client.validate_provisioning_target(
            location=request.region.strip(),
            vm_size=request.default_vm_size.strip(),
            resource_group=request.resource_group.strip(),
            vnet_name=vnet_name,
            subnet_name=request.subnet_name.strip(),
        )
        provider_config: dict[str, object] = {
            "tenant_id": request.tenant_id.strip(),
            "subscription_id": request.subscription_id.strip(),
            "resource_group": request.resource_group.strip(),
            "ssh_public_key": request.ssh_public_key.strip(),
            "admin_username": request.admin_username.strip(),
            "image_publisher": request.image_publisher.strip(),
            "image_offer": request.image_offer.strip(),
            "image_sku": request.image_sku.strip(),
            "image_version": request.image_version.strip(),
            "vnet_name": vnet_name,
            "subnet_name": request.subnet_name.strip(),
            "tags": list(dict.fromkeys(("shadowfleet", *tags))),
        }
        asset_id = self._asset_repo.create_asset(
            AssetCreateRequest(
                asset_type="azure",
                asset_name=request.asset_name.strip(),
                region=request.region.strip(),
                aws_account_id=provider_account_id,
                aws_access_key=request.client_id.strip(),
                aws_secret_key=request.client_secret.strip(),
                default_instance_type=request.default_vm_size.strip(),
                default_vcpu=request.default_vcpu,
                default_architecture="x64",
                provider_config=provider_config,
                remarks=self._normalize_optional_text(request.remarks),
            )
        )
        protocol_types = [request.protocol_type, *request.additional_protocol_types]
        first_protocol_config_id: int | None = None
        for index, protocol_type in enumerate(protocol for protocol in protocol_types if protocol):
            protocol_config_id = self._asset_repo.upsert_asset_protocol_config(
                AssetProtocolConfigRequest(
                    asset_id=asset_id,
                    protocol_type=protocol_type,
                    target_count=request.target_count,
                    max_count=request.max_count,
                    priority=request.priority + index,
                    allow_cdn_proxy=request.allow_cdn_proxy,
                    instance_type=request.default_vm_size.strip(),
                    vcpu=request.default_vcpu,
                    architecture="x64",
                )
            )
            if first_protocol_config_id is None:
                first_protocol_config_id = protocol_config_id

        self._asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=asset_id,
                event_type="asset_registered_from_dashboard",
                correlation_id=self._runtime_context.correlation_id,
                message="Azure asset registered from dashboard.",
                payload={
                    "asset_name": request.asset_name.strip(),
                    "region": request.region.strip(),
                    "subscription_id": request.subscription_id.strip(),
                    "resource_group": request.resource_group.strip(),
                    "protocol_type": request.protocol_type,
                },
            )
        )
        self._logger.info(
            "Registered Azure asset id=%s name=%s region=%s subscription_id=%s",
            asset_id,
            request.asset_name,
            request.region,
            request.subscription_id,
        )
        return AssetRegistrationResult(
            asset_id=asset_id,
            asset_name=request.asset_name.strip(),
            protocol_config_id=first_protocol_config_id,
        )

    def register_oci_asset(
        self,
        request: OCIAssetRegistrationRequest,
    ) -> AssetRegistrationResult:
        self._validate_oci_registration_request(request)
        credentials = OCICredentials(
            tenancy_ocid=request.tenancy_ocid.strip(),
            user_ocid=request.user_ocid.strip(),
            fingerprint=request.fingerprint.strip(),
            private_key=request.private_key.strip(),
            private_key_passphrase=request.private_key_passphrase,
        )
        client = self._build_oci_client(credentials, request.region.strip())
        client.validate_identity()
        target = client.validate_provisioning_target(
            compartment_ocid=request.compartment_ocid.strip(),
            subnet_ocid=request.subnet_ocid.strip(),
            network_security_group_ocid=request.network_security_group_ocid.strip(),
            image_ocid=request.image_ocid.strip(),
            shape=request.shape.strip(),
            availability_domain=self._normalize_optional_text(request.availability_domain),
        )
        if not target.is_flexible_shape and (
            request.ocpus is not None or request.memory_in_gbs is not None
        ):
            raise ValueError(
                "OCPU and memory overrides are only valid for flexible OCI shapes"
            )
        freeform_tags: dict[str, str] = {}
        for raw_tag in request.tags:
            tag = raw_tag.strip()
            if not tag:
                continue
            key, separator, value = tag.partition("=")
            freeform_tags[key.strip()] = value.strip() if separator else "true"

        provider_config: dict[str, object] = {
            "tenancy_ocid": request.tenancy_ocid.strip(),
            "fingerprint": request.fingerprint.strip(),
            "compartment_ocid": request.compartment_ocid.strip(),
            "subnet_ocid": request.subnet_ocid.strip(),
            "network_security_group_ocid": request.network_security_group_ocid.strip(),
            "image_ocid": request.image_ocid.strip(),
            "ssh_public_key": request.ssh_public_key.strip(),
            "availability_domain": target.availability_domain,
            "shape_is_flexible": target.is_flexible_shape,
            "freeform_tags": freeform_tags,
        }
        if request.private_key_passphrase is not None:
            provider_config["private_key_passphrase"] = request.private_key_passphrase
        if request.ocpus is not None:
            provider_config["ocpus"] = request.ocpus
        if request.memory_in_gbs is not None:
            provider_config["memory_in_gbs"] = request.memory_in_gbs

        asset_id = self._asset_repo.create_asset(
            AssetCreateRequest(
                asset_type="oci",
                asset_name=request.asset_name.strip(),
                region=request.region.strip(),
                aws_account_id=f"oci:{request.tenancy_ocid.strip()}",
                aws_access_key=request.user_ocid.strip(),
                aws_secret_key=request.private_key.strip(),
                default_instance_type=request.shape.strip(),
                default_vcpu=request.default_vcpu,
                default_architecture="x64",
                provider_config=provider_config,
                remarks=self._normalize_optional_text(request.remarks),
            )
        )
        protocol_types = [request.protocol_type, *request.additional_protocol_types]
        first_protocol_config_id: int | None = None
        for index, protocol_type in enumerate(protocol for protocol in protocol_types if protocol):
            protocol_config_id = self._asset_repo.upsert_asset_protocol_config(
                AssetProtocolConfigRequest(
                    asset_id=asset_id,
                    protocol_type=protocol_type,
                    target_count=request.target_count,
                    max_count=request.max_count,
                    priority=request.priority + index,
                    allow_cdn_proxy=request.allow_cdn_proxy,
                    instance_type=request.shape.strip(),
                    vcpu=request.default_vcpu,
                    architecture="x64",
                    ami_id=request.image_ocid.strip(),
                    subnet_id=request.subnet_ocid.strip(),
                    security_group_id=request.network_security_group_ocid.strip(),
                )
            )
            if first_protocol_config_id is None:
                first_protocol_config_id = protocol_config_id

        self._asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=asset_id,
                event_type="asset_registered_from_dashboard",
                correlation_id=self._runtime_context.correlation_id,
                message="OCI asset registered from dashboard.",
                payload={
                    "asset_name": request.asset_name.strip(),
                    "region": request.region.strip(),
                    "tenancy_ocid": request.tenancy_ocid.strip(),
                    "compartment_ocid": request.compartment_ocid.strip(),
                    "protocol_type": request.protocol_type,
                },
            )
        )
        self._logger.info(
            "Registered OCI asset id=%s name=%s region=%s tenancy=%s",
            asset_id,
            request.asset_name,
            request.region,
            request.tenancy_ocid,
        )
        return AssetRegistrationResult(
            asset_id=asset_id,
            asset_name=request.asset_name.strip(),
            protocol_config_id=first_protocol_config_id,
        )



    @staticmethod
    def _vultr_provider_account_id(api_token: str) -> str:
        fingerprint = hashlib.sha256(api_token.strip().encode("utf-8")).hexdigest()[:24]
        return f"vultr:{fingerprint}"

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

    def query_digitalocean_images(
        self,
        digitalocean_token: str,
        image_type: str = "distribution",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        return self._build_digitalocean_client(digitalocean_token).list_images(
            image_type=image_type,
            per_page=limit,
        )

    def query_digitalocean_sizes(
        self,
        digitalocean_token: str,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        return self._build_digitalocean_client(digitalocean_token).list_sizes(per_page=limit)

    def query_vultr_catalog(self, vultr_token: str) -> dict[str, list[dict[str, object]]]:
        client = self._build_vultr_client(vultr_token)
        client.validate_account()
        return {
            "regions": client.list_regions(),
            "plans": client.list_plans(),
            "operating_systems": client.list_operating_systems(),
            "ssh_keys": client.list_ssh_keys(),
            "vpcs": client.list_vpcs(),
            "firewall_groups": client.list_firewall_groups(),
        }

    def query_azure_catalog(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        subscription_id: str,
        location: str | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        client = self._build_azure_client(
            AzureCredentials(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
                subscription_id=subscription_id,
            )
        )
        client.validate_subscription()
        return {
            "locations": client.list_locations(),
            "vm_sizes": client.list_vm_sizes(location.strip()) if location and location.strip() else [],
        }
    def query_oci_catalog(
        self,
        *,
        region: str,
        tenancy_ocid: str,
        user_ocid: str,
        fingerprint: str,
        private_key: str,
        compartment_ocid: str,
        private_key_passphrase: str | None = None,
        availability_domain: str | None = None,
        operating_system: str | None = "Canonical Ubuntu",
    ) -> dict[str, list[dict[str, object]]]:
        client = self._build_oci_client(
            OCICredentials(
                tenancy_ocid=tenancy_ocid,
                user_ocid=user_ocid,
                fingerprint=fingerprint,
                private_key=private_key,
                private_key_passphrase=private_key_passphrase,
            ),
            region,
        )
        client.validate_identity()
        domains = client.list_availability_domains(compartment_ocid)
        selected_domain = self._normalize_optional_text(availability_domain)
        return {
            "availability_domains": domains,
            "images": client.list_images(
                compartment_ocid,
                operating_system=operating_system,
            ),
            "shapes": client.list_shapes(
                compartment_ocid,
                availability_domain=selected_domain,
            ),
            "subnets": client.list_subnets(compartment_ocid),
            "network_security_groups": client.list_network_security_groups(
                compartment_ocid
            ),
        }

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

    def _build_digitalocean_client(self, digitalocean_token: str) -> DigitalOceanClient:
        return DigitalOceanClient(
            runtime_context=self._runtime_context,
            api_token=digitalocean_token,
        )

    def _build_vultr_client(self, vultr_token: str) -> VultrClient:
        return VultrClient(
            runtime_context=self._runtime_context,
            api_token=vultr_token,
        )

    def _build_azure_client(self, credentials: AzureCredentials) -> AzureClient:
        return AzureClient(runtime_context=self._runtime_context, credentials=credentials)

    def _build_oci_client(
        self,
        credentials: OCICredentials,
        region: str,
    ) -> OCIClient:
        return OCIClient(
            runtime_context=self._runtime_context,
            credentials=credentials,
            region=region,
        )

    @staticmethod
    def _validate_digitalocean_registration_request(
        request: DigitalOceanAssetRegistrationRequest,
    ) -> None:
        if not request.asset_name or not request.asset_name.strip():
            raise ValueError("资产名称不能为空")
        if not request.region or not request.region.strip():
            raise ValueError("区域不能为空")
        if not request.digitalocean_token or not request.digitalocean_token.strip():
            raise ValueError("DigitalOcean Token 不能为空")
        if not request.default_size or not request.default_size.strip():
            raise ValueError("DigitalOcean size 不能为空")
        if not request.default_image or not request.default_image.strip():
            raise ValueError("DigitalOcean image 不能为空")
        if request.default_vcpu is not None and request.default_vcpu <= 0:
            raise ValueError("默认 vCPU 必须大于 0")
        if request.target_count < 0:
            raise ValueError("target_count 不能小于 0")
        if request.max_count < 0:
            raise ValueError("max_count 不能小于 0")
        if request.max_count > 0 and request.target_count > request.max_count:
            raise ValueError("target_count 不能大于 max_count")

    @staticmethod
    def _validate_vultr_registration_request(request: VultrAssetRegistrationRequest) -> None:
        if not request.asset_name or not request.asset_name.strip():
            raise ValueError("资产名称不能为空")
        if not request.region or not request.region.strip():
            raise ValueError("区域不能为空")
        if not request.vultr_token or not request.vultr_token.strip():
            raise ValueError("Vultr Token 不能为空")
        if not request.default_plan or not request.default_plan.strip():
            raise ValueError("Vultr Plan 不能为空")
        if request.default_os_id <= 0:
            raise ValueError("Vultr OS ID 必须大于 0")
        if request.default_vcpu is not None and request.default_vcpu <= 0:
            raise ValueError("默认 vCPU 必须大于 0")
        if request.target_count < 0:
            raise ValueError("target_count 不能小于 0")
        if request.max_count < 0:
            raise ValueError("max_count 不能小于 0")
        if request.max_count > 0 and request.target_count > request.max_count:
            raise ValueError("target_count 不能大于 max_count")

    @staticmethod
    def _validate_oci_registration_request(
        request: OCIAssetRegistrationRequest,
    ) -> None:
        required = {
            "资产名称": request.asset_name,
            "OCI 区域": request.region,
            "Tenancy OCID": request.tenancy_ocid,
            "User OCID": request.user_ocid,
            "Fingerprint": request.fingerprint,
            "PEM 私钥": request.private_key,
            "Compartment OCID": request.compartment_ocid,
            "Subnet OCID": request.subnet_ocid,
            "NSG OCID": request.network_security_group_ocid,
            "Image OCID": request.image_ocid,
            "Shape": request.shape,
            "SSH 公钥": request.ssh_public_key,
        }
        for label, value in required.items():
            if not value or not value.strip():
                raise ValueError(f"{label}不能为空")
        if request.ocpus is not None and request.ocpus <= 0:
            raise ValueError("OCPU 必须大于 0")
        if request.memory_in_gbs is not None and request.memory_in_gbs <= 0:
            raise ValueError("内存必须大于 0")
        if request.default_vcpu is not None and request.default_vcpu <= 0:
            raise ValueError("默认 vCPU 必须大于 0")
        if request.target_count < 0 or request.max_count < 0:
            raise ValueError("target_count 和 max_count 不能小于 0")
        if request.max_count > 0 and request.target_count > request.max_count:
            raise ValueError("target_count 不能大于 max_count")

    @staticmethod
    def _validate_azure_registration_request(request: AzureAssetRegistrationRequest) -> None:
        required = {
            "资产名称": request.asset_name,
            "Azure 区域": request.region,
            "Tenant ID": request.tenant_id,
            "Client ID": request.client_id,
            "Client Secret": request.client_secret,
            "Subscription ID": request.subscription_id,
            "Resource Group": request.resource_group,
            "SSH 公钥": request.ssh_public_key,
            "VM Size": request.default_vm_size,
            "管理员用户名": request.admin_username,
        }
        for label, value in required.items():
            if not value or not value.strip():
                raise ValueError(f"{label}不能为空")
        if request.default_vcpu is not None and request.default_vcpu <= 0:
            raise ValueError("默认 vCPU 必须大于 0")
        if request.target_count < 0 or request.max_count < 0:
            raise ValueError("target_count 和 max_count 不能小于 0")
        if request.max_count > 0 and request.target_count > request.max_count:
            raise ValueError("target_count 不能大于 max_count")

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
