"""
Reality 密钥对生成器
为 VLESS Reality 协议生成公钥/私钥对
"""
from __future__ import annotations

import subprocess
import base64
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class RealityKeyGeneratorError(RuntimeError):
    pass


class RealityKeyGenerator:
    """Reality 密钥对生成器"""

    @staticmethod
    def generate_key_pair() -> tuple[str, str]:
        """
        生成 Reality 密钥对

        优先使用 xray x25519 命令生成，如果失败则使用 Python cryptography 库

        Returns:
            (private_key, public_key) 元组
        """
        # 尝试使用 xray 命令生成
        try:
            return RealityKeyGenerator._generate_with_xray()
        except (FileNotFoundError, subprocess.SubprocessError, RuntimeError):
            # xray 不可用，使用 Python 实现
            return RealityKeyGenerator._generate_with_cryptography()

    @staticmethod
    def _generate_with_xray() -> tuple[str, str]:
        """
        使用 xray x25519 命令生成密钥对

        Returns:
            (private_key, public_key) 元组

        Raises:
            FileNotFoundError: xray 命令不存在
            RuntimeError: xray 命令执行失败
        """
        result = subprocess.run(
            ['xray', 'x25519'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            raise RuntimeError(f"xray x25519 failed: {result.stderr}")

        # 解析输出
        # 输出格式：
        # Private key: xxx
        # Public key: yyy
        lines = result.stdout.strip().split('\n')
        if len(lines) < 2:
            raise RuntimeError(f"Unexpected xray output: {result.stdout}")

        private_key = lines[0].split(': ', 1)[1].strip()
        public_key = lines[1].split(': ', 1)[1].strip()

        return private_key, public_key

    @staticmethod
    def _generate_with_cryptography() -> tuple[str, str]:
        """
        使用 Python cryptography 库生成密钥对（备用方法）

        Returns:
            (private_key, public_key) 元组

        Raises:
            ImportError: cryptography 库未安装
        """
        try:
            from cryptography.hazmat.primitives.asymmetric import x25519
            from cryptography.hazmat.primitives import serialization
        except ImportError as exc:
            raise RealityKeyGeneratorError(
                "Neither xray command nor cryptography library is available. "
                "Please install xray-core or run: pip install cryptography"
            ) from exc

        # 生成私钥
        private_key_obj = x25519.X25519PrivateKey.generate()
        public_key_obj = private_key_obj.public_key()

        # 转换为 raw bytes
        private_bytes = private_key_obj.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_bytes = public_key_obj.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )

        # 转换为 base64
        private_b64 = base64.b64encode(private_bytes).decode('utf-8')
        public_b64 = base64.b64encode(public_bytes).decode('utf-8')

        return private_b64, public_b64
