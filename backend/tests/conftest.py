"""Base de pruebas: PostgreSQL local (callcenter_test) con datos simulados.

Se recrea el esquema con las migraciones y se cargan datos de dos clientes.
URLs configurables con TEST_DATABASE_URL (rol app) y TEST_DATABASE_URL_OWNER.
"""
import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://cc_app:cc_app@localhost:5432/callcenter_test"
)
os.environ["DATABASE_URL_OWNER"] = os.environ.get(
    "TEST_DATABASE_URL_OWNER", "postgresql+psycopg://cc_owner:cc_owner@localhost:5432/callcenter_test"
)
os.environ["SECRET_KEY"] = "clave-de-pruebas"

from dataclasses import dataclass  # noqa: E402
from datetime import date  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import obtener_configuracion  # noqa: E402
from app.main import app  # noqa: E402
from scripts.generar_datos_simulados import PASSWORD_DEMO, generar  # noqa: E402

DIR_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class DatosPrueba:
    cliente_a: int
    cliente_b: int
    desde: date
    hasta: date


@pytest.fixture(scope="session")
def engine_owner() -> Engine:
    engine = create_engine(obtener_configuracion().database_url_owner)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def engine_app() -> Engine:
    engine = create_engine(obtener_configuracion().database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def datos(engine_owner: Engine) -> DatosPrueba:
    cfg = Config(os.path.join(DIR_BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(DIR_BACKEND, "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    desde = date(2026, 3, 2)  # lunes
    with Session(engine_owner) as sesion, sesion.begin():
        resumen = generar(sesion, semilla=1, desde=desde, dias=7, agentes_por_servicio=4)
    a, b = resumen.clientes.values()
    return DatosPrueba(cliente_a=a, cliente_b=b, desde=desde, hasta=date(2026, 3, 8))


@pytest.fixture
def cliente_http() -> TestClient:
    return TestClient(app)


@pytest.fixture
def token(cliente_http: TestClient):
    def _token(email: str, password: str = PASSWORD_DEMO) -> str:
        r = cliente_http.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    return _token


def ids_por_cliente(engine_owner: Engine, tabla: str, cliente_id: int) -> set[int]:
    with engine_owner.connect() as con:
        return set(con.execute(text(f"SELECT id FROM {tabla} WHERE cliente_id = :c"), {"c": cliente_id}).scalars())
