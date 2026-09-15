from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from api.auth.jwt import hash_password, verify_password
from api.exceptions.handlers import APIError

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class AuthUserRepo:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._ensure_schema()

    @classmethod
    def from_runtime_context(cls, runtime_context: "RuntimeContext") -> "AuthUserRepo":
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise RuntimeError(
                "RuntimeContext.sqlite_manager is required for authentication"
            )
        return cls(sqlite_manager.database_path)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._get_connection()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS auth_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                hashed_password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer'
                    CHECK (role IN ('admin', 'operator', 'viewer')),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_users_username
                ON auth_users (username COLLATE NOCASE);
        """)
        conn.commit()
        conn.close()

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM auth_users WHERE username = ? COLLATE NOCASE AND is_active = 1",
                (username,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM auth_users WHERE id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.get_by_username(username)
        if user is None:
            return None
        if not verify_password(password, user["hashed_password"]):
            return None
        return user

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "viewer",
    ) -> int:
        existing = self.get_by_username(username)
        if existing:
            raise APIError("Username already exists", code="USER_EXISTS", status_code=409)
        if role not in {"admin", "operator", "viewer"}:
            raise APIError("Invalid user role", code="INVALID_ROLE", status_code=422)

        conn = self._get_connection()
        try:
            hashed = hash_password(password)
            cursor = conn.execute(
                "INSERT INTO auth_users (username, hashed_password, role) VALUES (?, ?, ?)",
                (username, hashed, role),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def update_user(
        self,
        user_id: int,
        role: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            user = conn.execute(
                "SELECT id FROM auth_users WHERE id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
            if not user:
                return None

            updates: list[str] = []
            params: list[Any] = []
            if role is not None:
                if role not in {"admin", "operator", "viewer"}:
                    raise APIError(
                        "Invalid user role", code="INVALID_ROLE", status_code=422
                    )
                updates.append("role = ?")
                params.append(role)
            if password is not None:
                updates.append("hashed_password = ?")
                params.append(hash_password(password))
            updates.append("updated_at = ?")
            params.append(datetime.now(timezone.utc).isoformat())
            params.append(user_id)

            conn.execute(
                f"UPDATE auth_users SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
            return self.get_by_id(user_id)
        finally:
            conn.close()

    def delete_user(self, user_id: int) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "UPDATE auth_users SET is_active = 0, updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def list_users(self) -> list[dict[str, Any]]:
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT id, username, role, is_active, created_at, updated_at "
                "FROM auth_users WHERE is_active = 1 ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def ensure_bootstrap_admin(self, password: str | None) -> bool:
        """Create the first administrator only from an explicit bootstrap secret."""
        connection = self._get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM auth_users LIMIT 1"
            ).fetchone()
            if existing is not None:
                connection.commit()
                return False

            normalized_password = str(password or "")
            if len(normalized_password) < 12:
                raise RuntimeError(
                    "SHADOWFLEET_BOOTSTRAP_ADMIN_PASSWORD must contain at "
                    "least 12 characters when the auth database is empty"
                )
            connection.execute(
                """
                INSERT INTO auth_users (username, hashed_password, role)
                VALUES (?, ?, ?)
                """,
                ("admin", hash_password(normalized_password), "admin"),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
