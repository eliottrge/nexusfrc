"""Canonical Match Timeline: the single format every ingest adapter produces."""
from typing import Literal
from pydantic import BaseModel

SCHEMA_VERSION = 1
Alliance = Literal["red", "blue"]
Phase = Literal["pre", "auto", "transition", "teleop", "endgame", "post"]


class RobotState(BaseModel):
    team: int
    alliance: Alliance
    x: float  # meters, field frame
    y: float
    heading: float  # radians


class Frame(BaseModel):
    t: float  # seconds from match start
    phase: Phase = "teleop"
    robots: list[RobotState]


class Event(BaseModel):
    t: float  # seconds from match start (official clock; AUTO grace counted at t=20)
    kind: Literal[
        "shot",           # a robot launched fuel (future: robot tracking)
        "fuel_scored",    # alliance score rose (scorebug) - exact for an active hub
        "fuel_entry",     # balls seen entering a hub on video - approximate, sees inactive hubs too
        "foul_call",
        "card",
        "note",
    ]
    team: int | None = None
    alliance: Alliance | None = None
    count: int | None = None
    hub_active: bool | None = None
    source: str = ""  # e.g. "scorebug_ocr", "video_counter"
    detail: str = ""


class PeriodSummary(BaseModel):
    name: str
    start: float
    end: float
    blue_active: bool
    red_active: bool
    blue_scored: int
    red_scored: int
    blue_counted: int
    red_counted: int


class Timeline(BaseModel):
    schema_version: int = SCHEMA_VERSION
    game: str = "REBUILT-2026"
    match_id: str = ""
    duration: float = 160.0  # 20 s AUTO + 2:20 TELEOP (manual 6.4)
    field_length: float = 16.54  # meters (manual 5.2)
    field_width: float = 8.07
    teams: dict[str, list[int]] = {}  # {"blue": [...], "red": [...]}
    auto_winner: Alliance | None = None
    final_score: dict[str, int] = {}
    frames: list[Frame] = []  # robot poses - empty until robot tracking exists
    events: list[Event] = []
    periods: list[PeriodSummary] = []
