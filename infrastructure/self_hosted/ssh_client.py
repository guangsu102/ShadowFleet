from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import PurePosixPath
import socket

import paramiko
from paramiko import AutoAddPolicy, SSHClient
from paramiko.pkey import PKey
from paramiko.ssh_exception import AuthenticationException, SSHException

from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


DEFAULT_REMOTE_SCRIPT_PATH = "/tmp/shadowfleet-provision.sh"


class SelfHostedSshClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        exit_status: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.exit_status = exit_status
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True)
class SelfHostedSshConfig:
    host: str
    port: int
    username: str
    password: str | None = None
    private_key: str | None = None


@dataclass(frozen=True)
class RemoteCommandResult:
    exit_status: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class HardwareSpec:
    cpu_cores: int
    memory_gb: float


class SelfHostedSshClient:
    def __init__(self, runtime_context: RuntimeContext, ssh_config: SelfHostedSshConfig) -> None:
        self._runtime_context = runtime_context
        self._ssh_config = ssh_config
        self._logger = runtime_context.logger.getChild("infrastructure.self_hosted.ssh")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds

    def execute_script(
        self,
        script_content: str,
        remote_script_path: str = DEFAULT_REMOTE_SCRIPT_PATH,
    ) -> RemoteCommandResult:
        if not script_content.strip():
            raise ValueError("script_content must not be empty")

        remote_path = PurePosixPath(remote_script_path)
        client = self._connect()
        try:
            self._upload_text_file(
                client=client,
                remote_path=str(remote_path),
                content=script_content,
            )
            cleanup_command = (
                f"sudo bash {remote_path} ; "
                "exit_code=$? ; "
                "history -c || true ; "
                f"sudo rm -f {remote_path} ; "
                "exit $exit_code"
            )
            result = self._run_command(client=client, command=cleanup_command)
            if result.exit_status != 0:
                raise SelfHostedSshClientError(
                    f"Remote provisioning script failed with exit_status={result.exit_status}: "
                    f"{result.stderr.strip() or result.stdout.strip()}",
                    stage="execute_script",
                    exit_status=result.exit_status,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )

            set_event_type("self_hosted_script_executed")
            self._logger.info(
                "Executed remote provisioning script host=%s port=%s",
                self._ssh_config.host,
                self._ssh_config.port,
            )
            return result
        finally:
            client.close()

    def _connect(self) -> SSHClient:
        if not self._ssh_config.host.strip():
            raise ValueError("host must not be empty")
        if self._ssh_config.port <= 0:
            raise ValueError("port must be greater than 0")
        if not self._ssh_config.username.strip():
            raise ValueError("username must not be empty")
        if not self._ssh_config.password and not self._ssh_config.private_key:
            raise ValueError("password or private_key is required")

        client = SSHClient()
        client.set_missing_host_key_policy(AutoAddPolicy())
        try:
            client.connect(
                hostname=self._ssh_config.host.strip(),
                port=self._ssh_config.port,
                username=self._ssh_config.username.strip(),
                password=self._ssh_config.password,
                pkey=self._load_private_key(self._ssh_config.private_key),
                timeout=self._request_timeout_seconds,
                banner_timeout=self._request_timeout_seconds,
                auth_timeout=self._request_timeout_seconds,
            )
        except (AuthenticationException, SSHException, socket.timeout, OSError) as exc:
            set_event_type("self_hosted_ssh_connect_failed")
            self._logger.exception(
                "Failed to connect to self-hosted asset host=%s port=%s",
                self._ssh_config.host,
                self._ssh_config.port,
            )
            raise SelfHostedSshClientError(
                "Failed to connect to self-hosted asset over SSH",
                stage="connect",
            ) from exc

        set_event_type("self_hosted_ssh_connected")
        self._logger.info(
            "Connected to self-hosted asset host=%s port=%s",
            self._ssh_config.host,
            self._ssh_config.port,
        )
        return client

    def detect_hardware(self) -> HardwareSpec:
        """Detect CPU cores and memory (GB) on the remote machine via SSH."""
        client = self._connect()
        try:
            cpu_cmd = "nproc 2>/dev/null || grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo 1"
            mem_cmd = (
                "awk '/MemTotal/{printf \"%.1f\", $2/1024/1024}' /proc/meminfo 2>/dev/null "
                "|| echo 'unknown'"
            )
            cpu_result = self._run_command(client=client, command=cpu_cmd)
            mem_result = self._run_command(client=client, command=mem_cmd)

            cpu_cores: int
            memory_gb: float

            try:
                cpu_cores = max(1, int(cpu_result.stdout.strip()))
            except ValueError:
                cpu_cores = 1

            try:
                memory_gb = round(float(mem_result.stdout.strip()), 1)
            except ValueError:
                memory_gb = 0.0

            self._logger.info(
                "Detected hardware host=%s cpu_cores=%s memory_gb=%s",
                self._ssh_config.host,
                cpu_cores,
                memory_gb,
            )
            set_event_type("self_hosted_hardware_detected")
            return HardwareSpec(cpu_cores=cpu_cores, memory_gb=memory_gb)
        finally:
            client.close()

    def _upload_text_file(
        self,
        client: SSHClient,
        remote_path: str,
        content: str,
    ) -> None:
        try:
            sftp = client.open_sftp()
            with sftp.file(remote_path, "w") as remote_file:
                remote_file.write(content)
            sftp.chmod(remote_path, 0o700)
        except (OSError, SSHException) as exc:
            set_event_type("self_hosted_ssh_upload_failed")
            self._logger.exception("Failed to upload provisioning script to %s", remote_path)
            raise SelfHostedSshClientError(
                "Failed to upload provisioning script to self-hosted asset",
                stage="upload_script",
            ) from exc
        finally:
            try:
                sftp.close()
            except Exception:
                pass

        set_event_type("self_hosted_ssh_uploaded")
        self._logger.info("Uploaded provisioning script to %s", remote_path)

    def _run_command(self, client: SSHClient, command: str) -> RemoteCommandResult:
        try:
            stdin, stdout, stderr = client.exec_command(
                command,
                timeout=self._request_timeout_seconds,
                get_pty=True,
            )
            stdin.close()
            exit_status = int(stdout.channel.recv_exit_status())
            stdout_text = stdout.read().decode("utf-8", errors="replace")
            stderr_text = stderr.read().decode("utf-8", errors="replace")
        except (OSError, SSHException, socket.timeout) as exc:
            set_event_type("self_hosted_ssh_command_failed")
            self._logger.exception("Failed to execute remote SSH command")
            raise SelfHostedSshClientError(
                "Failed to execute remote SSH command",
                stage="execute_command",
            ) from exc

        return RemoteCommandResult(
            exit_status=exit_status,
            stdout=stdout_text,
            stderr=stderr_text,
        )

    @staticmethod
    def _load_private_key(private_key_text: str | None) -> PKey | None:
        if private_key_text is None or not private_key_text.strip():
            return None

        key_buffer = StringIO(private_key_text)
        key_loaders = (
            paramiko.RSAKey.from_private_key,
            paramiko.Ed25519Key.from_private_key,
            paramiko.ECDSAKey.from_private_key,
            paramiko.DSSKey.from_private_key,
        )
        for key_loader in key_loaders:
            key_buffer.seek(0)
            try:
                return key_loader(key_buffer)
            except Exception:
                continue

        raise SelfHostedSshClientError(
            "Unsupported or invalid SSH private key",
            stage="load_private_key",
        )
