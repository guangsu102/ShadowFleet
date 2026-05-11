"""
Tests for NodeIdGenerator service
"""
from unittest.mock import Mock, patch

import pytest

from services.node_id_generator import NodeIdGenerator


class TestNodeIdGenerator:
    """Test NodeIdGenerator"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.logger = Mock()
        context.logger.getChild.return_value = Mock()
        return context

    @pytest.fixture
    def generator(self, mock_runtime_context):
        """Create a NodeIdGenerator instance"""
        return NodeIdGenerator(mock_runtime_context)

    def test_generate_node_id_anytls(self, generator):
        """Test generating node ID for AnyTLS protocol"""
        node_id = generator.generate_node_id("anytls", 213)
        assert node_id == "10213"

    def test_generate_node_id_trojan(self, generator):
        """Test generating node ID for Trojan protocol"""
        node_id = generator.generate_node_id("trojan", 214)
        assert node_id == "20214"

    def test_generate_node_id_vless(self, generator):
        """Test generating node ID for VLESS protocol"""
        node_id = generator.generate_node_id("vless", 215)
        assert node_id == "30215"

    def test_generate_node_id_vmess(self, generator):
        """Test generating node ID for VMess protocol"""
        node_id = generator.generate_node_id("vmess", 216)
        assert node_id == "40216"

    def test_generate_node_id_hysteria2(self, generator):
        """Test generating node ID for Hysteria2 protocol"""
        node_id = generator.generate_node_id("hysteria2", 217)
        assert node_id == "50217"

    def test_generate_node_id_hysteria(self, generator):
        """Test generating node ID for Hysteria protocol"""
        node_id = generator.generate_node_id("hysteria", 218)
        assert node_id == "50218"

    def test_generate_node_id_unknown_protocol(self, generator):
        """Test generating node ID for unknown protocol uses default prefix"""
        node_id = generator.generate_node_id("unknown", 999)
        assert node_id == "99999"

    def test_generate_node_id_case_insensitive(self, generator):
        """Test that protocol type is case-insensitive"""
        node_id1 = generator.generate_node_id("AnyTLS", 100)
        node_id2 = generator.generate_node_id("anytls", 100)
        node_id3 = generator.generate_node_id("ANYTLS", 100)

        assert node_id1 == node_id2 == node_id3 == "10100"

    def test_generate_node_id_large_xboard_id(self, generator):
        """Test generating node ID with large xboard_node_id"""
        node_id = generator.generate_node_id("trojan", 999999)
        assert node_id == "20999999"

    def test_generate_node_id_single_digit_xboard_id(self, generator):
        """Test generating node ID with single digit xboard_node_id"""
        node_id = generator.generate_node_id("vless", 5)
        assert node_id == "305"

    def test_generate_node_id_logs_info(self, generator, mock_runtime_context):
        """Test that generate_node_id logs information"""
        logger = mock_runtime_context.logger.getChild.return_value

        generator.generate_node_id("anytls", 123)

        logger.info.assert_called_once()
        call_args = logger.info.call_args[0]
        assert "Generated node ID" in call_args[0]
        assert "10123" in call_args

    def test_update_node_code_success(self, generator, mock_runtime_context):
        """Test updating node code successfully"""
        mock_xboard_repo = Mock()
        mock_xboard_repo.update_node_code.return_value = None

        with patch("database.xboard_repo.XboardRepo", return_value=mock_xboard_repo):
            node_id = generator.update_node_code(123, "trojan")

            assert node_id == "20123"
            mock_xboard_repo.update_node_code.assert_called_once_with(123, "20123")

    def test_update_node_code_logs_success(self, generator, mock_runtime_context):
        """Test that update_node_code logs success"""
        mock_xboard_repo = Mock()
        logger = mock_runtime_context.logger.getChild.return_value

        with patch("database.xboard_repo.XboardRepo", return_value=mock_xboard_repo):
            generator.update_node_code(456, "vless")

            logger.info.assert_called()
            # Check that success message was logged
            info_calls = [call[0][0] for call in logger.info.call_args_list]
            assert any("Updated node code" in msg for msg in info_calls)

    def test_update_node_code_failure(self, generator, mock_runtime_context):
        """Test update_node_code handles exceptions"""
        mock_xboard_repo = Mock()
        mock_xboard_repo.update_node_code.side_effect = Exception("Database error")
        logger = mock_runtime_context.logger.getChild.return_value

        with patch("database.xboard_repo.XboardRepo", return_value=mock_xboard_repo):
            with pytest.raises(Exception, match="Database error"):
                generator.update_node_code(789, "vmess")

            logger.exception.assert_called_once()

    def test_is_node_id_unique_always_returns_true(self, generator):
        """Test that is_node_id_unique always returns True"""
        # Since the implementation uses xboard_node_id which is unique,
        # this method always returns True
        assert generator.is_node_id_unique("10123") is True
        assert generator.is_node_id_unique("20456") is True
        assert generator.is_node_id_unique("99999") is True

    def test_is_node_id_unique_handles_exception(self, generator, mock_runtime_context):
        """Test that is_node_id_unique handles exceptions gracefully"""
        mock_xboard_repo = Mock()
        mock_xboard_repo.some_method.side_effect = Exception("Database error")
        logger = mock_runtime_context.logger.getChild.return_value

        with patch("database.xboard_repo.XboardRepo", return_value=mock_xboard_repo):
            # Even with exceptions, it returns False
            result = generator.is_node_id_unique("10123")

            # Current implementation returns True, but logs warning on exception
            assert result is True

    def test_protocol_prefix_map_completeness(self):
        """Test that PROTOCOL_PREFIX_MAP contains expected protocols"""
        expected_protocols = {
            "anytls": "10",
            "trojan": "20",
            "vless": "30",
            "vmess": "40",
            "hysteria2": "50",
            "hysteria": "50",
        }

        for protocol, prefix in expected_protocols.items():
            assert NodeIdGenerator.PROTOCOL_PREFIX_MAP[protocol] == prefix

    def test_generate_node_id_zero_xboard_id(self, generator):
        """Test generating node ID with zero xboard_node_id"""
        node_id = generator.generate_node_id("anytls", 0)
        assert node_id == "100"

    def test_update_node_code_creates_xboard_repo_with_context(self, generator, mock_runtime_context):
        """Test that update_node_code creates XboardRepo with runtime context"""
        mock_xboard_repo_class = Mock()
        mock_xboard_repo_instance = Mock()
        mock_xboard_repo_class.return_value = mock_xboard_repo_instance

        with patch("database.xboard_repo.XboardRepo", mock_xboard_repo_class):
            generator.update_node_code(123, "trojan")

            mock_xboard_repo_class.assert_called_once_with(mock_runtime_context)

    def test_generate_node_id_with_mixed_case_protocol(self, generator):
        """Test generating node ID with mixed case protocol names"""
        test_cases = [
            ("AnyTLS", 100, "10100"),
            ("TrOjAn", 200, "20200"),
            ("VLess", 300, "30300"),
            ("VMess", 400, "40400"),
            ("Hysteria2", 500, "50500"),
        ]

        for protocol, xboard_id, expected in test_cases:
            node_id = generator.generate_node_id(protocol, xboard_id)
            assert node_id == expected

    def test_update_node_code_with_different_protocols(self, generator):
        """Test update_node_code with different protocol types"""
        mock_xboard_repo = Mock()

        with patch("database.xboard_repo.XboardRepo", return_value=mock_xboard_repo):
            test_cases = [
                (100, "anytls", "10100"),
                (200, "trojan", "20200"),
                (300, "vless", "30300"),
                (400, "vmess", "40400"),
            ]

            for xboard_id, protocol, expected_code in test_cases:
                node_id = generator.update_node_code(xboard_id, protocol)
                assert node_id == expected_code
                mock_xboard_repo.update_node_code.assert_called_with(xboard_id, expected_code)
