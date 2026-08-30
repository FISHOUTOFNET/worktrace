"""Runtime Statistics capability with prepared point-in-time export support."""

from __future__ import annotations

from ..api import export_api
from ..api.application_capabilities import StatisticsApplicationService
from ..services.page_read_context import page_read_scope


def _runtime_sync_payload(context) -> dict[str, bool]:
    """Expose the request-scoped runtime agreement needed for UI convergence."""

    return {
        "runtime_consistent": context.runtime_consistent is True,
        "needs_full_refresh": context.needs_full_refresh is True,
        "collection_live_eligible": context.collection_live_eligible is True,
    }


class RealtimeStatisticsApplicationService(StatisticsApplicationService):
    """Extend the shared Statistics capability with fail-closed live reads."""

    def get_statistics_export_view_model_live(
        self,
        date_from,
        date_to,
        project_id=None,
        *,
        collection_live_eligible: bool,
    ):
        with page_read_scope(
            allow_unpersisted_runtime=True,
            collection_live_eligible=collection_live_eligible,
        ) as context:
            envelope = super().get_statistics_export_view_model(
                date_from,
                date_to,
                project_id,
            )
            result = dict(envelope)
            result["runtime_sync"] = _runtime_sync_payload(context)
            return result

    def prepare_statistics_csv(self, date_from, date_to, project_id=None):
        return export_api.prepare_statistics_csv(date_from, date_to, project_id)

    def prepare_statistics_csv_live(
        self,
        date_from,
        date_to,
        project_id=None,
        *,
        collection_live_eligible: bool,
    ):
        with page_read_scope(
            allow_unpersisted_runtime=True,
            collection_live_eligible=collection_live_eligible,
        ) as context:
            if context.collection_live_eligible and context.needs_full_refresh:
                raise export_api.StatisticsExportError("statistics_sync_pending")
            return export_api.prepare_statistics_csv(date_from, date_to, project_id)

    def write_prepared_statistics_csv(self, prepared, output_path):
        return export_api.write_prepared_statistics_csv(prepared, output_path)


__all__ = ["RealtimeStatisticsApplicationService"]
