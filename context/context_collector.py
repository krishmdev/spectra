import asyncio
import time
from context.models import ContextSnapshot
from core.tree_reader import TreeReader

class ContextCollector:
    def __init__(self, ws_server):
        self.ws_server = ws_server

    async def collect(self) -> ContextSnapshot:
        lat, lng = None, None
        try:
            # Assumes ws_server exposes an async method to fetch location with timeout
            resp = await self.ws_server.request_location(timeout=3.0)
            if resp:
                lat = resp.get("lat")
                lng = resp.get("lng")
        except Exception:
            pass

        loop = asyncio.get_running_loop()
        def _get_tree():
            return TreeReader().snapshot()

        try:
            _, ref_map, meta = await loop.run_in_executor(None, _get_tree)
            app_bundle_id = meta.get("app_bundle_id", "unknown")
            visible_labels = [el.get("label") for ref, el in ref_map.items() if el.get("label")]
        except Exception:
            app_bundle_id = "unknown"
            visible_labels = []

        local_t = time.localtime()
        return ContextSnapshot(
            app_bundle_id=app_bundle_id,
            visible_labels=visible_labels,
            location_lat=lat,
            location_lng=lng,
            hour_of_day=local_t.tm_hour,
            day_of_week=local_t.tm_wday,
            captured_at=time.time()
        )
