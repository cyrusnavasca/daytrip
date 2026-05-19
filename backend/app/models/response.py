from pydantic import BaseModel
from typing import Optional


class Stop(BaseModel):
    time: str
    name: str
    description: str
    address: Optional[str] = None
    estimated_cost: Optional[float] = None
    travel_time_to_next: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class Itinerary(BaseModel):
    trip_id: str
    summary: str
    stops: list[Stop]
    total_estimated_cost: float
    warnings: list[str] = []
