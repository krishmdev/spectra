"""Passive Observer — always-on screen watcher.

Polls the accessibility tree every few seconds, diffs consecutive frames to
detect user actions, logs each action in natural language to the ActionLog,
and periodically runs the SequenceDetector to discover patterns and fire
suggestions via the WebSocket server.
"""
import asyncio
import time
import uuid
import os
from context.models import Episode
from context.episode_store import EpisodeStore
from context.action_log import ActionLog
from context.action_describer import describe_transition
from context.sequence_detector import SequenceDetector
from core.tree_reader import TreeReader
from context.inference_engine import infer_spectra_flow

# How often to re-scan the action log for new sequences
LEARN_INTERVAL_POLLS = 3  # every ~30s at 10s polling

# How often to prune/condense workflows via LLM
PRUNE_INTERVAL_POLLS = 3  # every ~30s at 10s polling


class PassiveObserver:
    def __init__(self, wda_url='http://localhost:8100', ws_state=None):
        self.wda_url = wda_url
        self.reader = TreeReader(self.wda_url)
        self.store = EpisodeStore()
        self.action_log = ActionLog()
        self.detector = SequenceDetector(self.action_log)
        self.ws_state = ws_state  # ConnectionState for sending suggestions

        self.prev_frame = None
        self.buffer = []
        self.is_recording = False
        self.current_session_app = None
        self._poll_count = 0
        print(f"[Observer] Initialized (wda_url={wda_url})")

    async def start(self):
        print(f"[Observer] Passive observation started (polling WDA every 10s)", flush=True)
        while True:
            try:
                await asyncio.sleep(10.0)
                await self._poll_once()
            except Exception as e:
                import traceback
                print(f"[Observer] Exception: {e}", flush=True)
                traceback.print_exc()

    async def _poll_once(self):
        self._poll_count += 1

        # --- Periodic sequence learning (runs regardless of snapshot success) ---
        if self._poll_count % LEARN_INTERVAL_POLLS == 0:
            await self._learn_sequences()

        # Pruning disabled — was deleting all workflows in a loop
        # if self._poll_count % PRUNE_INTERVAL_POLLS == 0:
        #     await self._prune_workflows()

        # --- Snapshot ---
        loop = asyncio.get_running_loop()
        def _snap():
            return self.reader.snapshot()

        try:
            tree_text, ref_map, meta = await loop.run_in_executor(None, _snap)
        except Exception as e:
            print(f"[Observer] Snapshot failed: {e}", flush=True)
            return

        bundle_id = meta.get('app_bundle_id', '') or meta.get('app_name', 'unknown')
        now = time.time()
        tree_hash = meta.get('tree_hash', str(hash(tree_text)))

        curr_frame = {
            'time': now,
            'app': bundle_id,
            'hash': tree_hash,
            'tree': tree_text,
            'ref_map': ref_map,
            'meta': meta,
        }

        # --- Action detection: diff prev vs curr ---
        if self.prev_frame and self.prev_frame['hash'] != curr_frame['hash']:
            action_nl = describe_transition(self.prev_frame, curr_frame)
            if action_nl:
                labels = [
                    el.get('label', '') for el in ref_map.values()
                    if isinstance(el, dict) and el.get('label')
                ]
                self.action_log.append(bundle_id, action_nl, labels)
                print(f"[Observer] Action: {action_nl}", flush=True)

                # Check for sequence match after every new action
                await self._check_sequence()

        self.prev_frame = curr_frame

        # --- Session tracking for inference engine (existing behavior) ---
        if 'springboard' in bundle_id.lower() or bundle_id == 'unknown':
            if self.is_recording and len(self.buffer) > 1:
                self._flush_session()
            self.is_recording = False
            self.buffer.clear()
            self.current_session_app = None
        else:
            if not self.is_recording:
                self.is_recording = True
                self.current_session_app = bundle_id
            if not self.buffer or self.buffer[-1]['hash'] != tree_hash:
                self.buffer.append(curr_frame)
                if len(self.buffer) > 10:
                    self.buffer.pop(0)

    async def _learn_sequences(self):
        loop = asyncio.get_running_loop()
        def _learn():
            return self.detector.learn_sequences()
        try:
            new_count = await loop.run_in_executor(None, _learn)
            if new_count > 0:
                print(f"[Observer] Learned {new_count} new action sequences", flush=True)
        except Exception as e:
            import traceback
            print(f"[Observer] Sequence learning error: {e}", flush=True)
            traceback.print_exc()

    async def _prune_workflows(self):
        loop = asyncio.get_running_loop()
        def _prune():
            return self.detector.prune_workflows()
        try:
            removed = await loop.run_in_executor(None, _prune)
            if removed > 0:
                print(f"[Observer] Pruned {removed} workflows", flush=True)
        except Exception as e:
            print(f"[Observer] Prune error: {e}", flush=True)

    async def _check_sequence(self):
        loop = asyncio.get_running_loop()
        def _check():
            return self.detector.check_for_suggestion()

        try:
            suggestion = await loop.run_in_executor(None, _check)
        except Exception as e:
            print(f"[Observer] Sequence check error: {e}")
            return

        if not suggestion:
            return

        print(f"[Observer] Sequence match! Suggesting: {suggestion['next_action']}")

        # Mark as triggered to start cooldown
        self.action_log.mark_sequence_triggered(suggestion['sequence_id'])

        # Send suggestion to iOS via WebSocket
        if self.ws_state:
            msg = {
                'type': 'sequence_suggestion',
                'sequence_id': suggestion['sequence_id'],
                'next_action': suggestion['next_action'],
                'prefix': suggestion['prefix'],
                'full_sequence': suggestion['full_sequence'],
                'occurrence_count': suggestion['occurrence_count'],
                'initial_state': suggestion.get('initial_state'),
                'goal_state': suggestion.get('goal_state'),
            }
            try:
                self.ws_state.send(msg)
            except Exception as e:
                print(f"[Observer] Failed to send suggestion: {e}")

    def _flush_session(self):
        frames = list(self.buffer)

        def _run_infer():
            try:
                spectra_path, description = infer_spectra_flow(frames)
                if spectra_path:
                    first_frame = frames[0]
                    t = time.localtime(first_frame['time'])
                    ep = Episode(
                        id=str(uuid.uuid4()),
                        task_description=f"Manual routine: {description}",
                        spectra_path=spectra_path,
                        step_count=len(frames)-1,
                        app_bundle_id=self.current_session_app,
                        visible_labels=[el.get('label') for ref, el in first_frame['ref_map'].items() if el.get('label')],
                        location_lat=None,
                        location_lng=None,
                        location_label=None,
                        hour_of_day=t.tm_hour,
                        day_of_week=t.tm_wday,
                        created_at=first_frame['time'],
                        occurrence_count=1,
                        last_suggested_at=None,
                        last_suggestion_accepted=None
                    )
                    self.store.save_episode(ep)
                    print(f"[Observer] Learned new routine! '{description}' (saved to EpisodeStore)")
            except Exception:
                pass  # Inference engine is best-effort; new sequence detector handles learning

        import threading
        threading.Thread(target=_run_infer, daemon=True).start()
