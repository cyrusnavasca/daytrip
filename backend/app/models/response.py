from typing import Literal, Optional

from pydantic import BaseModel, field_validator


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

    @field_validator("alternatives", mode="before")
    @classmethod
    def clean_alternatives(cls, v: list) -> list[str]:
        """Strip blank entries; downstream logic fills the rest."""
        if not isinstance(v, list):
            return []
        return [str(a).strip() for a in v if str(a).strip()]

    @field_validator("estimated_cost", mode="before")
    @classmethod
    def coerce_cost(cls, v: object) -> Optional[float]:
        """Accept string costs like '$15' or '15.00' from the LLM."""
        if v is None:
            return None
        if isinstance(v, str):
            cleaned = v.replace("$", "").replace(",", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return float(v)


class Itinerary(BaseModel):
    trip_id: str
    summary: str
    stops: list[Stop]
    total_estimated_cost: float
    weather_note: str = ""
    warnings: list[str] = []
    # Set only on JSON-parse failure — never sent to the LLM or DB
    raw_text: Optional[str] = None

    @field_validator("total_estimated_cost", mode="before")
    @classmethod
    def coerce_total_cost(cls, v: object) -> float:
        if isinstance(v, str):
            cleaned = v.replace("$", "").replace(",", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return 0.0
        return float(v) if v is not None else 0.0
