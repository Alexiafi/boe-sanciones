from app.models.documento import BoeDocumento
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.models.scraping_run import ScrapingRun
from app.models.seguimiento import Seguimiento

__all__ = [
    "BoeDocumento",
    "Sancionado",
    "Seguimiento",
    "Notificacion",
    "ScrapingRun",
]
