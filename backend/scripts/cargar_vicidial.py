"""Carga datos de VICIdial (CSV o base MySQL de solo lectura) al modelo estándar.

Uso:
    python -m scripts.cargar_vicidial --cliente-id 1 --csv /tmp/vicidial --desde 2026-03-10
    python -m scripts.cargar_vicidial --cliente-id 1 --origen-env VICIDIAL_DB_URL_ANDINO --desde 2026-03-10
    python -m scripts.cargar_vicidial --cliente-id 1 --reprocesar 12

Fechas en hora local de Chile; --hasta es exclusiva (por defecto, desde + 1 día; desde = ayer).
Nunca imprime URLs de conexión ni claves. Sale con código 1 si la carga queda "fallida".
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine

from app.ingesta.vicidial.conector import ResumenCarga, cargar, procesar
from app.ingesta.vicidial.lector import LectorCSV, LectorSQL, LectorVicidial

TZ_CHILE = ZoneInfo("America/Santiago")


def _inicio_dia(dia: date) -> datetime:
    return datetime(dia.year, dia.month, dia.day, tzinfo=TZ_CHILE)


def _lector(args: argparse.Namespace) -> LectorVicidial:
    if args.csv:
        if not args.csv.is_dir():
            sys.exit(f"error: el directorio CSV no existe: {args.csv}")
        return LectorCSV(args.csv)
    url = os.environ.get(args.origen_env)
    if not url:
        sys.exit(f"error: la variable de entorno {args.origen_env} no existe o está vacía")
    return LectorSQL(create_engine(url, pool_pre_ping=True), descripcion=f"vicidial-sql:{args.origen_env}")


def _imprimir(r: ResumenCarga) -> None:
    print(f"carga {r.carga_id}: {r.estado}")
    print(f"  leídos {r.leidos} | con error {r.con_error} | llamadas {r.llamadas} | eventos {r.eventos}")
    for motivo, n in sorted(r.problemas_por_motivo.items(), key=lambda x: -x[1]):
        print(f"  - {motivo}: {n}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Carga VICIdial al modelo estándar")
    ap.add_argument("--cliente-id", type=int, required=True)
    origen = ap.add_mutually_exclusive_group()
    origen.add_argument("--csv", type=Path, metavar="DIRECTORIO", help="exportes CSV de VICIdial")
    origen.add_argument("--origen-env", metavar="VARIABLE", help="variable de entorno con la URL SQLAlchemy de VICIdial")
    ap.add_argument("--desde", type=date.fromisoformat, help="YYYY-MM-DD (por defecto, ayer)")
    ap.add_argument("--hasta", type=date.fromisoformat, help="YYYY-MM-DD exclusiva (por defecto, desde + 1 día)")
    ap.add_argument("--reprocesar", type=int, metavar="CARGA_ID", help="reprocesa una carga ya guardada")
    args = ap.parse_args()

    if args.reprocesar is None and not (args.csv or args.origen_env):
        ap.error("falta el origen: use --csv o --origen-env (o --reprocesar)")
    if args.reprocesar is not None and (args.csv or args.origen_env or args.desde or args.hasta):
        ap.error("--reprocesar no se combina con origen ni fechas")

    if args.reprocesar is not None:
        try:
            resumen = procesar(args.cliente_id, args.reprocesar)
        except LookupError as exc:
            sys.exit(f"error: {exc}")
    else:
        desde = args.desde or date.today() - timedelta(days=1)
        hasta = args.hasta or desde + timedelta(days=1)
        if hasta <= desde:
            ap.error("--hasta debe ser posterior a --desde")
        resumen = cargar(args.cliente_id, _lector(args), _inicio_dia(desde), _inicio_dia(hasta))

    _imprimir(resumen)
    sys.exit(1 if resumen.estado == "fallida" else 0)


if __name__ == "__main__":
    main()
