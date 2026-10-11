"""Genera datos crudos 100% FICTICIOS con el formato de 3 tablas de VICIdial.

Sirve para probar el conector de ingesta sin tocar datos reales. Es determinista:
la misma semilla entrega exactamente los mismos datos.

Tablas: vicidial_closer_log (llamadas entrantes), vicidial_agent_log (ciclos
pausa -> espera -> conversación -> tipificación por agente) y vicidial_user_log
(login/logout). Todos los valores son str, como en un export; los epochs son
unix UTC en texto y las fechas son hora local de America/Santiago (09:00 a 18:00).

Con errores=True se agregan ADEMÁS estos casos (con errores=False no hay ninguno):
  1. closer_log: fila duplicada (mismo closecallid que otra existente, copia idéntica).
  2. closer_log: fila con start_epoch = "0".
  3. closer_log: una fila atendida con campaign_id = "INGROUP_DESCONOCIDO"
     (se reetiqueta una atendida existente para conservar su uniqueid en agent_log).
  4. closer_log: fila atendida con user = "agente_fantasma" (uniqueid propio, ausente de agent_log).
  5. agent_log: fila con user = "agente_fantasma".
  6. agent_log: fila de un agente real con pause_sec = "4294967295" (basura típica de
     VICIdial), demás segmentos en 0, después de su logout para no traslapar.
  7. user_log: LOGIN de "agente_fantasma".

Uso:
    python -m scripts.simular_vicidial --dia 2026-03-02 --directorio /tmp/vicidial
"""
import argparse
import csv
import random
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

TZ_CHILE = ZoneInfo("America/Santiago")
CAMPANA = "CAMP01"
FANTASMA = "agente_fantasma"
BASURA = "4294967295"
TIPIFICACIONES = (("VENTA", 25), ("NOINT", 40), ("CALLBK", 15), ("INFO", 20))

COLUMNAS = {
    "vicidial_closer_log": ("closecallid", "uniqueid", "campaign_id", "call_date", "start_epoch", "end_epoch",
                            "length_in_sec", "queue_seconds", "status", "user", "term_reason"),
    "vicidial_agent_log": ("agent_log_id", "user", "campaign_id", "event_time", "pause_epoch", "pause_sec",
                           "wait_epoch", "wait_sec", "talk_epoch", "talk_sec", "dispo_epoch", "dispo_sec",
                           "dead_sec", "status", "sub_status", "uniqueid"),
    "vicidial_user_log": ("user_log_id", "user", "event", "campaign_id", "event_date", "event_epoch"),
}


def _hora_local(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, TZ_CHILE).strftime("%Y-%m-%d %H:%M:%S")


def _ciclo(usuario, pausa, espera, conv, dispo, dead, status, sub, uid, ep):
    """Fila de agent_log (sin id) con los segmentos consecutivos a partir de ep."""
    w, t = ep + pausa, ep + pausa + espera
    d = t + conv
    fila = dict(user=usuario, campaign_id=CAMPANA, event_time=_hora_local(ep), pause_epoch=ep, pause_sec=pausa,
                wait_epoch=w, wait_sec=espera, talk_epoch=t, talk_sec=conv, dispo_epoch=d, dispo_sec=dispo,
                dead_sec=dead, status=status, sub_status=sub, uniqueid=uid)
    return fila


def _ciclos_agente(rnd, usuario, login, logout, n_llamadas, nuevo_uid):
    """Ciclos consecutivos de un agente entre login y logout, sin traslapes."""
    ventana = logout - login - 300
    banos = rnd.randint(1, 2)
    n_vacios = max(1, round(n_llamadas * 0.1))
    tipos = [True] * n_llamadas + [False] * n_vacios
    rnd.shuffle(tipos)
    n = len(tipos)
    pausas = [rnd.randint(0, 5) for _ in tipos]
    convs = [rnd.randint(60, 600) if t else 0 for t in tipos]
    dispos = [rnd.randint(10, 60) if t else 0 for t in tipos]
    duraciones_bano = [rnd.randint(300, 600) for _ in range(banos)]
    fijo_pausas = sum(pausas) + 3600 + sum(duraciones_bano)
    presupuesto = max(0, (ventana - fijo_pausas) * 0.6)
    llamado = sum(convs) + sum(dispos)
    factor = min(1.0, presupuesto / llamado) if llamado else 1.0  # evita desborde con muchas llamadas
    convs = [int(c * factor) if c else 0 for c in convs]
    dispos = [int(d * factor) if d else 0 for d in dispos]
    holgura = ventana - fijo_pausas - sum(convs) - sum(dispos)
    pesos = [rnd.random() + 0.2 for _ in tipos]
    esperas = [int(holgura * p / sum(pesos) * 0.97) for p in pesos]
    # los baños se intercalan en posiciones fijas; la colación al cruzar ~12:30 hora local
    pos_banos = {max(1, (k + 1) * n // (banos + 1)) for k in range(banos)}
    mediodia = int(datetime.combine(datetime.fromtimestamp(login, TZ_CHILE).date(), time(12, 30),
                                    tzinfo=TZ_CHILE).timestamp()) + rnd.randint(0, 1800)
    filas, ep, colacion, k_bano = [], login + rnd.randint(1, 5), False, 0
    for i, con_llamada in enumerate(tipos):
        if not colacion and (ep >= mediodia or i == n - 1):
            filas.append(_ciclo(usuario, 3600 + rnd.randint(-120, 120), 0, 0, 0, 0, "", "COLACION", "", ep))
            ep += filas[-1]["pause_sec"]
            colacion = True
        if i in pos_banos:
            filas.append(_ciclo(usuario, duraciones_bano[k_bano], 0, 0, 0, 0, "", "BANO", "", ep))
            ep += duraciones_bano[k_bano]
            k_bano += 1
        conv, dispo = convs[i], dispos[i]
        talk_ep = ep + pausas[i] + esperas[i]
        uid = f"{talk_ep}.{nuevo_uid()}" if con_llamada else ""
        status = rnd.choices([s for s, _ in TIPIFICACIONES], [p for _, p in TIPIFICACIONES])[0] if con_llamada else ""
        fila = _ciclo(usuario, pausas[i], esperas[i], conv, dispo, rnd.randint(0, min(15, conv)), status, "", uid, ep)
        filas.append(fila)
        ep = fila["dispo_epoch"] + dispo
    return filas


def simular(*, semilla: int = 1, dia: date, usuarios: list[str], ingroups: list[str],
            llamadas_por_ingroup: int = 40, errores: bool = True) -> dict[str, list[dict[str, str]]]:
    """Devuelve {"vicidial_closer_log": [...], "vicidial_agent_log": [...], "vicidial_user_log": [...]}"""
    rnd = random.Random(semilla)
    base = int(datetime.combine(dia, time(9, 0), tzinfo=TZ_CHILE).timestamp())
    fin = int(datetime.combine(dia, time(18, 0), tzinfo=TZ_CHILE).timestamp())
    contador = iter(range(100, 10**7))
    nuevo_uid = lambda: next(contador)  # noqa: E731

    total = llamadas_por_ingroup * len(ingroups)
    n_afthrs = min(3, total)
    n_abandonos = round(total * 0.08)
    n_atendidas = max(0, total - n_abandonos - n_afthrs)

    user_log, agent_log, sesiones = [], [], {}
    for u in usuarios:
        login = base + rnd.randint(-600, 600)
        logout = fin + rnd.randint(-300, 300)
        sesiones[u] = (login, logout)
        for ev, ep in (("LOGIN", login), ("LOGOUT", logout)):
            user_log.append(dict(user=u, event=ev, campaign_id=CAMPANA, event_date=_hora_local(ep), event_epoch=ep))
    for i, u in enumerate(usuarios):
        n = n_atendidas // len(usuarios) + (1 if i < n_atendidas % len(usuarios) else 0)
        agent_log += _ciclos_agente(rnd, u, *sesiones[u], n, nuevo_uid)

    def cola():
        return rnd.randint(0, 20) if rnd.random() < 0.85 else rnd.randint(21, 120)

    def fila_closer(uid, ingroup, inicio, queue, status, user, term, largo):
        return dict(uniqueid=uid, campaign_id=ingroup, call_date=_hora_local(inicio), start_epoch=inicio,
                    end_epoch=inicio + largo, length_in_sec=largo, queue_seconds=queue, status=status,
                    user=user, term_reason=term)

    closer = []
    for c in agent_log:  # cada ciclo con conversación es una llamada atendida
        if c["talk_sec"] > 0:
            q = cola()
            closer.append(fila_closer(c["uniqueid"], rnd.choice(ingroups), c["talk_epoch"] - q, q, c["status"],
                                      c["user"], rnd.choice(("CALLER", "AGENT")), q + c["talk_sec"]))
    for _ in range(n_abandonos):
        ini, q = rnd.randint(base, fin), rnd.randint(5, 60) if rnd.random() < 0.9 else rnd.randint(61, 120)
        closer.append(fila_closer(f"{ini}.{nuevo_uid()}", rnd.choice(ingroups), ini, q, "DROP", "VDCL", "ABANDON", q))
    for _ in range(n_afthrs):  # fuera de horario: antes de las 09:00 o después de las 18:00
        ini = rnd.randint(base - 7200, base - 60) if rnd.random() < 0.5 else rnd.randint(fin + 60, fin + 7200)
        closer.append(fila_closer(f"{ini}.{nuevo_uid()}", rnd.choice(ingroups), ini, 0, "AFTHRS", "VDCL", "AFTHRS", 0))

    if errores:
        atendidas = [f for f in closer if f["user"] in sesiones]
        closer_extra, agent_extra = [], []
        rnd.choice(atendidas)["campaign_id"] = "INGROUP_DESCONOCIDO"  # caso 3
        ini = rnd.randint(base, fin)
        closer_extra.append(fila_closer(f"{ini}.{nuevo_uid()}", rnd.choice(ingroups), ini, 3, "NOINT", FANTASMA,
                                        "CALLER", 123))  # caso 4
        agent_extra.append(_ciclo(FANTASMA, 2, 30, 0, 0, 0, "", "", "", rnd.randint(base, fin - 3600)))  # caso 5
        real = rnd.choice(usuarios)
        ep = sesiones[real][1] + 60
        agent_extra.append(dict(user=real, campaign_id=CAMPANA, event_time=_hora_local(ep), pause_epoch=ep,
                                pause_sec=BASURA, wait_epoch=ep, wait_sec=0, talk_epoch=ep, talk_sec=0,
                                dispo_epoch=ep, dispo_sec=0, dead_sec=0, status="", sub_status="", uniqueid=""))  # 6
        agent_log += agent_extra
        user_log.append(dict(user=FANTASMA, event="LOGIN", campaign_id=CAMPANA,
                             event_date=_hora_local(base + 120), event_epoch=base + 120))  # caso 7
    else:
        closer_extra = []

    for filas, orden in ((user_log, "event_epoch"), (agent_log, "pause_epoch"), (closer, "start_epoch")):
        filas.sort(key=lambda f: f[orden])
    for i, f in enumerate(user_log, 1):
        f["user_log_id"] = i
    for i, f in enumerate(agent_log, 1):
        f["agent_log_id"] = i
    for i, f in enumerate(closer + closer_extra, 1000):
        f["closecallid"] = i
    closer += closer_extra
    if errores:
        closer.append(dict(rnd.choice(closer)))  # caso 1: duplicado idéntico
        ini = rnd.randint(base, fin)
        closer.append(dict(fila_closer(f"{ini}.{nuevo_uid()}", rnd.choice(ingroups), ini, 12, "DROP", "VDCL",
                                       "ABANDON", 12), start_epoch=0, closecallid=1000 + len(closer)))  # caso 2

    return {t: [{c: str(f[c]) for c in COLUMNAS[t]} for f in filas]
            for t, filas in (("vicidial_closer_log", closer), ("vicidial_agent_log", agent_log),
                             ("vicidial_user_log", user_log))}


def escribir_csv(datos: dict[str, list[dict[str, str]]], directorio: Path) -> None:
    """Escribe <tabla>.csv por cada tabla (cabecera = columnas listadas, en ese orden, utf-8)."""
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    for tabla, filas in datos.items():
        with open(directorio / f"{tabla}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS[tabla])
            w.writeheader()
            w.writerows(filas)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Simula tablas crudas de VICIdial (datos ficticios)")
    ap.add_argument("--dia", type=date.fromisoformat, required=True, help="YYYY-MM-DD")
    ap.add_argument("--directorio", type=Path, default=Path("vicidial_simulado"))
    ap.add_argument("--semilla", type=int, default=1)
    ap.add_argument("--sin-errores", action="store_true")
    a = ap.parse_args()
    datos = simular(semilla=a.semilla, dia=a.dia, usuarios=["and1001", "and1002", "and1003", "and1004"],
                    ingroups=["CAMP01", "CAMP02"], errores=not a.sin_errores)
    escribir_csv(datos, a.directorio)
    for t, filas in datos.items():
        print(f"{t}: {len(filas)} filas")
