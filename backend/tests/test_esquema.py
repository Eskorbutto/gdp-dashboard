"""Guardas del esquema: fallan si una tabla nueva queda sin aislamiento."""
from sqlalchemy import Engine, text

from app.config import obtener_configuracion


def test_toda_tabla_tiene_cliente_id_y_rls(engine_owner: Engine):
    with engine_owner.connect() as con:
        tablas = con.execute(
            text(
                """
                SELECT c.relname AS tabla,
                       c.relrowsecurity AS rls,
                       EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) AS tiene_politica,
                       EXISTS (SELECT 1 FROM information_schema.columns k
                               WHERE k.table_schema = 'public' AND k.table_name = c.relname
                                 AND k.column_name = 'cliente_id') AS tiene_cliente_id
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version'
                """
            )
        ).all()
    assert len(tablas) >= 13
    for t in tablas:
        assert t.tabla == "clientes" or t.tiene_cliente_id, f"{t.tabla} no tiene cliente_id"
        assert t.rls, f"{t.tabla} no tiene Row-Level Security activo"
        assert t.tiene_politica, f"{t.tabla} no tiene política de aislamiento"


def test_rol_app_no_puede_saltarse_rls(engine_owner: Engine):
    rol = obtener_configuracion().app_db_role
    with engine_owner.connect() as con:
        r = con.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :r"), {"r": rol}
        ).one()
        tablas_propias = con.execute(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = :r"), {"r": rol}
        ).scalar()
    assert not r.rolsuper
    assert not r.rolbypassrls
    # Si el rol app fuera dueño de alguna tabla, RLS no le aplicaría.
    assert tablas_propias == 0
