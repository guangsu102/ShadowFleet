"""
Tests for RealityKeyGenerator service
"""
import subprocess
from unittest.mock import Mock, patch

import pytest

from services.reality_key_generator import RealityKeyGenerator, RealityKeyGeneratorError


class TestRealityKeyGenerator:
    """Test RealityKeyGenerator"""

    def test_generate_key_pair_with_xray_success(self):
        """Test generating key pair with xray command successfully"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Private key: test_private_key_123\nPublic key: test_public_key_456"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            private_key, public_key = RealityKeyGenerator.generate_key_pair()

            assert private_key == "test_private_key_123"
            assert public_key == "test_public_key_456"
            mock_run.assert_called_once_with(
                ["xray", "x25519"],
                capture_output=True,
                text=True,
                timeout=5
            )

    def test_generate_key_pair_xray_not_found_fallback_to_cryptography(self):
        """Test fallback to cryptography when xray is not found"""
        with patch("subprocess.run", side_effect=FileNotFoundError("xray not found")):
            with patch("cryptography.hazmat.primitives.asymmetric.x25519") as mock_x25519:
                mock_private_key = Mock()
                mock_public_key = Mock()
                mock_private_key.public_key.return_value = mock_public_key
                mock_private_key.private_bytes.return_value = b"private_bytes_32"
                mock_public_key.public_bytes.return_value = b"public_bytes_32_chars_here"

                mock_x25519.X25519PrivateKey.generate.return_value = mock_private_key

                private_key, public_key = RealityKeyGenerator.generate_key_pair()

                assert isinstance(private_key, str)
                assert isinstance(public_key, str)
                # Base64 encoded values
                assert len(private_key) > 0
                assert len(public_key) > 0

    def test_generate_key_pair_xray_subprocess_error_fallback(self):
        """Test fallback when xray subprocess fails"""
        with patch("subprocess.run", side_effect=subprocess.SubprocessError("xray error")):
            with patch("cryptography.hazmat.primitives.asymmetric.x25519") as mock_x25519:
                mock_private_key = Mock()
                mock_public_key = Mock()
                mock_private_key.public_key.return_value = mock_public_key
                mock_private_key.private_bytes.return_value = b"private_bytes_32"
                mock_public_key.public_bytes.return_value = b"public_bytes_32_chars_here"

                mock_x25519.X25519PrivateKey.generate.return_value = mock_private_key

                private_key, public_key = RealityKeyGenerator.generate_key_pair()

                assert isinstance(private_key, str)
                assert isinstance(public_key, str)

    def test_generate_with_xray_success(self):
        """Test _generate_with_xray method directly"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Private key: xray_private\nPublic key: xray_public"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            private_key, public_key = RealityKeyGenerator._generate_with_xray()

            assert private_key == "xray_private"
            assert public_key == "xray_public"

    def test_generate_with_xray_non_zero_return_code(self):
        """Test _generate_with_xray with non-zero return code"""
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "xray error message"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="xray x25519 failed"):
                RealityKeyGenerator._generate_with_xray()

    def test_generate_with_xray_unexpected_output_format(self):
        """Test _generate_with_xray with unexpected output format"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Invalid output"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Unexpected xray output"):
                RealityKeyGenerator._generate_with_xray()

    def test_generate_with_xray_single_line_output(self):
        """Test _generate_with_xray with single line output"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Private key: only_one_line"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Unexpected xray output"):
                RealityKeyGenerator._generate_with_xray()

    def test_generate_with_cryptography_success(self):
        """Test _generate_with_cryptography method directly"""
        with patch("cryptography.hazmat.primitives.asymmetric.x25519") as mock_x25519:
            mock_private_key = Mock()
            mock_public_key = Mock()
            mock_private_key.public_key.return_value = mock_public_key
            mock_private_key.private_bytes.return_value = b"a" * 32
            mock_public_key.public_bytes.return_value = b"b" * 32

            mock_x25519.X25519PrivateKey.generate.return_value = mock_private_key

            private_key, public_key = RealityKeyGenerator._generate_with_cryptography()

            assert isinstance(private_key, str)
            assert isinstance(public_key, str)
            # Base64 encoded 32 bytes should be 44 characters
            assert len(private_key) == 44
            assert len(public_key) == 44

    def test_generate_with_cryptography_import_error(self):
        """Test _generate_with_cryptography when cryptography is not installed"""
        import sys
        with patch.dict(sys.modules, {'cryptography.hazmat.primitives.asymmetric.x25519': None}):
            with pytest.raises(RealityKeyGeneratorError, match="Neither xray command nor cryptography library"):
                RealityKeyGenerator._generate_with_cryptography()

    def test_generate_key_pair_both_methods_fail(self):
        """Test when both xray and cryptography fail"""
        import sys
        with patch("subprocess.run", side_effect=FileNotFoundError("xray not found")):
            with patch.dict(sys.modules, {'cryptography.hazmat.primitives.asymmetric.x25519': None}):
                with pytest.raises(RealityKeyGeneratorError, match="Neither xray command nor cryptography library"):
                    RealityKeyGenerator.generate_key_pair()

    def test_generate_with_xray_timeout(self):
        """Test _generate_with_xray with timeout"""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("xray", 5)):
            with pytest.raises(subprocess.TimeoutExpired):
                RealityKeyGenerator._generate_with_xray()

    def test_generate_key_pair_xray_timeout_fallback(self):
        """Test fallback when xray times out"""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("xray", 5)):
            with patch("cryptography.hazmat.primitives.asymmetric.x25519") as mock_x25519:
                mock_private_key = Mock()
                mock_public_key = Mock()
                mock_private_key.public_key.return_value = mock_public_key
                mock_private_key.private_bytes.return_value = b"c" * 32
                mock_public_key.public_bytes.return_value = b"d" * 32

                mock_x25519.X25519PrivateKey.generate.return_value = mock_private_key

                private_key, public_key = RealityKeyGenerator.generate_key_pair()

                assert isinstance(private_key, str)
                assert isinstance(public_key, str)

    def test_generate_with_xray_output_with_extra_whitespace(self):
        """Test _generate_with_xray handles extra whitespace"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "  Private key:   key_with_spaces  \n  Public key:   pub_with_spaces  \n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            private_key, public_key = RealityKeyGenerator._generate_with_xray()

            assert private_key == "key_with_spaces"
            assert public_key == "pub_with_spaces"

    def test_generate_with_cryptography_encoding(self):
        """Test that cryptography method uses correct encoding"""
        with patch("cryptography.hazmat.primitives.asymmetric.x25519") as mock_x25519:
            with patch("cryptography.hazmat.primitives.serialization") as mock_serialization:
                mock_private_key = Mock()
                mock_public_key = Mock()
                mock_private_key.public_key.return_value = mock_public_key
                mock_private_key.private_bytes.return_value = b"private_32_bytes_test_value!"
                mock_public_key.public_bytes.return_value = b"public_32_bytes_test_value!!"

                mock_x25519.X25519PrivateKey.generate.return_value = mock_private_key

                private_key, public_key = RealityKeyGenerator._generate_with_cryptography()

                # Verify the encoding calls
                mock_private_key.private_bytes.assert_called_once_with(
                    encoding=mock_serialization.Encoding.Raw,
                    format=mock_serialization.PrivateFormat.Raw,
                    encryption_algorithm=mock_serialization.NoEncryption()
                )
                mock_public_key.public_bytes.assert_called_once_with(
                    encoding=mock_serialization.Encoding.Raw,
                    format=mock_serialization.PublicFormat.Raw
                )

    def test_reality_key_generator_error_inheritance(self):
        """Test that RealityKeyGeneratorError is a RuntimeError"""
        error = RealityKeyGeneratorError("test error")
        assert isinstance(error, RuntimeError)
        assert str(error) == "test error"
