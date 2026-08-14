from __future__ import annotations

import base64
import hashlib
import re
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from requests.structures import CaseInsensitiveDict

from infrastructure.oci import OCIClient, OCICredentials, OCIInstanceLaunchRequest


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.logger.getChild.return_value = MagicMock()
    runtime.config.app.request_timeout_seconds = 30
    runtime.config.app.max_retries = 0
    runtime.config.app.retry_backoff_seconds = 0.01
    return runtime


def _client() -> tuple[OCIClient, rsa.RSAPrivateKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    client = OCIClient(
        _runtime(),
        OCICredentials("tenancy", "user", "aa:bb", pem),
        "ap-tokyo-1",
    )
    return client, private_key


def test_signed_post_headers_include_body_hash_and_valid_signature() -> None:
    client, private_key = _client()
    body = b'{"displayName":"node"}'
    url = (
        "https://iaas.ap-tokyo-1.oraclecloud.com/20160918/instances"
        "?compartmentId=ocid1.compartment.oc1..test"
    )

    headers = client._build_signed_headers("POST", url, body)

    assert headers["x-content-sha256"] == base64.b64encode(
        hashlib.sha256(body).digest()
    ).decode("ascii")
    assert headers["content-length"] == str(len(body))
    authorization = headers["Authorization"]
    assert 'keyId="tenancy/user/aa:bb"' in authorization
    signature = re.search(r'signature="([^"]+)"', authorization)
    assert signature is not None
    signing_string = "\n".join(
        [
            "(request-target): post /20160918/instances?compartmentId=ocid1.compartment.oc1..test",
            f"host: {headers['host']}",
            f"date: {headers['date']}",
            f"x-content-sha256: {headers['x-content-sha256']}",
            "content-type: application/json",
            f"content-length: {len(body)}",
        ]
    ).encode("utf-8")
    private_key.public_key().verify(
        base64.b64decode(signature.group(1)),
        signing_string,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_list_collection_follows_opc_next_page() -> None:
    client, _ = _client()
    with patch.object(
        client,
        "_request_with_headers",
        side_effect=[
            ([{"id": "one"}], CaseInsensitiveDict({"opc-next-page": "next"})),
            ([{"id": "two"}], CaseInsensitiveDict()),
        ],
    ) as request:
        result = client.list_instances("compartment")

    assert [item["id"] for item in result] == ["one", "two"]
    assert request.call_args_list[0].kwargs["params"] == {
        "compartmentId": "compartment"
    }
    assert request.call_args_list[1].kwargs["params"] == {
        "compartmentId": "compartment",
        "page": "next",
    }


def test_launch_instance_protects_shadowfleet_tags_and_maps_addresses() -> None:
    client, _ = _client()
    request = OCIInstanceLaunchRequest(
        display_name="sf-oci",
        compartment_ocid="compartment",
        availability_domain="AD-1",
        shape="VM.Standard.E4.Flex",
        image_ocid="image",
        subnet_ocid="subnet",
        network_security_group_ocid="nsg",
        ssh_public_key="ssh-ed25519 AAAA",
        user_data="#cloud-config",
        ocpus=1,
        memory_in_gbs=6,
        freeform_tags={"ManagedBy": "external", "environment": "test"},
    )
    with patch.object(
        client,
        "_request",
        return_value={"id": "instance"},
    ) as send, patch.object(
        client,
        "wait_for_instance_running",
        return_value={"id": "instance", "lifecycleState": "RUNNING"},
    ), patch.object(
        client,
        "get_primary_vnic",
        return_value={"id": "vnic", "subnetId": "subnet", "publicIp": "192.0.2.10"},
    ), patch.object(
        client,
        "list_ipv6_addresses",
        return_value=[{"ipAddress": "2001:db8::10", "lifecycleState": "AVAILABLE"}],
    ):
        result = client.launch_instance(request)

    payload = send.call_args.kwargs["payload"]
    assert send.call_args.kwargs["retry_token"]
    assert payload["freeformTags"]["ManagedBy"] == "ShadowFleet"
    assert payload["freeformTags"]["environment"] == "test"
    assert payload["shapeConfig"] == {"ocpus": 1, "memoryInGBs": 6}
    assert result.ipv4_address == "192.0.2.10"
    assert result.ipv6_address == "2001:db8::10"
    assert client.created_instance_id == "instance"
