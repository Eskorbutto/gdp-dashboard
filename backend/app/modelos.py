"""Modelo de datos estándar (canónico), igual para todos los clientes.

Reglas:
- Toda tabla lleva `cliente_id` (en `clientes` el propio `id` cumple ese rol).
- Las relaciones entre tablas de un cliente usan FK compuestas (cliente_id, id),
  así la base impide que un registro del cliente A apunte a uno del cliente B.
- Ley 19.628: solo los datos personales mínimos. Agentes se identifican por su
  código de origen y un nombre visible; no se guardan RUT, teléfonos de clientes
  finales ni diagnósticos de licencias médicas.
- Fechas y horas en `timestamptz` (UTC en la base; se muestran en America/Santiago).
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TZ = TIMESTAMP(timezone=True)

ROLES = ("admin_plataforma", "gerente", "supervisor", "cliente_lectura")
TIPOS_EVENTO = ("login", "logout", "disponible", "en_llamada", "acw", "pausa")
TIPOS_AUSENCIA = ("licencia_medica", "vacaciones", "permiso", "falta", "otro")
INDICADORES = ("ns", "na", "tmo", "abandono", "ausentismo", "shrinkage", "adherencia")
CONECTORES = ("vicidial", "asterisk", "genesys", "archivo", "api", "sftp", "simulado")
ESTADOS_CARGA = ("en_proceso", "ok", "con_errores", "fallida")


def _en(columna: str, valores: tuple[str, ...]) -> str:
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


def _fk_cliente(tabla: str, columna: str, nombre_fk: str | None = None) -> ForeignKeyConstraint:
    """FK compuesta (cliente_id, columna) -> tabla(cliente_id, id)."""
    return ForeignKeyConstraint(
        ["cliente_id", columna],
        [f"{tabla}.cliente_id", f"{tabla}.id"],
        name=nombre_fk,
    )


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class ConCliente:
    """Columna cliente_id común a todas las tablas de un cliente."""

    cliente_id: Mapped[int] = mapped_column(Integer, ForeignKey("clientes.id"), nullable=False)


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    creado_en: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class Usuario(ConCliente, Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        UniqueConstraint("cliente_id", "id"),
        CheckConstraint(_en("rol", ROLES), name="rol"),
        CheckConstraint("email = lower(email)", name="email_minusculas"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    # Único global: el login busca por correo antes de conocer el cliente.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    rol: Mapped[str] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    creado_en: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class Servicio(ConCliente, Base):
    __tablename__ = "servicios"
    __table_args__ = (
        UniqueConstraint("cliente_id", "id"),
        UniqueConstraint("cliente_id", "nombre"),
        CheckConstraint("umbral_ns_seg > 0", name="umbral_ns_positivo"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    # Identificador en el sistema de origen (ej. campaign_id / ingroup de VICIdial).
    codigo_origen: Mapped[str | None] = mapped_column(String(60))
    # Umbral del NS en segundos (ej. 80/20 -> 20).
    umbral_ns_seg: Mapped[int] = mapped_column(SmallInteger, server_default=text("20"))
    activo: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Agente(ConCliente, Base):
    __tablename__ = "agentes"
    __table_args__ = (
        UniqueConstraint("cliente_id", "id"),
        UniqueConstraint("cliente_id", "codigo_origen"),
        _fk_cliente("servicios", "servicio_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    # Servicio principal del agente (puede atender otros).
    servicio_id: Mapped[int | None] = mapped_column(Integer)
    # Usuario en el sistema de origen (ej. user de VICIdial). Llave para mapear la ingesta.
    codigo_origen: Mapped[str] = mapped_column(String(60))
    nombre: Mapped[str] = mapped_column(String(120))
    horas_contratadas_semana: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    activo: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class CargaIngesta(ConCliente, Base):
    """Log de cargas, visible para el cliente."""

    __tablename__ = "cargas_ingesta"
    __table_args__ = (
        UniqueConstraint("cliente_id", "id"),
        CheckConstraint(_en("conector", CONECTORES), name="conector"),
        CheckConstraint(_en("estado", ESTADOS_CARGA), name="estado"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    conector: Mapped[str] = mapped_column(String(30))
    origen: Mapped[str | None] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(20), server_default=text("'en_proceso'"))
    iniciada_en: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    terminada_en: Mapped[datetime | None] = mapped_column(TZ)
    registros_leidos: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    registros_validos: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    registros_con_error: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Lista de {fila, campo, motivo}: duplicado, fecha inválida, agente sin mapear, etc.
    errores: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))


class RegistroCrudo(ConCliente, Base):
    """Zona de aterrizaje: el dato tal como llegó, para poder reprocesar."""

    __tablename__ = "registros_crudos"
    __table_args__ = (
        _fk_cliente("cargas_ingesta", "carga_id"),
        Index(None, "cliente_id", "carga_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    carga_id: Mapped[int] = mapped_column(BigInteger)
    tipo_registro: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    recibido_en: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class Llamada(ConCliente, Base):
    __tablename__ = "llamadas"
    __table_args__ = (
        UniqueConstraint("cliente_id", "id"),
        # Evita duplicados al reprocesar una carga.
        UniqueConstraint("cliente_id", "id_origen"),
        _fk_cliente("servicios", "servicio_id"),
        _fk_cliente("agentes", "agente_id"),
        _fk_cliente("cargas_ingesta", "carga_id"),
        CheckConstraint("resultado IN ('atendida', 'abandonada')", name="resultado"),
        CheckConstraint(
            "espera_seg >= 0 AND conversacion_seg >= 0 AND acw_seg >= 0", name="tiempos_no_negativos"
        ),
        Index(None, "cliente_id", "servicio_id", "inicio"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    servicio_id: Mapped[int] = mapped_column(Integer)
    agente_id: Mapped[int | None] = mapped_column(Integer)
    carga_id: Mapped[int | None] = mapped_column(BigInteger)
    id_origen: Mapped[str] = mapped_column(String(100))
    cola: Mapped[str | None] = mapped_column(String(60))
    inicio: Mapped[datetime] = mapped_column(TZ)
    espera_seg: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    conversacion_seg: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    acw_seg: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    resultado: Mapped[str] = mapped_column(String(20))
    tipificacion: Mapped[str | None] = mapped_column(String(100))


class EventoAgente(ConCliente, Base):
    """Login/logout son instantáneos (fin NULL); los estados tienen inicio y fin."""

    __tablename__ = "eventos_agente"
    __table_args__ = (
        _fk_cliente("agentes", "agente_id"),
        _fk_cliente("cargas_ingesta", "carga_id"),
        CheckConstraint(_en("tipo", TIPOS_EVENTO), name="tipo"),
        CheckConstraint("fin IS NULL OR fin >= inicio", name="fin_posterior"),
        Index(None, "cliente_id", "agente_id", "inicio"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    agente_id: Mapped[int] = mapped_column(Integer)
    carga_id: Mapped[int | None] = mapped_column(BigInteger)
    tipo: Mapped[str] = mapped_column(String(20))
    # Motivo de pausa tal como viene del origen (ej. BAÑO, COLACION, CAPACIT).
    motivo: Mapped[str | None] = mapped_column(String(60))
    inicio: Mapped[datetime] = mapped_column(TZ)
    fin: Mapped[datetime | None] = mapped_column(TZ)


class TurnoPlanificado(ConCliente, Base):
    """Malla. Compartida por dotación y asistencia (base de la adherencia)."""

    __tablename__ = "turnos_planificados"
    __table_args__ = (
        _fk_cliente("agentes", "agente_id"),
        _fk_cliente("servicios", "servicio_id"),
        UniqueConstraint("cliente_id", "agente_id", "inicio"),
        CheckConstraint("fin > inicio", name="fin_posterior"),
        Index(None, "cliente_id", "fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    agente_id: Mapped[int] = mapped_column(Integer)
    servicio_id: Mapped[int] = mapped_column(Integer)
    # Día al que pertenece el turno (un turno nocturno puede terminar al día siguiente).
    fecha: Mapped[date] = mapped_column(Date)
    inicio: Mapped[datetime] = mapped_column(TZ)
    fin: Mapped[datetime] = mapped_column(TZ)


class Ausencia(ConCliente, Base):
    __tablename__ = "ausencias"
    __table_args__ = (
        _fk_cliente("agentes", "agente_id"),
        CheckConstraint(_en("tipo", TIPOS_AUSENCIA), name="tipo"),
        CheckConstraint("fecha_hasta >= fecha_desde", name="rango_valido"),
        Index(None, "cliente_id", "agente_id", "fecha_desde"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    agente_id: Mapped[int] = mapped_column(Integer)
    fecha_desde: Mapped[date] = mapped_column(Date)
    fecha_hasta: Mapped[date] = mapped_column(Date)
    # Solo el tipo; nunca diagnóstico ni detalle médico.
    tipo: Mapped[str] = mapped_column(String(30))
    justificada: Mapped[bool] = mapped_column(Boolean)


class EvaluacionCalidad(ConCliente, Base):
    __tablename__ = "evaluaciones_calidad"
    __table_args__ = (
        _fk_cliente("agentes", "agente_id"),
        _fk_cliente("llamadas", "llamada_id"),
        _fk_cliente("usuarios", "evaluador_usuario_id"),
        CheckConstraint("nota BETWEEN 0 AND 100", name="nota_rango"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    agente_id: Mapped[int] = mapped_column(Integer)
    llamada_id: Mapped[int | None] = mapped_column(BigInteger)
    evaluador_usuario_id: Mapped[int | None] = mapped_column(Integer)
    fecha: Mapped[date] = mapped_column(Date)
    nota: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    comentario: Mapped[str | None] = mapped_column(Text)


class MetaIndicador(ConCliente, Base):
    """servicio_id NULL = meta general del cliente."""

    __tablename__ = "metas_indicador"
    __table_args__ = (
        _fk_cliente("servicios", "servicio_id"),
        UniqueConstraint(
            "cliente_id", "servicio_id", "indicador", "vigente_desde", postgresql_nulls_not_distinct=True
        ),
        CheckConstraint(_en("indicador", INDICADORES), name="indicador"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    servicio_id: Mapped[int | None] = mapped_column(Integer)
    indicador: Mapped[str] = mapped_column(String(20))
    # Porcentajes en 0-100; TMO en segundos.
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    vigente_desde: Mapped[date] = mapped_column(Date)


class ResumenIntervaloServicio(ConCliente, Base):
    """Indicadores precalculados por intervalo (15 o 30 min) para el dashboard.

    Se guardan contadores y sumas (no porcentajes) para poder agregar a cualquier
    periodo: NS, NA, TMO y abandono se calculan al leer.
    """

    __tablename__ = "resumen_intervalo_servicio"
    __table_args__ = (
        _fk_cliente("servicios", "servicio_id"),
        CheckConstraint("minutos_intervalo IN (15, 30)", name="minutos_intervalo"),
    )

    cliente_id: Mapped[int] = mapped_column(Integer, ForeignKey("clientes.id"), primary_key=True)
    servicio_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # '' = todas las colas del servicio.
    cola: Mapped[str] = mapped_column(String(60), primary_key=True, server_default=text("''"))
    minutos_intervalo: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    inicio_intervalo: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    ofrecidas: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    atendidas: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    atendidas_en_umbral: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    abandonadas: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    abandonadas_en_umbral: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    espera_seg_total: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    conversacion_seg_total: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    acw_seg_total: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    calculado_en: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


# Tablas con aislamiento por cliente: (tabla, columna que identifica al cliente).
TABLAS_CON_RLS: tuple[tuple[str, str], ...] = (("clientes", "id"),) + tuple(
    (t.name, "cliente_id") for t in Base.metadata.sorted_tables if t.name != "clientes"
)
