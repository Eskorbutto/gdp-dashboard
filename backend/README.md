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

## Estructura

```
app/
  modelos.py        modelo estándar (SQLAlchemy)
  db.py             sesiones con cliente fijado
  seguridad.py      contraseñas (scrypt) y tokens firmados
  dependencias.py   usuario actual, sesión por cliente, roles
  rutas/            endpoints
alembic/versions/   0001 modelo, 0002 RLS + permisos + login
scripts/            datos simulados
tests/              aislamiento (BD y API), esquema, datos simulados
```
