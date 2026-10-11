"""Contraseñas y tokens de sesión (solo biblioteca estándar).

El token lleva usuario_id, cliente_id y rol, firmado con HMAC-SHA256. El
cliente_id de cada consulta sale de aquí, nunca de un parámetro del usuario.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from app.config import obtener_configuracion

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hashear_password(password: str) -> str:
    sal = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=sal, **_SCRYPT)
    return f"scrypt${sal.hex()}${digest.hex()}"


def verificar_password(password: str, password_hash: str) -> bool:
    try:
        esquema, sal_hex, digest_hex = password_hash.split("$")
    except ValueError:
        return False
    if esquema != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(sal_hex), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


@dataclass(frozen=True)
class UsuarioSesion:
    usuario_id: int
    cliente_id: int
    rol: str


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _desde_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _firma(cuerpo: str) -> str:
    clave = obtener_configuracion().secret_key.encode()
    return _b64(hmac.new(clave, cuerpo.encode(), hashlib.sha256).digest())


def emitir_token(usuario: UsuarioSesion) -> str:
    expira = int(time.time()) + obtener_configuracion().token_minutos * 60
    datos = {"u": usuario.usuario_id, "c": usuario.cliente_id, "r": usuario.rol, "exp": expira}
    cuerpo = _b64(json.dumps(datos, separators=(",", ":")).encode())
    return f"{cuerpo}.{_firma(cuerpo)}"


def leer_token(token: str) -> UsuarioSesion | None:
    try:
        cuerpo, firma = token.split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(firma, _firma(cuerpo)):
        return None
    try:
        datos = json.loads(_desde_b64(cuerpo))
        if datos["exp"] < time.time():
            return None
        return UsuarioSesion(usuario_id=int(datos["u"]), cliente_id=int(datos["c"]), rol=str(datos["r"]))
    except (ValueError, KeyError, TypeError):
        return None
