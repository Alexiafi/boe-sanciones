"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.clientes import router as clientes_router
from app.api.dashboard import router as dashboard_router
from app.api.documentos import router as documentos_router
from app.api.enriquecimiento import router as enriquecimiento_router
from app.api.notificaciones import router as notificaciones_router
from app.api.sanciones import router as sanciones_router
from app.api.scraping import router as scraping_router

app = FastAPI(
    title="BOE Sanciones API",
    description="API para la extracción y gestión de sanciones del Boletín Oficial del Estado",
    version="1.0.0",
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
app.include_router(enriquecimiento_router)
app.include_router(clientes_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
