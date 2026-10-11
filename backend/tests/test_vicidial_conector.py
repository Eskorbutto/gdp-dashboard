"""Conector VICIdial de punta a punta contra la base de pruebas, con datos simulados."""
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app.ingesta.vicidial.conector import cargar, procesar
from app.ingesta.vicidial.lector import COLUMNAS, LectorCSV, LectorSQL
from app.ingesta.vicidial.transformar import Ventana
from scripts.simular_vicidial import TZ_CHILE, escribir_csv, simular
from tests.conftest import DatosPrueba

DIA = date(2026, 3, 10)  # fuera de la malla simulada, para no traslapar estados
DESDE = datetime(2026, 3, 10, tzinfo=TZ_CHILE)
HASTA = DESDE + timedelta(days=1)
USUARIOS = ["and1001", "and1002", "and1003", "and1004"]


@pytest.fixture(scope="module")
def directorio_csv(tmp_path_factory) -> Path:
    directorio = tmp_path_factory.mktemp("vicidial")
    escribir_csv(simular(semilla=7, dia=DIA, usuarios=USUARIOS, ingroups=["CAMP01", "CAMP02"]), directorio)
    return directorio


@pytest.fixture(scope="module", autouse=True)
def limpiar(engine_owner: Engine):
    yield
    with engine_owner.begin() as con:
        cargas = "SELECT id FROM cargas_ingesta WHERE conector = 'vicidial'"
        for tabla in ("llamadas", "eventos_agente", "registros_crudos"):
            con.execute(text(f"DELETE FROM {tabla} WHERE carga_id IN ({cargas})"))
        con.execute(text(f"DELETE FROM cargas_ingesta WHERE id IN ({cargas})"))


def _conteos(engine_owner: Engine, cliente_id: int) -> tuple[int, int]:
    with engine_owner.connect() as con:
        llamadas = con.execute(text("SELECT count(*) FROM llamadas WHERE cliente_id = :c"), {"c": cliente_id}).scalar()
        eventos = con.execute(
            text("SELECT count(*) FROM eventos_agente WHERE cliente_id = :c AND inicio >= :d AND inicio < :h"),
            {"c": cliente_id, "d": DESDE, "h": HASTA},
        ).scalar()
    return llamadas, eventos


def test_carga_registra_errores_esperados(directorio_csv: Path, datos: DatosPrueba, engine_owner: Engine):
    r = cargar(datos.cliente_a, LectorCSV(directorio_csv), DESDE, HASTA)
    assert r.estado == "con_errores"
    assert r.llamadas > 50 and r.eventos > 100
    assert {"duplicado en la carga", "fecha inválida", "servicio sin mapear", "agente sin mapear",
            "duración inválida en pause_sec"} <= set(r.problemas_por_motivo)
    assert _conteos(engine_owner, datos.cliente_a) == (r.llamadas, r.eventos)

    with engine_owner.connect() as con:
        crudos = con.execute(
            text("SELECT count(*) FROM registros_crudos WHERE carga_id = :c AND tipo_registro <> '_ventana'"),
            {"c": r.carga_id},
        ).scalar()
    assert crudos == r.leidos


def test_reprocesar_y_recargar_no_duplican(directorio_csv: Path, datos: DatosPrueba, engine_owner: Engine):
    primera = cargar(datos.cliente_a, LectorCSV(directorio_csv), DESDE, HASTA)
    antes = _conteos(engine_owner, datos.cliente_a)
    procesar(datos.cliente_a, primera.carga_id)
    assert _conteos(engine_owner, datos.cliente_a) == antes
    cargar(datos.cliente_a, LectorCSV(directorio_csv), DESDE, HASTA)
    assert _conteos(engine_owner, datos.cliente_a) == antes


def test_carga_de_un_cliente_no_toca_al_otro(directorio_csv: Path, datos: DatosPrueba, engine_owner: Engine):
    antes_b = _conteos(engine_owner, datos.cliente_b)
    cargar(datos.cliente_a, LectorCSV(directorio_csv), DESDE, HASTA)
    assert _conteos(engine_owner, datos.cliente_b) == antes_b


def test_mismo_codigo_de_origen_se_mapea_dentro_de_cada_cliente(tmp_path: Path, datos: DatosPrueba,
                                                                engine_owner: Engine):
    """Ambos clientes tienen un servicio CAMP01: cada carga debe usar el suyo."""
    escribir_csv(simular(semilla=3, dia=DIA, usuarios=["aus1001", "aus1002"], ingroups=["CAMP01"], errores=False),
                 tmp_path)
    r = cargar(datos.cliente_b, LectorCSV(tmp_path), DESDE, HASTA)
    assert r.estado == "ok"
    with engine_owner.connect() as con:
        cruzadas = con.execute(
            text("SELECT count(*) FROM llamadas l JOIN servicios s ON s.id = l.servicio_id "
                 "WHERE l.carga_id = :c AND s.cliente_id <> l.cliente_id"),
            {"c": r.carga_id},
        ).scalar()
    assert cruzadas == 0


def test_no_se_puede_procesar_la_carga_de_otro_cliente(directorio_csv: Path, datos: DatosPrueba):
    r = cargar(datos.cliente_a, LectorCSV(directorio_csv), DESDE, HASTA)
    with pytest.raises(LookupError):
        procesar(datos.cliente_b, r.carga_id)


class _LectorRoto:
    descripcion = "vicidial-sql"

    def leer(self, ventana):
        raise ConnectionError("mysql://usuario:CLAVE_SECRETA@vicidial/asterisk")


def test_origen_caido_queda_como_carga_fallida_sin_exponer_secretos(datos: DatosPrueba, engine_owner: Engine):
    r = cargar(datos.cliente_a, _LectorRoto(), DESDE, HASTA)
    assert r.estado == "fallida"
    with engine_owner.connect() as con:
        errores = con.execute(text("SELECT errores::text FROM cargas_ingesta WHERE id = :c"), {"c": r.carga_id}).scalar()
    assert "ConnectionError" in errores and "CLAVE_SECRETA" not in errores


def test_detalle_de_carga_visible_solo_para_su_cliente(directorio_csv: Path, datos: DatosPrueba,
                                                       cliente_http: TestClient, token):
    r = cargar(datos.cliente_a, LectorCSV(directorio_csv), DESDE, HASTA)
    tok_a = {"Authorization": f"Bearer {token('supervisor@andino.ejemplo.cl')}"}
    tok_b = {"Authorization": f"Bearer {token('supervisor@austral.ejemplo.cl')}"}
    detalle = cliente_http.get(f"/cargas/{r.carga_id}", headers=tok_a)
    assert detalle.status_code == 200
    assert detalle.json()["registros_con_error"] == r.con_error > 0
    assert any(e["motivo"] == "duplicado en la carga" for e in detalle.json()["errores"])
    assert cliente_http.get(f"/cargas/{r.carga_id}", headers=tok_b).status_code == 404


def test_lector_sql_filtra_por_ventana():
    """El lector SQL usa SQL estándar; se prueba con SQLite en memoria (VICIdial real es MySQL)."""
    engine = create_engine("sqlite://")
    with engine.begin() as con:
        for tabla, columnas in COLUMNAS.items():
            con.execute(text(f"CREATE TABLE {tabla} ({', '.join(columnas)})"))
        con.execute(text("INSERT INTO vicidial_user_log (user_log_id, user, event, event_epoch) "
                         "VALUES (1, 'and1001', 'LOGIN', 100), (2, 'and1001', 'LOGOUT', 200)"))
    datos = LectorSQL(engine).leer(Ventana(100, 200))
    assert [f["user_log_id"] for f in datos["vicidial_user_log"]] == ["1"]
    assert datos["vicidial_closer_log"] == [] and datos["vicidial_agent_log"] == []


def test_dia_grande_supera_un_lote(datos: DatosPrueba, engine_owner: Engine, tmp_path: Path, monkeypatch):
    """Más llamadas que FILAS_POR_LOTE: se cargan todas, en varios lotes."""
    monkeypatch.setattr("app.ingesta.vicidial.conector.FILAS_POR_LOTE", 7)
    escribir_csv(simular(semilla=5, dia=DIA, usuarios=USUARIOS, ingroups=["CAMP01"], llamadas_por_ingroup=30,
                         errores=False), tmp_path)
    r = cargar(datos.cliente_a, LectorCSV(tmp_path), DESDE, HASTA)
    assert r.estado == "ok" and r.llamadas > 7
    with engine_owner.connect() as con:
        n = con.execute(text("SELECT count(*) FROM llamadas WHERE carga_id = :c"), {"c": r.carga_id}).scalar()
    assert n == r.llamadas
