"""Migración de datos SQLite (producción local) → PostgreSQL/Neon.

Origen:  %APPDATA%\\WASI\\wasi.db  (modo lectura, NO toca producción).
Destino: engine de database.py (DATABASE_URL → Neon, o SQLite local para prueba).

Uso:
  python scripts/migrate_sqlite_to_neon.py                 # dry-run
  python scripts/migrate_sqlite_to_neon.py --apply          # ejecuta la copia
  python scripts/migrate_sqlite_to_neon.py --apply --images  # + sube imágenes a Supabase
  python scripts/migrate_sqlite_to_neon.py --apply --source C:\\ruta\\wasi.db
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from database import engine, SessionLocal, IS_POSTGRES
from migrations import run_migrations

TABLAS = [
    "clientes", "facturas", "factura_items", "productos", "cuenta_corriente",
    "movimientos_wasi", "entidades_gastos", "movimientos_gastos", "ordenes_produccion",
    "empleados_config", "asistencia_empleados", "actividad_reciente", "pagos_proveedores",
    "maquinas", "produccion_maquina", "notas_maquina", "cerrado_maquinas", "cerrado_notas",
    "cerrado_medias", "embolsado_empleados", "embolsado_notas", "embolsado_docenas",
    "categorias_gasto", "stock_movements", "factura_seq", "costos_medias",
]

# Tablas cuyo id NO se conserva (se regenera en destino): factura_seq se normaliza a 1 fila,
# costos_medias se migra desde el JSON local, no desde SQLite.
SIN_IDS = {"factura_seq", "costos_medias"}


def default_source() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "WASI", "wasi.db")


def source_conn(source: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{source}?mode=ro", uri=True)


def target_columns(db, table: str) -> list[str]:
    if IS_POSTGRES:
        rows = db.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = :t ORDER BY ordinal_position"
            ),
            {"t": table},
        ).fetchall()
        return [r[0] for r in rows]
    rows = db.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return [r[1] for r in rows]


def copy_rows(src: sqlite3.Connection, db, table: str, dry_run: bool) -> int:
    cols = [c[1] for c in src.execute(f'PRAGMA table_info("{table}")')]
    tcols = target_columns(db, table)
    cols = [c for c in cols if c in tcols]
    rows = src.execute(f'SELECT * FROM "{table}"').fetchall()
    if not rows:
        return 0
    idx = [c[1] for c in src.execute(f'PRAGMA table_info("{table}")')]
    sel_idx = [idx.index(c) for c in cols]
    placeholders = ", ".join([":" + c for c in cols])
    insert_sql = f'INSERT INTO "{table}" ({", ".join(cols)}) VALUES ({placeholders})'
    if IS_POSTGRES:
        insert_sql += " ON CONFLICT DO NOTHING"
    count = 0
    for row in rows:
        values = dict(zip(cols, [row[i] for i in sel_idx]))
        if dry_run:
            count += 1
            continue
        try:
            db.execute(text(insert_sql), values)
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] {table}: fila omitida: {exc}")
            continue
        count += 1
    return count


def reset_sequences(db, table: str) -> None:
    """Resetea la secuencia de cada tabla al MAX(id) en Postgres (no-op en SQLite)."""
    if not IS_POSTGRES:
        return
    db.execute(
        text(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"(SELECT COALESCE(MAX(id), 1) FROM {table}))"
        )
    )


def set_factura_seq(db) -> None:
    db.execute(text("DELETE FROM factura_seq"))
    row = db.execute(text("SELECT MAX(CAST(SUBSTR(COALESCE(NULLIF(numero,''),'F-0'),3) AS INTEGER)) FROM facturas")).scalar()
    counter = max(row or 10249, 10249)
    db.execute(text("INSERT INTO factura_seq (id, counter) VALUES (1, :c)"), {"c": counter})


def migrate_costos_medias(db, dry_run: bool) -> None:
    """Vuelca el JSON local de costos_medias.json a la tabla costos_medias."""
    import json

    path = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "WASI", "costos_medias.json")
    if not os.path.exists(path):
        print("  costos_medias: no hay JSON local, se omite")
        return
    data = json.loads(open(path, encoding="utf-8").read())
    if dry_run:
        print(f"  costos_medias: {len(data)} configs del JSON (dry-run)")
        return
    for nombre, calc in data.items():
        escenarios = calc.get("escenarios_precios", [])
        db.execute(
            text(
                "INSERT INTO costos_medias (nombre, docenas, pares_por_docena, peso_por_par_kg, algodon_total, "
                "lycra_base, goma_base, factor, descuento_efectivo_pct, mano_de_obra, otros_accesorios, escenarios_precios) "
                "VALUES (:nombre, :docenas, :pares_por_docena, :peso_por_par_kg, :algodon_total, :lycra_base, "
                ":goma_base, :factor, :descuento_efectivo_pct, :mano_de_obra, :otros_accesorios, :escenarios_precios) "
                "ON CONFLICT(nombre) DO UPDATE SET docenas=excluded.docenas, pares_por_docena=excluded.pares_por_docena, "
                "peso_por_par_kg=excluded.peso_por_par_kg, algodon_total=excluded.algodon_total, lycra_base=excluded.lycra_base, "
                "goma_base=excluded.goma_base, factor=excluded.factor, descuento_efectivo_pct=excluded.descuento_efectivo_pct, "
                "mano_de_obra=excluded.mano_de_obra, otros_accesorios=excluded.otros_accesorios, "
                "escenarios_precios=excluded.escenarios_precios"
            ),
            {"nombre": nombre, "docenas": calc.get("docenas", 1000), "pares_por_docena": calc.get("pares_por_docena", 12),
             "peso_por_par_kg": calc.get("peso_por_par_kg", 0.042), "algodon_total": calc.get("algodon_total", 2785944.0),
             "lycra_base": calc.get("lycra_base", 334660.0), "goma_base": calc.get("goma_base", 468220.0),
             "factor": calc.get("factor", 1.455), "descuento_efectivo_pct": calc.get("descuento_efectivo_pct", 0.15),
             "mano_de_obra": calc.get("mano_de_obra", 1700000.0), "otros_accesorios": calc.get("otros_accesorios", 500000.0),
             "escenarios_precios": json.dumps(escenarios)},
        )


def migrate_images(db, dry_run: bool, source: str) -> None:
    """Sube las imágenes de productos a Supabase y actualiza productos.imagen con la URL pública.

    Los paths guardados en la DB apuntan a una máquina vieja (product_images sin 's');
    se busca el archivo por basename en productos_images/ y product_images/.
    """
    import storage

    if not storage.storage_available():
        print("  imágenes: SUPABASE_URL/SERVICE_ROLE_KEY no configurados, se omite subida")
        return
    base = os.path.dirname(source)
    dirs = [os.path.join(base, "productos_images"), os.path.join(base, "product_images")]
    rows = db.execute(text("SELECT id, detalle, imagen FROM productos WHERE imagen != ''")).fetchall()
    subidas = 0
    sin_archivo = 0
    for pid, detalle, img_path in rows:
        basename = os.path.basename(str(img_path))
        found = None
        for d in dirs:
            cand = os.path.join(d, basename)
            if os.path.isfile(cand):
                found = cand
                break
        if not found:
            if not dry_run:
                db.execute(text("UPDATE productos SET imagen = '' WHERE id = :id"), {"id": pid})
            sin_archivo += 1
            continue
        ext = found.rsplit(".", 1)[-1].lower() if "." in found else "png"
        with open(found, "rb") as fh:
            data = fh.read()
        if dry_run:
            subidas += 1
            continue
        path = storage.build_path(f"producto-{pid}", ext)
        storage.upload_bytes(storage.BUCKET_PRODUCTOS, path, data, f"image/{ext}")
        url = storage.public_url(storage.BUCKET_PRODUCTOS, path)
        db.execute(text("UPDATE productos SET imagen = :url WHERE id = :id"), {"url": url, "id": pid})
        subidas += 1
    print(f"  imágenes: {subidas} subidas, {sin_archivo} sin archivo (imagen limpiada)")


def verify(src: sqlite3.Connection, db) -> list[str]:
    issues = []
    checks = [
        ("clientes", "clientes"), ("facturas", "facturas"), ("factura_items", "factura_items"),
        ("productos", "productos"), ("cuenta_corriente", "cuenta_corriente"),
        ("movimientos_wasi", "movimientos_wasi"), ("entidades_gastos", "entidades_gastos"),
        ("movimientos_gastos", "movimientos_gastos"), ("ordenes_produccion", "ordenes_produccion"),
        ("stock_movements", "stock_movements"),
    ]
    for table, _ in checks:
        s = src.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        t = db.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0
        if s != t:
            issues.append(f"COUNT {table}: origen={s} destino={t}")
    s_total = src.execute("SELECT COALESCE(SUM(total),0) FROM facturas").fetchone()[0]
    t_total = db.execute(text("SELECT COALESCE(SUM(total),0) FROM facturas")).scalar() or 0.0
    if abs(s_total - t_total) > 0.01:
        issues.append(f"TOTAL facturado: origen={s_total} destino={t_total}")
    s_cc = src.execute("SELECT COALESCE(SUM(debe-haber),0) FROM cuenta_corriente").fetchone()[0]
    t_cc = db.execute(text("SELECT COALESCE(SUM(debe-haber),0) FROM cuenta_corriente")).scalar() or 0.0
    if abs(s_cc - t_cc) > 0.01:
        issues.append(f"SUM CC: origen={s_cc} destino={t_cc}")
    s_stock = src.execute("SELECT COALESCE(SUM(stock_actual),0) FROM productos").fetchone()[0]
    t_stock = db.execute(text("SELECT COALESCE(SUM(stock_actual),0) FROM productos")).scalar() or 0.0
    if abs(s_stock - t_stock) > 0.01:
        issues.append(f"SUM stock: origen={s_stock} destino={t_stock}")
    s_mw = src.execute("SELECT COALESCE(SUM(CASE WHEN tipo='Ingreso' THEN monto ELSE 0 END),0) - COALESCE(SUM(CASE WHEN tipo='Egreso' THEN monto ELSE 0 END),0) FROM movimientos_wasi").fetchone()[0]
    t_mw = db.execute(text("SELECT COALESCE(SUM(CASE WHEN tipo='Ingreso' THEN monto ELSE 0 END),0) - COALESCE(SUM(CASE WHEN tipo='Egreso' THEN monto ELSE 0 END),0) FROM movimientos_wasi")).scalar() or 0.0
    if abs(s_mw - t_mw) > 0.01:
        issues.append(f"SALDO WASI: origen={s_mw} destino={t_mw}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra wasi.db a Neon/SQLite destino")
    parser.add_argument("--source", default=default_source(), help="ruta del wasi.db de origen")
    parser.add_argument("--apply", action="store_true", help="aplica la migración (default: dry-run)")
    parser.add_argument("--images", action="store_true", help="sube imágenes a Supabase y actualiza productos.imagen")
    args = parser.parse_args()

    src = source_conn(args.source)
    print(f"Origen: {args.source}")

    if args.apply:
        run_migrations()
    else:
        # En dry-run la app ya corrió migrations al importar; lo volvemos a asegurar
        from migrations import run_migrations as _rm
        _rm()

    totals = {}
    with SessionLocal() as db:
        with db.begin():
            for table in TABLAS:
                if table == "costos_medias":
                    migrate_costos_medias(db, args.apply)
                    continue
                if table in SIN_IDS:
                    continue
                if table == "categorias_gasto" and args.apply:
                    db.execute(text("DELETE FROM categorias_gasto"))
                n = copy_rows(src, db, table, dry_run=not args.apply)
                if not args.apply:
                    print(f"  {table}: {n} filas (dry-run)")
                    continue
                reset_sequences(db, table)
                print(f"  {table}: {n} filas")
            if args.apply:
                set_factura_seq(db)
                print("  factura_seq normalizada a 1 fila")
                if args.images:
                    migrate_images(db, dry_run=False, source=args.source)
                print("  Verificación:", end=" ")
                issues = verify(src, db)
                if issues:
                    print("FALLOS")
                    for i in issues:
                        print("   -", i)
                else:
                    print("OK — sin discrepancias")
    src.close()
    print("Migración finalizada.")


if __name__ == "__main__":
    main()