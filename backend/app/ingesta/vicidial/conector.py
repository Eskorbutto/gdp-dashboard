"""Conector VICIdial: origen -> zona de aterrizaje -> modelo estándar.

1. `cargar`: lee el origen, crea la carga y guarda cada fila cruda en `registros_crudos`.
2. `procesar`: transforma lo crudo de una carga y lo escribe en el modelo estándar.
   Se puede volver a llamar (reprocesar) sin pedirle nada al cliente.

Todo corre con el rol de aplicación y el cliente fijado en la sesión: RLS impide
escribir en otro cliente aunque haya un error en este código.

Reglas de escritura (idempotentes):
- llamadas: upsert por (cliente_id, id_origen).
- eventos_agente: la carga es dueña de su ventana; se borran los eventos VICIdial
  de esa ventana y se insertan los nuevos.

Limitaciones conocidas:
- Un segmento de agent_log que empieza después del fin de la ventana (ej. ciclo que
  cruza medianoche) se descarta con advertencia; relevante para operaciones 24 h.
- El id de origen es el closecallid: si un cliente tiene más de un servidor
  VICIdial, habría que agregarle un identificador de servidor.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import sesion_cliente
from app.ingesta.vicidial import transformar as tr
from app.ingesta.vicidial.lector import COLUMNAS, LectorVicidial
from app.modelos import Agente, CargaIngesta, EventoAgente, Llamada, RegistroCrudo, Servicio

CONECTOR = "vicidial"
TIPO_VENTANA = "_ventana"
MAX_ERRORES_GUARDADOS = 1000
# PostgreSQL acepta hasta 65.535 parámetros por sentencia; 2.000 filas x 12 columnas queda holgado.
FILAS_POR_LOTE = 2000


@dataclass(frozen=True)
class ResumenCarga:
    carga_id: int
    estado: str
    leidos: int
    con_error: int
    llamadas: int
    eventos: int
    problemas_por_motivo: dict[str, int]


def _ventana(desde: datetime, hasta: datetime) -> tr.Ventana:
    if desde.tzinfo is None or hasta.tzinfo is None:
        raise ValueError("desde y hasta deben tener zona horaria")
    if hasta <= desde:
        raise ValueError("hasta debe ser posterior a desde")
    return tr.Ventana(int(desde.timestamp()), int(hasta.timestamp()))


def cargar(cliente_id: int, lector: LectorVicidial, desde: datetime, hasta: datetime) -> ResumenCarga:
    ventana = _ventana(desde, hasta)
    try:
        datos = lector.leer(ventana)
    except Exception as exc:  # noqa: BLE001 - se registra en el log de cargas
        # Solo el tipo de error: el mensaje puede incluir la URL de conexión.
        with sesion_cliente(cliente_id) as sesion:
            carga = CargaIngesta(
                cliente_id=cliente_id, conector=CONECTOR, origen=lector.descripcion, estado="fallida",
                terminada_en=datetime.now(UTC),
                errores=[{"tabla": None, "id_origen": None, "severidad": "error",
                          "motivo": f"no se pudo leer el origen ({type(exc).__name__})"}],
            )
            sesion.add(carga)
            sesion.flush()
            carga_id = carga.id
        return ResumenCarga(carga_id, "fallida", 0, 0, 0, 0, {"no se pudo leer el origen": 1})

    with sesion_cliente(cliente_id) as sesion:
        carga = CargaIngesta(cliente_id=cliente_id, conector=CONECTOR, origen=lector.descripcion)
        sesion.add(carga)
        sesion.flush()
        crudos = [{"cliente_id": cliente_id, "carga_id": carga.id, "tipo_registro": TIPO_VENTANA,
                   "payload": {"desde": ventana.desde, "hasta": ventana.hasta}}]
        for tabla, filas in datos.items():
            crudos += [{"cliente_id": cliente_id, "carga_id": carga.id, "tipo_registro": tabla, "payload": f}
                       for f in filas]
        sesion.execute(insert(RegistroCrudo), crudos)
        carga_id = carga.id

    return procesar(cliente_id, carga_id)


def _mapeo(sesion: Session, modelo: type[Servicio] | type[Agente], cliente_id: int) -> dict[str, int]:
    filas = sesion.execute(
        select(modelo.codigo_origen, modelo.id).where(modelo.cliente_id == cliente_id, modelo.codigo_origen.is_not(None))
    )
    return {codigo: id_ for codigo, id_ in filas}


def procesar(cliente_id: int, carga_id: int) -> ResumenCarga:
    try:
        with sesion_cliente(cliente_id) as sesion:
            return _procesar(sesion, cliente_id, carga_id)
    except LookupError:
        raise
    except Exception as exc:
        with sesion_cliente(cliente_id) as sesion:
            carga = sesion.get(CargaIngesta, carga_id)
            carga.estado = "fallida"
            carga.terminada_en = datetime.now(UTC)
            carga.errores = [{"tabla": None, "id_origen": None, "severidad": "error",
                              "motivo": f"error al procesar ({type(exc).__name__})"}]
        raise


def _procesar(sesion: Session, cliente_id: int, carga_id: int) -> ResumenCarga:
    carga = sesion.scalar(
        select(CargaIngesta).where(CargaIngesta.id == carga_id, CargaIngesta.cliente_id == cliente_id)
    )
    if carga is None or carga.conector != CONECTOR:
        raise LookupError(f"carga VICIdial {carga_id} no encontrada")

    crudos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tipo, payload in sesion.execute(
        select(RegistroCrudo.tipo_registro, RegistroCrudo.payload)
        .where(RegistroCrudo.cliente_id == cliente_id, RegistroCrudo.carga_id == carga_id)
        .order_by(RegistroCrudo.id)
    ):
        crudos[tipo].append(payload)
    ventana = tr.Ventana(**crudos.pop(TIPO_VENTANA)[0])

    servicios = _mapeo(sesion, Servicio, cliente_id)
    agentes = _mapeo(sesion, Agente, cliente_id)
    agent_log = crudos.get("vicidial_agent_log", [])

    llamadas = tr.transformar_llamadas(
        crudos.get("vicidial_closer_log", []), servicios=servicios, agentes=agentes,
        acw=tr.acw_por_uniqueid(agent_log), ventana=ventana,
    )
    estados = tr.transformar_estados(agent_log, agentes=agentes, ventana=ventana)
    sesiones = tr.transformar_sesiones(crudos.get("vicidial_user_log", []), agentes=agentes, ventana=ventana)

    # Eventos: reemplazo completo de la ventana (de cualquier carga VICIdial previa).
    cargas_vicidial = select(CargaIngesta.id).where(
        CargaIngesta.cliente_id == cliente_id, CargaIngesta.conector == CONECTOR
    )
    sesion.execute(
        delete(EventoAgente).where(
            EventoAgente.cliente_id == cliente_id,
            EventoAgente.carga_id.in_(cargas_vicidial),
            EventoAgente.inicio >= tr.fecha_utc(ventana.desde),
            EventoAgente.inicio < tr.fecha_utc(ventana.hasta),
        )
    )
    eventos = [{**f, "cliente_id": cliente_id, "carga_id": carga_id} for f in estados.filas + sesiones.filas]
    if eventos:
        sesion.execute(insert(EventoAgente), eventos)

    # Llamadas: upsert por id de origen.
    filas = [{**f, "cliente_id": cliente_id, "carga_id": carga_id} for f in llamadas.filas]
    for i in range(0, len(filas), FILAS_POR_LOTE):
        stmt = pg_insert(Llamada).values(filas[i:i + FILAS_POR_LOTE])
        actualizables = {c: stmt.excluded[c] for c in filas[0] if c not in ("cliente_id", "id_origen")}
        sesion.execute(stmt.on_conflict_do_update(index_elements=["cliente_id", "id_origen"], set_=actualizables))

    problemas = llamadas.problemas + estados.problemas + sesiones.problemas
    errores = [p for p in problemas if p.severidad == "error"]
    leidos = sum(len(crudos.get(t, [])) for t in COLUMNAS)
    con_error = len({(p.tabla, p.id_origen) for p in errores})

    carga.estado = "con_errores" if errores else "ok"
    carga.terminada_en = datetime.now(UTC)
    carga.registros_leidos = leidos
    carga.registros_con_error = con_error
    carga.registros_validos = leidos - con_error
    carga.errores = [p.como_dict() for p in problemas[:MAX_ERRORES_GUARDADOS]]

    por_motivo = Counter(p.motivo.split(":")[0] for p in problemas)
    return ResumenCarga(carga_id, carga.estado, leidos, con_error, len(llamadas.filas), len(eventos), dict(por_motivo))
