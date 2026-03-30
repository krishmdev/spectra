import math
from typing import Optional
from context.models import Episode, ContextSnapshot, EpisodeMatch
from core.planner import Planner

def score_episode(episode: Episode, ctx: ContextSnapshot) -> Optional[EpisodeMatch]:
    if episode.step_count < 3:
        return None
    if episode.occurrence_count < 2:
        return None
    if episode.last_suggestion_accepted is False:
        return None
    if episode.last_suggested_at is not None:
        hours_passed = (ctx.captured_at - episode.last_suggested_at) / 3600.0
        if hours_passed <= 4.0:
            return None

    score = 0.0
    matched_signals = []

    # App bundle
    if episode.app_bundle_id == ctx.app_bundle_id:
        score += 0.35
        matched_signals.append(f"using {ctx.app_bundle_id}")

    # Visible labels overlap (Jaccard)
    set1 = set([l.lower() for l in episode.visible_labels if l])
    set2 = set([l.lower() for l in ctx.visible_labels if l])
    if set1 and set2:
        intersect = len(set1.intersection(set2))
        union = len(set1.union(set2))
        jaccard = intersect / union
        score += 0.30 * jaccard
        if jaccard > 0.3:
            matched_signals.append("similar screen context")

    # Time proximity (within 2 hours)
    diff = abs(episode.hour_of_day - ctx.hour_of_day)
    time_diff = min(diff, 24 - diff)
    if time_diff <= 2:
        time_score = (2.0 - time_diff) / 2.0
        score += 0.20 * time_score
        matched_signals.append("similar time of day")

    # Location proximity (within 500m)
    if episode.location_lat is not None and ctx.location_lat is not None:
        lat1, lon1 = math.radians(episode.location_lat), math.radians(episode.location_lng)
        lat2, lon2 = math.radians(ctx.location_lat), math.radians(ctx.location_lng)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        dist_m = 6371000.0 * c
        if dist_m <= 500:
            loc_score = (500.0 - dist_m) / 500.0
            score += 0.15 * loc_score
            matched_signals.append("exact location match")

    if score < 0.65:
        return None

    # LLM Suggestion Text Generation
    planner = Planner()
    prompt = f"""Generate a suggestion to execute a recorded automated task.

Task: "{episode.task_description}"
Triggered by: {', '.join(matched_signals)}

Rules:
- Reference checking the context signal that triggered the match
- Describe the task at a high level
- Phrase as a question
- Under 20 words
- NEVER use: "detected", "pattern", "trigger", "algorithm", "system"
"""
    try:
        from google.genai import types
        config = types.GenerateContentConfig(max_output_tokens=60, temperature=0.7)
        res = planner.client.models.generate_content(
            model=planner.model,
            contents=[types.Content(role='user', parts=[types.Part(text=prompt)])],
            config=config,
        )
        suggestion_text = res.text.strip().strip('"')
    except Exception:
        suggestion_text = f"Should I run your usual routine: {episode.task_description}?"

    return EpisodeMatch(episode=episode, score=score, matched_signals=matched_signals, suggestion_text=suggestion_text)
