"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dashboard import router as dashboard_router
from app.api.documentos import router as documentos_router
from app.api.notificaciones import router as notificaciones_router
from app.api.sanciones import router as sanciones_router
from app.api.scraping import router as scraping_router
from app.database import Base, async_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="BOE Sanciones API",
    description="API para la extracción y gestión de sanciones del Boletín Oficial del Estado",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://frontend:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)
app.include_router(sanciones_router)
app.include_router(documentos_router)
app.include_router(scraping_router)
app.include_router(notificaciones_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
