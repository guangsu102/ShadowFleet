"""Tests for TelegramReporter without real network calls."""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock

from telegram.error import TelegramError

from models.message_models import TelegramMessage
from utils.tg_reporter import TelegramReporter


def make_reporter(
    enabled: bool = True,
    bot_token: str | None = "dummy-token",
    chat_id: str | None = "123456",
    max_retries: int = 2,
    retry_backoff_seconds: float = 0.001,
) -> TelegramReporter:
    return TelegramReporter(
        enabled=enabled,
        bot_token=bot_token,
        chat_id=chat_id,
        message_prefix="[ShadowFleet]",
        timeout_seconds=5,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        logger=logging.getLogger("test.tg_reporter"),
    )


class TestTelegramReporterBasic:
    def test_disabled_returns_false(self) -> None:
        reporter = make_reporter(enabled=False)
        message = TelegramMessage(level="INFO", title="t", body="b")
        assert reporter.send(message) is False

    def test_not_configured_returns_false(self) -> None:
        reporter = make_reporter(enabled=True, bot_token=None)
        message = TelegramMessage(level="INFO", title="t", body="b")
        assert reporter.send(message) is False

    def test_missing_chat_id_returns_false(self) -> None:
        reporter = make_reporter(enabled=True, chat_id=None)
        message = TelegramMessage(level="INFO", title="t", body="b")
        assert reporter.send(message) is False

    def test_message_format(self) -> None:
        reporter = make_reporter()
        message = TelegramMessage(level="ERROR", title="title", body="line1\nline2")
        text = reporter._build_message_text(message)
        assert "[ShadowFleet] [ERROR]" in text
        assert "title" in text
        assert "line1" in text


class TestTelegramReporterSend:
    def test_send_success_calls_bot_with_timeouts(self) -> None:
        reporter = make_reporter(max_retries=0)
        reporter._bot = MagicMock()
        reporter._bot.send_message = MagicMock(return_value=object())
        reporter._run_async = MagicMock(return_value=None)

        message = TelegramMessage(level="INFO", title="ok", body="done")
        result = reporter.send(message)

        assert result is True
        reporter._bot.send_message.assert_called_once()
        kwargs = reporter._bot.send_message.call_args.kwargs
        assert kwargs["chat_id"] == "123456"
        assert kwargs["connect_timeout"] == 5
        assert kwargs["read_timeout"] == 5
        assert kwargs["write_timeout"] == 5
        assert kwargs["pool_timeout"] == 5

    def test_send_retries_then_success(self) -> None:
        reporter = make_reporter(max_retries=2, retry_backoff_seconds=0.001)
        reporter._bot = MagicMock()
        reporter._bot.send_message = MagicMock(return_value=object())
        reporter._run_async = MagicMock(
            side_effect=[
                TelegramError("rate-limit"),
                TelegramError("temporary"),
                None,
            ]
        )

        message = TelegramMessage(level="INFO", title="retry", body="body")
        result = reporter.send(message)

        assert result is True
        assert reporter._run_async.call_count == 3
        assert reporter._bot.send_message.call_count == 3

    def test_send_exhausts_retries(self) -> None:
        reporter = make_reporter(max_retries=2, retry_backoff_seconds=0.001)
        reporter._bot = MagicMock()
        reporter._bot.send_message = MagicMock(return_value=object())
        reporter._run_async = MagicMock(side_effect=TelegramError("fail"))

        message = TelegramMessage(level="ERROR", title="fail", body="body")
        result = reporter.send(message)

        assert result is False
        assert reporter._run_async.call_count == 3

    def test_send_runtime_error_exhausts_retries(self) -> None:
        reporter = make_reporter(max_retries=1, retry_backoff_seconds=0.001)
        reporter._bot = MagicMock()
        reporter._bot.send_message = MagicMock(return_value=object())
        reporter._run_async = MagicMock(side_effect=RuntimeError("bridge"))

        message = TelegramMessage(level="ERROR", title="runtime", body="body")
        result = reporter.send(message)

        assert result is False
        assert reporter._run_async.call_count == 2

    def test_backoff_applies_delay(self) -> None:
        reporter = make_reporter(max_retries=3, retry_backoff_seconds=0.01)
        reporter._bot = MagicMock()
        reporter._bot.send_message = MagicMock(return_value=object())
        reporter._run_async = MagicMock(side_effect=TelegramError("always fail"))

        message = TelegramMessage(level="ERROR", title="backoff", body="body")
        start = time.monotonic()
        reporter.send(message)
        elapsed = time.monotonic() - start

        assert elapsed >= 0.05
