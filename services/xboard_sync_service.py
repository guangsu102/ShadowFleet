from __future__ import annotations

from datetime import datetime, timezone

from database.state_repo import StateRepo
from database.xboard_repo import XboardRepo
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class XboardSyncService:
    """Service to synchronize Xboard node runtime status with local database."""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.xboard_sync_service")
        self._state_repo = StateRepo(runtime_context)
        self._xboard_repo = XboardRepo(runtime_context)

    def sync_all_nodes(self) -> tuple[int, int]:
        """
        Synchronize Xboard status for all active nodes from PostgreSQL.
        Returns (success_count, failed_count).
        """
        nodes = self._state_repo.list_active_nodes()
        success_count = 0
        failed_count = 0

        for node in nodes:
            try:
                self._sync_single_node(node.xboard_node_id, node.node_type)
                success_count += 1
            except Exception:
                self._logger.exception(
                    "Failed to sync Xboard status for xboard_node_id=%s",
                    node.xboard_node_id,
                )
                failed_count += 1

        self._logger.info(
            "Xboard sync completed: success=%s failed=%s",
            success_count,
            failed_count,
        )
        set_event_type("xboard_sync_completed")
        return success_count, failed_count

    def _sync_single_node(self, xboard_node_id: int, node_type: str) -> None:
        """Synchronize a single node's Xboard status by querying PostgreSQL directly."""
        try:
            runtime = self._xboard_repo.get_node_runtime(xboard_node_id)

            xboard_status = "online" if runtime.show else "hidden"
            self._state_repo.update_node_xboard_status(
                xboard_node_id=xboard_node_id,
                xboard_status=xboard_status,
                xboard_show=runtime.show,
                xboard_updated_at=_utcnow_iso(),
            )
            self._logger.debug(
                "Synced Xboard status for xboard_node_id=%s status=%s show=%s",
                xboard_node_id,
                xboard_status,
                runtime.show,
            )
        except Exception as exc:
            self._logger.warning(
                "Failed to get Xboard runtime for xboard_node_id=%s: %s",
                xboard_node_id,
                exc,
            )
            self._state_repo.update_node_xboard_status(
                xboard_node_id=xboard_node_id,
                xboard_status="offline",
                xboard_show=None,
                xboard_updated_at=_utcnow_iso(),
            )
