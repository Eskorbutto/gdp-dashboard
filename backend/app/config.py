from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Rol de aplicación: sujeto a Row-Level Security.
    database_url: str = "postgresql+psycopg://cc_app:cc_app@localhost:5432/callcenter"
    # Rol dueño: solo para migraciones y datos simulados.
    database_url_owner: str = "postgresql+psycopg://cc_owner:cc_owner@localhost:5432/callcenter"
    app_db_role: str = "cc_app"
    secret_key: str = "solo-para-desarrollo-local"
    token_minutos: int = 480


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()
