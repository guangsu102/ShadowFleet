from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Coroutine
from typing import Any

from telegram import Bot
from telegram.error import TelegramError

from models.message_models import TelegramMessage
from utils.logger import set_event_type


class TelegramReporter:
    def __init__(
        self,
        enabled: bool,
        bot_token: str | None,
        chat_id: str | None,
        message_prefix: str,
        timeout_seconds: int,
        max_retries: int,
        retry_backoff_seconds: float,
        logger: logging.Logger,
    ) -> None:
        self._enabled = enabled
        self._chat_id = chat_id
        self._message_prefix = message_prefix
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._logger = logger
        self._bot = Bot(token=bot_token) if enabled and bot_token else None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def send(self, message: TelegramMessage) -> bool:
        if not self._enabled:
            set_event_type("telegram_disabled")
            self._logger.info("Telegram reporter disabled; message skipped.")
            return False

        if self._bot is None or self._chat_id is None:
            set_event_type("telegram_not_configured")
            self._logger.error("Telegram reporter is enabled but bot client is not configured.")
            return False

        text = self._build_message_text(message)

        for attempt in range(self._max_retries + 1):
            try:
                self._run_async(
                    self._bot.send_message(
                        chat_id=self._chat_id,
                        text=text,
                        connect_timeout=self._timeout_seconds,
                        read_timeout=self._timeout_seconds,
                        write_timeout=self._timeout_seconds,
                        pool_timeout=self._timeout_seconds,
                    )
                )
                set_event_type("telegram_message_sent")
                self._logger.info("Telegram message sent successfully.")
                return True
            except TelegramError:
                set_event_type("telegram_message_failed")
                self._logger.exception(
                    "Telegram API returned an error while sending message.",
                )
            except RuntimeError:
                set_event_type("telegram_message_failed")
                self._logger.exception(
                    "Failed to execute Telegram coroutine.",
                )

            if attempt < self._max_retries:
                time.sleep(self._retry_backoff_seconds * (2**attempt))

        set_event_type("telegram_message_failed")
        self._logger.error("Telegram message exhausted all retries.")
        return False

    def _build_message_text(self, message: TelegramMessage) -> str:
        return (
            f"{self._message_prefix} [{message.level}] [{message.type.value}]\n"
            f"{message.title}\n"
            f"{message.body}"
        )

    def _run_async(self, coroutine: Coroutine[Any, Any, Any]) -> None:
        def _run_in_thread() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(coroutine)
            finally:
                loop.close()

        thread = threading.Thread(target=_run_in_thread, daemon=True)
        thread.start()
        thread.join()
