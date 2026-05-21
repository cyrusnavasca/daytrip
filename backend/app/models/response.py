from typing import Literal, Optional

from pydantic import BaseModel


class Stop(BaseModel):
    time: str
    name: str
    description: str
    address: Optional[str] = None
    estimated_cost: Optional[float] = None
    travel_time_to_next: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    category: Optional[Literal["activity", "food", "coffee", "hidden_gem", "nature", "shopping"]] = None
    alternatives: list[str] = []


class Itinerary(BaseModel):
    trip_id: str
    summary: str
    stops: list[Stop]
    total_estimated_cost: float
    weather_note: str = ""
    warnings: list[str] = []
