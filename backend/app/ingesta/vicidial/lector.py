"""Lectores del origen VICIdial. Devuelven filas crudas (valores en texto) por tabla."""
import csv
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import Engine, text

from app.ingesta.vicidial.transformar import Ventana

COLUMNAS = {
    "vicidial_closer_log": (
        "closecallid", "uniqueid", "campaign_id", "call_date", "start_epoch", "end_epoch",
        "length_in_sec", "queue_seconds", "status", "user", "term_reason",
    ),
    "vicidial_agent_log": (
        "agent_log_id", "user", "campaign_id", "event_time", "pause_epoch", "pause_sec", "wait_epoch",
        "wait_sec", "talk_epoch", "talk_sec", "dispo_epoch", "dispo_sec", "dead_sec", "status",
        "sub_status", "uniqueid",
    ),
    "vicidial_user_log": ("user_log_id", "user", "event", "campaign_id", "event_date", "event_epoch"),
}
# Columna epoch con la que se filtra cada tabla por ventana.
COLUMNA_FECHA = {
    "vicidial_closer_log": "start_epoch",
    "vicidial_agent_log": "pause_epoch",
    "vicidial_user_log": "event_epoch",
}

Datos = dict[str, list[dict[str, str]]]


class LectorVicidial(Protocol):
    descripcion: str

    def leer(self, ventana: Ventana) -> Datos: ...


def _a_texto(valor: Any) -> str:
    return "" if valor is None else str(valor)


class LectorSQL:
    """Lee directo de la base de VICIdial (MySQL/MariaDB) con un usuario de solo lectura.

    La URL de conexión viene de una variable de entorno; nunca se guarda en el repositorio.
    """

    def __init__(self, engine: Engine, descripcion: str = "vicidial-sql") -> None:
        self.engine = engine
        self.descripcion = descripcion

    def leer(self, ventana: Ventana) -> Datos:
        datos: Datos = {}
        with self.engine.connect() as con:
            for tabla, columnas in COLUMNAS.items():
                consulta = text(
                    f"SELECT {', '.join(columnas)} FROM {tabla} "
                    f"WHERE {COLUMNA_FECHA[tabla]} >= :desde AND {COLUMNA_FECHA[tabla]} < :hasta"
                )
                filas = con.execute(consulta, {"desde": ventana.desde, "hasta": ventana.hasta}).mappings()
                datos[tabla] = [{c: _a_texto(f[c]) for c in columnas} for f in filas]
        return datos


class LectorCSV:
    """Lee exportes CSV: <directorio>/<tabla>.csv. Las tablas sin archivo quedan vacías."""

    def __init__(self, directorio: Path) -> None:
        self.directorio = Path(directorio)
        self.descripcion = f"csv:{self.directorio.name}"

    def leer(self, ventana: Ventana) -> Datos:
        datos: Datos = {}
        for tabla in COLUMNAS:
            archivo = self.directorio / f"{tabla}.csv"
            if not archivo.exists():
                datos[tabla] = []
                continue
            with archivo.open(encoding="utf-8", newline="") as f:
                datos[tabla] = [dict(fila) for fila in csv.DictReader(f)]
        return datos
