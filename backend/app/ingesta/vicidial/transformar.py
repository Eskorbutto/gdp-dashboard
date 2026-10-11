"""Traducción de tablas crudas de VICIdial al modelo estándar.

Funciones puras (sin base de datos): reciben filas crudas tal como se guardaron en
la zona de aterrizaje y devuelven filas del modelo estándar más los problemas
encontrados. Así se pueden probar con casos conocidos y reprocesar sin el cliente.

Tablas de origen:
- vicidial_closer_log -> llamadas (entrantes). Una fila por llamada a un ingroup.
- vicidial_agent_log  -> eventos_agente (pausa, disponible, en_llamada, acw).
- vicidial_user_log   -> eventos_agente (login, logout).

Supuestos (validar con datos reales):
- Se usan los *_epoch (UTC) y no call_date/event_time (hora local del servidor).
- Atendida = el campo user es un agente (no VDCL/VDAD/vacío). Conversación =
  length_in_sec - queue_seconds (incluye el tiempo muerto, dead_sec).
- ACW de la llamada = dispo_sec del ciclo de agent_log con el mismo uniqueid.
- En agent_log, en_llamada = talk_sec (incluye dead_sec) y acw = dispo_sec, para
  no contar dos veces el tiempo muerto.
- Llamadas con status AFTHRS (fuera de horario) no son ofrecidas: se descartan.
"""
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

USUARIOS_SISTEMA = frozenset({"", "VDCL", "VDAD"})
STATUS_NO_OFRECIDAS = frozenset({"AFTHRS"})
# Duración máxima creíble de un segmento: VICIdial a veces deja valores basura (ej. 4294967295).
MAX_SEGUNDOS = 24 * 3600


@dataclass(frozen=True)
class Problema:
    tabla: str
    id_origen: str | None
    motivo: str
    severidad: Literal["error", "advertencia"] = "error"

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Ventana:
    """Rango [desde, hasta) en epoch UTC que cubre una carga."""

    desde: int
    hasta: int

    def contiene(self, epoch: int) -> bool:
        return self.desde <= epoch < self.hasta


@dataclass
class Resultado:
    filas: list[dict[str, Any]]
    problemas: list[Problema]
    descartadas: int = 0


def _texto(fila: dict[str, Any], campo: str) -> str:
    valor = fila.get(campo)
    return "" if valor is None else str(valor).strip()


def _entero(fila: dict[str, Any], campo: str) -> int | None:
    try:
        return int(float(_texto(fila, campo)))
    except ValueError:
        return None


def fecha_utc(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


def _epoch_valido(epoch: int | None, ventana: Ventana) -> str | None:
    """Devuelve el motivo del problema, o None si la fecha es válida y está en la ventana."""
    if epoch is None or epoch <= 0:
        return "fecha inválida"
    if not ventana.contiene(epoch):
        return "fuera del rango de la carga"
    return None


def acw_por_uniqueid(agent_log: Iterable[dict[str, Any]]) -> dict[str, int]:
    acw: dict[str, int] = {}
    for fila in agent_log:
        uniqueid = _texto(fila, "uniqueid")
        dispo = _entero(fila, "dispo_sec")
        if uniqueid and dispo is not None and 0 <= dispo < MAX_SEGUNDOS:
            acw[uniqueid] = dispo
    return acw


def transformar_llamadas(
    closer_log: Iterable[dict[str, Any]],
    *,
    servicios: dict[str, int],
    agentes: dict[str, int],
    acw: dict[str, int],
    ventana: Ventana,
) -> Resultado:
    """vicidial_closer_log -> llamadas. `servicios` y `agentes` mapean código de origen -> id."""
    tabla = "vicidial_closer_log"
    resultado = Resultado(filas=[], problemas=[])
    vistos: set[str] = set()

    for fila in closer_log:
        id_origen = _texto(fila, "closecallid")
        if not id_origen:
            resultado.problemas.append(Problema(tabla, None, "fila sin closecallid"))
            continue
        if id_origen in vistos:
            resultado.problemas.append(Problema(tabla, id_origen, "duplicado en la carga"))
            continue
        vistos.add(id_origen)

        status = _texto(fila, "status")
        if status in STATUS_NO_OFRECIDAS:
            resultado.descartadas += 1
            continue

        inicio = _entero(fila, "start_epoch")
        if motivo := _epoch_valido(inicio, ventana):
            severidad = "advertencia" if motivo == "fuera del rango de la carga" else "error"
            resultado.problemas.append(Problema(tabla, id_origen, motivo, severidad))
            continue

        largo, cola_seg = _entero(fila, "length_in_sec"), _entero(fila, "queue_seconds")
        if largo is None or cola_seg is None or not (0 <= cola_seg < MAX_SEGUNDOS and 0 <= largo < MAX_SEGUNDOS):
            resultado.problemas.append(Problema(tabla, id_origen, "tiempos inválidos"))
            continue

        ingroup = _texto(fila, "campaign_id")
        servicio_id = servicios.get(ingroup)
        if servicio_id is None:
            resultado.problemas.append(Problema(tabla, id_origen, f"servicio sin mapear: {ingroup}"))
            continue

        usuario = _texto(fila, "user")
        atendida = usuario not in USUARIOS_SISTEMA
        agente_id = agentes.get(usuario) if atendida else None
        if atendida and agente_id is None:
            resultado.problemas.append(
                Problema(tabla, id_origen, f"agente sin mapear: {usuario} (llamada cargada sin agente)", "advertencia")
            )

        resultado.filas.append(
            {
                "servicio_id": servicio_id,
                "agente_id": agente_id,
                "id_origen": f"vicidial:closer:{id_origen}",
                "cola": ingroup,
                "inicio": fecha_utc(inicio),
                "espera_seg": cola_seg,
                "conversacion_seg": max(largo - cola_seg, 0) if atendida else 0,
                "acw_seg": acw.get(_texto(fila, "uniqueid"), 0) if atendida else 0,
                "resultado": "atendida" if atendida else "abandonada",
                "tipificacion": status or None,
            }
        )
    return resultado


# (tipo en el modelo estándar, columna epoch, columna segundos)
_SEGMENTOS = (
    ("pausa", "pause_epoch", "pause_sec"),
    ("disponible", "wait_epoch", "wait_sec"),
    ("en_llamada", "talk_epoch", "talk_sec"),
    ("acw", "dispo_epoch", "dispo_sec"),
)


def transformar_estados(
    agent_log: Iterable[dict[str, Any]], *, agentes: dict[str, int], ventana: Ventana
) -> Resultado:
    """vicidial_agent_log -> eventos_agente. Cada fila es un ciclo pausa → espera → llamada → disposición."""
    tabla = "vicidial_agent_log"
    resultado = Resultado(filas=[], problemas=[])
    vistos: set[str] = set()

    for fila in agent_log:
        id_origen = _texto(fila, "agent_log_id") or None
        if id_origen is not None:
            if id_origen in vistos:
                resultado.problemas.append(Problema(tabla, id_origen, "duplicado en la carga"))
                continue
            vistos.add(id_origen)

        usuario = _texto(fila, "user")
        agente_id = agentes.get(usuario)
        if agente_id is None:
            resultado.problemas.append(Problema(tabla, id_origen, f"agente sin mapear: {usuario}"))
            continue

        for tipo, col_epoch, col_seg in _SEGMENTOS:
            segundos = _entero(fila, col_seg)
            if not segundos:  # None o 0: segmento sin duración
                continue
            epoch = _entero(fila, col_epoch)
            if segundos < 0 or segundos >= MAX_SEGUNDOS:
                resultado.problemas.append(Problema(tabla, id_origen, f"duración inválida en {col_seg}: {segundos}"))
                continue
            if motivo := _epoch_valido(epoch, ventana):
                severidad = "advertencia" if motivo == "fuera del rango de la carga" else "error"
                resultado.problemas.append(Problema(tabla, id_origen, f"{motivo} en {col_epoch}", severidad))
                continue
            resultado.filas.append(
                {
                    "agente_id": agente_id,
                    "tipo": tipo,
                    "motivo": (_texto(fila, "sub_status") or None) if tipo == "pausa" else None,
                    "inicio": fecha_utc(epoch),
                    "fin": fecha_utc(epoch + segundos),
                }
            )
    return resultado


def transformar_sesiones(
    user_log: Iterable[dict[str, Any]], *, agentes: dict[str, int], ventana: Ventana
) -> Resultado:
    """vicidial_user_log -> eventos_agente (login/logout, instantáneos)."""
    tabla = "vicidial_user_log"
    resultado = Resultado(filas=[], problemas=[])
    vistos: set[str] = set()

    for fila in user_log:
        id_origen = _texto(fila, "user_log_id") or None
        if id_origen is not None:
            if id_origen in vistos:
                resultado.problemas.append(Problema(tabla, id_origen, "duplicado en la carga"))
                continue
            vistos.add(id_origen)

        evento = _texto(fila, "event").upper()
        if evento == "LOGIN":
            tipo = "login"
        elif "LOGOUT" in evento:  # LOGOUT, TIMEOUTLOGOUT, etc.
            tipo = "logout"
        else:
            resultado.descartadas += 1
            continue

        usuario = _texto(fila, "user")
        agente_id = agentes.get(usuario)
        if agente_id is None:
            resultado.problemas.append(Problema(tabla, id_origen, f"agente sin mapear: {usuario}"))
            continue

        epoch = _entero(fila, "event_epoch")
        if motivo := _epoch_valido(epoch, ventana):
            severidad = "advertencia" if motivo == "fuera del rango de la carga" else "error"
            resultado.problemas.append(Problema(tabla, id_origen, motivo, severidad))
            continue

        resultado.filas.append(
            {"agente_id": agente_id, "tipo": tipo, "motivo": None, "inicio": fecha_utc(epoch), "fin": None}
        )
    return resultado
