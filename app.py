from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os



from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse
from limiter import limiter
from scan import router as scan_router
from geocode import router as geocode_router

load_dotenv()

TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")


app = FastAPI(
    title="Environmental Screening API",
    description="Environmental screening for endangered species near construction sites",
    version="1.1"
)

# Allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."}
    )

@app.get("/")
def root():
    return {
        "message": "Environmental Screening API is running",
        "allowed_origins": FRONTEND_ORIGIN,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# Routers
app.include_router(scan_router, tags=["scan"])
app.include_router(geocode_router, prefix="/geocode", tags=["geocode"])

