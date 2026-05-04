from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class TelegramNotificationType(str, Enum):
    SYSTEM_STARTUP = "system_startup"
    PROVISION_SUCCESS = "provision_success"
    PROVISION_FAILURE = "provision_failure"
    HEALING_SUCCESS = "healing_success"
    HEALING_FAILURE = "healing_failure"
    ACCOUNT_ABANDONED = "account_abandoned"
    DAEMON_WORKER_FAILED = "daemon_worker_failed"


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TelegramNotificationType
    level: Literal["INFO", "ERROR", "CRITICAL"]
    title: str
    body: str

    @field_validator("title", "body")
    @classmethod
    def validate_non_empty_fields(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("message fields must not be empty")
        return value.strip()
