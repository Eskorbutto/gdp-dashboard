"""Consultas básicas del cliente autenticado.

Cada consulta filtra explícitamente por el cliente_id de la sesión, además de
la política RLS de la base (doble barrera).
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencias import requerir_rol, sesion_bd, usuario_actual
from app.esquemas import AgenteSalida, CargaDetalle, CargaSalida, ServicioSalida, TurnoSalida, UsuarioSalida
from app.modelos import Agente, CargaIngesta, Servicio, TurnoPlanificado, Usuario
from app.seguridad import UsuarioSesion

router = APIRouter()


@router.get("/servicios", response_model=list[ServicioSalida], tags=["catálogo"])
def listar_servicios(
    usuario: UsuarioSesion = Depends(usuario_actual), sesion: Session = Depends(sesion_bd)
) -> list[Servicio]:
    consulta = select(Servicio).where(Servicio.cliente_id == usuario.cliente_id).order_by(Servicio.nombre)
    return list(sesion.scalars(consulta))


@router.get("/agentes", response_model=list[AgenteSalida], tags=["catálogo"])
def listar_agentes(
    servicio_id: int | None = None,
    usuario: UsuarioSesion = Depends(usuario_actual),
    sesion: Session = Depends(sesion_bd),
) -> list[Agente]:
    consulta = select(Agente).where(Agente.cliente_id == usuario.cliente_id).order_by(Agente.nombre)
    if servicio_id is not None:
        consulta = consulta.where(Agente.servicio_id == servicio_id)
    return list(sesion.scalars(consulta))


@router.get("/agentes/{agente_id}", response_model=AgenteSalida, tags=["catálogo"])
def obtener_agente(
    agente_id: int, usuario: UsuarioSesion = Depends(usuario_actual), sesion: Session = Depends(sesion_bd)
) -> Agente:
    agente = sesion.scalar(select(Agente).where(Agente.id == agente_id, Agente.cliente_id == usuario.cliente_id))
    if agente is None:
        # 404 (no 403) para no revelar que el id existe en otro cliente.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    return agente


@router.get("/turnos", response_model=list[TurnoSalida], tags=["asistencia"])
def listar_turnos(
    desde: date,
    hasta: date,
    servicio_id: int | None = None,
    agente_id: int | None = None,
    limite: int = Query(default=1000, le=5000),
    usuario: UsuarioSesion = Depends(usuario_actual),
    sesion: Session = Depends(sesion_bd),
) -> list[TurnoPlanificado]:
    if hasta < desde:
        raise HTTPException(status_code=422, detail="'hasta' debe ser igual o posterior a 'desde'")
    consulta = (
        select(TurnoPlanificado)
        .where(
            TurnoPlanificado.cliente_id == usuario.cliente_id,
            TurnoPlanificado.fecha.between(desde, hasta),
        )
        .order_by(TurnoPlanificado.inicio, TurnoPlanificado.agente_id)
        .limit(limite)
    )
    if servicio_id is not None:
        consulta = consulta.where(TurnoPlanificado.servicio_id == servicio_id)
    if agente_id is not None:
        consulta = consulta.where(TurnoPlanificado.agente_id == agente_id)
    return list(sesion.scalars(consulta))


@router.get("/cargas", response_model=list[CargaSalida], tags=["ingesta"])
def listar_cargas(
    usuario: UsuarioSesion = Depends(usuario_actual), sesion: Session = Depends(sesion_bd)
) -> list[CargaIngesta]:
    consulta = (
        select(CargaIngesta)
        .where(CargaIngesta.cliente_id == usuario.cliente_id)
        .order_by(CargaIngesta.iniciada_en.desc())
        .limit(200)
    )
    return list(sesion.scalars(consulta))


@router.get("/cargas/{carga_id}", response_model=CargaDetalle, tags=["ingesta"])
def obtener_carga(
    carga_id: int, usuario: UsuarioSesion = Depends(usuario_actual), sesion: Session = Depends(sesion_bd)
) -> CargaIngesta:
    carga = sesion.scalar(
        select(CargaIngesta).where(CargaIngesta.id == carga_id, CargaIngesta.cliente_id == usuario.cliente_id)
    )
    if carga is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carga no encontrada")
    return carga


@router.get("/usuarios", response_model=list[UsuarioSalida], tags=["administración"])
def listar_usuarios(
    usuario: UsuarioSesion = Depends(requerir_rol("admin_plataforma", "gerente")),
    sesion: Session = Depends(sesion_bd),
) -> list[Usuario]:
    consulta = select(Usuario).where(Usuario.cliente_id == usuario.cliente_id).order_by(Usuario.nombre)
    return list(sesion.scalars(consulta))
