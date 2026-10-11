"""Transformación VICIdial -> modelo estándar con casos conocidos (sin base de datos)."""
from datetime import UTC, datetime

from app.ingesta.vicidial.transformar import (
    Ventana,
    acw_por_uniqueid,
    transformar_estados,
    transformar_llamadas,
    transformar_sesiones,
)

T0 = 1772456400  # 2026-03-02 13:00:00 UTC (10:00 en Chile)
VENTANA = Ventana(T0 - 3600, T0 + 8 * 3600)
SERVICIOS = {"SOPORTE": 10}
AGENTES = {"and1001": 100}


def _closer(**cambios) -> dict[str, str]:
    fila = {"closecallid": "1", "uniqueid": f"{T0}.1", "campaign_id": "SOPORTE", "start_epoch": str(T0),
            "length_in_sec": "200", "queue_seconds": "15", "status": "VENTA", "user": "and1001"}
    return {**fila, **cambios}


def _llamadas(*filas, acw=None):
    return transformar_llamadas(filas, servicios=SERVICIOS, agentes=AGENTES, acw=acw or {}, ventana=VENTANA)


def test_llamada_atendida():
    r = _llamadas(_closer(), acw={f"{T0}.1": 30})
    assert r.problemas == []
    assert r.filas == [{
        "servicio_id": 10, "agente_id": 100, "id_origen": "vicidial:closer:1", "cola": "SOPORTE",
        "inicio": datetime(2026, 3, 2, 13, 0, tzinfo=UTC), "espera_seg": 15, "conversacion_seg": 185,
        "acw_seg": 30, "resultado": "atendida", "tipificacion": "VENTA",
    }]


def test_llamada_abandonada_no_tiene_conversacion_ni_agente():
    (fila,) = _llamadas(_closer(user="VDCL", status="DROP", length_in_sec="40", queue_seconds="40")).filas
    assert (fila["resultado"], fila["agente_id"], fila["espera_seg"], fila["conversacion_seg"]) == ("abandonada", None, 40, 0)


def test_fuera_de_horario_se_descarta_sin_error():
    r = _llamadas(_closer(user="VDCL", status="AFTHRS"))
    assert (r.filas, r.problemas, r.descartadas) == ([], [], 1)


def test_duplicado_en_la_carga():
    r = _llamadas(_closer(), _closer())
    assert len(r.filas) == 1
    assert [p.motivo for p in r.problemas] == ["duplicado en la carga"]


def test_fecha_invalida_es_error_y_fuera_de_ventana_es_advertencia():
    r = _llamadas(_closer(closecallid="1", start_epoch="0"), _closer(closecallid="2", start_epoch=str(T0 + 9 * 3600)),
                  _closer(closecallid="3", start_epoch="abc"))
    assert r.filas == []
    assert [(p.id_origen, p.motivo, p.severidad) for p in r.problemas] == [
        ("1", "fecha inválida", "error"),
        ("2", "fuera del rango de la carga", "advertencia"),
        ("3", "fecha inválida", "error"),
    ]


def test_servicio_sin_mapear_es_error():
    r = _llamadas(_closer(campaign_id="OTRO"))
    assert r.filas == [] and r.problemas[0].motivo == "servicio sin mapear: OTRO"


def test_agente_sin_mapear_carga_la_llamada_sin_agente():
    r = _llamadas(_closer(user="nuevo01"))
    assert r.filas[0]["agente_id"] is None and r.filas[0]["resultado"] == "atendida"
    assert r.problemas[0].severidad == "advertencia"


def test_tiempos_negativos_o_basura_son_error():
    r = _llamadas(_closer(closecallid="1", queue_seconds="-5"), _closer(closecallid="2", length_in_sec="4294967295"))
    assert r.filas == [] and {p.motivo for p in r.problemas} == {"tiempos inválidos"}


def test_conversacion_nunca_negativa():
    (fila,) = _llamadas(_closer(length_in_sec="10", queue_seconds="12")).filas
    assert fila["conversacion_seg"] == 0


def _ciclo(**cambios) -> dict[str, str]:
    fila = {"agent_log_id": "1", "user": "and1001", "pause_epoch": str(T0), "pause_sec": "120",
            "wait_epoch": str(T0 + 120), "wait_sec": "30", "talk_epoch": str(T0 + 150), "talk_sec": "200",
            "dispo_epoch": str(T0 + 350), "dispo_sec": "25", "dead_sec": "5", "sub_status": "BANO",
            "uniqueid": f"{T0}.1"}
    return {**fila, **cambios}


def test_ciclo_de_agente_genera_cuatro_estados_encadenados():
    r = transformar_estados([_ciclo()], agentes=AGENTES, ventana=VENTANA)
    assert r.problemas == []
    tramos = [(f["tipo"], f["motivo"], int(f["inicio"].timestamp()) - T0, int(f["fin"].timestamp()) - T0) for f in r.filas]
    assert tramos == [("pausa", "BANO", 0, 120), ("disponible", None, 120, 150), ("en_llamada", None, 150, 350),
                      ("acw", None, 350, 375)]


def test_segmentos_en_cero_se_omiten():
    r = transformar_estados([_ciclo(pause_sec="0", talk_sec="0", dispo_sec="0")], agentes=AGENTES, ventana=VENTANA)
    assert [f["tipo"] for f in r.filas] == ["disponible"]


def test_duracion_basura_descarta_solo_ese_segmento():
    r = transformar_estados([_ciclo(pause_sec="4294967295")], agentes=AGENTES, ventana=VENTANA)
    assert [f["tipo"] for f in r.filas] == ["disponible", "en_llamada", "acw"]
    assert r.problemas[0].motivo == "duración inválida en pause_sec: 4294967295"


def test_estado_de_agente_sin_mapear_es_error():
    r = transformar_estados([_ciclo(user="agente_fantasma")], agentes=AGENTES, ventana=VENTANA)
    assert r.filas == [] and r.problemas[0].motivo == "agente sin mapear: agente_fantasma"


def test_acw_por_uniqueid_ignora_ciclos_sin_llamada_y_basura():
    acw = acw_por_uniqueid([_ciclo(), _ciclo(uniqueid="", dispo_sec="9"), _ciclo(uniqueid="x", dispo_sec="-1")])
    assert acw == {f"{T0}.1": 25}


def test_sesiones_login_logout():
    filas = [
        {"user_log_id": "1", "user": "and1001", "event": "LOGIN", "event_epoch": str(T0)},
        {"user_log_id": "2", "user": "and1001", "event": "TIMEOUTLOGOUT", "event_epoch": str(T0 + 3600)},
        {"user_log_id": "3", "user": "and1001", "event": "OTRO", "event_epoch": str(T0)},
        {"user_log_id": "4", "user": "agente_fantasma", "event": "LOGIN", "event_epoch": str(T0)},
    ]
    r = transformar_sesiones(filas, agentes=AGENTES, ventana=VENTANA)
    assert [(f["tipo"], f["fin"]) for f in r.filas] == [("login", None), ("logout", None)]
    assert r.descartadas == 1
    assert [p.id_origen for p in r.problemas] == ["4"]
