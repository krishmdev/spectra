import asyncio
from recorder.replayer import Replayer

class TriggerLoop:
    POLL_INTERVAL_SECONDS = 120

    def __init__(self, store, collector, ws_server, idle_checker):
        self.store = store
        self.collector = collector
        self.ws_server = ws_server
        self.idle_checker = idle_checker

    async def start(self) -> None:
        while True:
            try:
                await self._check_once()
            except Exception as e:
                print(f"[TriggerLoop] Error: {e}")
            await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

    async def _check_once(self) -> None:
        if self.idle_checker.is_active():
            pass

        ctx = await self.collector.collect()
        matches = self.store.find_matching_episodes(ctx)
        
        if not matches:
            return
            
        best = matches[0]
        episode = best.episode
        log_id = self.store.log_suggestion(episode.id)

        is_idle = not self.idle_checker.is_active()
        delivery = "notification" if is_idle else "in_app"

        req = {
            "type": "context_suggestion",
            "delivery": delivery,
            "episode_id": episode.id,
            "suggestion": best.suggestion_text,
            "log_id": log_id
        }

        resp = await self.ws_server.request_suggestion_response(req, timeout=60.0)
        accepted = False
        if resp and resp.get("accepted"):
            accepted = True

        self.store.mark_suggestion_responded(log_id, accepted)

        if accepted:
            loop = asyncio.get_running_loop()
            def _run_replay():
                replayer = Replayer(filepath=episode.spectra_path)
                replayer.run()
            loop.run_in_executor(None, _run_replay)
