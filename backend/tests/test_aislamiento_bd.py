"""Aislamiento a nivel de base de datos, con el rol de aplicación (sin pasar por la API)."""
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.conftest import DatosPrueba, ids_por_cliente

TABLAS = (
    "usuarios", "servicios", "agentes", "cargas_ingesta", "registros_crudos", "llamadas",
    "eventos_agente", "turnos_planificados", "ausencias", "evaluaciones_calidad",
    "metas_indicador", "resumen_intervalo_servicio",
)
TABLAS_CON_DATOS = ("usuarios", "servicios", "agentes", "cargas_ingesta", "registros_crudos",
                    "eventos_agente", "turnos_planificados", "ausencias", "metas_indicador")


def _fijar_cliente(con, cliente_id: int) -> None:
    con.execute(text("SELECT set_config('app.cliente_id', :c, true)"), {"c": str(cliente_id)})


@pytest.mark.parametrize("tabla", TABLAS + ("clientes",))
def test_sin_cliente_en_sesion_no_ve_nada(engine_app: Engine, tabla: str):
    with engine_app.begin() as con:
        assert con.execute(text(f"SELECT count(*) FROM {tabla}")).scalar() == 0


@pytest.mark.parametrize("tabla", TABLAS)
def test_cada_cliente_ve_solo_lo_suyo(engine_app: Engine, datos: DatosPrueba, tabla: str):
    for propio, ajeno in ((datos.cliente_a, datos.cliente_b), (datos.cliente_b, datos.cliente_a)):
        with engine_app.begin() as con:
            _fijar_cliente(con, propio)
            clientes_vistos = set(con.execute(text(f"SELECT DISTINCT cliente_id FROM {tabla}")).scalars())
            ajenos = con.execute(text(f"SELECT count(*) FROM {tabla} WHERE cliente_id = :c"), {"c": ajeno}).scalar()
        assert ajenos == 0
        if tabla in TABLAS_CON_DATOS:
            assert clientes_vistos == {propio}
        else:
            assert clientes_vistos <= {propio}


def test_clientes_solo_ve_su_propia_fila(engine_app: Engine, datos: DatosPrueba):
    with engine_app.begin() as con:
        _fijar_cliente(con, datos.cliente_a)
        assert list(con.execute(text("SELECT id FROM clientes")).scalars()) == [datos.cliente_a]


def test_no_puede_insertar_datos_en_otro_cliente(engine_app: Engine, datos: DatosPrueba):
    with pytest.raises(DBAPIError, match="row-level security"):
        with engine_app.begin() as con:
            _fijar_cliente(con, datos.cliente_a)
            con.execute(
                text("INSERT INTO servicios (cliente_id, nombre) VALUES (:c, 'Intruso')"), {"c": datos.cliente_b}
            )


def test_no_puede_modificar_ni_borrar_datos_de_otro_cliente(engine_app: Engine, engine_owner: Engine,
                                                            datos: DatosPrueba):
    ids_b = ids_por_cliente(engine_owner, "agentes", datos.cliente_b)
    with engine_app.connect() as con:
        with con.begin() as trx:
            _fijar_cliente(con, datos.cliente_a)
            actualizados = con.execute(
                text("UPDATE agentes SET nombre = 'x' WHERE id = ANY(:ids)"), {"ids": list(ids_b)}
            ).rowcount
            borrados = con.execute(text("DELETE FROM ausencias WHERE cliente_id = :c"), {"c": datos.cliente_b}).rowcount
            trx.rollback()
    assert actualizados == 0
    assert borrados == 0


def test_no_puede_mover_un_registro_a_otro_cliente(engine_app: Engine, datos: DatosPrueba):
    with pytest.raises(DBAPIError, match="row-level security"):
        with engine_app.begin() as con:
            _fijar_cliente(con, datos.cliente_a)
            con.execute(text("UPDATE metas_indicador SET cliente_id = :b"), {"b": datos.cliente_b})


def test_rol_app_no_puede_crear_clientes(engine_app: Engine, datos: DatosPrueba):
    with pytest.raises(DBAPIError, match="permission denied"):
        with engine_app.begin() as con:
            _fijar_cliente(con, datos.cliente_a)
            con.execute(text("INSERT INTO clientes (nombre) VALUES ('Nuevo')"))


def test_cliente_de_sesion_no_se_filtra_entre_transacciones(engine_app: Engine, datos: DatosPrueba):
    """Con pool de conexiones, el cliente fijado no debe sobrevivir al fin de la transacción."""
    with engine_app.connect() as con:
        with con.begin():
            _fijar_cliente(con, datos.cliente_a)
            assert con.execute(text("SELECT count(*) FROM agentes")).scalar() > 0
        with con.begin():
            assert con.execute(text("SELECT count(*) FROM agentes")).scalar() == 0


def test_fk_compuesta_impide_referencias_cruzadas(engine_owner: Engine, datos: DatosPrueba):
    """Aun con el rol dueño (que no pasa por RLS), un turno de A no puede apuntar a un agente de B."""
    agente_b = min(ids_por_cliente(engine_owner, "agentes", datos.cliente_b))
    servicio_a = min(ids_por_cliente(engine_owner, "servicios", datos.cliente_a))
    with pytest.raises(IntegrityError):
        with engine_owner.begin() as con:
            con.execute(
                text(
                    "INSERT INTO turnos_planificados (cliente_id, agente_id, servicio_id, fecha, inicio, fin) "
                    "VALUES (:c, :ag, :sv, '2026-03-02', '2026-03-02 08:00-03', '2026-03-02 17:00-03')"
                ),
                {"c": datos.cliente_a, "ag": agente_b, "sv": servicio_a},
            )


def test_login_solo_devuelve_el_usuario_consultado(engine_app: Engine):
    with engine_app.begin() as con:
        filas = con.execute(
            text("SELECT * FROM fn_login_buscar_usuario('GERENTE@andino.ejemplo.cl')")
        ).all()
        vacio = con.execute(text("SELECT count(*) FROM fn_login_buscar_usuario('%')")).scalar()
    assert len(filas) == 1 and filas[0].rol == "gerente"
    assert vacio == 0
