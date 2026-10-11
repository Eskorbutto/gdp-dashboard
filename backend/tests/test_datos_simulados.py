"""Coherencia de los datos simulados de asistencia."""
from sqlalchemy import Engine, text

from tests.conftest import DatosPrueba


def _escalar(engine: Engine, sql: str):
    with engine.connect() as con:
        return con.execute(text(sql)).scalar()


def test_hay_turnos_y_eventos_para_ambos_clientes(engine_owner: Engine, datos: DatosPrueba):
    for tabla in ("turnos_planificados", "eventos_agente", "agentes"):
        assert _escalar(engine_owner, f"SELECT count(DISTINCT cliente_id) FROM {tabla}") == 2


def test_turnos_solo_en_dias_habiles_y_dentro_del_rango(engine_owner: Engine, datos: DatosPrueba):
    assert _escalar(engine_owner, "SELECT count(*) FROM turnos_planificados WHERE extract(isodow FROM fecha) > 5") == 0
    assert _escalar(engine_owner, f"SELECT min(fecha) FROM turnos_planificados") == datos.desde


def test_estados_del_agente_no_se_traslapan(engine_owner: Engine):
    traslapes = _escalar(
        engine_owner,
        """
        SELECT count(*) FROM (
            SELECT inicio, lag(fin) OVER (PARTITION BY agente_id ORDER BY inicio, fin) AS fin_anterior
            FROM eventos_agente WHERE fin IS NOT NULL
        ) x WHERE x.fin_anterior > x.inicio + interval '1 second'
        """,
    )
    assert traslapes == 0


def test_cada_login_tiene_su_logout(engine_owner: Engine):
    assert _escalar(
        engine_owner,
        "SELECT count(*) FILTER (WHERE tipo = 'login') - count(*) FILTER (WHERE tipo = 'logout') FROM eventos_agente",
    ) == 0


def test_ausencias_no_tienen_eventos(engine_owner: Engine):
    assert _escalar(
        engine_owner,
        """
        SELECT count(*) FROM eventos_agente e JOIN ausencias a
          ON a.cliente_id = e.cliente_id AND a.agente_id = e.agente_id
         AND (e.inicio AT TIME ZONE 'America/Santiago')::date BETWEEN a.fecha_desde AND a.fecha_hasta
        """,
    ) == 0


def test_incluye_atrasos_y_faltas_injustificadas(engine_owner: Engine):
    # Atraso: primer login más de 5 min después del inicio del turno.
    atrasos = _escalar(
        engine_owner,
        """
        SELECT count(*) FROM turnos_planificados t
        JOIN LATERAL (SELECT min(inicio) AS login FROM eventos_agente e
                      WHERE e.cliente_id = t.cliente_id AND e.agente_id = t.agente_id AND e.tipo = 'login'
                        AND e.inicio BETWEEN t.inicio - interval '1 hour' AND t.fin) l ON true
        WHERE l.login > t.inicio + interval '5 minutes'
        """,
    )
    # Falta injustificada: turno sin login y sin ausencia registrada.
    faltas = _escalar(
        engine_owner,
        """
        SELECT count(*) FROM turnos_planificados t
        WHERE NOT EXISTS (SELECT 1 FROM eventos_agente e WHERE e.cliente_id = t.cliente_id
                            AND e.agente_id = t.agente_id AND e.tipo = 'login'
                            AND e.inicio BETWEEN t.inicio - interval '1 hour' AND t.fin)
          AND NOT EXISTS (SELECT 1 FROM ausencias a WHERE a.cliente_id = t.cliente_id
                            AND a.agente_id = t.agente_id AND t.fecha BETWEEN a.fecha_desde AND a.fecha_hasta)
        """,
    )
    assert atrasos > 0
    assert faltas > 0
