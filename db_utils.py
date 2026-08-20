"""Helpers SQL con compatibilidad SQLite/PostgreSQL.

Las diferencias críticas entre ambos dialectos:
  - MAX(a, b)  (SQLite, escalar)  vs  GREATEST(a, b)  (PostgreSQL)
  - INSERT ... RETURNING id (PostgreSQL) vs cursor.lastrowid (SQLite)
"""
from sqlalchemy import text

from database import IS_POSTGRES


def scalar_max(*args: str) -> str:
    """Máximo escalar de N expresiones: GREATEST(a,b,...) en Postgres, MAX(a,b,...) en SQLite."""
    if IS_POSTGRES:
        return f"GREATEST({', '.join(args)})"
    return f"MAX({', '.join(args)})"


def exec_insert(db, table: str, columns, values, returning_id: bool = True) -> int | None:
    """INSERT genérico con retorno del id nuevo cuando aplica.

    columns: lista de nombres de columna.
    values:  lista de valores (kwargs para SQLAlchemy text()).
    """
    cols = ", ".join(columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
    if returning_id and IS_POSTGRES:
        sql += " RETURNING id"
    result = db.execute(text(sql), values)
    if returning_id:
        if IS_POSTGRES:
            return result.scalar()
        return result.lastrowid
    return None


def now_dm_YHM() -> str:
    """Equivalente a chrono::Local::now().format("%d/%m/%Y %H:%M")."""
    from datetime import datetime

    return datetime.now().strftime("%d/%m/%Y %H:%M")


def now_dm_YHMS() -> str:
    """Equivalente a chrono::Local::now().format("%d/%m/%Y %H:%M:%S")."""
    from datetime import datetime

    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def now_iso() -> str:
    """Equivalente a chrono::Local::now().format("%Y-%m-%d %H:%M:%S") (notas máquinas)."""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fmt_date_for_sql(dd_mm_yyyy: str) -> str:
    """dd/mm/YYYY -> YYYYmmdd para comparación lexicográfica en SQL."""
    parts = dd_mm_yyyy.split("/")
    if len(parts) == 3:
        return f"{parts[2]}{parts[1]}{parts[0]}"
    return dd_mm_yyyy


def where_fecha(fecha_desde: str, fecha_hasta: str, alias: str = "") -> tuple[str, list]:
    """Cláusula WHERE para filtrar fechas dd/mm/YYYY por rango (alias opcional)."""
    clauses = []
    params = []
    pref = f"{alias}." if alias else ""
    if fecha_desde:
        clauses.append(
            f"(SUBSTR({pref}fecha, 7, 4) || SUBSTR({pref}fecha, 4, 2) || SUBSTR({pref}fecha, 1, 2)) >= :fecha_desde"
        )
        params.append(fmt_date_for_sql(fecha_desde))
    if fecha_hasta:
        clauses.append(
            f"(SUBSTR({pref}fecha, 7, 4) || SUBSTR({pref}fecha, 4, 2) || SUBSTR({pref}fecha, 1, 2)) <= :fecha_hasta"
        )
        params.append(fmt_date_for_sql(fecha_hasta))
    where_clause = "1=1" if not clauses else " AND ".join(clauses)
    return where_clause, params


def params_dict(has_desde: bool, has_hasta: bool, val_desde, val_hasta) -> dict:
    """Construye dict de parámetros para where_fecha en orden correcto."""
    out = {}
    if has_desde:
        out["fecha_desde"] = val_desde
    if has_hasta:
        out["fecha_hasta"] = val_hasta
    return out