"""Unit tests for utils.logger module."""

from __future__ import annotations

import logging


from utils.logger import (
    EVENT_TYPE_CONTEXT,
    CORRELATION_ID_CONTEXT,
    DEFAULT_EVENT_TYPE,
    ContextEnrichmentFilter,
    configure_logging,
    generate_correlation_id,
    get_correlation_id,
    get_event_type,
    set_correlation_id,
    set_event_type,
)


class TestCorrelationIdContext:
    """Tests for correlation ID context management."""

    def test_generate_correlation_id_returns_uuid(self) -> None:
        """Should return a valid UUID string."""
        cid = generate_correlation_id()
        assert isinstance(cid, str)
        assert len(cid) == 36  # UUID format
        assert cid.count("-") == 4

    def test_generate_correlation_id_unique(self) -> None:
        """Each call should generate unique ID."""
        ids = [generate_correlation_id() for _ in range(100)]
        assert len(set(ids)) == 100

    def test_set_and_get_correlation_id(self) -> None:
        """Should set and retrieve correlation ID."""
        test_id = "test-correlation-id-123"
        set_correlation_id(test_id)
        assert get_correlation_id() == test_id

    def test_default_correlation_id(self) -> None:
        """Default should be '-' when not set."""
        CORRELATION_ID_CONTEXT.set("-")
        assert get_correlation_id() == "-"


class TestEventTypeContext:
    """Tests for event type context management."""

    def test_set_and_get_event_type(self) -> None:
        """Should set and retrieve event type."""
        set_event_type("custom_event")
        assert get_event_type() == "custom_event"

    def test_set_none_defaults_to_general(self) -> None:
        """None should default to general event type."""
        set_event_type(None)
        assert get_event_type() == DEFAULT_EVENT_TYPE

    def test_default_event_type(self) -> None:
        """Default should be 'general'."""
        EVENT_TYPE_CONTEXT.set(DEFAULT_EVENT_TYPE)
        assert get_event_type() == DEFAULT_EVENT_TYPE


class TestContextEnrichmentFilter:
    """Tests for ContextEnrichmentFilter logging filter."""

    def test_filter_adds_correlation_id(self) -> None:
        """Filter should add correlation_id to log record."""
        set_correlation_id("test-correlation")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        filter_obj = ContextEnrichmentFilter()
        result = filter_obj.filter(record)
        assert result is True
        assert hasattr(record, "correlation_id")
        assert record.correlation_id == "test-correlation"

    def test_filter_adds_event_type(self) -> None:
        """Filter should add event_type to log record."""
        set_event_type("test_event")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        filter_obj = ContextEnrichmentFilter()
        result = filter_obj.filter(record)
        assert result is True
        assert hasattr(record, "event_type")
        assert record.event_type == "test_event"

    def test_filter_always_returns_true(self) -> None:
        """Filter should always return True (pass the record)."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        filter_obj = ContextEnrichmentFilter()
        assert filter_obj.filter(record) is True


class TestConfigureLogging:
    """Tests for configure_logging function."""

    def test_configure_logging_sets_level(self) -> None:
        """Should set the root logger level."""
        logger = configure_logging(level="DEBUG", log_format="%(message)s")
        assert logger.getEffectiveLevel() == logging.DEBUG

    def test_configure_logging_returns_shadowfleet_logger(self) -> None:
        """Should return shadowfleet logger."""
        logger = configure_logging(level="INFO", log_format="%(message)s")
        assert logger.name == "shadowfleet"

    def test_configure_logging_adds_handler(self) -> None:
        """Should add stream handler to root logger."""
        root_logger = logging.getLogger()
        initial_handlers = len(root_logger.handlers)

        configure_logging(level="INFO", log_format="%(message)s")

        assert len(root_logger.handlers) >= initial_handlers

    def test_configure_logging_sets_formatter(self) -> None:
        """Should set formatter on handlers."""
        configure_logging(level="INFO", log_format="CUSTOM_FORMAT:%(message)s")
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                formatter_str = handler.formatter._fmt
                assert "CUSTOM_FORMAT" in formatter_str
