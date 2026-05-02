"""Mock responses for external API testing (AWS, Cloudflare, PostgreSQL)."""

from __future__ import annotations

from typing import Any


class MockBoto3EC2Responses:
    """Mock responses for AWS EC2 Boto3 client."""

    DESCRIBE_SUBNETS_IPV6_CIDR = {
        "Subnets": [
            {
                "SubnetId": "subnet-1234567890abcdef0",
                "Ipv6CidrBlock": "2600:1f14:804:as03::/64",
                "VpcId": "vpc-1234567890abcdef0",
                "State": "available",
            }
        ]
    }

    DESCRIBE_NETWORK_INTERFACES = {
        "NetworkInterfaces": [
            {
                "NetworkInterfaceId": "eni-1234567890abcdef0",
                "SubnetId": "subnet-1234567890abcdef0",
                "VpcId": "vpc-1234567890abcdef0",
                "PrivateIpAddresses": [
                    {
                        "PrivateIpAddress": "10.0.1.100",
                        "Primary": True,
                        "Association": {
                            "PublicIp": "54.123.45.67",
                            "Ipv6Address": "2600:1f14:804:as03:1234::",
                        },
                    }
                ],
                "Ipv6Addresses": [
                    {"Ipv6Address": "2600:1f14:804:as03:1234::"},
                ],
            }
        ]
    }

    ASSIGN_IPV6_ADDRESSES_SUCCESS = {
        "NetworkInterfaceId": "eni-1234567890abcdef0",
        "AssignedIpv6Addresses": ["2600:1f14:804:as03:5678::"],
    }

    UNASSIGN_IPV6_ADDRESSES_SUCCESS = {
        "NetworkInterfaceId": "eni-1234567890abcdef0",
        "UnassignedIpv6Addresses": ["2600:1f14:804:as03:1234::"],
    }

    RUN_INSTANCES_SUCCESS = {
        "Instances": [
            {
                "InstanceId": "i-0abcdef1234567890",
                "InstanceState": {"Name": "running"},
                "PublicIpv4Address": None,
                "Ipv6Address": "2600:1f14:804:as03:abcd::",
                "SubnetId": "subnet-1234567890abcdef0",
                "NetworkInterfaces": [
                    {
                        "NetworkInterfaceId": "eni-1234567890abcdef0",
                        "Ipv6Addresses": [{"Ipv6Address": "2600:1f14:804:as03:abcd::"}],
                    }
                ],
            }
        ],
        "ReservationId": "r-1234567890abcdef0",
    }

    TERMINATE_INSTANCES_SUCCESS = {
        "TerminatingInstances": [
            {
                "InstanceId": "i-0abcdef1234567890",
                "PreviousState": {"Name": "running"},
                "CurrentState": {"Name": "terminated"},
            }
        ]
    }

    DESCRIBE_INSTANCES_RUNNING = {
        "Reservations": [
            {
                "ReservationId": "r-1234567890abcdef0",
                "Instances": [
                    {
                        "InstanceId": "i-0abcdef1234567890",
                        "State": {"Name": "running"},
                        "Tags": [{"Key": "Name", "Value": "test-node"}],
                    }
                ],
            }
        ]
    }

    DESCRIBE_INSTANCES_STOPPED = {
        "Reservations": [
            {
                "ReservationId": "r-1234567890abcdef0",
                "Instances": [
                    {
                        "InstanceId": "i-0abcdef1234567890",
                        "State": {"Name": "stopped"},
                        "Tags": [{"Key": "Name", "Value": "test-node"}],
                    }
                ],
            }
        ]
    }


class MockCloudflareAPIResponses:
    """Mock responses for Cloudflare API."""

    ZONE_DNS_RECORDS_EMPTY = {
        "result": [],
        "result_info": {"count": 0, "page": 1, "per_page": 100},
        "success": True,
        "errors": [],
        "messages": [],
    }

    ZONE_DNS_RECORDS_WITH_AAAA = {
        "result": [
            {
                "id": "zone_record_123",
                "type": "AAAA",
                "name": "sf-12345.example.com",
                "content": "2600:1f14:804:as03:1234::",
                "proxied": False,
                "ttl": 300,
            }
        ],
        "result_info": {"count": 1, "page": 1, "per_page": 100},
        "success": True,
        "errors": [],
        "messages": [],
    }

    CREATE_DNS_RECORD_SUCCESS = {
        "result": {
            "id": "zone_record_456",
            "type": "AAAA",
            "name": "sf-12345.example.com",
            "content": "2600:1f14:804:as03:5678::",
            "proxied": False,
            "ttl": 300,
        },
        "success": True,
        "errors": [],
        "messages": [],
    }

    UPDATE_DNS_RECORD_SUCCESS = {
        "result": {
            "id": "zone_record_123",
            "type": "AAAA",
            "name": "sf-12345.example.com",
            "content": "2600:1f14:804:as03:5678::",
            "proxied": True,
            "ttl": 300,
        },
        "success": True,
        "errors": [],
        "messages": [],
    }

    DELETE_DNS_RECORD_SUCCESS = {
        "result": {
            "id": "zone_record_123",
        },
        "success": True,
        "errors": [],
        "messages": [],
    }


class MockXboardPostgreSQLResponses:
    """Mock responses for Xboard PostgreSQL queries."""

    INSERT_NODE_RETURNING_ID = 12345

    SELECT_NODE_BY_ID = {
        "id": 12345,
        "name": "sf-node-12345",
        "server_key": "server_key_abc123",
        "mode": "tcp",
        "type": "vmess",
        "host": "",
        "address": "",
        "port": 443,
        "show": 1,
        "uplink": 0,
        "downlink": 0,
        "created_at": "2026-03-23T10:00:00Z",
    }

    UPDATE_NODE_SHOW_ONLINE = {
        "id": 12345,
        "show": 1,
    }

    UPDATE_NODE_SHOW_OFFLINE = {
        "id": 12345,
        "show": 0,
    }

    DELETE_NODE = {"id": 12345}


def create_boto3_client_error(code: str, message: str) -> dict[str, Any]:
    """Create a mock botocore ClientError response structure."""
    return {
        "Error": {
            "Code": code,
            "Message": message,
        }
    }


AWS_ERROR_INVALID_IPV6_ADDRESS = create_boto3_client_error(
    "InvalidParameterValue",
    "This IPv6 address is not available in the specified subnet",
)

AWS_ERROR_AUTH_FAILURE = create_boto3_client_error(
    "AuthFailure",
    "AWS was not able to validate the provided access credentials",
)

AWS_ERROR_REQUEST_LIMIT = create_boto3_client_error(
    "RequestLimitExceeded",
    "Request limit exceeded",
)

AWS_ERROR_INSTANCE_NOT_FOUND = create_boto3_client_error(
    "InvalidInstanceID.NotFound",
    "The instance ID i-nonexistent does not exist",
)
