# CLAUDE.md — Plataforma web para call centers

## Qué es este proyecto
Plataforma web multicliente (SaaS) donde cada call center entra a su propio panel para ver y administrar sus servicios, indicadores y reportes. Idioma del producto, código de negocio y comentarios: **español de Chile**. Nombres técnicos de código (funciones, variables) en inglés o español, pero consistentes.

## Arquitectura (decisión central)
Separar la **fuente de datos** de la **plataforma**. Tres capas:

1. **Conectores de ingesta (varían por cliente):** VICIdial (primero), Asterisk, Genesys, Excel/CSV, API, SFTP. Cada conector lee un origen y lo traduce al modelo estándar.
2. **Base de datos estándar (modelo canónico, igual para todos los clientes):** PostgreSQL.
3. **Reportes y dashboard:** leen **solo** del modelo estándar. Nunca saben de qué fuente vino el dato.

Reglas de arquitectura:
- Cada cliente nuevo cuesta **un conector**, no un reporte. Un reporte nuevo debe funcionar para todos los clientes a la vez.
- **Zona de aterrizaje (raw):** guardar primero el dato crudo tal como llega; luego transformarlo al modelo estándar. Debe ser posible reprocesar sin pedirle nada al cliente.
- **Validaciones al ingresar:** duplicados, fechas inválidas, agentes sin mapear. Log de cargas con errores, visible para el cliente.
- **Indicadores precalculados** por intervalo (15 o 30 min) en tablas resumen, para que el dashboard sea rápido.

## Multi-tenant (crítico)
- Una sola base de datos con aislamiento estricto por cliente.
- **Todas** las tablas llevan `cliente_id`. Toda consulta filtra por `cliente_id` obtenido de la sesión, nunca de un parámetro que envíe el usuario.
- Un error de permisos entre clientes es el peor fallo posible: toda funcionalidad nueva debe incluir pruebas de aislamiento (un cliente no puede ver datos de otro).
- Roles: administrador de plataforma, gerente, supervisor, cliente final (solo lectura).

## Modelo de datos estándar (base inicial)
`clientes`, `usuarios`, `servicios`, `agentes`, `llamadas`, `eventos_agente` (login, logout, pausa, disponible, etc.), `turnos_planificados` (malla), `ausencias`, `evaluaciones_calidad`, `metas_indicador`, `cargas_ingesta` (log), más tablas resumen por intervalo.

La tabla de `turnos_planificados` la comparten los módulos de dotación y asistencia (sin malla no hay adherencia).

## Módulos del producto
- **Indicadores:** NS (nivel de servicio), NA (nivel de atención), TMO, tasa de abandono, llamadas ofrecidas y atendidas, por servicio y por cola, en vivo y por periodo.
- **Dotación:** agentes por intervalo, requerido vs. real (Erlang C), shrinkage, ausentismo.
- **Reportes de asistencia:** por agente (entrada/salida, atrasos, ausencias justificadas o no, horas trabajadas vs. contratadas, tiempo por estado); por servicio o turno (% asistencia y puntualidad); adherencia a la malla; alertas (agente sin conectarse a su hora, ausentismo sobre la meta, déficit de dotación); exportables a Excel y PDF, también programados por correo.
- **Desempeño y calidad:** ranking de agentes, evaluaciones de calidad, tipificaciones y reclamos.
- **Reportes a pedido:** el cliente elige servicio, rango de fechas y métricas, y exporta a Excel o PDF. Es el módulo más valorado.
- **Administración:** servicios, usuarios y roles, metas por indicador.

## Stack
- Backend: Python + FastAPI.
- Base de datos: PostgreSQL (migraciones con Alembic).
- Frontend: web responsive (React; gráficos con Recharts o ECharts). App móvil más adelante.
- Tareas programadas para consolidar indicadores por intervalo y enviar reportes por correo.
- Pruebas: pytest. CI con GitHub Actions.

## Reglas de trabajo
- **Nunca** subir datos reales de clientes ni claves (VICIdial, bases de datos, SMTP). Usar datos simulados y variables de entorno; incluir un `.env.example` sin valores reales.
- La base de pruebas es PostgreSQL local con datos simulados.
- Trabajar por etapas pequeñas, cada una en su propia rama, para revisar antes de unir a `main`. Orden: modelo de datos → conectores → reportes → dashboard.
- Pruebas desde el inicio, sobre todo para el cálculo de indicadores (NS, NA, TMO, abandono, shrinkage, Erlang C). Los cálculos deben tener pruebas unitarias con casos conocidos.
- Cumplir con la Ley 19.628 de protección de datos personales de Chile: minimizar datos personales de agentes y clientes finales.
- Antes de cambiar el modelo de datos o la lógica de aislamiento por cliente, explicar el cambio y esperar confirmación.
- Mensajes de commit en español, cortos y descriptivos.

## Contexto del dueño del proyecto
Daniel es analista de datos con experiencia en call center (Erlang C, shrinkage, VICIdial, KPIs de servicio) y maneja SQL Server, Python, Power BI y Excel. Usa terminología del rubro sin necesidad de explicarla. Supervisa el avance desde el celular, así que los resúmenes deben ser breves y claros, y las decisiones importantes se le plantean con una recomendación y alternativas.

## Primer paso sugerido
Crear la estructura inicial: backend FastAPI, modelo de datos estándar con migraciones, datos simulados de asistencia, y pruebas de aislamiento multicliente.

## Cómo está implementado el aislamiento (etapa 1)
Ver `backend/README.md`. Resumen: Row-Level Security de PostgreSQL + rol de aplicación sin privilegios (`cc_app`) + `cliente_id` de la sesión fijado por transacción (`app.cliente_id`) + FK compuestas `(cliente_id, id)` entre tablas de un mismo cliente. La prueba `tests/test_esquema.py` falla si se agrega una tabla sin `cliente_id` o sin RLS.
