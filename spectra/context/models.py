from dataclasses import dataclass
from typing import Optional

@dataclass
class Episode:
    id: str
    task_description: str
    spectra_path: str
    step_count: int
    app_bundle_id: str
    visible_labels: list[str]
    location_lat: Optional[float]
    location_lng: Optional[float]
    location_label: Optional[str]
    hour_of_day: int
    day_of_week: int
    created_at: float
    occurrence_count: int
    last_suggested_at: Optional[float]
    last_suggestion_accepted: Optional[bool]

@dataclass
class ContextSnapshot:
    app_bundle_id: str
    visible_labels: list[str]
    location_lat: Optional[float]
    location_lng: Optional[float]
    hour_of_day: int
    day_of_week: int
    captured_at: float

@dataclass
class EpisodeMatch:
    episode: Episode
    score: float
    matched_signals: list[str]
    suggestion_text: str
