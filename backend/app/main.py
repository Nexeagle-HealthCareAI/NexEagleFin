import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agents_api import router as agents_router
from .api import router
from .db import init_db
from .loans_api import router as loans_router
from .money_api import router as money_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="NexEagleFin API", version="0.1.0", lifespan=lifespan)

origins = [o for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

app.include_router(router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(loans_router, prefix="/api")
app.include_router(money_router, prefix="/api")


@app.get("/health")
def health():
    return {"ok": True}
