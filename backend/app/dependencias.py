from collections.abc import Callable, Iterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import sesion_cliente
from app.seguridad import UsuarioSesion, leer_token

_bearer = HTTPBearer(auto_error=False)
_NO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="No autenticado",
    headers={"WWW-Authenticate": "Bearer"},
)


def _usuario_del_token(credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> UsuarioSesion:
    if credenciales is None:
        raise _NO_AUTENTICADO
    usuario = leer_token(credenciales.credentials)
    if usuario is None:
        raise _NO_AUTENTICADO
    return usuario


def sesion_bd(usuario: UsuarioSesion = Depends(_usuario_del_token)) -> Iterator[Session]:
    """Sesión de base de datos acotada al cliente del usuario autenticado."""
    with sesion_cliente(usuario.cliente_id) as sesion:
        # Revalida que el usuario siga activo (ya filtrado por RLS a su cliente).
        activo = sesion.execute(
            text(
                "SELECT u.activo AND c.activo FROM usuarios u JOIN clientes c ON c.id = u.cliente_id "
                "WHERE u.id = :id"
            ),
            {"id": usuario.usuario_id},
        ).scalar()
        if not activo:
            raise _NO_AUTENTICADO
        yield sesion


def usuario_actual(usuario: UsuarioSesion = Depends(_usuario_del_token), _: Session = Depends(sesion_bd)) -> UsuarioSesion:
    return usuario


def requerir_rol(*roles: str) -> Callable[[UsuarioSesion], UsuarioSesion]:
    def _verificar(usuario: UsuarioSesion = Depends(usuario_actual)) -> UsuarioSesion:
        if usuario.rol not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permiso")
        return usuario

    return _verificar
