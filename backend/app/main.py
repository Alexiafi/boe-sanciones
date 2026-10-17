"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agenda import router as agenda_router
from app.api.clientes import router as clientes_router
from app.api.configuracion import router as configuracion_router
from app.api.dashboard import router as dashboard_router
from app.api.documentos import router as documentos_router
from app.api.documentos_comerciales import router as documentos_comerciales_router
from app.api.enriquecimiento import router as enriquecimiento_router
from app.api.historico import router as historico_router
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
    # The app is the same whether Judit opens it as localhost or 127.0.0.1;
    # with only the first origin allowed, the second one loaded the page but
    # every data request was blocked by the browser.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
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
app.include_router(agenda_router)
app.include_router(historico_router)
app.include_router(documentos_comerciales_router)
app.include_router(configuracion_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
