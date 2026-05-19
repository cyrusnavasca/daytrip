from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load backend/.env (and any parent-level .env.local) before anything else
load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api.routes import router  # noqa: E402
from app.db.client import close_pool, get_pool  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the asyncpg connection pool on startup; close it on shutdown."""
    try:
        await get_pool()
    except Exception:
        # DB not configured in dev is non-fatal — tools degrade gracefully
        pass
    yield
    await close_pool()


app = FastAPI(title="Daytrip API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.2.0"}
