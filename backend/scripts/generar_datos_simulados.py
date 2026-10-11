"""Genera datos simulados de asistencia (100% ficticios) en el modelo estándar.

Por cliente: servicios, agentes, usuarios (uno por rol), malla de turnos,
eventos de agente (login/logout, estados y pausas), ausencias y metas.

Incluye casos que los reportes de asistencia deben detectar:
- atrasos (login 5 a 45 min después del inicio del turno),
- salidas anticipadas,
- faltas injustificadas (turno sin login y sin ausencia registrada),
- ausencias justificadas (licencia, vacaciones, permiso).

Uso (con el rol dueño, ver DATABASE_URL_OWNER):
    python -m scripts.generar_datos_simulados --reiniciar
"""
import argparse
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, insert, text
from sqlalchemy.orm import Session

from app.config import obtener_configuracion
from app.modelos import (
    Agente,
    Ausencia,
    CargaIngesta,
    Cliente,
    EventoAgente,
    MetaIndicador,
    RegistroCrudo,
    Servicio,
    TurnoPlanificado,
    Usuario,
)
from app.seguridad import hashear_password

TZ_CHILE = ZoneInfo("America/Santiago")
PASSWORD_DEMO = "demo1234"

CLIENTES_DEMO = (
    ("Contacto Andino SpA", "andino", ("Atención Clientes", "Cobranza")),
    ("Fono Austral Ltda", "austral", ("Mesa de Ayuda", "Ventas")),
)
NOMBRES = ("Camila", "Matías", "Valentina", "Benjamín", "Javiera", "Vicente", "Catalina", "Tomás",
           "Fernanda", "Joaquín", "Antonia", "Diego", "Constanza", "Felipe", "Isidora", "Cristóbal")
APELLIDOS = ("González", "Muñoz", "Rojas", "Díaz", "Pérez", "Soto", "Contreras", "Silva",
             "Martínez", "Sepúlveda", "Morales", "Fuentes", "Araya", "Espinoza", "Tapia", "Reyes")

# (nombre, hora inicio, duración, colación en minutos o None, horas semanales contratadas)
TIPOS_TURNO = (
    ("mañana", time(8, 0), timedelta(hours=9, minutes=24), 60, 42),
    ("tarde", time(13, 0), timedelta(hours=9, minutes=24), 60, 42),
    ("part-time", time(16, 0), timedelta(hours=6), None, 30),
)


@dataclass
class Resumen:
    clientes: dict[str, int] = field(default_factory=dict)
    turnos: int = 0
    eventos: int = 0
    ausencias: int = 0
    faltas_injustificadas: int = 0
    atrasos: int = 0


def _local(dia: date, hora: time) -> datetime:
    return datetime.combine(dia, hora, tzinfo=TZ_CHILE)


def _dias_habiles(desde: date, dias: int) -> list[date]:
    return [d for d in (desde + timedelta(n) for n in range(dias)) if d.weekday() < 5]


def _bloques_trabajo(agente_id: int, cliente_id: int, carga_id: int, inicio: datetime, fin: datetime,
                     rng: random.Random) -> list[dict]:
    """Divide un tramo conectado en bloques de 30 min: en_llamada, acw y disponible."""
    filas = []
    t = inicio
    while t < fin:
        bloque_fin = min(t + timedelta(minutes=30), fin)
        minutos = (bloque_fin - t).total_seconds() / 60
        reparto = (("en_llamada", rng.uniform(0.55, 0.75)), ("acw", rng.uniform(0.05, 0.15)))
        for tipo, fraccion in reparto:
            dur = timedelta(minutes=round(minutos * fraccion, 1))
            filas.append(_evento(cliente_id, agente_id, carga_id, tipo, t, t + dur))
            t += dur
        filas.append(_evento(cliente_id, agente_id, carga_id, "disponible", t, bloque_fin))
        t = bloque_fin
    return filas


def _evento(cliente_id: int, agente_id: int, carga_id: int, tipo: str, inicio: datetime,
            fin: datetime | None, motivo: str | None = None) -> dict:
    return {"cliente_id": cliente_id, "agente_id": agente_id, "carga_id": carga_id, "tipo": tipo,
            "motivo": motivo, "inicio": inicio, "fin": fin}


def _jornada(agente: Agente, carga_id: int, inicio_turno: datetime, fin_turno: datetime,
             colacion_min: int | None, rng: random.Random, resumen: Resumen) -> list[dict]:
    """Eventos de un día trabajado: login, estados, pausas y logout."""
    cid, aid = agente.cliente_id, agente.id
    if rng.random() < 0.10:
        login = inicio_turno + timedelta(minutes=rng.randint(5, 45))
        resumen.atrasos += 1
    else:
        login = inicio_turno + timedelta(minutes=rng.randint(-10, 2))
    if rng.random() < 0.03:
        logout = fin_turno - timedelta(minutes=rng.randint(30, 90))
    else:
        logout = fin_turno + timedelta(minutes=rng.randint(0, 15))

    pausas = [("BAÑO", login + timedelta(hours=2), 10)]
    if colacion_min:
        mitad = inicio_turno + (fin_turno - inicio_turno) / 2
        pausas.append(("COLACION", mitad - timedelta(minutes=30), colacion_min))
    pausas.append(("BAÑO", logout - timedelta(hours=1, minutes=30), 10))
    pausas = sorted(
        ((m, i, i + timedelta(minutes=d)) for m, i, d in pausas if login < i and i + timedelta(minutes=d) < logout),
        key=lambda p: p[1],
    )

    filas = [_evento(cid, aid, carga_id, "login", login, None)]
    cursor = login
    for motivo, p_ini, p_fin in pausas:
        if p_ini < cursor:
            continue
        filas += _bloques_trabajo(aid, cid, carga_id, cursor, p_ini, rng)
        filas.append(_evento(cid, aid, carga_id, "pausa", p_ini, p_fin, motivo))
        cursor = p_fin
    filas += _bloques_trabajo(aid, cid, carga_id, cursor, logout, rng)
    filas.append(_evento(cid, aid, carga_id, "logout", logout, None))
    return filas


def _ausencias_agente(agente: Agente, dias: list[date], rng: random.Random, forzar_licencia: bool = False) -> list[dict]:
    """Bloques de ausencias justificadas, sin traslapes."""
    filas = []
    ocupados: set[date] = set()
    for tipo, prob, largo in (("licencia_medica", 0.15, (1, 3)), ("vacaciones", 0.08, (5, 5)),
                              ("permiso", 0.10, (1, 1))):
        if not dias or (rng.random() >= prob and not (forzar_licencia and tipo == "licencia_medica")):
            continue
        n = rng.randint(*largo)
        i = rng.randrange(max(1, len(dias) - n + 1))
        bloque = dias[i:i + n]
        if not bloque or ocupados & set(bloque):
            continue
        ocupados |= set(bloque)
        filas.append({"cliente_id": agente.cliente_id, "agente_id": agente.id, "fecha_desde": bloque[0],
                      "fecha_hasta": bloque[-1], "tipo": tipo, "justificada": True})
    return filas


def generar(sesion: Session, *, semilla: int = 19628, desde: date | None = None, dias: int = 14,
            agentes_por_servicio: int = 8, clientes=CLIENTES_DEMO) -> Resumen:
    """Inserta los datos simulados. Debe usarse con una sesión del rol dueño."""
    rng = random.Random(semilla)
    desde = desde or date.today() - timedelta(days=dias)
    dias_habiles = _dias_habiles(desde, dias)
    password_hash = hashear_password(PASSWORD_DEMO)
    resumen = Resumen()

    for nombre_cliente, alias, servicios in clientes:
        cliente = Cliente(nombre=nombre_cliente)
        sesion.add(cliente)
        sesion.flush()
        resumen.clientes[nombre_cliente] = cliente.id

        for rol in ("gerente", "supervisor", "cliente_lectura"):
            sesion.add(Usuario(cliente_id=cliente.id, email=f"{rol}@{alias}.ejemplo.cl",
                               nombre=f"{rol.replace('_', ' ').title()} {alias.title()}", rol=rol,
                               password_hash=password_hash))

        carga = CargaIngesta(cliente_id=cliente.id, conector="simulado", origen="generar_datos_simulados",
                             estado="ok", terminada_en=datetime.now(TZ_CHILE))
        sesion.add(carga)
        sesion.flush()
        sesion.add(MetaIndicador(cliente_id=cliente.id, indicador="ausentismo", valor=5, vigente_desde=desde))

        for n_servicio, nombre_servicio in enumerate(servicios):
            servicio = Servicio(cliente_id=cliente.id, nombre=nombre_servicio, codigo_origen=f"CAMP{n_servicio + 1:02d}")
            sesion.add(servicio)
            sesion.flush()
            sesion.add(MetaIndicador(cliente_id=cliente.id, servicio_id=servicio.id, indicador="ns", valor=80,
                                     vigente_desde=desde))

            for n_agente in range(agentes_por_servicio):
                tipo_turno = TIPOS_TURNO[n_agente % len(TIPOS_TURNO)]
                _, hora_inicio, duracion, colacion, horas_semana = tipo_turno
                agente = Agente(cliente_id=cliente.id, servicio_id=servicio.id,
                                codigo_origen=f"{alias[:3]}{n_servicio + 1}{n_agente + 1:03d}",
                                nombre=f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}",
                                horas_contratadas_semana=horas_semana)
                sesion.add(agente)
                sesion.flush()

                # El primer agente de cada cliente siempre tiene una licencia, para que haya casos.
                primero = n_servicio == 0 and n_agente == 0
                ausencias = _ausencias_agente(agente, dias_habiles, rng, forzar_licencia=primero)
                dias_ausente = {a["fecha_desde"] + timedelta(k)
                                for a in ausencias for k in range((a["fecha_hasta"] - a["fecha_desde"]).days + 1)}
                turnos, eventos = [], []
                for dia in dias_habiles:
                    inicio = _local(dia, hora_inicio)
                    fin = inicio + duracion
                    turnos.append({"cliente_id": cliente.id, "agente_id": agente.id, "servicio_id": servicio.id,
                                   "fecha": dia, "inicio": inicio, "fin": fin})
                    if dia in dias_ausente:
                        continue
                    if rng.random() < 0.04:
                        resumen.faltas_injustificadas += 1
                        continue
                    eventos += _jornada(agente, carga.id, inicio, fin, colacion, rng, resumen)

                if turnos:
                    sesion.execute(insert(TurnoPlanificado), turnos)
                if ausencias:
                    sesion.execute(insert(Ausencia), ausencias)
                if eventos:
                    sesion.execute(insert(EventoAgente), eventos)
                resumen.turnos += len(turnos)
                resumen.ausencias += len(ausencias)
                resumen.eventos += len(eventos)

        # Zona de aterrizaje: una muestra del "dato crudo" de la carga simulada.
        sesion.add(RegistroCrudo(cliente_id=cliente.id, carga_id=carga.id, tipo_registro="resumen_carga",
                                 payload={"semilla": semilla, "desde": desde.isoformat(), "dias": dias}))
        carga.registros_leidos = carga.registros_validos = resumen.eventos
        sesion.flush()

    return resumen


def reiniciar(sesion: Session) -> None:
    """Vacía todas las tablas del modelo (solo para la base local de desarrollo)."""
    sesion.execute(text("TRUNCATE clientes RESTART IDENTITY CASCADE"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reiniciar", action="store_true", help="vacía las tablas antes de generar")
    parser.add_argument("--dias", type=int, default=14)
    parser.add_argument("--agentes-por-servicio", type=int, default=8)
    parser.add_argument("--semilla", type=int, default=19628)
    args = parser.parse_args()

    engine = create_engine(obtener_configuracion().database_url_owner)
    with Session(engine) as sesion, sesion.begin():
        if args.reiniciar:
            reiniciar(sesion)
        r = generar(sesion, semilla=args.semilla, dias=args.dias, agentes_por_servicio=args.agentes_por_servicio)
    print(f"Clientes: {r.clientes}")
    print(f"Turnos: {r.turnos} | Eventos: {r.eventos} | Ausencias: {r.ausencias} | "
          f"Atrasos: {r.atrasos} | Faltas injustificadas: {r.faltas_injustificadas}")
    print(f"Usuarios demo: gerente@andino.ejemplo.cl, supervisor@austral.ejemplo.cl, etc. Clave: {PASSWORD_DEMO}")


if __name__ == "__main__":
    main()
