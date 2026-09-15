from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


ENCRYPTED_VALUE_PREFIX = "enc:v1:"


class CredentialCipherError(RuntimeError):
    pass


class CredentialCipher:
    def __init__(self, encryption_key: str | None) -> None:
        normalized_key = (
            encryption_key.strip()
            if isinstance(encryption_key, str) and encryption_key.strip()
            else None
        )
        self._fernet: Fernet | None = None
        if normalized_key is not None:
            try:
                self._fernet = Fernet(normalized_key.encode("ascii"))
            except (TypeError, ValueError) as exc:
                raise CredentialCipherError(
                    "asset credential encryption key must be a valid Fernet key"
                ) from exc

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    @staticmethod
    def is_encrypted(value: str | None) -> bool:
        return isinstance(value, str) and value.startswith(ENCRYPTED_VALUE_PREFIX)

    def encrypt(self, value: str | None) -> str | None:
        if value is None or not self.enabled:
            return value
        if self.is_encrypted(value):
            self.decrypt(value)
            return value
        assert self._fernet is not None
        token = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        return f"{ENCRYPTED_VALUE_PREFIX}{token}"

    def decrypt(self, value: str | None) -> str | None:
        if value is None or not self.is_encrypted(value):
            return value
        if self._fernet is None:
            raise CredentialCipherError(
                "encrypted asset credentials exist but "
                "app.asset_credential_encryption_key is not configured"
            )
        token = value[len(ENCRYPTED_VALUE_PREFIX):]
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise CredentialCipherError(
                "failed to decrypt asset credentials; verify the configured encryption key"
            ) from exc
