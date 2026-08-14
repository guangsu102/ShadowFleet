from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
import json
import time
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import requests

from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import execute_with_backoff


API_VERSION = "20160918"
RETRYABLE_STATUS_CODES = {409, 429, 500, 502, 503, 504}
MANAGED_BY_TAG = "ManagedBy"
MANAGED_BY_VALUE = "ShadowFleet"
CREATED_AT_TAG = "shadowfleet_created_at"


class OCIClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OCICredentials:
    tenancy_ocid: str
    user_ocid: str
    fingerprint: str
    private_key: str
    private_key_passphrase: str | None = None


@dataclass(frozen=True)
class OCIProvisioningTarget:
    availability_domain: str
    shape: str
    is_flexible_shape: bool
    architecture: str = "x64"


@dataclass(frozen=True)
class OCIInstanceLaunchRequest:
    display_name: str
    compartment_ocid: str
    availability_domain: str
    shape: str
    image_ocid: str
    subnet_ocid: str
    network_security_group_ocid: str
    ssh_public_key: str
    user_data: str
    ocpus: float | None = None
    memory_in_gbs: float | None = None
    freeform_tags: dict[str, str] | None = None


@dataclass(frozen=True)
class OCIInstanceLaunchResult:
    instance_id: str
    display_name: str
    availability_domain: str
    shape: str
    vnic_id: str
    subnet_ocid: str
    ipv4_address: str | None
    ipv6_address: str | None


class OCIClient:
    """Minimal OCI REST adapter with RSA HTTP request signing."""

    def __init__(
        self,
        runtime_context: RuntimeContext,
        credentials: OCICredentials,
        region: str,
        *,
        iaas_base_url: str | None = None,
        identity_base_url: str | None = None,
    ) -> None:
        self._credentials = _validate_credentials(credentials)
        self._region = _required_text(region, "region")
        self._logger = runtime_context.logger.getChild("infrastructure.oci")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._iaas_base_url = (
            iaas_base_url or f"https://iaas.{self._region}.oraclecloud.com/{API_VERSION}"
        ).rstrip("/")
        self._identity_base_url = (
            identity_base_url
            or f"https://identity.{self._region}.oraclecloud.com/{API_VERSION}"
        ).rstrip("/")
        self._private_key = _load_private_key(
            self._credentials.private_key,
            self._credentials.private_key_passphrase,
        )
        self._key_id = (
            f"{self._credentials.tenancy_ocid}/"
            f"{self._credentials.user_ocid}/"
            f"{self._credentials.fingerprint}"
        )
        self._session = requests.Session()
        self._created_instance_id: str | None = None

    @property
    def created_instance_id(self) -> str | None:
        return self._created_instance_id

    def validate_identity(self) -> dict[str, Any]:
        tenancy = self._request(
            "GET",
            f"/tenancies/{self._credentials.tenancy_ocid}",
            service="identity",
        )
        self._request(
            "GET",
            f"/users/{self._credentials.user_ocid}",
            service="identity",
        )
        if not isinstance(tenancy, dict) or tenancy.get("id") != self._credentials.tenancy_ocid:
            raise OCIClientError("OCI tenancy validation returned an unexpected tenancy")
        return tenancy

    def list_availability_domains(self, compartment_ocid: str) -> list[dict[str, Any]]:
        return self._list_collection(
            "/availabilityDomains",
            service="identity",
            params={"compartmentId": _required_text(compartment_ocid, "compartment_ocid")},
        )

    def list_images(
        self,
        compartment_ocid: str,
        *,
        operating_system: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, object] = {
            "compartmentId": _required_text(compartment_ocid, "compartment_ocid"),
            "sortBy": "TIMECREATED",
            "sortOrder": "DESC",
        }
        if operating_system and operating_system.strip():
            params["operatingSystem"] = operating_system.strip()
        return self._list_collection("/images", params=params)

    def list_shapes(
        self,
        compartment_ocid: str,
        *,
        availability_domain: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, object] = {
            "compartmentId": _required_text(compartment_ocid, "compartment_ocid")
        }
        if availability_domain and availability_domain.strip():
            params["availabilityDomain"] = availability_domain.strip()
        return self._list_collection("/shapes", params=params)

    def list_image_shape_compatibility_entries(
        self,
        compartment_ocid: str,
        image_ocid: str,
        shape: str,
    ) -> list[dict[str, Any]]:
        return self._list_collection(
            f"/images/{_required_text(image_ocid, 'image_ocid')}/shapes",
            params={
                "compartmentId": _required_text(compartment_ocid, "compartment_ocid"),
                "shapeName": _required_text(shape, "shape"),
            },
        )

    def list_subnets(self, compartment_ocid: str) -> list[dict[str, Any]]:
        return self._list_collection(
            "/subnets",
            params={
                "compartmentId": _required_text(compartment_ocid, "compartment_ocid"),
                "lifecycleState": "AVAILABLE",
            },
        )

    def list_network_security_groups(self, compartment_ocid: str) -> list[dict[str, Any]]:
        return self._list_collection(
            "/networkSecurityGroups",
            params={"compartmentId": _required_text(compartment_ocid, "compartment_ocid")},
        )

    def get_image(self, image_ocid: str) -> dict[str, Any]:
        return self._require_object(self._request("GET", f"/images/{image_ocid}"), "image")

    def get_subnet(self, subnet_ocid: str) -> dict[str, Any]:
        return self._require_object(self._request("GET", f"/subnets/{subnet_ocid}"), "subnet")

    def get_network_security_group(self, nsg_ocid: str) -> dict[str, Any]:
        return self._require_object(
            self._request("GET", f"/networkSecurityGroups/{nsg_ocid}"),
            "network security group",
        )

    def validate_provisioning_target(
        self,
        *,
        compartment_ocid: str,
        subnet_ocid: str,
        network_security_group_ocid: str,
        image_ocid: str,
        shape: str,
        availability_domain: str | None = None,
    ) -> OCIProvisioningTarget:
        compartment_id = _required_text(compartment_ocid, "compartment_ocid")
        domains = self.list_availability_domains(compartment_id)
        if not domains:
            raise OCIClientError("OCI compartment has no availability domains")
        selected_domain = availability_domain.strip() if availability_domain else ""
        if selected_domain:
            _require_catalog_item(domains, selected_domain, "name", "availability domain")
        else:
            selected_domain = _required_text(domains[0].get("name"), "availability domain name")

        image = self.get_image(_required_text(image_ocid, "image_ocid"))
        _require_compartment(image, compartment_id, "image", allow_tenancy_image=True)
        if str(image.get("lifecycleState") or "AVAILABLE").upper() != "AVAILABLE":
            raise OCIClientError(f"OCI image is not available: {image_ocid}")

        subnet = self.get_subnet(_required_text(subnet_ocid, "subnet_ocid"))
        _require_compartment(subnet, compartment_id, "subnet")
        if str(subnet.get("lifecycleState") or "AVAILABLE").upper() != "AVAILABLE":
            raise OCIClientError(f"OCI subnet is not available: {subnet_ocid}")
        if subnet.get("ipv6CidrBlock") is None and not subnet.get("ipv6CidrBlocks"):
            raise OCIClientError("OCI subnet must have IPv6 enabled")

        nsg = self.get_network_security_group(
            _required_text(network_security_group_ocid, "network_security_group_ocid")
        )
        _require_compartment(nsg, compartment_id, "network security group")
        if str(nsg.get("lifecycleState") or "AVAILABLE").upper() != "AVAILABLE":
            raise OCIClientError(
                f"OCI network security group is not available: {network_security_group_ocid}"
            )
        if subnet.get("vcnId") and nsg.get("vcnId") and subnet["vcnId"] != nsg["vcnId"]:
            raise OCIClientError("OCI subnet and network security group must belong to the same VCN")

        shapes = self.list_shapes(compartment_id, availability_domain=selected_domain)
        selected_shape = _require_catalog_item(
            shapes,
            _required_text(shape, "shape"),
            "shape",
            "shape",
        )
        selected_shape_name = _required_text(selected_shape.get("shape"), "shape")
        if not self.list_image_shape_compatibility_entries(
            compartment_id,
            image_ocid,
            selected_shape_name,
        ):
            raise OCIClientError(
                f"OCI image is not compatible with shape: "
                f"image={image_ocid} shape={selected_shape_name}"
            )
        return OCIProvisioningTarget(
            availability_domain=selected_domain,
            shape=selected_shape_name,
            is_flexible_shape=bool(selected_shape.get("isFlexible")),
            architecture=_shape_architecture(selected_shape),
        )

    def list_network_security_group_rules(self, nsg_ocid: str) -> list[dict[str, Any]]:
        return self._list_collection(
            f"/networkSecurityGroups/{_required_text(nsg_ocid, 'nsg_ocid')}/securityRules"
        )

    def ensure_network_security_group_ports(
        self,
        nsg_ocid: str,
        inbound_ports: tuple[int, ...],
    ) -> None:
        ports = tuple(dict.fromkeys(inbound_ports))
        if not ports:
            raise ValueError("inbound_ports must not be empty")
        if any(port <= 0 or port > 65535 for port in ports):
            raise ValueError("inbound port must be between 1 and 65535")
        existing = self.list_network_security_group_rules(nsg_ocid)
        additions: list[dict[str, object]] = []
        for source in ("0.0.0.0/0", "::/0"):
            for port in ports:
                if any(_nsg_rule_allows_tcp_port(rule, source, port) for rule in existing):
                    continue
                additions.append(
                    {
                        "direction": "INGRESS",
                        "protocol": "6",
                        "source": source,
                        "sourceType": "CIDR_BLOCK",
                        "description": "ShadowFleet managed inbound TCP",
                        "isStateless": False,
                        "tcpOptions": {
                            "destinationPortRange": {"min": port, "max": port}
                        },
                    }
                )
        if not additions:
            return
        self._request(
            "POST",
            f"/networkSecurityGroups/{nsg_ocid}/actions/addSecurityRules",
            payload={"securityRules": additions},
            expected_status={200},
            retry_token=str(uuid4()),
        )
        set_event_type("oci_nsg_rules_added")

    def launch_instance(
        self,
        request: OCIInstanceLaunchRequest,
        *,
        wait_timeout_seconds: int = 600,
        poll_interval_seconds: float = 5.0,
    ) -> OCIInstanceLaunchResult:
        tags = {
            **(request.freeform_tags or {}),
            MANAGED_BY_TAG: MANAGED_BY_VALUE,
            CREATED_AT_TAG: datetime.now(timezone.utc).isoformat(),
        }
        payload: dict[str, object] = {
            "availabilityDomain": request.availability_domain,
            "compartmentId": request.compartment_ocid,
            "displayName": request.display_name,
            "shape": request.shape,
            "createVnicDetails": {
                "assignPublicIp": True,
                "assignIpv6Ip": True,
                "subnetId": request.subnet_ocid,
                "nsgIds": [request.network_security_group_ocid],
                "displayName": f"{request.display_name}-vnic",
            },
            "metadata": {
                "ssh_authorized_keys": request.ssh_public_key,
                "user_data": base64.b64encode(request.user_data.encode("utf-8")).decode("ascii"),
            },
            "sourceDetails": {
                "sourceType": "image",
                "imageId": request.image_ocid,
            },
            "freeformTags": {str(key): str(value) for key, value in tags.items()},
        }
        if request.ocpus is not None or request.memory_in_gbs is not None:
            shape_config: dict[str, float] = {}
            if request.ocpus is not None:
                if request.ocpus <= 0:
                    raise ValueError("ocpus must be greater than 0")
                shape_config["ocpus"] = request.ocpus
            if request.memory_in_gbs is not None:
                if request.memory_in_gbs <= 0:
                    raise ValueError("memory_in_gbs must be greater than 0")
                shape_config["memoryInGBs"] = request.memory_in_gbs
            payload["shapeConfig"] = shape_config

        instance = self._require_object(
            self._request(
                "POST",
                "/instances",
                payload=payload,
                expected_status={200},
                retry_token=str(uuid4()),
            ),
            "instance",
        )
        instance_id = _required_text(instance.get("id"), "instance.id")
        self._created_instance_id = instance_id
        set_event_type("oci_instance_created")
        instance = self.wait_for_instance_running(
            instance_id,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        vnic = self.get_primary_vnic(request.compartment_ocid, instance_id)
        vnic_id = _required_text(vnic.get("id"), "vnic.id")
        ipv6_address = self.wait_for_ipv6_address(
            request.compartment_ocid,
            vnic_id,
            timeout_seconds=min(wait_timeout_seconds, 120),
            poll_interval_seconds=poll_interval_seconds,
        )
        return OCIInstanceLaunchResult(
            instance_id=instance_id,
            display_name=str(instance.get("displayName") or request.display_name),
            availability_domain=str(
                instance.get("availabilityDomain") or request.availability_domain
            ),
            shape=str(instance.get("shape") or request.shape),
            vnic_id=vnic_id,
            subnet_ocid=str(vnic.get("subnetId") or request.subnet_ocid),
            ipv4_address=_optional_text(vnic.get("publicIp")),
            ipv6_address=ipv6_address,
        )

    def get_instance(self, instance_id: str) -> dict[str, Any]:
        return self._require_object(
            self._request("GET", f"/instances/{_required_text(instance_id, 'instance_id')}"),
            "instance",
        )

    def list_instances(self, compartment_ocid: str) -> list[dict[str, Any]]:
        return self._list_collection(
            "/instances",
            params={"compartmentId": _required_text(compartment_ocid, "compartment_ocid")},
        )

    def wait_for_instance_running(
        self,
        instance_id: str,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            instance = self.get_instance(instance_id)
            state = str(instance.get("lifecycleState") or "").upper()
            if state == "RUNNING":
                return instance
            if state in {"TERMINATED", "TERMINATING"}:
                raise OCIClientError(
                    f"OCI instance entered {state} while waiting for RUNNING: {instance_id}"
                )
            time.sleep(poll_interval_seconds)
        raise OCIClientError(f"Timed out waiting for OCI instance to become RUNNING: {instance_id}")

    def list_vnic_attachments(
        self,
        compartment_ocid: str,
        instance_id: str,
    ) -> list[dict[str, Any]]:
        return self._list_collection(
            "/vnicAttachments",
            params={
                "compartmentId": _required_text(compartment_ocid, "compartment_ocid"),
                "instanceId": _required_text(instance_id, "instance_id"),
            },
        )

    def get_vnic(self, vnic_id: str) -> dict[str, Any]:
        return self._require_object(
            self._request("GET", f"/vnics/{_required_text(vnic_id, 'vnic_id')}"),
            "VNIC",
        )

    def get_primary_vnic(self, compartment_ocid: str, instance_id: str) -> dict[str, Any]:
        attachments = self.list_vnic_attachments(compartment_ocid, instance_id)
        candidates = [
            item
            for item in attachments
            if str(item.get("lifecycleState") or "ATTACHED").upper() == "ATTACHED"
        ]
        if not candidates:
            raise OCIClientError(f"OCI instance has no attached VNIC: {instance_id}")
        primary = next(
            (item for item in candidates if int(item.get("nicIndex") or 0) == 0),
            candidates[0],
        )
        return self.get_vnic(_required_text(primary.get("vnicId"), "vnic attachment vnicId"))

    def list_ipv6_addresses(
        self,
        compartment_ocid: str,
        vnic_id: str,
    ) -> list[dict[str, Any]]:
        return self._list_collection(
            "/ipv6",
            params={
                "compartmentId": _required_text(compartment_ocid, "compartment_ocid"),
                "vnicId": _required_text(vnic_id, "vnic_id"),
            },
        )

    def wait_for_ipv6_address(
        self,
        compartment_ocid: str,
        vnic_id: str,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            address = _first_ipv6_address(
                self.list_ipv6_addresses(compartment_ocid, vnic_id)
            )
            if address:
                return address
            time.sleep(poll_interval_seconds)
        raise OCIClientError(
            f"Timed out waiting for OCI IPv6 address on VNIC: {vnic_id}"
        )

    def create_ipv6_address(
        self,
        vnic_id: str,
        *,
        display_name: str,
    ) -> dict[str, Any]:
        ipv6 = self._require_object(
            self._request(
                "POST",
                "/ipv6",
                payload={
                    "vnicId": _required_text(vnic_id, "vnic_id"),
                    "displayName": _required_text(display_name, "display_name"),
                },
                expected_status={200},
                retry_token=str(uuid4()),
            ),
            "IPv6 address",
        )
        set_event_type("oci_ipv6_created")
        return ipv6

    def delete_ipv6_address(self, ipv6_ocid: str) -> None:
        self._request(
            "DELETE",
            f"/ipv6/{_required_text(ipv6_ocid, 'ipv6_ocid')}",
            expected_status={202, 204, 404},
        )
        set_event_type("oci_ipv6_deleted")

    def delete_instance(self, instance_id: str) -> None:
        self._request(
            "DELETE",
            f"/instances/{_required_text(instance_id, 'instance_id')}",
            params={"preserveBootVolume": "false"},
            expected_status={202, 204, 404},
        )
        set_event_type("oci_instance_deleted")
        self._logger.info("Terminated OCI instance id=%s", instance_id)

    def _list_collection(
        self,
        endpoint: str,
        *,
        service: str = "iaas",
        params: dict[str, object] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            page_params = dict(params or {})
            if page:
                page_params["page"] = page
            payload, headers = self._request_with_headers(
                "GET", endpoint, service=service, params=page_params
            )
            if not isinstance(payload, list):
                raise OCIClientError(f"OCI collection response must be a list: {endpoint}")
            items.extend(item for item in payload if isinstance(item, dict))
            next_page = _optional_text(headers.get("opc-next-page"))
            if not next_page or next_page == page:
                return items
            page = next_page

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        service: str = "iaas",
        params: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
        expected_status: set[int] | None = None,
        retry_token: str | None = None,
    ) -> Any:
        body, _ = self._request_with_headers(
            method,
            endpoint,
            service=service,
            params=params,
            payload=payload,
            expected_status=expected_status,
            retry_token=retry_token,
        )
        return body

    def _request_with_headers(
        self,
        method: str,
        endpoint: str,
        *,
        service: str = "iaas",
        params: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
        expected_status: set[int] | None = None,
        retry_token: str | None = None,
    ) -> tuple[Any, requests.structures.CaseInsensitiveDict[str]]:
        normalized_method = method.upper()
        expected = expected_status or {200}
        base_url = self._identity_base_url if service == "identity" else self._iaas_base_url
        query = urlencode(params or {}, doseq=True)
        url = f"{base_url}{endpoint}"
        if query:
            url = f"{url}?{query}"
        body = (
            json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            if payload is not None
            else None
        )

        def _send_request() -> tuple[Any, requests.structures.CaseInsensitiveDict[str]]:
            headers = self._build_signed_headers(normalized_method, url, body)
            if retry_token:
                headers["opc-retry-token"] = retry_token
            response = self._session.request(
                method=normalized_method,
                url=url,
                headers=headers,
                data=body,
                timeout=self._request_timeout_seconds,
            )
            if response.status_code not in expected:
                raise self._build_error(response)
            if response.status_code == 204 or not response.content:
                parsed: Any = {}
            else:
                try:
                    parsed = response.json()
                except ValueError as exc:
                    raise OCIClientError(
                        f"OCI returned a non-JSON response: status={response.status_code}",
                        status_code=response.status_code,
                    ) from exc
            return parsed, response.headers

        try:
            return execute_with_backoff(
                operation_name=f"oci_{normalized_method.lower()}_{endpoint}",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="oci",
                func=_send_request,
                should_retry=self._should_retry_exception,
            )
        except (OCIClientError, requests.ConnectionError, requests.Timeout):
            set_event_type("oci_request_failed")
            self._logger.exception("OCI request failed: method=%s endpoint=%s", method, endpoint)
            raise

    def _build_signed_headers(
        self,
        method: str,
        url: str,
        body: bytes | None,
    ) -> dict[str, str]:
        parsed = urlsplit(url)
        request_target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        headers = {
            "host": parsed.netloc,
            "date": format_datetime(datetime.now(timezone.utc), usegmt=True),
        }
        signed_headers = ["(request-target)", "host", "date"]
        signing_lines = [f"(request-target): {method.lower()} {request_target}"]
        signing_lines.extend([f"host: {headers['host']}", f"date: {headers['date']}"])
        if body is not None:
            content_hash = base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
            headers.update(
                {
                    "x-content-sha256": content_hash,
                    "content-type": "application/json",
                    "content-length": str(len(body)),
                }
            )
            signed_headers.extend(
                ["x-content-sha256", "content-type", "content-length"]
            )
            signing_lines.extend(
                [
                    f"x-content-sha256: {content_hash}",
                    "content-type: application/json",
                    f"content-length: {len(body)}",
                ]
            )
        signature = self._private_key.sign(
            "\n".join(signing_lines).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        encoded_signature = base64.b64encode(signature).decode("ascii")
        headers["Authorization"] = (
            'Signature version="1",'
            f'keyId="{self._key_id}",'
            'algorithm="rsa-sha256",'
            f'headers="{" ".join(signed_headers)}",'
            f'signature="{encoded_signature}"'
        )
        return headers

    @staticmethod
    def _require_object(payload: Any, resource_name: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise OCIClientError(f"OCI {resource_name} response must be a JSON object")
        return payload

    @staticmethod
    def _should_retry_exception(exc: BaseException) -> bool:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
        return isinstance(exc, OCIClientError) and exc.status_code in RETRYABLE_STATUS_CODES

    @staticmethod
    def _build_error(response: requests.Response) -> OCIClientError:
        message = response.text.strip()
        try:
            parsed = response.json()
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            message = str(parsed.get("message") or parsed.get("code") or message)
        return OCIClientError(
            f"OCI API error {response.status_code}: {message}",
            status_code=response.status_code,
        )


def _validate_credentials(credentials: OCICredentials) -> OCICredentials:
    for name in ("tenancy_ocid", "user_ocid", "fingerprint", "private_key"):
        _required_text(getattr(credentials, name), name)
    return credentials


def _load_private_key(
    private_key_pem: str,
    passphrase: str | None,
) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=passphrase.encode("utf-8") if passphrase else None,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("OCI private key is not a valid PEM RSA private key") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("OCI private key must be an RSA private key")
    return key


def _require_catalog_item(
    items: list[dict[str, Any]],
    expected: str,
    id_field: str,
    resource_name: str,
) -> dict[str, Any]:
    normalized = expected.casefold()
    for item in items:
        if str(item.get(id_field) or "").casefold() == normalized:
            return item
    raise OCIClientError(f"OCI {resource_name} not found: {expected}")


def _require_compartment(
    resource: dict[str, Any],
    compartment_ocid: str,
    resource_name: str,
    *,
    allow_tenancy_image: bool = False,
) -> None:
    resource_compartment = _optional_text(resource.get("compartmentId"))
    if resource_compartment is None:
        return
    if resource_compartment == compartment_ocid:
        return
    if allow_tenancy_image and resource.get("id"):
        # Platform images may be owned by the tenancy and shared into the compartment.
        return
    raise OCIClientError(
        f"OCI {resource_name} belongs to a different compartment: {resource_compartment}"
    )


def _nsg_rule_allows_tcp_port(rule: dict[str, Any], source: str, port: int) -> bool:
    if str(rule.get("direction") or "").upper() != "INGRESS":
        return False
    if str(rule.get("protocol") or "") not in {"6", "all"}:
        return False
    if str(rule.get("source") or "") != source:
        return False
    if str(rule.get("protocol") or "") == "all":
        return True
    tcp_options = rule.get("tcpOptions")
    if not isinstance(tcp_options, dict):
        return True
    port_range = tcp_options.get("destinationPortRange")
    if not isinstance(port_range, dict):
        return True
    try:
        return int(port_range.get("min")) <= port <= int(port_range.get("max"))
    except (TypeError, ValueError):
        return False


def _first_ipv6_address(resources: list[dict[str, Any]]) -> str | None:
    for resource in resources:
        if str(resource.get("lifecycleState") or "AVAILABLE").upper() != "AVAILABLE":
            continue
        address = _optional_text(resource.get("ipAddress"))
        if address:
            return address
    return None


def _shape_architecture(shape: dict[str, Any]) -> str:
    shape_name = str(shape.get("shape") or "").casefold()
    processor = str(shape.get("processorDescription") or "").casefold()
    if any(token in shape_name for token in (".a1.", ".a2.")):
        return "arm64"
    if "ampere" in processor or "arm" in processor:
        return "arm64"
    return "x64"


def _required_text(value: object, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
