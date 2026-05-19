from pydantic import BaseModel
from typing import Literal


class TripRequest(BaseModel):
    location: str
    budget: float
    transport: Literal["walking", "driving", "transit", "cycling"]
    duration_hours: float
    vibe: str
    constraints: str | None = None
