from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import sesion_sin_cliente
from app.dependencias import sesion_bd, usuario_actual
from app.esquemas import Login, Token, Yo
from app.modelos import Cliente, Usuario
from app.seguridad import UsuarioSesion, emitir_token, verificar_password

router = APIRouter(prefix="/auth", tags=["autenticación"])


@router.post("/login", response_model=Token)
def login(datos: Login) -> Token:
    with sesion_sin_cliente() as sesion:
        fila = sesion.execute(
            text("SELECT usuario_id, cliente_id, rol, password_hash, activo FROM fn_login_buscar_usuario(:email)"),
            {"email": datos.email},
        ).first()
    if fila is None or not fila.activo or not verificar_password(datos.password, fila.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    usuario = UsuarioSesion(usuario_id=fila.usuario_id, cliente_id=fila.cliente_id, rol=fila.rol)
    return Token(access_token=emitir_token(usuario))


@router.get("/yo", response_model=Yo)
def yo(usuario: UsuarioSesion = Depends(usuario_actual), sesion: Session = Depends(sesion_bd)) -> Yo:
    u, nombre_cliente = sesion.execute(
        select(Usuario, Cliente.nombre)
        .join(Cliente, Cliente.id == Usuario.cliente_id)
        .where(Usuario.id == usuario.usuario_id, Usuario.cliente_id == usuario.cliente_id)
    ).one()
    return Yo(id=u.id, cliente_id=u.cliente_id, cliente_nombre=nombre_cliente, nombre=u.nombre, email=u.email, rol=u.rol)
