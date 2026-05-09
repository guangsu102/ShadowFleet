from __future__ import annotations

from datetime import datetime, timezone

from database.state_repo import StateRepo
from services.runtime_service import RuntimeContext
from services.xboard_sentinel_client import XboardSentinelClient
from utils.logger import set_event_type


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class XboardSyncService:
    """Service to synchronize Xboard node runtime status with local database."""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.xboard_sync_service")
        self._state_repo = StateRepo(runtime_context)
        self._sentinel_client = XboardSentinelClient(runtime_context)

    def sync_all_nodes(self) -> tuple[int, int]:
        """
        Synchronize Xboard status for all active nodes from Xboard API.
        Returns (success_count, failed_count).
        """
        try:
            server_list = self._sentinel_client.get_server_list()
        except Exception:
            self._logger.exception("Failed to fetch server list from Xboard")
            set_event_type("xboard_sync_failed")
            return 0, 0

        success_count = 0
        failed_count = 0

        for server in server_list.servers:
            try:
                self._sync_single_node(server)
                success_count += 1
            except Exception:
                self._logger.exception(
                    "Failed to sync Xboard status for server id=%s",
                    server.id,
                )
                failed_count += 1

        self._logger.info(
            "Xboard sync completed: success=%s failed=%s",
            success_count,
            failed_count,
        )
        set_event_type("xboard_sync_completed")
        return success_count, failed_count

    def _sync_single_node(self, server) -> None:
        """Synchronize a single node's Xboard status from server list."""
        # Map Xboard status to ShadowFleet status
        # is_online: 1 = online, 0 = offline
        # available_status: string describing the status
        xboard_status = "online" if server.is_online == 1 else "offline"
        if not server.show:
            xboard_status = "hidden"

        self._state_repo.update_node_xboard_status(
            xboard_node_id=server.id,
            xboard_status=xboard_status,
            xboard_show=server.show,
            xboard_updated_at=_utcnow_iso(),
        )
        self._logger.debug(
            "Synced Xboard status for server id=%s status=%s show=%s is_online=%s",
            server.id,
            xboard_status,
            server.show,
            server.is_online,
        )
