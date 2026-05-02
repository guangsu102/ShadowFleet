from __future__ import annotations

import os
from pathlib import Path

from botocore.client import BaseClient
from botocore.exceptions import ClientError

from models.aws_credentials import AwsCredentials
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type
from utils.resilience import TokenBucketRateLimiter

__all__ = ["KeyPairManager", "KeyPairManagerError"]


def _build_key_name(account_id: str) -> str:
    return account_id


class KeyPairManagerError(Exception):
    pass


class KeyPairManager:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._config = runtime_context.config.app
        self._logger = runtime_context.logger.getChild("key_pair_manager")
        self._key_pair_dir = Path(self._config.key_pair_local_dir)
        self._rate_limiter = self._build_rate_limiter()

    def _build_rate_limiter(self) -> "TokenBucketRateLimiter":
        return TokenBucketRateLimiter(
            tokens_per_second=0.5,
            burst_capacity=2,
        )

    def _key_pair_path(self, account_id: str) -> Path:
        account_dir = self._key_pair_dir / account_id
        return account_dir / f"{account_id}.pem"

    def _ensure_parent_dir(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def ensure_key_pair_for_account(
        self,
        aws_credential: AwsCredentials,
        ec2_client: BaseClient,
    ) -> str:
        account_id = aws_credential.account_id
        key_name = _build_key_name(account_id)

        if self._key_pair_exists_remotely(ec2_client, key_name):
            self._logger.info("KeyPair %s already exists in AWS, skipping creation.", key_name)
            set_event_type("aws_keypair_found")
            return key_name

        self._logger.info("KeyPair %s not found, generating and importing...", key_name)
        key_name = self._generate_and_import_key_pair(
            aws_credential=aws_credential,
            ec2_client=ec2_client,
        )
        set_event_type("aws_keypair_imported")
        return key_name

    def _key_pair_exists_remotely(
        self,
        ec2_client: BaseClient,
        key_name: str,
    ) -> bool:
        try:
            response = ec2_client.describe_key_pairs(KeyNames=[key_name])
            return bool(response.get("KeyPairs"))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "InvalidKeyPair.NotFound":
                return False
            raise KeyPairManagerError(f"describe_key_pairs failed for {key_name}: {exc}") from exc

    def _generate_and_import_key_pair(
        self,
        aws_credential: AwsCredentials,
        ec2_client: BaseClient,
    ) -> str:
        account_id = aws_credential.account_id
        region = aws_credential.region
        key_name = _build_key_name(account_id)
        pem_path = self._key_pair_path(account_id)

        self._rate_limiter.acquire()
        private_key_pem, public_key_openssh = _generate_rsa_key_pair()

        try:
            self._ensure_parent_dir(pem_path)
            self._write_private_key(pem_path, private_key_pem)
            pem_path.chmod(0o600)

            response = ec2_client.import_key_pair(
                KeyName=key_name,
                PublicKeyMaterial=public_key_openssh.decode("ascii"),
                TagSpecifications=[
                    {
                        "ResourceType": "key-pair",
                        "Tags": [
                            {"Key": "CreatedBy", "Value": "ShadowFleet"},
                            {"Key": "AccountId", "Value": account_id},
                            {"Key": "Region", "Value": region},
                        ],
                    }
                ],
            )
            imported_key_fingerprint = response.get("KeyPairId", "")

            self._logger.info(
                "Imported KeyPair %s (AWS ID: %s) for account %s in region %s",
                key_name,
                imported_key_fingerprint,
                account_id,
                region,
            )
            return key_name

        except ClientError as exc:
            os.remove(pem_path)
            raise KeyPairManagerError(f"import_key_pair failed for {key_name}: {exc}") from exc
        except OSError as exc:
            raise KeyPairManagerError(f"Failed to write private key to {pem_path}: {exc}") from exc

    def _write_private_key(self, path: Path, content: str) -> None:
        with open(path, "w", encoding="ascii") as f:
            f.write(content)


def _generate_rsa_key_pair() -> tuple[str, bytes]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend

    private_key = rsa.generate_private_key(
        key_size=4096,
        public_exponent=65537,
        backend=default_backend(),
    )
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")

    public_key_openssh = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    return private_key_pem, public_key_openssh
