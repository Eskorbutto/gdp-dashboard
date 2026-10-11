from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.config import obtener_configuracion
from app.modelos import Base

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    # Las migraciones corren con el rol dueño, nunca con el rol de aplicación.
    url = context.config.attributes.get("url") or obtener_configuracion().database_url_owner
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
