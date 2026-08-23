"""Runtime Statistics capability with prepared point-in-time export support."""

from __future__ import annotations

from ..api import export_api
from ..api.application_capabilities import StatisticsApplicationService


class RealtimeStatisticsApplicationService(StatisticsApplicationService):
    """Extend the shared Statistics capability with freeze-then-write export."""

    def prepare_statistics_csv(self, date_from, date_to, project_id=None):
        return export_api.prepare_statistics_csv(date_from, date_to, project_id)

    def write_prepared_statistics_csv(self, prepared, output_path):
        return export_api.write_prepared_statistics_csv(prepared, output_path)


__all__ = ["RealtimeStatisticsApplicationService"]
