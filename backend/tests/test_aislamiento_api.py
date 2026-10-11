"""Aislamiento a través de la API: el cliente sale del token, nunca de un parámetro."""
import base64
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.conftest import DatosPrueba, ids_por_cliente

GERENTE_A = "gerente@andino.ejemplo.cl"
GERENTE_B = "gerente@austral.ejemplo.cl"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_correcto_e_incorrecto(cliente_http: TestClient, token):
    assert token(GERENTE_A)
    for email, password in ((GERENTE_A, "mala"), ("nadie@ejemplo.cl", "demo1234")):
        r = cliente_http.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 401


def test_yo_devuelve_el_cliente_del_token(cliente_http: TestClient, token, datos: DatosPrueba):
    r = cliente_http.get("/auth/yo", headers=_h(token(GERENTE_B)))
    assert r.status_code == 200
    assert r.json()["cliente_id"] == datos.cliente_b
    assert r.json()["cliente_nombre"] == "Fono Austral Ltda"


@pytest.mark.parametrize(
    "ruta,tabla",
    [
        ("/servicios", "servicios"),
        ("/agentes", "agentes"),
        ("/turnos?desde=2026-03-01&hasta=2026-03-31", "turnos_planificados"),
        ("/cargas", "cargas_ingesta"),
        ("/usuarios", "usuarios"),
    ],
)
def test_listados_solo_devuelven_datos_propios(cliente_http: TestClient, token, engine_owner: Engine,
                                               datos: DatosPrueba, ruta: str, tabla: str):
    for email, propio in ((GERENTE_A, datos.cliente_a), (GERENTE_B, datos.cliente_b)):
        r = cliente_http.get(ruta, headers=_h(token(email)))
        assert r.status_code == 200, r.text
        ids = {fila["id"] for fila in r.json()}
        assert ids, f"{ruta} vino vacío"
        assert ids <= ids_por_cliente(engine_owner, tabla, propio)


def test_parametro_cliente_id_es_ignorado(cliente_http: TestClient, token, engine_owner: Engine,
                                          datos: DatosPrueba):
    r = cliente_http.get(f"/agentes?cliente_id={datos.cliente_b}", headers=_h(token(GERENTE_A)))
    ids = {a["id"] for a in r.json()}
    assert ids == ids_por_cliente(engine_owner, "agentes", datos.cliente_a)


def test_agente_de_otro_cliente_da_404(cliente_http: TestClient, token, engine_owner: Engine, datos: DatosPrueba):
    tok = token(GERENTE_A)
    for agente_b in ids_por_cliente(engine_owner, "agentes", datos.cliente_b):
        assert cliente_http.get(f"/agentes/{agente_b}", headers=_h(tok)).status_code == 404
    agente_a = min(ids_por_cliente(engine_owner, "agentes", datos.cliente_a))
    assert cliente_http.get(f"/agentes/{agente_a}", headers=_h(tok)).status_code == 200


def test_filtro_por_servicio_de_otro_cliente_devuelve_vacio(cliente_http: TestClient, token, engine_owner: Engine,
                                                            datos: DatosPrueba):
    servicio_b = min(ids_por_cliente(engine_owner, "servicios", datos.cliente_b))
    tok = token(GERENTE_A)
    assert cliente_http.get(f"/agentes?servicio_id={servicio_b}", headers=_h(tok)).json() == []
    r = cliente_http.get(f"/turnos?desde=2026-03-01&hasta=2026-03-31&servicio_id={servicio_b}", headers=_h(tok))
    assert r.json() == []


def test_sin_token_o_token_invalido_da_401(cliente_http: TestClient):
    assert cliente_http.get("/servicios").status_code == 401
    assert cliente_http.get("/servicios", headers=_h("basura")).status_code == 401


def test_token_adulterado_para_otro_cliente_da_401(cliente_http: TestClient, token, datos: DatosPrueba):
    cuerpo, firma = token(GERENTE_A).split(".")
    datos_token = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    datos_token["c"] = datos.cliente_b
    cuerpo_falso = base64.urlsafe_b64encode(json.dumps(datos_token).encode()).rstrip(b"=").decode()
    assert cliente_http.get("/servicios", headers=_h(f"{cuerpo_falso}.{firma}")).status_code == 401


def test_usuario_desactivado_pierde_acceso(cliente_http: TestClient, token, engine_owner: Engine):
    email = "supervisor@austral.ejemplo.cl"
    tok = token(email)
    assert cliente_http.get("/servicios", headers=_h(tok)).status_code == 200
    with engine_owner.begin() as con:
        con.execute(text("UPDATE usuarios SET activo = false WHERE email = :e"), {"e": email})
    try:
        assert cliente_http.get("/servicios", headers=_h(tok)).status_code == 401
        r = cliente_http.post("/auth/login", json={"email": email, "password": "demo1234"})
        assert r.status_code == 401
    finally:
        with engine_owner.begin() as con:
            con.execute(text("UPDATE usuarios SET activo = true WHERE email = :e"), {"e": email})


@pytest.mark.parametrize("email", ["supervisor@andino.ejemplo.cl", "cliente_lectura@andino.ejemplo.cl"])
def test_usuarios_requiere_rol_gerente(cliente_http: TestClient, token, email: str):
    assert cliente_http.get("/usuarios", headers=_h(token(email))).status_code == 403
