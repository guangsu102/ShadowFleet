from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
import signal
import socket
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from services.monitor import MonitorService
from services.manual_operation_service import ManualOperationService
from services.provisioning_task_service import ProvisioningTaskService
from services.runtime_service import RuntimeContext, build_runtime_context, get_daemon_public_ipv6
from utils.logger import set_correlation_id, set_event_type
import logging
from utils.template_models import GITHUB_ARTIFACT_MANIFEST
from services.daemon_notifier import notify_daemon_worker_cycle_failed, DaemonWorkerAlertContext

READY_CALLBACK_PATH = "/api/v1/provisioning/ready"

PROBE_REGISTER_PATH = "/probe/register"
PROBE_HEARTBEAT_PATH = "/probe/heartbeat"
PROBE_POLL_PATH = "/probe/poll"
PROBE_RESULT_PATH = "/probe/result"
PROBE_CONFIG_PATH = "/probe/config"

ARTIFACT_CACHE_DIR = "/var/www/shadowfleet-artifacts"


def _build_artifact_cache_dir() -> Path:
    return Path(ARTIFACT_CACHE_DIR)



def _ensure_artifact_cache_dir() -> Path:
    cache_dir = _build_artifact_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _download_artifact(url: str, dest_path: Path, timeout: int = 30) -> bool:
    import subprocess
    try:
        result = subprocess.run(
            ["curl", "-fsSL", "--max-time", str(timeout), "-o", str(dest_path), url],
            capture_output=True,
            timeout=timeout + 5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _get_latest_v2bx_version() -> str | None:
    import subprocess
    try:
        result = subprocess.run(
            [
                "curl", "-fsSL", "--max-time", "10",
                "https://api.github.com/repos/wyx2685/V2bX/releases/latest",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return None
        import re as _re
        match = _re.search(r'"tag_name":\s*"([^"]+)"', result.stdout)
        return match.group(1) if match else None
    except Exception:
        return None


def _sync_artifact(artifact_name: str, origin_url: str, cache_dir: Path) -> bool:
    dest = cache_dir / artifact_name
    if _download_artifact(origin_url, dest):
        dest.chmod(0o644)
        return True
    return False


def _ensure_artifact(artifact_name: str) -> bool:
    """Fetch artifact from GitHub if missing from cache. Returns success."""
    cache_dir = _build_artifact_cache_dir()
    dest = cache_dir / artifact_name
    if dest.exists():
        return True
    origin_url = GITHUB_ARTIFACT_MANIFEST.get(artifact_name)
    if not origin_url:
        return False
    return _sync_artifact(artifact_name, origin_url, cache_dir)


def _ensure_v2bx_binary(arch: str, version: str | None = None) -> bool:
    """Fetch V2bX binary zip if missing. Returns success."""
    if version is None:
        version = _get_latest_v2bx_version()
        if version is None:
            return False
    cache_dir = _build_artifact_cache_dir()
    releases_dir = cache_dir / "releases" / version
    releases_dir.mkdir(parents=True, exist_ok=True)
    filename = f"V2bX-linux-{arch}.zip"
    dest = releases_dir / filename
    if dest.exists():
        return True
    return _sync_v2bx_binaries_for_arch(arch, version)


def _ensure_all_artifacts() -> dict[str, bool]:
    """Ensure all artifacts are present, fetching from GitHub on demand."""
    results: dict[str, bool] = {}
    for name in GITHUB_ARTIFACT_MANIFEST:
        results[name] = _ensure_artifact(name)
    return results


def _sync_all_artifacts() -> dict[str, bool]:
    """Sync all static scripts from GitHub to local cache. Returns name -> success."""
    cache_dir = _ensure_artifact_cache_dir()
    results: dict[str, bool] = {}
    for name, url in GITHUB_ARTIFACT_MANIFEST.items():
        results[name] = _sync_artifact(name, url, cache_dir)
    return results


def _save_cached_version(version: str) -> None:
    """Persist the synced V2bX version so provisioning can read it without GitHub."""
    cache_dir = _build_artifact_cache_dir()
    version_file = cache_dir / ".v2bx_version"
    version_file.write_text(version.strip() + "\n")


def _load_cached_version() -> str | None:
    """Load the last synced V2bX version from disk. Returns None if not cached."""
    cache_dir = _build_artifact_cache_dir()
    version_file = cache_dir / ".v2bx_version"
    if not version_file.exists():
        return None
    return version_file.read_text().strip() or None


def _sync_v2bx_binaries_for_arch(arch: str, version: str) -> bool:
    """Sync V2bX binary zip for a given arch+version into cache/releases/."""
    cache_dir = _ensure_artifact_cache_dir()
    releases_dir = cache_dir / "releases" / version
    releases_dir.mkdir(parents=True, exist_ok=True)
    filename = f"V2bX-linux-{arch}.zip"
    dest = releases_dir / filename
    url = f"https://github.com/wyx2685/V2bX/releases/download/{version}/{filename}"
    return _download_artifact(url, dest)


def _artifact_cache_needs_sync(cache_dir: Path) -> bool:
    """Return True if any cached artifact is missing or older than 24 hours."""
    import time
    now = time.time()
    cutoff = now - 86400  # 24 hours
    for name in GITHUB_ARTIFACT_MANIFEST:
        f = cache_dir / name
        if not f.exists():
            return True
        if f.stat().st_mtime < cutoff:
            return True
    return False


def _build_artifact_base_url(runtime_context: RuntimeContext) -> str | None:
    ipv6 = get_daemon_public_ipv6()
    if not ipv6:
        return None
    port = runtime_context.config.app.artifact_cache_listen_port
    return f"http://[{ipv6}]:{port}"


def _build_worker_id() -> str:
    hostname = socket.gethostname().strip() or "shadowfleet"
    return f"{hostname}-pid-{os.getpid()}"


def _recover_stale_tasks(
    runtime_context: RuntimeContext,
    task_service: ProvisioningTaskService,
    worker_id: str,
) -> tuple[int, int, int]:
    app_config = runtime_context.config.app
    recovery_result = task_service.recover_stale_running_tasks(
        worker_id=worker_id,
        running_timeout_seconds=app_config.daemon_running_task_timeout_seconds,
        retry_after_seconds=app_config.daemon_recovered_task_retry_delay_seconds,
    )
    return (
        recovery_result.scanned_task_count,
        recovery_result.requeued_task_count,
        recovery_result.failed_task_count,
    )


def _build_ready_callback_handler(
    runtime_context: RuntimeContext,
) -> type[BaseHTTPRequestHandler]:
    from services.probe_command_service import ProbeCommandService
    from services.probe_registry_service import ProbeRegistryService, ProbeRegistryServiceError
    from services.ready_callback_service import ReadyCallbackService

    ready_callback_service = ReadyCallbackService(runtime_context)
    probe_registry_service = ProbeRegistryService(runtime_context)
    probe_command_service = ProbeCommandService(runtime_context)
    logger = runtime_context.logger.getChild("daemon.ready_callback_http")

    class ReadyCallbackHandler(BaseHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self._ready_callback_service = ready_callback_service
            self._probe_registry_service = probe_registry_service
            self._probe_command_service = probe_command_service
            self._logger = logger

        def do_POST(self) -> None:  # noqa: N802
            if self.path == READY_CALLBACK_PATH:
                self._handle_ready_callback()
                return
            if self.path == PROBE_REGISTER_PATH:
                self._handle_probe_register()
                return
            if self.path == PROBE_HEARTBEAT_PATH:
                self._handle_probe_heartbeat()
                return
            if self.path == PROBE_POLL_PATH:
                self._handle_probe_poll()
                return
            if self.path == PROBE_RESULT_PATH:
                self._handle_probe_result()
                return
            self._send_json_response(404, {"error": "not_found"})

        def do_GET(self) -> None:  # noqa: N802
            if urlparse(self.path).path == PROBE_CONFIG_PATH:
                self._handle_probe_config()
                return
            self._send_json_response(404, {"error": "not_found"})

        def _handle_ready_callback(self) -> None:
            from database.ready_callback_repo import ReadyCallbackNotFoundError
            from services.ready_callback_service import ReadyCallbackServiceError
            try:
                payload = self._read_json_payload()
                callback_token = payload.get("token")
                if not isinstance(callback_token, str) or not callback_token.strip():
                    raise ValueError("token is required")

                callback_record = self._ready_callback_service.record_ready_callback(
                    callback_token=callback_token,
                    payload=payload,
                )
                self._send_json_response(
                    200,
                    {
                        "status": "accepted",
                        "task_id": callback_record.task_id,
                        "xboard_node_id": callback_record.xboard_node_id,
                    },
                )
            except ValueError as exc:
                self._logger.warning("Invalid ready callback request: %s", exc)
                self._send_json_response(400, {"error": str(exc)})
            except (ReadyCallbackNotFoundError, ReadyCallbackServiceError) as exc:
                self._logger.warning("Rejected ready callback request: %s", exc)
                self._send_json_response(404, {"error": str(exc)})
            except Exception:
                self._logger.exception("Unexpected error while handling ready callback")
                self._send_json_response(500, {"error": "internal_server_error"})

        def _handle_probe_register(self) -> None:
            try:
                payload = self._read_json_payload()
                bootstrap_token = self._require_non_empty_string(payload, "bootstrap_token")
                probe_name = self._require_non_empty_string(payload, "probe_name")
                machine_fingerprint = self._require_non_empty_string(payload, "machine_fingerprint")
                public_ip = self._optional_string(payload.get("public_ip"))
                region = self._optional_string(payload.get("region"))
                isp = self._optional_string(payload.get("isp"))
                tags = self._optional_string_list(payload.get("tags"))
                capabilities = self._optional_json_object(payload.get("capabilities"))
                registration = self._probe_registry_service.register_probe(
                    bootstrap_token=bootstrap_token,
                    probe_name=probe_name,
                    machine_fingerprint=machine_fingerprint,
                    public_ip=public_ip,
                    region=region,
                    isp=isp,
                    tags=tags,
                    capabilities=capabilities,
                )
                self._send_json_response(
                    200,
                    {
                        "probe_id": registration.probe_id,
                        "probe_name": registration.probe_name,
                        "auth_token": registration.auth_token,
                        "config_version": registration.config_version,
                        "config": registration.config,
                    },
                )
            except (ValueError, ProbeRegistryServiceError) as exc:
                self._logger.warning("Invalid probe register request: %s", exc)
                self._send_json_response(400, {"error": str(exc)})
            except Exception:
                self._logger.exception("Unexpected error while handling probe register")
                self._send_json_response(500, {"error": "internal_server_error"})

        def _handle_probe_heartbeat(self) -> None:
            try:
                payload = self._read_json_payload()
                probe_id = self._require_non_empty_string(payload, "probe_id")
                auth_token = self._require_non_empty_string(payload, "auth_token")
                public_ip = self._optional_string(payload.get("public_ip"))
                agent_version = self._optional_string(payload.get("agent_version"))
                capabilities = self._optional_json_object(payload.get("capabilities"))
                runtime_metrics = self._optional_json_object(payload.get("runtime_metrics"))
                probe_record, config_version = self._probe_registry_service.record_heartbeat(
                    probe_id=probe_id,
                    auth_token=auth_token,
                    public_ip=public_ip,
                    agent_version=agent_version,
                    capabilities=capabilities,
                    runtime_metrics=runtime_metrics,
                )
                self._send_json_response(
                    200,
                    {
                        "status": probe_record.status,
                        "probe_id": probe_record.probe_id,
                        "config_version": config_version,
                    },
                )
            except (ValueError, ProbeRegistryServiceError) as exc:
                self._logger.warning("Invalid probe heartbeat request: %s", exc)
                self._send_json_response(400, {"error": str(exc)})
            except Exception:
                self._logger.exception("Unexpected error while handling probe heartbeat")
                self._send_json_response(500, {"error": "internal_server_error"})

        def _handle_probe_poll(self) -> None:
            from services.probe_command_service import ProbeCommandServiceError
            try:
                payload = self._read_json_payload()
                probe_id = self._require_non_empty_string(payload, "probe_id")
                auth_token = self._require_non_empty_string(payload, "auth_token")
                lease_owner = self._optional_string(payload.get("lease_owner")) or probe_id
                max_commands = int(payload.get("max_commands", 5))
                command_records = self._probe_command_service.poll_commands(
                    probe_id=probe_id,
                    auth_token=auth_token,
                    lease_owner=lease_owner,
                    max_commands=max_commands,
                )
                self._send_json_response(
                    200,
                    {
                        "commands": [
                            {
                                "command_id": record.command_id,
                                "command_type": record.command_type,
                                "correlation_id": record.correlation_id,
                                "payload": record.payload,
                            }
                            for record in command_records
                        ]
                    },
                )
            except (ValueError, ProbeRegistryServiceError, ProbeCommandServiceError) as exc:
                self._logger.warning("Invalid probe poll request: %s", exc)
                self._send_json_response(400, {"error": str(exc)})
            except Exception:
                self._logger.exception("Unexpected error while handling probe poll")
                self._send_json_response(500, {"error": "internal_server_error"})

        def _handle_probe_result(self) -> None:
            from services.probe_command_service import ProbeCommandServiceError
            try:
                payload = self._read_json_payload()
                probe_id = self._require_non_empty_string(payload, "probe_id")
                auth_token = self._require_non_empty_string(payload, "auth_token")
                command_id = self._require_non_empty_string(payload, "command_id")
                status = self._require_non_empty_string(payload, "status")
                result_payload = self._optional_json_object(payload.get("result_payload"))
                last_error = self._optional_string(payload.get("last_error"))
                updated_record = self._probe_command_service.submit_command_result(
                    probe_id=probe_id,
                    auth_token=auth_token,
                    command_id=command_id,
                    status=status,
                    result_payload=result_payload,
                    last_error=last_error,
                )
                self._send_json_response(
                    200,
                    {
                        "command_id": updated_record.command_id,
                        "status": updated_record.status,
                    },
                )
            except (ValueError, ProbeRegistryServiceError, ProbeCommandServiceError) as exc:
                self._logger.warning("Invalid probe result request: %s", exc)
                self._send_json_response(400, {"error": str(exc)})
            except Exception:
                self._logger.exception("Unexpected error while handling probe result")
                self._send_json_response(500, {"error": "internal_server_error"})

        def _handle_probe_config(self) -> None:
            try:
                query = parse_qs(urlparse(self.path).query)
                probe_id = self._require_non_empty_string_from_query(query, "probe_id")
                auth_token = self._require_non_empty_string_from_query(query, "auth_token")
                config_record = self._probe_registry_service.get_probe_config(
                    probe_id=probe_id,
                    auth_token=auth_token,
                )
                self._send_json_response(
                    200,
                    {
                        "probe_id": config_record.probe_id,
                        "config_version": config_record.config_version,
                        "config": config_record.config,
                    },
                )
            except (ValueError, ProbeRegistryServiceError) as exc:
                self._logger.warning("Invalid probe config request: %s", exc)
                self._send_json_response(400, {"error": str(exc)})
            except Exception:
                self._logger.exception("Unexpected error while handling probe config")
                self._send_json_response(500, {"error": "internal_server_error"})

        def log_message(self, format: str, *args: object) -> None:
            self._logger.info("Ready callback HTTP %s", format % args)

        def _read_json_payload(self) -> dict[str, object]:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            if not isinstance(payload, dict):
                raise ValueError("request payload must be a JSON object")
            return payload

        @staticmethod
        def _require_non_empty_string(payload: dict[str, object], key: str) -> str:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} is required")
            return value.strip()

        @staticmethod
        def _require_non_empty_string_from_query(query: dict[str, list[str]], key: str) -> str:
            values = query.get(key, [])
            if not values or not values[0].strip():
                raise ValueError(f"{key} is required")
            return values[0].strip()

        @staticmethod
        def _optional_string(value: object) -> str | None:
            if value is None:
                return None
            text = str(value).strip()
            return text or None

        @staticmethod
        def _optional_string_list(value: object) -> list[str] | None:
            if value is None:
                return None
            if not isinstance(value, list):
                raise ValueError("tags must be a JSON array")
            return [str(item).strip() for item in value if str(item).strip()]

        @staticmethod
        def _optional_json_object(value: object) -> dict[str, object] | None:
            if value is None:
                return None
            if not isinstance(value, dict):
                raise ValueError("value must be a JSON object")
            return value

        def _send_json_response(self, status_code: int, payload: dict[str, object]) -> None:
            response_body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

    return ReadyCallbackHandler


def _check_host_bindable(host: str, port: int) -> bool:
    try:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        pass
    return False


def _resolve_listen_host(configured_host: str, configured_port: int) -> tuple[str, int]:
    if _check_host_bindable(configured_host, configured_port):
        return configured_host, configured_port

    fallbacks: list[str] = []
    if configured_host in ("0.0.0.0", "::"):
        others = ["::", "0.0.0.0"] if configured_host == "0.0.0.0" else ["0.0.0.0", "::"]
        fallbacks = [h for h in others if h != configured_host]

    for fb_host in fallbacks:
        if _check_host_bindable(fb_host, configured_port):
            return fb_host, configured_port

    raise RuntimeError(
        f"Cannot bind to configured host '{configured_host}' port {configured_port} "
        f"and no fallback available."
    )


def _start_ready_callback_server(runtime_context: RuntimeContext) -> ThreadingHTTPServer:
    app_config = runtime_context.config.app
    resolved_host, resolved_port = _resolve_listen_host(
        app_config.phone_home_listen_host,
        app_config.phone_home_listen_port,
    )
    server = ThreadingHTTPServer(
        (resolved_host, resolved_port),
        _build_ready_callback_handler(runtime_context),
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    runtime_context.logger.getChild("daemon").info(
        "Control plane HTTP server started host=%s port=%s ready_path=%s",
        resolved_host,
        resolved_port,
        READY_CALLBACK_PATH,
    )
    return server


def _run_artifact_cache_sync_worker(
    runtime_context: RuntimeContext,
    *,
    stop_event: threading.Event,
) -> None:
    app_config = runtime_context.config.app
    ipv6 = get_daemon_public_ipv6()
    if not ipv6:
        return
    logger = runtime_context.logger.getChild("daemon.artifact_sync")
    set_event_type("daemon_artifact_sync_worker_started")
    logger.info("Artifact cache sync worker started cache_dir=%s", ARTIFACT_CACHE_DIR)

    # Initial sync on startup
    results = _sync_all_artifacts()
    ok = all(results.values())
    logger.info(
        "Initial artifact sync completed success=%s results=%s",
        ok,
        results,
    )

    # Cache miss path: also sync on first provisioning call if not yet synced
    synced_atleast_once = ok

    while not stop_event.is_set():
        try:
            if not synced_atleast_once or _artifact_cache_needs_sync(_build_artifact_cache_dir()):
                results = _sync_all_artifacts()
                synced_atleast_once = True
                ok = all(results.values())
                if not ok:
                    logger.warning("Some artifacts failed to sync: %s", results)
                else:
                    logger.info("Artifact sync completed results=%s", results)
            else:
                logger.debug("Artifact cache is up-to-date, skipping sync")

            # Sync V2bX binaries for all known archs
            latest_version = _get_latest_v2bx_version()
            if latest_version:
                _save_cached_version(latest_version)
                for arch in ("64", "arm64-v8a", "s390x"):
                    _sync_v2bx_binaries_for_arch(arch, latest_version)
                logger.info("V2bX binaries synced for version=%s", latest_version)

            stop_event.wait(86400.0)  # sync every 24 hours
        except Exception:
            logger.exception("Artifact sync worker cycle failed")
            stop_event.wait(300.0)  # retry in 5 min on error


def _build_static_file_handler(
    cache_dir: Path,
    logger_parent: "logging.Logger",
) -> type[BaseHTTPRequestHandler]:
    class StaticFileHandler(BaseHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.lstrip("/")
            if not path or path in ("", "index", "index.html"):
                self._send_file("index.html" if (cache_dir / "index.html").exists() else None)
                return

            # Security: prevent path traversal
            safe_path = cache_dir / path
            if not str(safe_path.resolve()).startswith(str(cache_dir.resolve())):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Forbidden")
                return

            if safe_path.is_file():
                self._send_file(safe_path)
            elif safe_path.is_dir():
                self._send_dir_listing(safe_path)
            else:
                # On-demand fetch: try to pull from GitHub if it's a known artifact
                if self._try_ondemand_fetch(path):
                    safe_path = cache_dir / path.lstrip("/")
                    if safe_path.is_file():
                        self._send_file(safe_path)
                        return
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")

        def _send_file(self, file_path: Path | None) -> None:
            if file_path is None or not file_path.exists():
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(file_path.stat().st_size))
            self.end_headers()
            with open(file_path, "rb") as fh:
                shutil.copyfileobj(fh, self.wfile)

        def _send_dir_listing(self, dir_path: Path) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            files = [f.name for f in dir_path.iterdir()]
            body = f"<html><body><h1>{dir_path.name}/</h1><ul>"
            body += "".join(f"<li><a href='{n}'>{n}</a></li>" for n in files)
            body += "</ul></body></html>"
            self.wfile.write(body.encode("utf-8"))

        def _try_ondemand_fetch(self, path: str) -> bool:
            """Try to fetch a known artifact from GitHub on demand. Returns True if cached."""
            import re as _re

            filename = path.lstrip("/").split("/")[-1]
            arch_match = _re.match(r"V2bX-linux-(.+)\.zip", filename)
            if arch_match:
                arch = arch_match.group(1)
                return _ensure_v2bx_binary(arch)
            if filename in GITHUB_ARTIFACT_MANIFEST:
                return _ensure_artifact(filename)
            return False

        def log_message(self, format: str, *args: object) -> None:
            logger_parent.info("Artifact HTTP %s", format % args)

    return StaticFileHandler


def _start_artifact_cache_server(
    runtime_context: RuntimeContext,
) -> ThreadingHTTPServer | None:
    app_config = runtime_context.config.app
    ipv6 = get_daemon_public_ipv6()
    if not ipv6:
        return None
    cache_dir = _ensure_artifact_cache_dir()
    logger = runtime_context.logger.getChild("daemon.artifact_http")

    # Blocking warm-up: ensure all artifacts exist before HTTP server starts accepting requests.
    # This avoids a race where a provisioning task dispatches before the cache is populated.
    logger.info("Warming up artifact cache (blocking)...")
    warmup_results = _ensure_all_artifacts()
    if not all(warmup_results.values()):
        missing = [k for k, v in warmup_results.items() if not v]
        logger.warning("Some artifacts failed warm-up, will retry on demand: %s", missing)
    else:
        logger.info("Artifact cache warm-up complete: %s", warmup_results)

    # Pre-fetch binaries for common archs (non-blocking, best-effort)
    latest_version = _get_latest_v2bx_version()
    if latest_version:
        _save_cached_version(latest_version)
        for arch in ("64", "arm64-v8a"):
            ok = _ensure_v2bx_binary(arch, latest_version)
            logger.debug("Binary warm-up arch=%s version=%s ok=%s", arch, latest_version, ok)
        logger.info("V2bX binary warm-up done version=%s", latest_version)
    else:
        # Try to load from previous sync run
        prev = _load_cached_version()
        if prev:
            logger.info("Using previously cached V2bX version: %s", prev)
    handler_class = _build_static_file_handler(cache_dir, logger)
    server = ThreadingHTTPServer(("::", app_config.artifact_cache_listen_port), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ipv6 = get_daemon_public_ipv6()
    logger.info(
        "Artifact cache HTTP server started port=%s cache_dir=%s ipv6=%s",
        app_config.artifact_cache_listen_port,
        cache_dir,
        ipv6,
    )
    return server


def _run_provisioning_worker(
    runtime_context: RuntimeContext,
    *,
    worker_id: str,
    stop_event: threading.Event,
) -> None:
    app_config = runtime_context.config.app
    logger = runtime_context.logger.getChild("daemon.provisioning")
    task_service = ProvisioningTaskService(runtime_context)
    next_recovery_at_monotonic = 0.0
    set_event_type("daemon_provisioning_worker_started")
    logger.info("Provisioning worker started worker_id=%s", worker_id)

    while not stop_event.is_set():
        try:
            current_monotonic = time.monotonic()
            if current_monotonic >= next_recovery_at_monotonic:
                scanned_count, requeued_count, failed_count = _recover_stale_tasks(
                    runtime_context=runtime_context,
                    task_service=task_service,
                    worker_id=worker_id,
                )
                set_correlation_id(runtime_context.correlation_id)
                next_recovery_at_monotonic = (
                    current_monotonic + app_config.daemon_stale_task_recovery_interval_seconds
                )
                if scanned_count > 0:
                    set_event_type("daemon_stale_task_recovered")
                    logger.warning(
                        "Recovered stale running tasks scanned=%s requeued=%s failed=%s",
                        scanned_count,
                        requeued_count,
                        failed_count,
                    )

            processed_task = task_service.process_next_task(worker_id=worker_id)
            set_correlation_id(runtime_context.correlation_id)
            if processed_task is None:
                set_event_type("daemon_idle")
                stop_event.wait(app_config.daemon_idle_poll_interval_seconds)
                continue

            set_event_type("daemon_task_cycle_completed")
            logger.info(
                "Provisioning worker finished task id=%s status=%s attempts=%s/%s",
                processed_task.id,
                processed_task.status,
                processed_task.attempt_count,
                processed_task.max_attempts,
            )
            stop_event.wait(app_config.daemon_idle_poll_interval_seconds)
        except Exception as exc:
            set_correlation_id(runtime_context.correlation_id)
            set_event_type("daemon_cycle_failed")
            logger.exception("Provisioning worker cycle failed")
            notify_daemon_worker_cycle_failed(
                runtime_context,
                DaemonWorkerAlertContext(
                    worker_name="provisioning",
                    error_message=str(exc),
                    correlation_id=runtime_context.correlation_id,
                ),
            )
            stop_event.wait(app_config.daemon_failure_backoff_seconds)


def _run_sentinel_worker(
    runtime_context: RuntimeContext,
    *,
    stop_event: threading.Event,
) -> None:
    app_config = runtime_context.config.app
    logger = runtime_context.logger.getChild("daemon.sentinel")
    if not app_config.sentinel_enabled:
        logger.info("Sentinel worker disabled by configuration")
        return

    monitor_service = MonitorService(runtime_context)
    set_event_type("daemon_sentinel_worker_started")
    logger.info("Sentinel worker started")
    while not stop_event.is_set():
        try:
            result = monitor_service.run_scan_cycle()
            set_correlation_id(runtime_context.correlation_id)
            set_event_type("daemon_sentinel_cycle_completed")
            logger.info(
                "Sentinel cycle completed cycle_id=%s candidates=%s confirmed=%s healed=%s failed=%s",
                result.cycle_id,
                result.candidate_count,
                result.confirmed_count,
                result.healed_count,
                result.failed_count,
            )
            stop_event.wait(app_config.sentinel_poll_interval_seconds)
        except Exception as exc:
            set_correlation_id(runtime_context.correlation_id)
            set_event_type("daemon_sentinel_cycle_failed")
            logger.exception("Sentinel worker cycle failed")
            notify_daemon_worker_cycle_failed(
                runtime_context,
                DaemonWorkerAlertContext(
                    worker_name="sentinel",
                    error_message=str(exc),
                    correlation_id=runtime_context.correlation_id,
                ),
            )
            stop_event.wait(app_config.daemon_failure_backoff_seconds)


def _run_manual_operation_worker(
    runtime_context: RuntimeContext,
    *,
    worker_id: str,
    stop_event: threading.Event,
) -> None:
    app_config = runtime_context.config.app
    logger = runtime_context.logger.getChild("daemon.manual_operation")
    task_service = ManualOperationService(runtime_context)
    set_event_type("daemon_manual_worker_started")
    logger.info("Manual operation worker started worker_id=%s", worker_id)
    while not stop_event.is_set():
        try:
            processed_task = task_service.process_next_task(worker_id=worker_id)
            set_correlation_id(runtime_context.correlation_id)
            if processed_task is None:
                set_event_type("daemon_idle")
                stop_event.wait(app_config.daemon_idle_poll_interval_seconds)
                continue
            set_event_type("daemon_manual_task_cycle_completed")
            logger.info(
                "Manual operation worker finished task id=%s status=%s attempts=%s/%s",
                processed_task.id,
                processed_task.status,
                processed_task.attempt_count,
                processed_task.max_attempts,
            )
        except Exception as exc:
            set_correlation_id(runtime_context.correlation_id)
            set_event_type("daemon_manual_task_cycle_failed")
            logger.exception("Manual operation worker cycle failed")
            notify_daemon_worker_cycle_failed(
                runtime_context,
                DaemonWorkerAlertContext(
                    worker_name="manual_operation",
                    error_message=str(exc),
                    correlation_id=runtime_context.correlation_id,
                ),
            )
            stop_event.wait(app_config.daemon_failure_backoff_seconds)


def _shutdown_servers(
    rc_server: ThreadingHTTPServer,
    art_server: ThreadingHTTPServer | None,
) -> None:
    rc_server.shutdown()
    rc_server.server_close()
    if art_server is not None:
        art_server.shutdown()
        art_server.server_close()


def main() -> None:
    runtime_context = build_runtime_context()
    logger = runtime_context.logger.getChild("daemon")
    ready_callback_server = _start_ready_callback_server(runtime_context)
    artifact_cache_server: ThreadingHTTPServer | None = None
    if runtime_context.daemon_ipv6:
        artifact_cache_server = _start_artifact_cache_server(runtime_context)
        artifact_sync_thread = threading.Thread(
            target=_run_artifact_cache_sync_worker,
            kwargs={
                "runtime_context": runtime_context,
                "stop_event": threading.Event(),
            },
            daemon=True,
            name="shadowfleet-artifact-sync-worker",
        )
        artifact_sync_thread.start()
        logger.info("Artifact cache workers started")
    stop_event = threading.Event()
    provisioning_thread = threading.Thread(
        target=_run_provisioning_worker,
        kwargs={
            "runtime_context": runtime_context,
            "worker_id": _build_worker_id(),
            "stop_event": stop_event,
        },
        daemon=True,
        name="shadowfleet-provisioning-worker",
    )
    sentinel_thread = threading.Thread(
        target=_run_sentinel_worker,
        kwargs={
            "runtime_context": runtime_context,
            "stop_event": stop_event,
        },
        daemon=True,
        name="shadowfleet-sentinel-worker",
    )
    manual_operation_thread = threading.Thread(
        target=_run_manual_operation_worker,
        kwargs={
            "runtime_context": runtime_context,
            "worker_id": f"{_build_worker_id()}-manual",
            "stop_event": stop_event,
        },
        daemon=True,
        name="shadowfleet-manual-operation-worker",
    )

    set_event_type("daemon_started")
    logger.info("ShadowFleet daemon started")
    provisioning_thread.start()
    sentinel_thread.start()
    manual_operation_thread.start()

    def _sigterm_handler(signum: int, frame: object) -> None:
        set_correlation_id(runtime_context.correlation_id)
        set_event_type("daemon_stopped")
        logger.info("Provisioning daemon stopped by SIGTERM")
        stop_event.set()
        _shutdown_servers(ready_callback_server, artifact_cache_server)

    previous_sigterm_handler = signal.signal(signal.SIGTERM, _sigterm_handler)
    try:
        while True:
            if not provisioning_thread.is_alive():
                raise RuntimeError("Provisioning worker thread exited unexpectedly")
            if runtime_context.config.app.sentinel_enabled and not sentinel_thread.is_alive():
                raise RuntimeError("Sentinel worker thread exited unexpectedly")
            if not manual_operation_thread.is_alive():
                raise RuntimeError("Manual operation worker thread exited unexpectedly")
            time.sleep(1.0)
    except KeyboardInterrupt:
        set_correlation_id(runtime_context.correlation_id)
        set_event_type("daemon_stopped")
        logger.info("Provisioning daemon stopped by keyboard interrupt")
        stop_event.set()
        _shutdown_servers(ready_callback_server, artifact_cache_server)
        raise
    except Exception:
        set_correlation_id(runtime_context.correlation_id)
        set_event_type("daemon_cycle_failed")
        logger.exception("Daemon supervisor failed")
        stop_event.set()
        _shutdown_servers(ready_callback_server, artifact_cache_server)
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
        try:
            provisioning_thread.join(timeout=5.0)
            sentinel_thread.join(timeout=5.0)
            manual_operation_thread.join(timeout=5.0)
        finally:
            _shutdown_servers(ready_callback_server, artifact_cache_server)


if __name__ == "__main__":
    main()
