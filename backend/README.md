# Backend — Plataforma Call Center

FastAPI + PostgreSQL. Etapa 1: modelo de datos estándar, aislamiento por cliente, datos simulados de asistencia.

## Puesta en marcha local

```bash
cd backend
pip install -r requirements-dev.txt
cp .env.example .env   # completar claves locales

# Roles y bases (una vez). cc_owner es dueño del esquema; cc_app es el rol de la aplicación.
sudo -u postgres psql <<'SQL'
CREATE ROLE cc_owner LOGIN PASSWORD '...' CREATEDB;
CREATE ROLE cc_app   LOGIN PASSWORD '...';
CREATE DATABASE callcenter      OWNER cc_owner;
CREATE DATABASE callcenter_test OWNER cc_owner;
SQL

alembic upgrade head                                   # crea el modelo y el aislamiento
python -m scripts.generar_datos_simulados --reiniciar  # 2 clientes ficticios, 14 días
uvicorn app.main:app --reload                          # http://localhost:8000/docs
```

Usuarios demo (ficticios): `gerente@andino.ejemplo.cl`, `supervisor@andino.ejemplo.cl`,
`cliente_lectura@andino.ejemplo.cl` y lo mismo con `@austral.ejemplo.cl`. Clave: `demo1234`.

## Pruebas

```bash
python -m pytest -q
```

Usan la base `callcenter_test` (se recrea en cada corrida). Configurable con
`TEST_DATABASE_URL` y `TEST_DATABASE_URL_OWNER`.

## Aislamiento entre clientes

Tres barreras independientes:

1. **API:** el `cliente_id` sale del token firmado; cada consulta filtra por él. Un id de otro cliente responde 404.
2. **Row-Level Security:** cada tabla tiene la política `aislamiento_cliente`
   (`cliente_id = app.cliente_id`). La app fija `app.cliente_id` por transacción
   (`SET LOCAL`), así que no se filtra entre conexiones del pool. Sin cliente fijado → 0 filas.
   La app se conecta como `cc_app`, que no es dueño de tablas ni tiene `BYPASSRLS`.
3. **FK compuestas `(cliente_id, id)`:** la base impide que un registro de un cliente apunte a uno de otro.

`tests/test_esquema.py` falla si se crea una tabla sin `cliente_id` o sin RLS.

## Conector VICIdial

Flujo: **origen** (CSV o MySQL de solo lectura) → `registros_crudos` (aterrizaje, por carga) → **modelo estándar**.
Cada carga queda en `cargas_ingesta` con su estado (`ok`, `con_errores`, `fallida`) y el detalle de problemas.

| Tabla VICIdial | Va a |
|---|---|
| `vicidial_closer_log` | `llamadas` (entrantes) |
| `vicidial_agent_log` | `eventos_agente` (pausa, disponible, en_llamada, acw) |
| `vicidial_user_log` | `eventos_agente` (login, logout) |

Mapeo (hay que crearlo antes en el panel/BD):
- Servicio: `servicios.codigo_origen` = ingroup de VICIdial.
- Agente: `agentes.codigo_origen` = `user` de VICIdial.

Validaciones:
- **Error** (la fila se omite): sin id, duplicada, fecha inválida, tiempos inválidos, servicio sin mapear, agente sin mapear en eventos.
- **Advertencia** (se carga igual o se ignora): llamada atendida por agente sin mapear (queda sin agente) y fecha fuera del rango de la carga.

Idempotencia: las llamadas se hacen upsert por id de origen; los eventos de la ventana se reemplazan por completo. Se puede cargar dos veces el mismo día sin duplicar.

Reprocesar: `--reprocesar ID` vuelve a transformar lo crudo guardado (útil tras mapear agentes o servicios), sin pedirle nada al cliente.

Uso (CSV con datos simulados):

```bash
python -m scripts.simular_vicidial --dia 2026-03-10 --directorio /tmp/vicidial
python -m scripts.cargar_vicidial --cliente-id 1 --csv /tmp/vicidial --desde 2026-03-10
python -m scripts.cargar_vicidial --cliente-id 1 --reprocesar 12
# Directo desde VICIdial: una variable por cliente (ver .env.example)
python -m scripts.cargar_vicidial --cliente-id 1 --origen-env VICIDIAL_DB_URL_ANDINO --desde 2026-03-10
```

Fechas en hora de Chile; `--hasta` exclusiva (por defecto desde = ayer, hasta = desde + 1 día). Sale con código 1 si la carga queda `fallida`. Nunca imprime URLs ni claves.

Supuestos a validar con datos reales:
- Se usan los `*_epoch` (UTC), no `call_date`/`event_time` (hora local del servidor).
- Atendida = `user` es un agente (no `VDCL`/`VDAD`/vacío). Conversación = `length_in_sec - queue_seconds` (incluye tiempo muerto).
- ACW de la llamada = `dispo_sec` del ciclo de `agent_log` con el mismo `uniqueid`.
- En `agent_log`: en_llamada = `talk_sec` (incluye `dead_sec`) y acw = `dispo_sec`, para no contar doble el tiempo muerto.
- Llamadas con status `AFTHRS` (fuera de horario) no son ofrecidas: se descartan.

Limitaciones conocidas:
- Un ciclo de `agent_log` que cruza el fin de la ventana (ej. medianoche) pierde los segmentos posteriores; relevante para operaciones 24 h.
- Por ahora solo llamadas entrantes (`closer_log`); las salientes (`vicidial_log`) requieren ampliar el modelo de `llamadas`.
- Un ingroup se mapea a un solo servicio y se asume un servidor VICIdial por cliente.

## Estructura

```
app/
  modelos.py        modelo estándar (SQLAlchemy)
  db.py             sesiones con cliente fijado
  seguridad.py      contraseñas (scrypt) y tokens firmados
  dependencias.py   usuario actual, sesión por cliente, roles
  rutas/            endpoints
  ingesta/vicidial/ lector (CSV/SQL), transformar (puro), conector (cargar/procesar)
alembic/versions/   0001 modelo, 0002 RLS + permisos + login
scripts/            generar_datos_simulados, simular_vicidial, cargar_vicidial
tests/              aislamiento (BD y API), esquema, datos simulados, conector VICIdial
```
