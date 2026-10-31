import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import orders, payments, products
from app.database import SessionLocal
from app.migrate import run_migrations
from app.seed import seed_products
from app.web import router as pages

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_migrations()
    db = SessionLocal()
    try:
        seed_products(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Bread Factory", lifespan=lifespan)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(pages)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}
