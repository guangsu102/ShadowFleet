from __future__ import annotations


from infrastructure.cloudflare.cf_client import CFClient
from services.asset_selector_service import AssetSelectionResult
from services.provisioning_models import DnsRecordSnapshot, DnsSyncResult, ProtocolType
from services.provisioning_support import ProvisionerServiceError, build_dns_snapshot
from services.runtime_service import RuntimeContext


def sync_dns_records(
    runtime_context: RuntimeContext,
    protocol_type: ProtocolType,
    domain_name: str,
    selection_result: AssetSelectionResult,
    require_cdn_proxy: bool,
    ipv4_address: str | None,
    ipv6_address: str | None,
) -> DnsSyncResult:
    if not runtime_context.config.cloudflare.enabled:
        raise ProvisionerServiceError("Cloudflare must be enabled for DNS-required protocols")
    if ipv4_address is None and ipv6_address is None:
        raise ProvisionerServiceError("At least one IP address is required before DNS synchronization")

    cf_client = CFClient(runtime_context)
    proxied = require_cdn_proxy and selection_result.allow_cdn_proxy
    if protocol_type == "AnyTLS":
        proxied = False

    snapshots = capture_dns_snapshots(
        cf_client=cf_client,
        domain_name=domain_name,
        include_a=ipv4_address is not None,
        include_aaaa=ipv6_address is not None,
    )
    primary_record_id: str | None = None
    a_record_id: str | None = None
    aaaa_record_id: str | None = None
    if ipv6_address is not None:
        aaaa_record_id = cf_client.sync_aaaa_record(
            record_name=domain_name,
            ipv6_address=ipv6_address,
            proxied=proxied,
        )
        primary_record_id = aaaa_record_id
    if ipv4_address is not None:
        a_record_id = cf_client.sync_a_record(
            record_name=domain_name,
            ipv4_address=ipv4_address,
            proxied=proxied,
        )
        if primary_record_id is None:
            primary_record_id = a_record_id

    if primary_record_id is None:
        raise ProvisionerServiceError("Failed to determine a primary Cloudflare record id")
    return DnsSyncResult(
        primary_record_id=primary_record_id,
        a_record_id=a_record_id,
        aaaa_record_id=aaaa_record_id,
        snapshots=tuple(snapshots),
    )


def rollback_dns_records(
    runtime_context: RuntimeContext,
    dns_sync_result: DnsSyncResult,
) -> None:
    cf_client = CFClient(runtime_context)
    for snapshot in dns_sync_result.snapshots:
        current_record_id = (
            dns_sync_result.a_record_id if snapshot.record_type == "A" else dns_sync_result.aaaa_record_id
        )
        if current_record_id is None:
            continue

        if snapshot.existed:
            if snapshot.content is None:
                raise ProvisionerServiceError("Existing DNS snapshot content is missing")
            record_name = get_record_name_by_id(cf_client, current_record_id)
            cf_client.upsert_dns_record(
                record_name=record_name,
                record_type=snapshot.record_type,
                content=snapshot.content,
                proxied=snapshot.proxied,
                ttl=1,
            )
        else:
            cf_client.delete_dns_record(current_record_id)


def capture_dns_snapshots(
    cf_client: CFClient,
    domain_name: str,
    include_a: bool,
    include_aaaa: bool,
) -> list[DnsRecordSnapshot]:
    snapshots: list[DnsRecordSnapshot] = []
    if include_a:
        snapshots.append(
            build_dns_snapshot(
                "A",
                cf_client.get_dns_record(record_name=domain_name, record_type="A"),
            )
        )
    if include_aaaa:
        snapshots.append(
            build_dns_snapshot(
                "AAAA",
                cf_client.get_dns_record(record_name=domain_name, record_type="AAAA"),
            )
        )
    return snapshots


def get_record_name_by_id(cf_client: CFClient, record_id: str) -> str:
    record = cf_client.get_dns_record_by_id(record_id)
    record_name = record.get("name")
    if not isinstance(record_name, str) or not record_name.strip():
        raise ProvisionerServiceError(f"Cloudflare record name missing for record_id={record_id}")
    return record_name.strip()
