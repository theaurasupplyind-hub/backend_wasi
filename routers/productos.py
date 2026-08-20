"""Router /productos — port de commands/productos.rs + imágenes a Supabase."""
import math

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_api_key
from db_utils import exec_insert, now_dm_YHMS
import storage

router = APIRouter(prefix="/productos", tags=["productos"], dependencies=[Depends(verify_api_key)])

PRODUCTO_COLS = (
    "id, detalle, precio_unitario, stock_actual, stock_minimo, "
    "stock_reservado_factura, stock_reservado_produccion, imagen"
)


class ProductoData(BaseModel):
    id: int | None = None
    detalle: str
    precio_unitario: float = 0
    stock_actual: float = 0
    stock_minimo: float = 0
    imagen: str = ""


def _row_producto(row) -> dict:
    return {
        "id": row[0], "detalle": row[1], "precio_unitario": row[2], "stock_actual": row[3],
        "stock_minimo": row[4], "stock_reservado_factura": row[5], "stock_reservado_produccion": row[6],
        "imagen": row[7],
    }


def registrar_movimiento_stock(db, producto_id, tipo, referencia, cantidad, stock_anterior, stock_nuevo, detalle) -> None:
    exec_insert(
        db, "stock_movements",
        ["producto_id", "fecha_hora", "tipo", "referencia", "cantidad", "stock_anterior", "stock_nuevo", "detalle"],
        {
            "producto_id": producto_id, "fecha_hora": now_dm_YHMS(), "tipo": tipo,
            "referencia": referencia, "cantidad": cantidad, "stock_anterior": stock_anterior,
            "stock_nuevo": stock_nuevo, "detalle": detalle,
        },
    )


def ajustar_stock_inner(db, prod_id: int, delta: float) -> float:
    stock_actual = db.execute(
        text("SELECT stock_actual FROM productos WHERE id = :id"), {"id": prod_id}
    ).scalar() or 0.0
    nuevo = max(stock_actual + delta, 0.0)
    db.execute(
        text("UPDATE productos SET stock_actual = :nuevo WHERE id = :id"), {"nuevo": nuevo, "id": prod_id}
    )
    registrar_movimiento_stock(
        db, prod_id, "ajuste", f"manual:{delta:+.0f}", delta, stock_actual, nuevo,
        f"Ajuste manual: {delta:+.0f} unidades",
    )
    return nuevo


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("")
def get_productos(
    search: str = "", stock_filter: str = "", limit: int = 500, offset: int = 0,
    db: Session = Depends(get_db),
):
    sql = f"SELECT {PRODUCTO_COLS} FROM productos"
    conds = []
    params = {}
    if search:
        conds.append("detalle LIKE :search")
        params["search"] = f"%{search}%"
    if stock_filter == "sin":
        conds.append("stock_actual <= 0")
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    if stock_filter == "menos":
        sql += " ORDER BY stock_actual ASC"
    elif stock_filter == "mas":
        sql += " ORDER BY stock_actual DESC"
    else:
        sql += " ORDER BY detalle ASC"
    sql += " LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset
    rows = db.execute(text(sql), params).fetchall()
    return [_row_producto(r) for r in rows]


@router.get("/all")
def get_all_productos(stock_filter: str = "", db: Session = Depends(get_db)):
    sql = f"SELECT {PRODUCTO_COLS} FROM productos"
    if stock_filter == "sin":
        sql += " WHERE stock_actual <= 0"
    sql += " ORDER BY detalle ASC"
    rows = db.execute(text(sql)).fetchall()
    return [_row_producto(r) for r in rows]


@router.get("/bajo-stock")
def get_stock_bajo(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            f"SELECT {PRODUCTO_COLS} FROM productos "
            "WHERE stock_minimo > 0 AND stock_actual <= stock_minimo "
            "ORDER BY (stock_actual - stock_minimo) ASC LIMIT 200"
        )
    ).fetchall()
    return [_row_producto(r) for r in rows]


@router.get("/by-detalle/{detalle}")
def get_producto_by_detalle(detalle: str, db: Session = Depends(get_db)):
    row = db.execute(
        text(f"SELECT {PRODUCTO_COLS} FROM productos WHERE LOWER(TRIM(detalle)) = LOWER(TRIM(:d))"),
        {"d": detalle},
    ).first()
    return _row_producto(row) if row else None


@router.post("")
def save_producto(data: ProductoData, db: Session = Depends(get_db)):
    if data.id is not None:
        old = db.execute(
            text("SELECT stock_actual FROM productos WHERE id = :id"), {"id": data.id}
        ).first()
        old_stock = old[0] if old else 0.0
        db.execute(
            text(
                "UPDATE productos SET detalle=:detalle, precio_unitario=:precio, stock_actual=:stock, "
                "stock_minimo=:minimo, imagen=:imagen WHERE id=:id"
            ),
            {
                "id": data.id, "detalle": data.detalle, "precio": data.precio_unitario,
                "stock": data.stock_actual, "minimo": data.stock_minimo, "imagen": data.imagen,
            },
        )
        if data.stock_actual != old_stock:
            registrar_movimiento_stock(
                db, data.id, "ajuste", f"update:{data.id}", data.stock_actual - old_stock,
                old_stock, data.stock_actual,
                f"Ajuste manual de stock: {old_stock:.0f} → {data.stock_actual:.0f}",
            )
        db.commit()
        return data.id

    existing = db.execute(
        text("SELECT id FROM productos WHERE LOWER(TRIM(detalle)) = LOWER(TRIM(:d))"), {"d": data.detalle}
    ).first()
    if existing:
        pid = existing[0]
        old = db.execute(text("SELECT stock_actual FROM productos WHERE id = :id"), {"id": pid}).first()
        old_stock = old[0] if old else 0.0
        db.execute(
            text(
                "UPDATE productos SET precio_unitario=:precio, stock_actual=:stock, stock_minimo=:minimo, "
                "imagen=:imagen WHERE id=:id"
            ),
            {
                "id": pid, "precio": data.precio_unitario, "stock": data.stock_actual,
                "minimo": data.stock_minimo, "imagen": data.imagen,
            },
        )
        if data.stock_actual != old_stock:
            registrar_movimiento_stock(
                db, pid, "ajuste", f"update:{pid}", data.stock_actual - old_stock,
                old_stock, data.stock_actual,
                f"Ajuste manual de stock: {old_stock:.0f} → {data.stock_actual:.0f}",
            )
        db.commit()
        return pid

    new_id = exec_insert(
        db, "productos",
        ["detalle", "precio_unitario", "stock_actual", "stock_minimo", "stock_reservado_factura", "imagen"],
        {
            "detalle": data.detalle, "precio_unitario": data.precio_unitario, "stock_actual": data.stock_actual,
            "stock_minimo": data.stock_minimo, "stock_reservado_factura": 0.0, "imagen": data.imagen,
        },
    )
    if data.stock_actual > 0.0:
        registrar_movimiento_stock(
            db, new_id, "inicial", "creacion", data.stock_actual, 0.0, data.stock_actual,
            f"Stock inicial al crear producto: {data.stock_actual:.0f}",
        )
    db.commit()
    return new_id


@router.post("/{prod_id}/ajustar-stock")
def ajustar_stock(prod_id: int, delta: float, db: Session = Depends(get_db)):
    nuevo = ajustar_stock_inner(db, prod_id, delta)
    db.commit()
    return nuevo


@router.get("/{prod_id}/dependencies")
def get_producto_dependencies(prod_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text(
            "SELECT detalle, stock_actual, stock_reservado_factura, stock_reservado_produccion "
            "FROM productos WHERE id = :id"
        ),
        {"id": prod_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    detalle, stock_actual, stock_reservado_factura, stock_reservado_produccion = row
    factura_items = db.execute(
        text("SELECT COUNT(*) FROM factura_items WHERE producto_id = :id"), {"id": prod_id}
    ).scalar() or 0
    if factura_items == 0 and detalle:
        factura_items = db.execute(
            text("SELECT COUNT(*) FROM factura_items WHERE LOWER(TRIM(detalle)) = LOWER(TRIM(:d))"),
            {"d": detalle},
        ).scalar() or 0
    ordenes_produccion = db.execute(
        text("SELECT COUNT(*) FROM ordenes_produccion WHERE LOWER(TRIM(detalle)) = LOWER(TRIM(:d))"),
        {"d": detalle},
    ).scalar() or 0
    stock_movements = db.execute(
        text("SELECT COUNT(*) FROM stock_movements WHERE producto_id = :id"), {"id": prod_id}
    ).scalar() or 0
    return {
        "detalle": detalle, "stock_actual": stock_actual,
        "stock_reservado_factura": stock_reservado_factura, "stock_reservado_produccion": stock_reservado_produccion,
        "factura_items": factura_items, "ordenes_produccion": ordenes_produccion, "stock_movements": stock_movements,
    }


@router.delete("/{prod_id}")
def delete_producto(prod_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM productos WHERE id = :id"), {"id": prod_id})
    db.commit()
    return {"status": "ok"}


@router.get("/{prod_id}/stock-movements")
def get_stock_movements(prod_id: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT id, producto_id, fecha_hora, tipo, referencia, cantidad, stock_anterior, stock_nuevo, detalle "
            "FROM stock_movements WHERE producto_id = :id ORDER BY fecha_hora DESC LIMIT 100"
        ),
        {"id": prod_id},
    ).fetchall()
    return [
        {
            "id": r[0], "producto_id": r[1], "fecha_hora": r[2], "tipo": r[3], "referencia": r[4],
            "cantidad": r[5], "stock_anterior": r[6], "stock_nuevo": r[7], "detalle": r[8],
        }
        for r in rows
    ]


@router.get("/verificar-integridad")
def verificar_integridad_stock(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, detalle, stock_actual FROM productos")).fetchall()
    inconsistencias = []
    for pid, detalle, real in rows:
        total_mov = db.execute(
            text("SELECT COALESCE(SUM(cantidad), 0) FROM stock_movements WHERE producto_id = :id"),
            {"id": pid},
        ).scalar() or 0.0
        if abs(total_mov - real) > 0.001:
            inconsistencias.append({
                "id": pid, "detalle": detalle, "stock_actual": real,
                "stock_segun_movimientos": total_mov, "diferencia": real - total_mov,
            })
    return inconsistencias


@router.post("/recalcular-stock")
def recalcular_stock_desde_movimientos(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, detalle, stock_actual FROM productos")).fetchall()
    inconsistencias = []
    for pid, _detalle, real in rows:
        total_mov = db.execute(
            text("SELECT COALESCE(SUM(cantidad), 0) FROM stock_movements WHERE producto_id = :id"),
            {"id": pid},
        ).scalar() or 0.0
        if abs(total_mov - real) > 0.001:
            inconsistencias.append((pid, real, total_mov))
    corregidos = 0
    for pid, real, suma in inconsistencias:
        if suma < 0.0:
            registrar_movimiento_stock(db, pid, "ajuste", "recalcular", -suma, suma, 0.0,
                                       "Ajuste por recálculo (suma movs negativa)")
            db.execute(text("UPDATE productos SET stock_actual = 0.0 WHERE id = :id"), {"id": pid})
        elif abs(suma - real) > 0.001:
            registrar_movimiento_stock(db, pid, "ajuste", "recalcular", real - suma, suma, real,
                                       "Ajuste por recálculo de integridad")
        corregidos += 1
    db.commit()
    return corregidos


@router.post("/{prod_id}/imagen")
async def upload_producto_imagen(prod_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not storage.storage_available():
        raise HTTPException(status_code=503, detail="Storage no configurado (faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "png"
    data = await file.read()
    path = storage.build_path(f"producto-{prod_id}", ext)
    storage.upload_bytes(storage.BUCKET_PRODUCTOS, path, data, f"image/{ext}")
    url = storage.public_url(storage.BUCKET_PRODUCTOS, path)
    db.execute(text("UPDATE productos SET imagen = :url WHERE id = :id"), {"url": url, "id": prod_id})
    db.commit()
    return {"url": url}


@router.get("/{prod_id}/imagen")
def get_producto_imagen(prod_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT imagen FROM productos WHERE id = :id"), {"id": prod_id}).first()
    if not row or not row[0]:
        return None
    return {"url": row[0]}