from __future__ import annotations

import sqlite3
from contextlib import contextmanager
import logging
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from database.asset_models import AssetCreateRequest, AssetEventCreateRequest
from database.asset_repo import AssetRepo
from database.credential_cipher import CredentialCipherError, ENCRYPTED_VALUE_PREFIX


def _repo(sqlite_connection, encryption_key: str | None = None) -> AssetRepo:
    runtime = MagicMock()
    runtime.logger = MagicMock(spec=logging.Logger)
    runtime.logger.getChild.return_value = runtime.logger
    sqlite_manager = MagicMock()
    sqlite_manager.connection.return_value.__enter__.return_value = sqlite_connection
    sqlite_manager.connection.return_value.__exit__.return_value = False
    runtime.sqlite_manager = sqlite_manager
    runtime.config.app.asset_credential_encryption_key = encryption_key
    return AssetRepo(runtime)


def _seed_allocations(connection) -> int:
    connection.execute(
        """
        INSERT INTO fleet_assets (
            asset_type, asset_name, status, created_at, updated_at
        ) VALUES ('vultr', 'vultr-test', 'active', '2026-01-01', '2026-01-01')
        """
    )
    allocation_id = int(
        connection.execute(
            """
            INSERT INTO fleet_asset_allocations (
                asset_id, fleet_node_id, xboard_node_id, protocol_type,
                allocation_status, vcpu_count, created_at, updated_at
            ) VALUES (1, NULL, 9001, 'Trojan', 'allocated', 1, '2026-01-01', '2026-01-01')
            """
        ).lastrowid
    )
    connection.execute(
        """
        INSERT INTO fleet_asset_port_allocations (
            asset_id, fleet_node_id, xboard_node_id, server_port,
            protocol_type, allocation_status, created_at, updated_at
        ) VALUES (1, NULL, 9001, 443, 'Trojan', 'allocated', '2026-01-01', '2026-01-01')
        """
    )
    connection.execute(
        """
        INSERT INTO fleet_asset_port_allocations (
            asset_id, fleet_node_id, xboard_node_id, server_port,
            protocol_type, allocation_status, created_at, updated_at
        ) VALUES (1, NULL, 9002, 8443, 'Trojan', 'allocated', '2026-01-01', '2026-01-01')
        """
    )
    connection.commit()
    return allocation_id


def test_release_allocation_by_id_releases_only_linked_ports(
    in_memory_sqlite_db,
) -> None:
    allocation_id = _seed_allocations(in_memory_sqlite_db)
    repo = _repo(in_memory_sqlite_db)

    assert repo.release_allocation_by_id(allocation_id) is True

    allocation = in_memory_sqlite_db.execute(
        "SELECT allocation_status FROM fleet_asset_allocations WHERE id = ?",
        (allocation_id,),
    ).fetchone()
    ports = in_memory_sqlite_db.execute(
        """
        SELECT xboard_node_id, allocation_status
        FROM fleet_asset_port_allocations
        ORDER BY xboard_node_id
        """
    ).fetchall()
    assert allocation["allocation_status"] == "released"
    assert [(row["xboard_node_id"], row["allocation_status"]) for row in ports] == [
        (9001, "released"),
        (9002, "allocated"),
    ]


def test_release_allocation_by_id_is_idempotent(in_memory_sqlite_db) -> None:
    allocation_id = _seed_allocations(in_memory_sqlite_db)
    repo = _repo(in_memory_sqlite_db)

    assert repo.release_allocation_by_id(allocation_id) is True
    assert repo.release_allocation_by_id(allocation_id) is False


def test_release_allocation_by_id_rejects_invalid_id(in_memory_sqlite_db) -> None:
    repo = _repo(in_memory_sqlite_db)

    with pytest.raises(ValueError, match="greater than 0"):
        repo.release_allocation_by_id(0)

def test_asset_credentials_are_encrypted_at_rest_and_decrypted_on_read(
    in_memory_sqlite_db,
) -> None:
    key = Fernet.generate_key().decode("ascii")
    repo = _repo(in_memory_sqlite_db, key)

    asset_id = repo.create_asset(
        AssetCreateRequest(
            asset_type="gcp",
            asset_name="encrypted-gcp",
            region="asia-east1-a",
            aws_account_id="gcp:project",
            aws_access_key="service@example.test",
            aws_secret_key="private-key",
            ssh_password="ssh-password",
            ssh_private_key="ssh-private-key",
            provider_config={
                "project_id": "project",
                "private_key_passphrase": "provider-secret",
            },
        )
    )

    raw = in_memory_sqlite_db.execute(
        """
        SELECT aws_access_key, aws_secret_key, ssh_password,
               ssh_private_key, provider_config_json
        FROM fleet_assets
        WHERE id = ?
        """,
        (asset_id,),
    ).fetchone()
    assert all(
        raw[column].startswith(ENCRYPTED_VALUE_PREFIX)
        for column in raw.keys()
    )

    asset = repo.get_asset_by_id(asset_id)
    assert asset.aws_access_key == "service@example.test"
    assert asset.aws_secret_key == "private-key"
    assert asset.ssh_password == "ssh-password"
    assert asset.ssh_private_key == "ssh-private-key"
    assert asset.provider_config == {
        "project_id": "project",
        "private_key_passphrase": "provider-secret",
    }


def test_encryption_key_migrates_existing_plaintext_credentials(
    in_memory_sqlite_db,
) -> None:
    cursor = in_memory_sqlite_db.execute(
        """
        INSERT INTO fleet_assets (
            asset_type, asset_name, status, aws_access_key, aws_secret_key,
            provider_config_json, created_at, updated_at
        ) VALUES ('kamatera', 'legacy', 'active', 'client-id', 'secret',
                  '{"private_key_passphrase":"legacy-secret"}', 'now', 'now')
        """
    )
    asset_id = int(cursor.lastrowid)
    key = Fernet.generate_key().decode("ascii")

    repo = _repo(in_memory_sqlite_db, key)

    raw = in_memory_sqlite_db.execute(
        "SELECT aws_access_key, aws_secret_key, provider_config_json "
        "FROM fleet_assets WHERE id = ?",
        (asset_id,),
    ).fetchone()
    assert all(
        raw[column].startswith(ENCRYPTED_VALUE_PREFIX)
        for column in raw.keys()
    )
    assert repo.get_asset_by_id(asset_id).aws_secret_key == "secret"


def test_encrypted_credentials_require_the_configured_key(
    in_memory_sqlite_db,
) -> None:
    key = Fernet.generate_key().decode("ascii")
    repo = _repo(in_memory_sqlite_db, key)
    asset_id = repo.create_asset(
        AssetCreateRequest(
            asset_type="vultr",
            asset_name="encrypted-vultr",
            region="ewr",
            aws_access_key="token",
        )
    )

    repo_without_key = _repo(in_memory_sqlite_db)
    with pytest.raises(CredentialCipherError, match="not configured"):
        repo_without_key.get_asset_by_id(asset_id)
def test_credential_update_rolls_back_when_audit_event_fails(
    in_memory_sqlite_db,
) -> None:
    repo = _repo(in_memory_sqlite_db)

    @contextmanager
    def transaction():
        try:
            yield in_memory_sqlite_db
            in_memory_sqlite_db.commit()
        except Exception:
            in_memory_sqlite_db.rollback()
            raise

    repo._sqlite_manager.connection.side_effect = transaction
    asset_id = repo.create_asset(
        AssetCreateRequest(
            asset_type="vultr",
            asset_name="transaction-test",
            region="sgp",
            aws_account_id="vultr:account",
            aws_access_key="old-token",
        )
    )
    repo.update_asset_status(asset_id, "banned")
    in_memory_sqlite_db.execute(
        """
        CREATE TRIGGER fail_credential_audit
        BEFORE INSERT ON fleet_asset_events
        WHEN NEW.event_type = 'asset_credentials_rotated'
        BEGIN
            SELECT RAISE(ABORT, 'forced audit failure');
        END
        """
    )
    in_memory_sqlite_db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced audit failure"):
        repo.update_asset_credentials(
            asset_id,
            aws_access_key="new-token",
            reactivate=True,
            event=AssetEventCreateRequest(
                asset_id=asset_id,
                event_type="asset_credentials_rotated",
                correlation_id="transaction-test",
                message="rotated",
                payload={},
            ),
        )

    asset = repo.get_asset_by_id(asset_id)
    assert asset.aws_access_key == "old-token"
    assert asset.status == "banned"
    event_count = in_memory_sqlite_db.execute(
        "SELECT COUNT(*) FROM fleet_asset_events WHERE asset_id = ?",
        (asset_id,),
    ).fetchone()[0]
    assert event_count == 0
