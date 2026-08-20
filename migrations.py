"""Migraciones idempotentes inline + seeds (patrón run_db_migrations de backend_gal).

Ejecuta:
  1. CREATE ALL (tablas nuevas desde models.metadata).
  2. Columnas faltantes en bases existentes.
  3. Índices.
  4. Seeds (categorias_gasto, factura_seq).
"""
from sqlalchemy import text

from database import engine, IS_POSTGRES
from models import metadata

SEED_CATEGORIAS = [
    "Hilo", "Nylon", "Goma", "Comida",
    "Artículo embolsado", "Técnico", "Dibujo",
    "Spandex", "Repuesto", "Cuota de máquina", "Deuda de socio",
]


def _column_exists(conn, table: str, column: str) -> bool:
    if IS_POSTGRES:
        row = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).first()
        return row is not None
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    if _column_exists(conn, table, column):
        return
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _ensure_columns(conn, table: str, cols: list) -> None:
    for column, ddl in cols:
        _ensure_column(conn, table, column, ddl)


def _migrate_drop_localidad(conn) -> None:
    for table in ["clientes", "facturas"]:
        if not _column_exists(conn, table, "localidad"):
            continue
        conn.execute(
            text(
                f"UPDATE {table} SET domicilio = localidad "
                f"WHERE TRIM(COALESCE(localidad, '')) != '' AND TRIM(COALESCE(domicilio, '')) = ''"
            )
        )
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN localidad"))


INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_cc_cliente_id ON cuenta_corriente(cliente_id)",
    "CREATE INDEX IF NOT EXISTS idx_facturas_estado ON facturas(estado)",
    "CREATE INDEX IF NOT EXISTS idx_facturas_fecha ON facturas(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_fi_factura_id ON factura_items(factura_id)",
    "CREATE INDEX IF NOT EXISTS idx_mg_entidad_id ON movimientos_gastos(entidad_id)",
    "CREATE INDEX IF NOT EXISTS idx_op_estado ON ordenes_produccion(estado)",
    "CREATE INDEX IF NOT EXISTS idx_mw_fecha ON movimientos_wasi(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_mw_factura_id ON movimientos_wasi(factura_id)",
    "CREATE INDEX IF NOT EXISTS idx_mw_cc_id ON movimientos_wasi(cuenta_corriente_id)",
    "CREATE INDEX IF NOT EXISTS idx_clientes_nombre ON clientes(nombre)",
    "CREATE INDEX IF NOT EXISTS idx_ar_fecha ON actividad_reciente(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_stock_movements_producto ON stock_movements(producto_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_cerrado_maquina ON cerrado_medias(maquina_id, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_embolsado_maquina ON embolsado_docenas(maquina_id, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_asistencia_entidad ON asistencia_empleados(entidad_id, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_produccion_maquina ON produccion_maquina(maquina_id, fecha)",
]


def run_migrations() -> None:
    metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for table in ["clientes", "facturas"]:
            _ensure_columns(
                conn, table,
                [
                    ("dni", "TEXT DEFAULT ''"),
                    ("provincia", "TEXT DEFAULT ''"),
                    ("sucursal_recibir", "TEXT DEFAULT ''"),
                    ("cp", "TEXT DEFAULT ''"),
                ],
            )
        _ensure_columns(
            conn, "movimientos_wasi",
            [
                ("factura_id", "INTEGER DEFAULT NULL"),
                ("cuenta_corriente_id", "INTEGER DEFAULT NULL"),
            ],
        )
        _migrate_drop_localidad(conn)

        for idx in INDEXES:
            try:
                conn.execute(text(idx))
            except Exception as exc:  # noqa: BLE001
                print(f"[migrations] índice omitido ({idx}): {exc}")

        # Seeds
        for cat in SEED_CATEGORIAS:
            if IS_POSTGRES:
                conn.execute(
                    text("INSERT INTO categorias_gasto (nombre) VALUES (:n) ON CONFLICT (nombre) DO NOTHING"),
                    {"n": cat},
                )
            else:
                conn.execute(text("INSERT OR IGNORE INTO categorias_gasto (nombre) VALUES (:n)"), {"n": cat})

        # factura_seq: inicializar fila única (numeración F-XXXXX). Idempotente.
        from db_utils import scalar_max

        if IS_POSTGRES:
            conn.execute(
                text("INSERT INTO factura_seq (id, counter) VALUES (1, 10249) ON CONFLICT (id) DO NOTHING")
            )
        else:
            conn.execute(text("INSERT OR IGNORE INTO factura_seq (id, counter) VALUES (1, 10249)"))
        max_numero = conn.execute(
            text("SELECT MAX(CAST(SUBSTR(COALESCE(NULLIF(numero, ''), 'F-0'), 3) AS INTEGER)) FROM facturas")
        ).scalar()
        conn.execute(
            text(f"UPDATE factura_seq SET counter = {scalar_max('counter', '10249', str(max_numero or 0))} WHERE id = 1")
        )

    print("[migrations] OK")