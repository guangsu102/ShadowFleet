from __future__ import annotations

import base64
from dataclasses import dataclass
import time
from typing import Any

import requests

from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import execute_with_backoff


DEFAULT_BASE_URL = "https://api.vultr.com/v2"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MANAGED_FIREWALL_DESCRIPTION_PREFIX = "ShadowFleet managed:"


class VultrClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class VultrInstanceLaunchRequest:
    label: str
    region: str
    plan: str
    os_id: int
    user_data: str
    ssh_key_ids: tuple[str, ...] = ()
    vpc_ids: tuple[str, ...] = ()
    firewall_group_id: str | None = None
    tags: tuple[str, ...] = ()
    enable_ipv6: bool = True


@dataclass(frozen=True)
class VultrInstanceLaunchResult:
    instance_id: str
    label: str
    region: str
    plan: str
    os_id: int
    ipv4_address: str | None
    ipv6_address: str | None
    subnet_id: str | None = None


@dataclass(frozen=True)
class VultrFirewallEnsureResult:
    firewall_group_id: str
    created: bool


class VultrClient:
    """Small adapter around Vultr API v2 instance operations."""

    def __init__(
        self,
        runtime_context: RuntimeContext,
        api_token: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        if not api_token or not api_token.strip():
            raise ValueError("Vultr API token must not be empty")

        self._logger = runtime_context.logger.getChild("infrastructure.vultr")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._base_url = base_url.rstrip("/")
        self._created_instance_id: str | None = None
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_token.strip()}",
                "Content-Type": "application/json",
            }
        )

    def validate_account(self) -> dict[str, Any]:
        payload = self._request("GET", "/account")
        account = payload.get("account", payload)
        if not isinstance(account, dict):
            raise VultrClientError("Vultr account response missing account payload")
        return account

    def list_instances(self, per_page: int = 500) -> list[dict[str, Any]]:
        return self._list_collection("/instances", "instances", per_page=per_page)

    def list_regions(self, per_page: int = 500) -> list[dict[str, Any]]:
        return self._list_collection("/regions", "regions", per_page=per_page)

    def list_plans(self, per_page: int = 500) -> list[dict[str, Any]]:
        return self._list_collection("/plans", "plans", per_page=per_page)

    def list_operating_systems(self, per_page: int = 500) -> list[dict[str, Any]]:
        return self._list_collection("/os", "os", per_page=per_page)

    def list_ssh_keys(self, per_page: int = 500) -> list[dict[str, Any]]:
        return self._list_collection("/ssh-keys", "ssh_keys", per_page=per_page)

    def list_vpcs(self, per_page: int = 500) -> list[dict[str, Any]]:
        return self._list_collection("/vpcs", "vpcs", per_page=per_page)

    def list_firewall_groups(self, per_page: int = 500) -> list[dict[str, Any]]:
        return self._list_collection("/firewalls", "firewall_groups", per_page=per_page)

    def get_firewall_group(self, firewall_group_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/firewalls/{firewall_group_id}")
        firewall_group = payload.get("firewall_group")
        if not isinstance(firewall_group, dict):
            raise VultrClientError(
                f"Vultr firewall response missing firewall_group: {firewall_group_id}"
            )
        return firewall_group

    def create_firewall_group(self, description: str) -> str:
        payload = self._request(
            "POST",
            "/firewalls",
            payload={"description": description},
            expected_status={201},
        )
        firewall_group = payload.get("firewall_group")
        if not isinstance(firewall_group, dict) or not firewall_group.get("id"):
            raise VultrClientError("Vultr create firewall response missing firewall_group.id")
        firewall_group_id = str(firewall_group["id"])
        set_event_type("vultr_firewall_group_created")
        return firewall_group_id

    def delete_firewall_group(self, firewall_group_id: str) -> None:
        self._request(
            "DELETE",
            f"/firewalls/{firewall_group_id}",
            expected_status={204, 404},
        )
        set_event_type("vultr_firewall_group_deleted")

    def delete_managed_firewall_group(self, firewall_group_id: str) -> bool:
        try:
            firewall_group = self.get_firewall_group(firewall_group_id)
        except VultrClientError as exc:
            if exc.status_code == 404:
                return False
            raise
        description = str(firewall_group.get("description") or "")
        if not description.startswith(MANAGED_FIREWALL_DESCRIPTION_PREFIX):
            return False
        self.delete_firewall_group(firewall_group_id)
        return True

    def list_firewall_rules(
        self,
        firewall_group_id: str,
        per_page: int = 500,
    ) -> list[dict[str, Any]]:
        return self._list_collection(
            f"/firewalls/{firewall_group_id}/rules",
            "firewall_rules",
            per_page=per_page,
        )

    def create_firewall_rule(
        self,
        firewall_group_id: str,
        *,
        ip_type: str,
        port: int,
    ) -> dict[str, Any]:
        if ip_type not in {"v4", "v6"}:
            raise ValueError("ip_type must be v4 or v6")
        if port <= 0 or port > 65535:
            raise ValueError("port must be between 1 and 65535")
        payload = self._request(
            "POST",
            f"/firewalls/{firewall_group_id}/rules",
            payload={
                "ip_type": ip_type,
                "protocol": "tcp",
                "subnet": "0.0.0.0" if ip_type == "v4" else "::",
                "subnet_size": 0,
                "port": str(port),
                "notes": "ShadowFleet managed inbound TCP",
            },
            expected_status={201},
        )
        firewall_rule = payload.get("firewall_rule")
        if not isinstance(firewall_rule, dict):
            raise VultrClientError("Vultr create firewall rule response is missing firewall_rule")
        set_event_type("vultr_firewall_rule_created")
        return firewall_rule

    def ensure_firewall_ports(
        self,
        *,
        firewall_group_id: str | None,
        label: str,
        inbound_ports: tuple[int, ...],
    ) -> VultrFirewallEnsureResult:
        normalized_ports = tuple(dict.fromkeys(inbound_ports))
        if not normalized_ports:
            raise ValueError("inbound_ports must not be empty")
        for port in normalized_ports:
            if port <= 0 or port > 65535:
                raise ValueError("inbound port must be between 1 and 65535")

        created = False
        if firewall_group_id:
            self.get_firewall_group(firewall_group_id)
            group_id = firewall_group_id
        else:
            group_id = self.create_firewall_group(
                f"{MANAGED_FIREWALL_DESCRIPTION_PREFIX} {label}"
            )
            created = True

        try:
            existing_rules = self.list_firewall_rules(group_id)
            for ip_type in ("v4", "v6"):
                for port in normalized_ports:
                    if any(
                        _firewall_rule_allows_tcp_port(rule, ip_type, port)
                        for rule in existing_rules
                    ):
                        continue
                    existing_rules.append(
                        self.create_firewall_rule(
                            group_id,
                            ip_type=ip_type,
                            port=port,
                        )
                    )
        except Exception:
            if created:
                try:
                    self.delete_firewall_group(group_id)
                except Exception:
                    self._logger.exception(
                        "Failed to rollback Vultr firewall group id=%s", group_id
                    )
            raise
        return VultrFirewallEnsureResult(
            firewall_group_id=group_id,
            created=created,
        )

    def validate_provisioning_target(
        self,
        *,
        region: str,
        plan: str,
        os_id: int,
        ssh_key_ids: tuple[str, ...] = (),
        vpc_ids: tuple[str, ...] = (),
        firewall_group_id: str | None = None,
    ) -> None:
        selected_region = _require_catalog_item(
            self.list_regions(),
            region,
            id_fields=("id",),
            resource_name="region",
        )
        if selected_region.get("available") is False:
            raise VultrClientError(f"Vultr region is unavailable: {region}")

        selected_plan = _require_catalog_item(
            self.list_plans(),
            plan,
            id_fields=("id",),
            resource_name="plan",
        )
        plan_locations = selected_plan.get("locations")
        if (
            isinstance(plan_locations, list)
            and plan_locations
            and region.casefold()
            not in {str(item).casefold() for item in plan_locations}
        ):
            raise VultrClientError(
                f"Vultr plan {plan!r} is not available in region {region!r}"
            )

        _require_catalog_item(
            self.list_operating_systems(),
            str(os_id),
            id_fields=("id",),
            resource_name="operating system",
        )
        ssh_keys = self.list_ssh_keys() if ssh_key_ids else []
        for ssh_key_id in ssh_key_ids:
            _require_catalog_item(
                ssh_keys,
                ssh_key_id,
                id_fields=("id",),
                resource_name="SSH key",
            )
        vpcs = self.list_vpcs() if vpc_ids else []
        for vpc_id in vpc_ids:
            vpc = _require_catalog_item(
                vpcs,
                vpc_id,
                id_fields=("id",),
                resource_name="VPC",
            )
            vpc_region = _optional_text(vpc.get("region"))
            if vpc_region and vpc_region.casefold() != region.casefold():
                raise VultrClientError(
                    f"Vultr VPC {vpc_id!r} is in {vpc_region!r}, "
                    f"not {region!r}"
                )
        if firewall_group_id:
            self.get_firewall_group(firewall_group_id)

    @property
    def created_instance_id(self) -> str | None:
        """The most recently created instance, including while activation is pending."""
        return self._created_instance_id

    def launch_instance(
        self,
        request: VultrInstanceLaunchRequest,
        wait_timeout_seconds: int = 300,
        poll_interval_seconds: float = 5.0,
    ) -> VultrInstanceLaunchResult:
        encoded_user_data = base64.b64encode(request.user_data.encode("utf-8")).decode("ascii")
        payload: dict[str, object] = {
            "region": request.region,
            "plan": request.plan,
            "os_id": request.os_id,
            "label": request.label,
            "enable_ipv6": request.enable_ipv6,
            "user_data": encoded_user_data,
            "tags": list(request.tags),
        }
        if request.ssh_key_ids:
            payload["sshkey_id"] = list(request.ssh_key_ids)
        if request.vpc_ids:
            payload["attach_vpc"] = list(request.vpc_ids)
        if request.firewall_group_id:
            payload["firewall_group_id"] = request.firewall_group_id

        response_payload = self._request("POST", "/instances", payload=payload, expected_status={201})
        instance = response_payload.get("instance")
        if not isinstance(instance, dict) or not instance.get("id"):
            raise VultrClientError("Vultr create instance response missing instance.id")

        instance_id = str(instance["id"])
        self._created_instance_id = instance_id
        set_event_type("vultr_instance_created")
        self._logger.info("Created Vultr instance id=%s label=%s", instance_id, request.label)
        instance = self.wait_for_instance_running(
            instance_id=instance_id,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        return self._map_launch_result(instance, request)

    def get_instance(self, instance_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/instances/{instance_id}")
        instance = payload.get("instance")
        if not isinstance(instance, dict):
            raise VultrClientError(f"Vultr instance not found: {instance_id}")
        return instance

    def get_instance_user_data(self, instance_id: str) -> str:
        payload = self._request("GET", f"/instances/{instance_id}/user-data")
        user_data = payload.get("user_data")
        encoded_data = user_data.get("data") if isinstance(user_data, dict) else None
        if not isinstance(encoded_data, str) or not encoded_data.strip():
            raise VultrClientError(
                f"Vultr instance user-data is missing for instance: {instance_id}"
            )
        try:
            return base64.b64decode(encoded_data, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise VultrClientError(
                f"Vultr instance user-data is invalid for instance: {instance_id}"
            ) from exc

    def list_instance_vpcs(self, instance_id: str) -> list[dict[str, Any]]:
        return self._list_collection(
            f"/instances/{instance_id}/vpcs",
            "vpcs",
            per_page=500,
        )

    def wait_for_instance_running(
        self,
        instance_id: str,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            instance = self.get_instance(instance_id)
            if (
                instance.get("status") == "active"
                and instance.get("power_status") == "running"
                and instance.get("server_status") == "ok"
            ):
                return instance
            time.sleep(poll_interval_seconds)
        raise VultrClientError(f"Timed out waiting for Vultr instance to become running: {instance_id}")

    def delete_instance(self, instance_id: str) -> None:
        self._request("DELETE", f"/instances/{instance_id}", expected_status={204, 404})
        set_event_type("vultr_instance_deleted")
        self._logger.info("Deleted Vultr instance id=%s", instance_id)

    def _list_collection(
        self,
        endpoint: str,
        collection_key: str,
        *,
        per_page: int,
    ) -> list[dict[str, Any]]:
        if per_page <= 0:
            raise ValueError("per_page must be greater than 0")

        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, object] = {"per_page": min(per_page, 500)}
            if cursor:
                params["cursor"] = cursor
            payload = self._request("GET", endpoint, params=params)
            page_items = payload.get(collection_key, [])
            if not isinstance(page_items, list):
                raise VultrClientError(f"Vultr {collection_key} response must be a list")
            items.extend(item for item in page_items if isinstance(item, dict))

            meta = payload.get("meta")
            links = meta.get("links") if isinstance(meta, dict) else None
            next_link = links.get("next") if isinstance(links, dict) else None
            next_cursor = _cursor_from_link(next_link)
            if not next_cursor or next_cursor == cursor:
                return items
            cursor = next_cursor

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
        expected_status: set[int] | None = None,
    ) -> dict[str, Any]:
        expected = expected_status or {200}
        url = f"{self._base_url}{endpoint}"

        def _send_request() -> dict[str, Any]:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                json=payload,
                timeout=self._request_timeout_seconds,
            )
            if response.status_code not in expected:
                raise self._build_error(response)
            if response.status_code == 204 or not response.content:
                return {}
            try:
                parsed = response.json()
            except ValueError as exc:
                raise VultrClientError(
                    f"Vultr returned a non-JSON response: status={response.status_code}",
                    status_code=response.status_code,
                ) from exc
            if not isinstance(parsed, dict):
                raise VultrClientError("Vultr response payload must be a JSON object")
            return parsed

        try:
            return execute_with_backoff(
                operation_name=f"vultr_{method.lower()}_{endpoint}",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="vultr",
                func=_send_request,
                should_retry=self._should_retry_exception,
            )
        except (VultrClientError, requests.ConnectionError, requests.Timeout):
            set_event_type("vultr_request_failed")
            self._logger.exception("Vultr request failed: method=%s endpoint=%s", method, endpoint)
            raise

    @staticmethod
    def _should_retry_exception(exc: BaseException) -> bool:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
        return isinstance(exc, VultrClientError) and exc.status_code in RETRYABLE_STATUS_CODES

    @staticmethod
    def _build_error(response: requests.Response) -> VultrClientError:
        message = response.text.strip()
        try:
            parsed = response.json()
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or error.get("description") or message)
            elif error:
                message = str(error)
        return VultrClientError(
            f"Vultr API error {response.status_code}: {message}",
            status_code=response.status_code,
        )

    @staticmethod
    def _map_launch_result(
        instance: dict[str, Any],
        request: VultrInstanceLaunchRequest,
    ) -> VultrInstanceLaunchResult:
        return VultrInstanceLaunchResult(
            instance_id=str(instance["id"]),
            label=str(instance.get("label") or request.label),
            region=request.region,
            plan=str(instance.get("plan") or request.plan),
            os_id=int(instance.get("os_id") or request.os_id),
            ipv4_address=_optional_text(instance.get("main_ip")),
            ipv6_address=_optional_text(instance.get("v6_main_ip")),
            subnet_id=request.vpc_ids[0] if request.vpc_ids else None,
        )


def _require_catalog_item(
    items: list[dict[str, Any]],
    expected_id: str,
    *,
    id_fields: tuple[str, ...],
    resource_name: str,
) -> dict[str, Any]:
    normalized_id = expected_id.strip().casefold()
    for item in items:
        if any(
            str(item.get(field) or "").strip().casefold() == normalized_id
            for field in id_fields
        ):
            return item
    raise VultrClientError(
        f"Vultr {resource_name} was not found or is not accessible: {expected_id}"
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _firewall_rule_allows_tcp_port(
    rule: dict[str, Any],
    ip_type: str,
    port: int,
) -> bool:
    if str(rule.get("ip_type") or "").casefold() != ip_type:
        return False
    protocol = str(rule.get("protocol") or "").casefold()
    if protocol not in {"tcp", "any"}:
        return False
    configured_port = str(rule.get("port") or "").strip()
    if not configured_port:
        return True
    if configured_port.isdigit():
        return int(configured_port) == port
    if ":" in configured_port:
        start_text, end_text = configured_port.split(":", 1)
        if start_text.isdigit() and end_text.isdigit():
            return int(start_text) <= port <= int(end_text)
    return False


def _cursor_from_link(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(value).query)
    cursor_values = query.get("cursor")
    if not cursor_values:
        return None
    return _optional_text(cursor_values[0])
