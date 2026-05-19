from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.models.request import TripRequest
from app.agents.orchestrator import run_trip_plan

router = APIRouter()


@router.post("/plan")
async def plan_trip(request: TripRequest):
    return StreamingResponse(
        run_trip_plan(request),
        media_type="text/event-stream",
    )
