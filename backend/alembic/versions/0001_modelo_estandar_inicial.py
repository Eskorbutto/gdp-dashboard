"""Modelo de datos estándar inicial.

Revision ID: 0001
Revises:
Create Date: 2026-10-11 02:54:44.316810
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('clientes',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('nombre', sa.String(length=120), nullable=False),
    sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('creado_en', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clientes')),
    sa.UniqueConstraint('nombre', name=op.f('uq_clientes_nombre'))
    )
    op.create_table('cargas_ingesta',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('conector', sa.String(length=30), nullable=False),
    sa.Column('origen', sa.String(length=255), nullable=True),
    sa.Column('estado', sa.String(length=20), server_default=sa.text("'en_proceso'"), nullable=False),
    sa.Column('iniciada_en', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('terminada_en', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('registros_leidos', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('registros_validos', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('registros_con_error', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('errores', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("conector IN ('vicidial', 'asterisk', 'genesys', 'archivo', 'api', 'sftp', 'simulado')", name=op.f('ck_cargas_ingesta_conector')),
    sa.CheckConstraint("estado IN ('en_proceso', 'ok', 'con_errores', 'fallida')", name=op.f('ck_cargas_ingesta_estado')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_cargas_ingesta_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cargas_ingesta')),
    sa.UniqueConstraint('cliente_id', 'id', name=op.f('uq_cargas_ingesta_cliente_id_id'))
    )
    op.create_table('servicios',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('nombre', sa.String(length=120), nullable=False),
    sa.Column('codigo_origen', sa.String(length=60), nullable=True),
    sa.Column('umbral_ns_seg', sa.SmallInteger(), server_default=sa.text('20'), nullable=False),
    sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.CheckConstraint('umbral_ns_seg > 0', name=op.f('ck_servicios_umbral_ns_positivo')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_servicios_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_servicios')),
    sa.UniqueConstraint('cliente_id', 'id', name=op.f('uq_servicios_cliente_id_id')),
    sa.UniqueConstraint('cliente_id', 'nombre', name=op.f('uq_servicios_cliente_id_nombre'))
    )
    op.create_table('usuarios',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('nombre', sa.String(length=120), nullable=False),
    sa.Column('rol', sa.String(length=30), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('creado_en', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.CheckConstraint('email = lower(email)', name=op.f('ck_usuarios_email_minusculas')),
    sa.CheckConstraint("rol IN ('admin_plataforma', 'gerente', 'supervisor', 'cliente_lectura')", name=op.f('ck_usuarios_rol')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_usuarios_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usuarios')),
    sa.UniqueConstraint('cliente_id', 'id', name=op.f('uq_usuarios_cliente_id_id')),
    sa.UniqueConstraint('email', name=op.f('uq_usuarios_email'))
    )
    op.create_table('agentes',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('servicio_id', sa.Integer(), nullable=True),
    sa.Column('codigo_origen', sa.String(length=60), nullable=False),
    sa.Column('nombre', sa.String(length=120), nullable=False),
    sa.Column('horas_contratadas_semana', sa.Numeric(precision=4, scale=1), nullable=True),
    sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['cliente_id', 'servicio_id'], ['servicios.cliente_id', 'servicios.id'], name=op.f('fk_agentes_cliente_id_servicio_id_servicios')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_agentes_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agentes')),
    sa.UniqueConstraint('cliente_id', 'codigo_origen', name=op.f('uq_agentes_cliente_id_codigo_origen')),
    sa.UniqueConstraint('cliente_id', 'id', name=op.f('uq_agentes_cliente_id_id'))
    )
    op.create_table('metas_indicador',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('servicio_id', sa.Integer(), nullable=True),
    sa.Column('indicador', sa.String(length=20), nullable=False),
    sa.Column('valor', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('vigente_desde', sa.Date(), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("indicador IN ('ns', 'na', 'tmo', 'abandono', 'ausentismo', 'shrinkage', 'adherencia')", name=op.f('ck_metas_indicador_indicador')),
    sa.ForeignKeyConstraint(['cliente_id', 'servicio_id'], ['servicios.cliente_id', 'servicios.id'], name=op.f('fk_metas_indicador_cliente_id_servicio_id_servicios')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_metas_indicador_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_metas_indicador')),
    sa.UniqueConstraint('cliente_id', 'servicio_id', 'indicador', 'vigente_desde', name=op.f('uq_metas_indicador_cliente_id_servicio_id_indicador_vigente_desde'), postgresql_nulls_not_distinct=True)
    )
    op.create_table('registros_crudos',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('carga_id', sa.BigInteger(), nullable=False),
    sa.Column('tipo_registro', sa.String(length=60), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('recibido_en', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['cliente_id', 'carga_id'], ['cargas_ingesta.cliente_id', 'cargas_ingesta.id'], name=op.f('fk_registros_crudos_cliente_id_carga_id_cargas_ingesta')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_registros_crudos_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_registros_crudos'))
    )
    op.create_index(op.f('ix_registros_crudos_cliente_id_carga_id'), 'registros_crudos', ['cliente_id', 'carga_id'], unique=False)
    op.create_table('resumen_intervalo_servicio',
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('servicio_id', sa.Integer(), nullable=False),
    sa.Column('cola', sa.String(length=60), server_default=sa.text("''"), nullable=False),
    sa.Column('minutos_intervalo', sa.SmallInteger(), nullable=False),
    sa.Column('inicio_intervalo', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('ofrecidas', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('atendidas', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('atendidas_en_umbral', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('abandonadas', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('abandonadas_en_umbral', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('espera_seg_total', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('conversacion_seg_total', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('acw_seg_total', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('calculado_en', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('minutos_intervalo IN (15, 30)', name=op.f('ck_resumen_intervalo_servicio_minutos_intervalo')),
    sa.ForeignKeyConstraint(['cliente_id', 'servicio_id'], ['servicios.cliente_id', 'servicios.id'], name=op.f('fk_resumen_intervalo_servicio_cliente_id_servicio_id_servicios')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_resumen_intervalo_servicio_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('cliente_id', 'servicio_id', 'cola', 'minutos_intervalo', 'inicio_intervalo', name=op.f('pk_resumen_intervalo_servicio'))
    )
    op.create_table('ausencias',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('agente_id', sa.Integer(), nullable=False),
    sa.Column('fecha_desde', sa.Date(), nullable=False),
    sa.Column('fecha_hasta', sa.Date(), nullable=False),
    sa.Column('tipo', sa.String(length=30), nullable=False),
    sa.Column('justificada', sa.Boolean(), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("tipo IN ('licencia_medica', 'vacaciones', 'permiso', 'falta', 'otro')", name=op.f('ck_ausencias_tipo')),
    sa.CheckConstraint('fecha_hasta >= fecha_desde', name=op.f('ck_ausencias_rango_valido')),
    sa.ForeignKeyConstraint(['cliente_id', 'agente_id'], ['agentes.cliente_id', 'agentes.id'], name=op.f('fk_ausencias_cliente_id_agente_id_agentes')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_ausencias_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ausencias'))
    )
    op.create_index(op.f('ix_ausencias_cliente_id_agente_id_fecha_desde'), 'ausencias', ['cliente_id', 'agente_id', 'fecha_desde'], unique=False)
    op.create_table('eventos_agente',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('agente_id', sa.Integer(), nullable=False),
    sa.Column('carga_id', sa.BigInteger(), nullable=True),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('motivo', sa.String(length=60), nullable=True),
    sa.Column('inicio', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('fin', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("tipo IN ('login', 'logout', 'disponible', 'en_llamada', 'acw', 'pausa')", name=op.f('ck_eventos_agente_tipo')),
    sa.CheckConstraint('fin IS NULL OR fin >= inicio', name=op.f('ck_eventos_agente_fin_posterior')),
    sa.ForeignKeyConstraint(['cliente_id', 'agente_id'], ['agentes.cliente_id', 'agentes.id'], name=op.f('fk_eventos_agente_cliente_id_agente_id_agentes')),
    sa.ForeignKeyConstraint(['cliente_id', 'carga_id'], ['cargas_ingesta.cliente_id', 'cargas_ingesta.id'], name=op.f('fk_eventos_agente_cliente_id_carga_id_cargas_ingesta')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_eventos_agente_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eventos_agente'))
    )
    op.create_index(op.f('ix_eventos_agente_cliente_id_agente_id_inicio'), 'eventos_agente', ['cliente_id', 'agente_id', 'inicio'], unique=False)
    op.create_table('llamadas',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('servicio_id', sa.Integer(), nullable=False),
    sa.Column('agente_id', sa.Integer(), nullable=True),
    sa.Column('carga_id', sa.BigInteger(), nullable=True),
    sa.Column('id_origen', sa.String(length=100), nullable=False),
    sa.Column('cola', sa.String(length=60), nullable=True),
    sa.Column('inicio', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('espera_seg', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('conversacion_seg', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('acw_seg', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('resultado', sa.String(length=20), nullable=False),
    sa.Column('tipificacion', sa.String(length=100), nullable=True),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("resultado IN ('atendida', 'abandonada')", name=op.f('ck_llamadas_resultado')),
    sa.CheckConstraint('espera_seg >= 0 AND conversacion_seg >= 0 AND acw_seg >= 0', name=op.f('ck_llamadas_tiempos_no_negativos')),
    sa.ForeignKeyConstraint(['cliente_id', 'agente_id'], ['agentes.cliente_id', 'agentes.id'], name=op.f('fk_llamadas_cliente_id_agente_id_agentes')),
    sa.ForeignKeyConstraint(['cliente_id', 'carga_id'], ['cargas_ingesta.cliente_id', 'cargas_ingesta.id'], name=op.f('fk_llamadas_cliente_id_carga_id_cargas_ingesta')),
    sa.ForeignKeyConstraint(['cliente_id', 'servicio_id'], ['servicios.cliente_id', 'servicios.id'], name=op.f('fk_llamadas_cliente_id_servicio_id_servicios')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_llamadas_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llamadas')),
    sa.UniqueConstraint('cliente_id', 'id', name=op.f('uq_llamadas_cliente_id_id')),
    sa.UniqueConstraint('cliente_id', 'id_origen', name=op.f('uq_llamadas_cliente_id_id_origen'))
    )
    op.create_index(op.f('ix_llamadas_cliente_id_servicio_id_inicio'), 'llamadas', ['cliente_id', 'servicio_id', 'inicio'], unique=False)
    op.create_table('turnos_planificados',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('agente_id', sa.Integer(), nullable=False),
    sa.Column('servicio_id', sa.Integer(), nullable=False),
    sa.Column('fecha', sa.Date(), nullable=False),
    sa.Column('inicio', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('fin', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.CheckConstraint('fin > inicio', name=op.f('ck_turnos_planificados_fin_posterior')),
    sa.ForeignKeyConstraint(['cliente_id', 'agente_id'], ['agentes.cliente_id', 'agentes.id'], name=op.f('fk_turnos_planificados_cliente_id_agente_id_agentes')),
    sa.ForeignKeyConstraint(['cliente_id', 'servicio_id'], ['servicios.cliente_id', 'servicios.id'], name=op.f('fk_turnos_planificados_cliente_id_servicio_id_servicios')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_turnos_planificados_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_turnos_planificados')),
    sa.UniqueConstraint('cliente_id', 'agente_id', 'inicio', name=op.f('uq_turnos_planificados_cliente_id_agente_id_inicio'))
    )
    op.create_index(op.f('ix_turnos_planificados_cliente_id_fecha'), 'turnos_planificados', ['cliente_id', 'fecha'], unique=False)
    op.create_table('evaluaciones_calidad',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('agente_id', sa.Integer(), nullable=False),
    sa.Column('llamada_id', sa.BigInteger(), nullable=True),
    sa.Column('evaluador_usuario_id', sa.Integer(), nullable=True),
    sa.Column('fecha', sa.Date(), nullable=False),
    sa.Column('nota', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('comentario', sa.Text(), nullable=True),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.CheckConstraint('nota BETWEEN 0 AND 100', name=op.f('ck_evaluaciones_calidad_nota_rango')),
    sa.ForeignKeyConstraint(['cliente_id', 'agente_id'], ['agentes.cliente_id', 'agentes.id'], name=op.f('fk_evaluaciones_calidad_cliente_id_agente_id_agentes')),
    sa.ForeignKeyConstraint(['cliente_id', 'evaluador_usuario_id'], ['usuarios.cliente_id', 'usuarios.id'], name=op.f('fk_evaluaciones_calidad_cliente_id_evaluador_usuario_id_usuarios')),
    sa.ForeignKeyConstraint(['cliente_id', 'llamada_id'], ['llamadas.cliente_id', 'llamadas.id'], name=op.f('fk_evaluaciones_calidad_cliente_id_llamada_id_llamadas')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_evaluaciones_calidad_cliente_id_clientes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evaluaciones_calidad'))
    )


def downgrade() -> None:
    op.drop_table('evaluaciones_calidad')
    op.drop_index(op.f('ix_turnos_planificados_cliente_id_fecha'), table_name='turnos_planificados')
    op.drop_table('turnos_planificados')
    op.drop_index(op.f('ix_llamadas_cliente_id_servicio_id_inicio'), table_name='llamadas')
    op.drop_table('llamadas')
    op.drop_index(op.f('ix_eventos_agente_cliente_id_agente_id_inicio'), table_name='eventos_agente')
    op.drop_table('eventos_agente')
    op.drop_index(op.f('ix_ausencias_cliente_id_agente_id_fecha_desde'), table_name='ausencias')
    op.drop_table('ausencias')
    op.drop_table('resumen_intervalo_servicio')
    op.drop_index(op.f('ix_registros_crudos_cliente_id_carga_id'), table_name='registros_crudos')
    op.drop_table('registros_crudos')
    op.drop_table('metas_indicador')
    op.drop_table('agentes')
    op.drop_table('usuarios')
    op.drop_table('servicios')
    op.drop_table('cargas_ingesta')
    op.drop_table('clientes')
