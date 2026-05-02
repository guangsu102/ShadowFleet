from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["INFO", "ERROR", "CRITICAL"]
    title: str
    body: str

    @field_validator("title", "body")
    @classmethod
    def validate_non_empty_fields(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("message fields must not be empty")
        return value.strip()
