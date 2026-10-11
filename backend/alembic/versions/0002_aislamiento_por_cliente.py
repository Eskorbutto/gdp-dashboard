"""Aislamiento por cliente: Row-Level Security, permisos del rol de aplicación y login.

Cómo funciona:
- Cada tabla tiene RLS activo con una política que compara su cliente_id con
  `app.cliente_id`, que la aplicación fija en cada transacción desde la sesión.
- Si `app.cliente_id` no está fijado, la política no deja ver ni escribir filas.
- La aplicación se conecta con un rol sin privilegios (APP_DB_ROLE): no es dueño
  de las tablas ni tiene BYPASSRLS, por lo que la política siempre le aplica.
- El login necesita buscar un usuario antes de conocer su cliente; para eso existe
  una única función SECURITY DEFINER que solo devuelve los datos de ese correo.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-11
"""
import re
from collections.abc import Sequence

from alembic import op

from app.config import obtener_configuracion

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Lista congelada a la fecha de esta migración (tabla, columna que identifica al cliente).
# Tablas nuevas deben activar RLS en su propia migración; tests/test_esquema.py lo exige.
TABLAS = (
    ("clientes", "id"),
    ("usuarios", "cliente_id"),
    ("servicios", "cliente_id"),
    ("agentes", "cliente_id"),
    ("cargas_ingesta", "cliente_id"),
    ("registros_crudos", "cliente_id"),
    ("llamadas", "cliente_id"),
    ("eventos_agente", "cliente_id"),
    ("turnos_planificados", "cliente_id"),
    ("ausencias", "cliente_id"),
    ("evaluaciones_calidad", "cliente_id"),
    ("metas_indicador", "cliente_id"),
    ("resumen_intervalo_servicio", "cliente_id"),
)

CLIENTE_DE_LA_SESION = "NULLIF(current_setting('app.cliente_id', true), '')::integer"


def _rol_app() -> str:
    rol = obtener_configuracion().app_db_role
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", rol):
        raise ValueError(f"APP_DB_ROLE inválido: {rol!r}")
    return rol


def upgrade() -> None:
    rol = _rol_app()
    op.execute(f"GRANT USAGE ON SCHEMA public TO {rol}")

    for tabla, columna in TABLAS:
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY aislamiento_cliente ON {tabla} "
            f"USING ({columna} = {CLIENTE_DE_LA_SESION}) "
            f"WITH CHECK ({columna} = {CLIENTE_DE_LA_SESION})"
        )
        # La aplicación no crea ni modifica clientes: eso es tarea de la plataforma.
        permisos = "SELECT" if tabla == "clientes" else "SELECT, INSERT, UPDATE, DELETE"
        op.execute(f"GRANT {permisos} ON {tabla} TO {rol}")

    op.execute(
        """
        CREATE FUNCTION fn_login_buscar_usuario(p_email text)
        RETURNS TABLE (usuario_id integer, cliente_id integer, rol varchar, password_hash varchar, activo boolean)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT u.id, u.cliente_id, u.rol, u.password_hash, (u.activo AND c.activo)
            FROM public.usuarios u
            JOIN public.clientes c ON c.id = u.cliente_id
            WHERE u.email = lower(p_email)
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION fn_login_buscar_usuario(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION fn_login_buscar_usuario(text) TO {rol}")


def downgrade() -> None:
    rol = _rol_app()
    op.execute("DROP FUNCTION fn_login_buscar_usuario(text)")
    for tabla, _ in reversed(TABLAS):
        op.execute(f"REVOKE ALL ON {tabla} FROM {rol}")
        op.execute(f"DROP POLICY aislamiento_cliente ON {tabla}")
        op.execute(f"ALTER TABLE {tabla} DISABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {rol}")
