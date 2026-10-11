"""Conexión a PostgreSQL con aislamiento por cliente.

Cada transacción de la aplicación fija `app.cliente_id` (con alcance local a la
transacción). Las políticas RLS de la base filtran todas las tablas por ese
valor; si no está fijado, las consultas devuelven cero filas.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import obtener_configuracion


@lru_cache
def obtener_engine() -> Engine:
    return create_engine(obtener_configuracion().database_url, pool_pre_ping=True)


@lru_cache
def _fabrica_sesiones() -> sessionmaker[Session]:
    return sessionmaker(obtener_engine(), expire_on_commit=False)


@contextmanager
def sesion_sin_cliente() -> Iterator[Session]:
    """Sesión sin cliente fijado: RLS no deja ver ninguna fila.

    Solo sirve para llamar funciones SECURITY DEFINER acotadas (ej. login).
    """
    with _fabrica_sesiones()() as sesion, sesion.begin():
        yield sesion


@contextmanager
def sesion_cliente(cliente_id: int) -> Iterator[Session]:
    with _fabrica_sesiones()() as sesion, sesion.begin():
        sesion.execute(
            text("SELECT set_config('app.cliente_id', :cliente_id, true)"),
            {"cliente_id": str(int(cliente_id))},
        )
        yield sesion
