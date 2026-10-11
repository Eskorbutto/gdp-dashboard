from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Login(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class Yo(_Base):
    id: int
    cliente_id: int
    cliente_nombre: str
    nombre: str
    email: str
    rol: str


class UsuarioSalida(_Base):
    id: int
    nombre: str
    email: str
    rol: str
    activo: bool


class ServicioSalida(_Base):
    id: int
    nombre: str
    codigo_origen: str | None
    umbral_ns_seg: int
    activo: bool


class AgenteSalida(_Base):
    id: int
    servicio_id: int | None
    codigo_origen: str
    nombre: str
    horas_contratadas_semana: Decimal | None
    activo: bool


class TurnoSalida(_Base):
    id: int
    agente_id: int
    servicio_id: int
    fecha: date
    inicio: datetime
    fin: datetime


class CargaSalida(_Base):
    id: int
    conector: str
    origen: str | None
    estado: str
    iniciada_en: datetime
    terminada_en: datetime | None
    registros_leidos: int
    registros_validos: int
    registros_con_error: int
