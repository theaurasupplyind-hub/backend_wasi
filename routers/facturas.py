"""Router /facturas — port de commands/facturas.rs (transaccional).

Incluye la numeración F-XXXXX con factura_seq (lock FOR UPDATE en Postgres)
y el guardado atómico (revertir → save/update → stock inicial → procesar).
"""
import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import SessionLocal, get_db, IS_POSTGRES
from auth import verify_api_key
from db_utils import exec_insert, now_dm_YHM, now_dm_YHMS, scalar_max

router = APIRouter(prefix="/facturas", tags=["facturas"], dependencies=[Depends(verify_api_key)])

FACTURA_COLS = (
    "id, numero, fecha, cliente_nombre, total, estado, entrega_estado, "
    "domicilio, telefono, taller, galeria, envio, tipo_entrega, fecha_estimada, "
    "notas, descuento_tipo, descuento_valor, dni, provincia, sucursal_recibir, cp"
)

_LOCK = " FOR UPDATE" if IS_POSTGRES else ""


class FacturaItem(BaseModel):
    id: int | None = None
    cantidad: float = 1
    detalle: str = ""
    precio_unitario: float = 0
    total: float = 0
    producto_id: int | None = None


class FacturaData(BaseModel):
    fecha: str = ""
    cliente: str = ""
    domicilio: str = ""
    telefono: str = ""
    dni: str = ""
    provincia: str = ""
    sucursal_recibir: str = ""
    cp: str = ""
    taller: str = ""
    galeria: str = ""
    envio: float = 0
    total: float = 0
    tipo_entrega: str = ""
    fecha_estimada: str = ""
    descuento_tipo: str = "percent"
    descuento_valor: float = 0
    items: list[FacturaItem] = []


class GuardarFacturaRequest(BaseModel):
    data: FacturaData
    numero_opcional: str | None = None
    stocks_iniciales: dict[str, float] = {}


def _fin(x) -> bool:
    return isinstance(x, float) and math.isfinite(x)


def _row_factura(row) -> dict:
    return {
        "id": row[0], "numero": row[1], "fecha": row[2], "cliente_nombre": row[3],
        "total": row[4], "estado": row[5], "entrega_estado": row[6],
        "domicilio": row[7], "telefono": row[8], "taller": row[9], "galeria": row[10],
        "envio": row[11], "tipo_entrega": row[12], "fecha_estimada": row[13],
        "notas": row[14], "descuento_tipo": row[15], "descuento_valor": row[16],
        "dni": row[17], "provincia": row[18], "sucursal_recibir": row[19], "cp": row[20],
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


def registrar_actividad(db, tipo, descripcion, referencia) -> None:
    exec_insert(
        db, "actividad_reciente",
        ["fecha", "tipo", "descripcion", "referencia"],
        {"fecha": now_dm_YHM(), "tipo": tipo, "descripcion": descripcion, "referencia": referencia},
    )


def cancelar_ordenes_de_factura(db, numero: str) -> None:
    db.execute(
        text("UPDATE ordenes_produccion SET estado = 'Cancelada' WHERE numero_factura = :n AND estado = 'Pendiente'"),
        {"n": numero},
    )


def _next_numero(db) -> str:
    row = db.execute(text(f"SELECT counter FROM factura_seq WHERE id = 1{_LOCK}")).first()
    if row is None:
        db.execute(text("INSERT INTO factura_seq (id, counter) VALUES (1, 10249) ON CONFLICT (id) DO NOTHING"))
        counter = 10249
    else:
        counter = row[0]
    n = counter + 1
    db.execute(text("UPDATE factura_seq SET counter = :c WHERE id = 1"), {"c": n})
    return f"F-{n}"


def _find_producto_id(db, detalle: str) -> int | None:
    row = db.execute(
        text("SELECT id FROM productos WHERE LOWER(TRIM(detalle)) = LOWER(TRIM(:d))"), {"d": detalle}
    ).first()
    return row[0] if row else None


def _saldo_cliente(db, cliente_id: int) -> float:
    return db.execute(
        text("SELECT COALESCE(SUM(debe - haber), 0) FROM cuenta_corriente WHERE cliente_id = :id"),
        {"id": cliente_id},
    ).scalar() or 0.0


def _upsert_cliente(db, data: FacturaData) -> int | None:
    """Auto-crea/actualiza el cliente a partir de los datos de la factura. Devuelve su id o None."""
    cliente_nombre = data.cliente.strip()
    if not cliente_nombre:
        return None
    row = db.execute(
        text("SELECT id FROM clientes WHERE LOWER(TRIM(nombre)) = LOWER(TRIM(:n))"), {"n": cliente_nombre}
    ).first()
    if row:
        cid = row[0]
        db.execute(
            text(
                "UPDATE clientes SET domicilio=:domicilio, telefono=:telefono, dni=:dni, provincia=:provincia, "
                "sucursal_recibir=:sucursal_recibir, cp=:cp, taller=:taller, galeria=:galeria WHERE id=:id"
            ),
            {
                "id": cid, "domicilio": data.domicilio, "telefono": data.telefono, "dni": data.dni,
                "provincia": data.provincia, "sucursal_recibir": data.sucursal_recibir, "cp": data.cp,
                "taller": data.taller, "galeria": data.galeria,
            },
        )
        return cid
    return exec_insert(
        db, "clientes",
        ["nombre", "domicilio", "telefono", "dni", "provincia", "sucursal_recibir", "cp", "taller", "galeria"],
        {
            "nombre": cliente_nombre, "domicilio": data.domicilio, "telefono": data.telefono,
            "dni": data.dni, "provincia": data.provincia, "sucursal_recibir": data.sucursal_recibir,
            "cp": data.cp, "taller": data.taller, "galeria": data.galeria,
        },
    )


def _insert_items(db, factura_id: int, items: list[FacturaItem]) -> None:
    for item in items:
        detalle = item.detalle.strip()
        if not detalle:
            continue
        producto_id = _find_producto_id(db, detalle)
        exec_insert(
            db, "factura_items",
            ["factura_id", "cantidad", "detalle", "precio_unitario", "total", "producto_id"],
            {
                "factura_id": factura_id, "cantidad": item.cantidad, "detalle": detalle,
                "precio_unitario": item.precio_unitario, "total": item.total, "producto_id": producto_id,
            },
        )


def _auto_create_productos(db, items: list[FacturaItem]) -> None:
    for item in items:
        detalle = item.detalle.strip()
        if not detalle:
            continue
        exists = db.execute(
            text("SELECT COUNT(*) FROM productos WHERE LOWER(TRIM(detalle)) = LOWER(TRIM(:d))"),
            {"d": detalle},
        ).scalar() or 0
        if exists == 0:
            exec_insert(
                db, "productos",
                ["detalle", "precio_unitario", "stock_actual", "stock_minimo", "stock_reservado_factura", "imagen"],
                {"detalle": detalle, "precio_unitario": item.precio_unitario, "stock_actual": 0.0,
                 "stock_minimo": 0.0, "stock_reservado_factura": 0.0, "imagen": ""},
            )


def _backfill_producto_id(db, factura_id: int) -> None:
    db.execute(
        text(
            "UPDATE factura_items SET producto_id = "
            "(SELECT id FROM productos WHERE LOWER(TRIM(detalle)) = LOWER(TRIM(factura_items.detalle)) LIMIT 1) "
            "WHERE factura_id = :fid AND producto_id IS NULL"
        ),
        {"fid": factura_id},
    )


def _registrar_cc_factura(db, numero: str, cliente_id: int, total: float) -> None:
    if total <= 0.0:
        return
    saldo_previo = _saldo_cliente(db, cliente_id)
    nuevo_saldo = saldo_previo + total
    exec_insert(
        db, "cuenta_corriente",
        ["cliente_id", "fecha", "tipo", "referencia", "descripcion", "debe", "haber", "saldo"],
        {
            "cliente_id": cliente_id, "fecha": now_dm_YHM(), "tipo": "Factura",
            "referencia": numero, "descripcion": f"Factura {numero}", "debe": total,
            "haber": 0.0, "saldo": nuevo_saldo,
        },
    )


def _save_factura_inner(db, data: FacturaData) -> str:
    if not _fin(data.total) or data.total < 0.0:
        raise HTTPException(status_code=400, detail="El total de la factura debe ser válido y no negativo")
    numero = _next_numero(db)
    fecha = data.fecha.strip() or now_dm_YHM()[:10]
    factura_id = exec_insert(
        db, "facturas",
        ["numero", "fecha", "cliente_nombre", "domicilio", "telefono", "dni", "provincia", "sucursal_recibir",
         "cp", "taller", "galeria", "envio", "total", "tipo_entrega", "fecha_estimada", "estado",
         "descuento_tipo", "descuento_valor"],
        {
            "numero": numero, "fecha": fecha, "cliente_nombre": data.cliente, "domicilio": data.domicilio,
            "telefono": data.telefono, "dni": data.dni, "provincia": data.provincia,
            "sucursal_recibir": data.sucursal_recibir, "cp": data.cp, "taller": data.taller,
            "galeria": data.galeria, "envio": data.envio, "total": data.total,
            "tipo_entrega": data.tipo_entrega, "fecha_estimada": data.fecha_estimada, "estado": "Pendiente",
            "descuento_tipo": data.descuento_tipo, "descuento_valor": data.descuento_valor,
        },
    )
    _insert_items(db, factura_id, data.items)
    cliente_id = _upsert_cliente(db, data)
    _auto_create_productos(db, data.items)
    _backfill_producto_id(db, factura_id)
    if cliente_id is not None:
        _registrar_cc_factura(db, numero, cliente_id, data.total)
    registrar_actividad(db, "factura_creada", f"Creada {numero}", numero)
    return numero


def _update_factura_inner(db, numero: str, data: FacturaData) -> str:
    row = db.execute(text("SELECT id FROM facturas WHERE numero = :n"), {"n": numero}).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Factura {numero} no encontrada")
    factura_id = row[0]
    old_cliente = db.execute(
        text("SELECT COALESCE(cliente_nombre, '') FROM facturas WHERE id = :id"), {"id": factura_id}
    ).scalar() or ""
    cobrado = db.execute(
        text("SELECT COALESCE(SUM(haber), 0) FROM cuenta_corriente WHERE referencia = :n AND tipo = 'Pago'"),
        {"n": numero},
    ).scalar() or 0.0
    if not _fin(cobrado) or cobrado < 0.0:
        raise HTTPException(status_code=400, detail="La factura tiene cobros inválidos y no puede editarse")
    if cobrado > 0.0 and old_cliente.strip().lower() != data.cliente.strip().lower():
        raise HTTPException(status_code=400, detail="No se puede cambiar el cliente de una factura con cobros registrados")
    if not _fin(data.total) or data.total < cobrado - 1e-9:
        raise HTTPException(status_code=400, detail=f"El total no puede ser menor que lo cobrado ({cobrado:.2f})")

    fecha = data.fecha.strip() or now_dm_YHM()[:10]
    db.execute(
        text(
            "UPDATE facturas SET fecha=:fecha, cliente_nombre=:cliente, domicilio=:domicilio, telefono=:telefono, "
            "dni=:dni, provincia=:provincia, sucursal_recibir=:sucursal_recibir, cp=:cp, taller=:taller, "
            "galeria=:galeria, envio=:envio, total=:total, tipo_entrega=:tipo_entrega, "
            "fecha_estimada=:fecha_estimada, descuento_tipo=:descuento_tipo, descuento_valor=:descuento_valor "
            "WHERE id=:id"
        ),
        {
            "id": factura_id, "fecha": fecha, "cliente": data.cliente, "domicilio": data.domicilio,
            "telefono": data.telefono, "dni": data.dni, "provincia": data.provincia,
            "sucursal_recibir": data.sucursal_recibir, "cp": data.cp, "taller": data.taller,
            "galeria": data.galeria, "envio": data.envio, "total": data.total,
            "tipo_entrega": data.tipo_entrega, "fecha_estimada": data.fecha_estimada,
            "descuento_tipo": data.descuento_tipo, "descuento_valor": data.descuento_valor,
        },
    )
    db.execute(text("DELETE FROM factura_items WHERE factura_id = :id"), {"id": factura_id})
    _insert_items(db, factura_id, data.items)
    _auto_create_productos(db, data.items)
    _backfill_producto_id(db, factura_id)

    cliente_nombre = data.cliente.strip()
    if cliente_nombre:
        cid = _upsert_cliente(db, data)
        db.execute(
            text("DELETE FROM cuenta_corriente WHERE referencia = :n AND tipo = 'Factura'"), {"n": numero}
        )
        if cid is not None:
            _registrar_cc_factura(db, numero, cid, data.total)
    else:
        db.execute(
            text("DELETE FROM cuenta_corriente WHERE referencia = :n AND tipo = 'Factura'"), {"n": numero}
        )

    estado = "Pagado" if data.total > 0.0 and cobrado >= data.total - 1e-9 else "Pendiente"
    db.execute(text("UPDATE facturas SET estado = :e WHERE id = :id"), {"e": estado, "id": factura_id})
    registrar_actividad(db, "factura_creada", f"Actualizada {numero}", numero)
    return numero


def _procesar_stock_factura_inner(db, numero: str, cliente_nombre: str, items: list[FacturaItem]) -> list[dict]:
    ya_procesado = db.execute(
        text("SELECT COUNT(*) FROM stock_movements WHERE referencia = :n AND tipo = 'factura'"), {"n": numero}
    ).scalar() or 0
    if ya_procesado > 0:
        return []
    ordenes = []
    for item in items:
        detalle = item.detalle.strip()
        cantidad_pedida = item.cantidad
        if not detalle or cantidad_pedida <= 0.0:
            continue
        prod = db.execute(
            text("SELECT id, stock_actual FROM productos WHERE LOWER(TRIM(detalle)) = LOWER(TRIM(:d))"),
            {"d": detalle},
        ).first()
        if not prod:
            continue
        prod_id, stock_actual = prod[0], prod[1]
        a_descontar = min(cantidad_pedida, stock_actual)
        falta = cantidad_pedida - a_descontar
        if a_descontar > 0.0:
            db.execute(
                text(f"UPDATE productos SET stock_actual = {scalar_max('0', 'stock_actual - :a')} WHERE id = :id"),
                {"a": a_descontar, "id": prod_id},
            )
            nuevo = max(stock_actual - a_descontar, 0.0)
            registrar_movimiento_stock(
                db, prod_id, "factura", numero, -a_descontar, stock_actual, nuevo,
                f"{detalle}: {a_descontar:.0f} descontado por factura",
            )
        if falta > 0.0:
            exec_insert(
                db, "ordenes_produccion",
                ["fecha", "numero_factura", "cliente_nombre", "detalle", "cantidad_pedida",
                 "stock_disponible", "cantidad_a_producir", "estado"],
                {
                    "fecha": now_dm_YHM(), "numero_factura": numero, "cliente_nombre": cliente_nombre,
                    "detalle": detalle, "cantidad_pedida": cantidad_pedida, "stock_disponible": a_descontar,
                    "cantidad_a_producir": falta, "estado": "Pendiente",
                },
            )
            ordenes.append({"detalle": detalle, "cantidad_a_producir": falta, "stock_disponible": a_descontar})
    return ordenes


def _revertir_stock_factura_inner(db, numero: str) -> None:
    db.execute(
        text("DELETE FROM stock_movements WHERE referencia = :n AND tipo = 'factura'"), {"n": numero}
    )
    items = db.execute(
        text(
            "SELECT fi.producto_id, fi.cantidad FROM factura_items fi "
            "JOIN facturas f ON f.id = fi.factura_id "
            "WHERE f.numero = :n AND fi.producto_id IS NOT NULL"
        ),
        {"n": numero},
    ).fetchall()
    for prod_id, cantidad in items:
        if prod_id is None or cantidad <= 0.0:
            continue
        db.execute(
            text("UPDATE productos SET stock_actual = stock_actual + :c WHERE id = :id"),
            {"c": cantidad, "id": prod_id},
        )
    cancelar_ordenes_de_factura(db, numero)


def _ajustar_stock_inner(db, prod_id: int, delta: float) -> float:
    stock_actual = db.execute(
        text("SELECT stock_actual FROM productos WHERE id = :id"), {"id": prod_id}
    ).scalar() or 0.0
    nuevo = max(stock_actual + delta, 0.0)
    db.execute(
        text("UPDATE productos SET stock_actual = :nuevo WHERE id = :id"),
        {"nuevo": nuevo, "id": prod_id},
    )
    registrar_movimiento_stock(
        db, prod_id, "ajuste", f"manual:{delta:+.0f}", delta, stock_actual, nuevo,
        f"Ajuste manual: {delta:+.0f} unidades",
    )
    return nuevo


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("")
def get_facturas(limit: int, offset: int, search: str, db: Session = Depends(get_db)):
    base = f"SELECT {FACTURA_COLS} FROM facturas f WHERE 1=1"
    params = {"limit": limit, "offset": offset}
    if search:
        like = f"%{search}%"
        base += " AND (f.numero LIKE :like OR f.cliente_nombre LIKE :like OR f.fecha LIKE :like)"
        params["like"] = like
    base += " ORDER BY f.id DESC LIMIT :limit OFFSET :offset"
    rows = db.execute(text(base), params).fetchall()
    return [_row_factura(r) for r in rows]


@router.get("/{numero}")
def get_factura_by_numero(numero: str, db: Session = Depends(get_db)):
    row = db.execute(
        text(f"SELECT {FACTURA_COLS} FROM facturas WHERE numero = :n"), {"n": numero}
    ).first()
    if not row:
        return None
    factura = _row_factura(row)
    items = db.execute(
        text(
            "SELECT id, cantidad, detalle, precio_unitario, total, producto_id "
            "FROM factura_items WHERE factura_id = :id"
        ),
        {"id": factura["id"]},
    ).fetchall()
    factura["items"] = [
        {"id": it[0], "cantidad": it[1], "detalle": it[2], "precio_unitario": it[3], "total": it[4], "producto_id": it[5]}
        for it in items
    ]
    return factura


@router.post("/{numero}/estado")
def update_factura_estado(factura_id: int, estado: str, db: Session = Depends(get_db)):
    db.execute(text("UPDATE facturas SET estado = :e WHERE id = :id"), {"e": estado, "id": factura_id})
    db.commit()
    return {"status": "ok"}


@router.delete("/{numero}")
def delete_factura(numero: str, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT id, COALESCE(cliente_nombre, '') FROM facturas WHERE numero = :n"), {"n": numero}
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    factura_id, cliente_nombre = row[0], row[1]
    pagos = db.execute(
        text("SELECT COUNT(*) FROM cuenta_corriente WHERE referencia = :n AND tipo = 'Pago' AND haber > 0"),
        {"n": numero},
    ).scalar() or 0
    if pagos > 0:
        raise HTTPException(
            status_code=400,
            detail="No se puede eliminar una factura con cobros registrados. Anule o regularice sus cobros primero",
        )
    if cliente_nombre.strip():
        cli = db.execute(
            text("SELECT id FROM clientes WHERE LOWER(TRIM(nombre)) = LOWER(TRIM(:n))"), {"n": cliente_nombre}
        ).first()
        if cli:
            db.execute(
                text("DELETE FROM cuenta_corriente WHERE cliente_id = :cid AND referencia = :n AND tipo = 'Factura'"),
                {"cid": cli[0], "n": numero},
            )
    items = db.execute(
        text("SELECT fi.producto_id, fi.cantidad FROM factura_items fi WHERE fi.factura_id = :id AND fi.producto_id IS NOT NULL"),
        {"id": factura_id},
    ).fetchall()
    for prod_id, cantidad in items:
        if prod_id is None or cantidad <= 0.0:
            continue
        stock_actual = db.execute(
            text("SELECT stock_actual FROM productos WHERE id = :id"), {"id": prod_id}
        ).scalar() or 0.0
        db.execute(
            text("UPDATE productos SET stock_actual = stock_actual + :c WHERE id = :id"),
            {"c": cantidad, "id": prod_id},
        )
        registrar_movimiento_stock(
            db, prod_id, "reversion", f"delete:{numero}", cantidad, stock_actual, stock_actual + cantidad,
            f"Restaurado a stock al eliminar factura {numero}",
        )
    cancelar_ordenes_de_factura(db, numero)
    db.execute(text("DELETE FROM factura_items WHERE factura_id = :id"), {"id": factura_id})
    db.execute(text("DELETE FROM facturas WHERE id = :id"), {"id": factura_id})
    registrar_actividad(db, "factura_eliminada", f"Eliminada {numero}", numero)
    db.commit()
    return {"status": "ok"}


@router.get("/{numero}/movimientos")
def get_stock_movements_by_reference(referencia: str, db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT sm.id, sm.producto_id, sm.fecha_hora, sm.tipo, sm.referencia, sm.cantidad, "
            "sm.stock_anterior, sm.stock_nuevo, sm.detalle, p.detalle "
            "FROM stock_movements sm JOIN productos p ON p.id = sm.producto_id "
            "WHERE sm.referencia = :ref ORDER BY sm.fecha_hora"
        ),
        {"ref": referencia},
    ).fetchall()
    return [
        {
            "id": r[0], "producto_id": r[1], "fecha_hora": r[2], "tipo": r[3], "referencia": r[4],
            "cantidad": r[5], "stock_anterior": r[6], "stock_nuevo": r[7], "detalle": r[8],
            "producto_detalle": r[9],
        }
        for r in rows
    ]


@router.get("/{numero}/dependencies")
def get_factura_dependencies(numero: str, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT id, estado, entrega_estado, total FROM facturas WHERE numero = :n"), {"n": numero}
    ).first()
    if not row:
        return None
    factura_id, estado, entrega_estado, total = row
    items_count = db.execute(
        text("SELECT COUNT(*) FROM factura_items WHERE factura_id = :id"), {"id": factura_id}
    ).scalar() or 0
    cc_count = db.execute(
        text("SELECT COUNT(*) FROM cuenta_corriente WHERE referencia = :n AND tipo = 'Factura'"), {"n": numero}
    ).scalar() or 0
    return {
        "id": factura_id, "estado": estado, "entrega_estado": entrega_estado, "total": total,
        "items_count": items_count, "cuenta_corriente_count": cc_count,
    }


@router.get("/pendientes-cliente/{cliente_nombre}")
def get_facturas_pendientes_cliente(cliente_nombre: str, db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT f.id, f.numero, f.fecha, f.total, "
            "COALESCE((SELECT SUM(cc.haber) FROM cuenta_corriente cc "
            "JOIN clientes cl ON cl.id = cc.cliente_id "
            "WHERE cl.nombre = f.cliente_nombre AND cc.referencia = f.numero AND cc.tipo = 'Pago'), 0) AS cobrado "
            "FROM facturas f WHERE f.cliente_nombre = :n AND f.estado = 'Pendiente' ORDER BY f.id DESC"
        ),
        {"n": cliente_nombre},
    ).fetchall()
    facturas = [
        {"id": r[0], "numero": r[1], "fecha": r[2], "total": r[3], "cobrado": r[4]} for r in rows
    ]
    if not facturas:
        return facturas
    saldo_real = db.execute(
        text(
            "SELECT COALESCE(SUM(cc.debe - cc.haber), 0) FROM cuenta_corriente cc "
            "JOIN clientes cl ON cl.id = cc.cliente_id WHERE cl.nombre = :n"
        ),
        {"n": cliente_nombre},
    ).scalar() or 0.0
    total_oficial = sum(f["total"] - f["cobrado"] for f in facturas)
    if total_oficial > saldo_real:
        exceso = total_oficial - saldo_real
        for f in reversed(facturas):
            if exceso <= 0.0:
                break
            restante = f["total"] - f["cobrado"]
            if restante <= 0.0:
                continue
            aplicar = min(restante, exceso)
            f["cobrado"] += aplicar
            exceso -= aplicar
    return facturas


@router.post("/guardar")
def guardar_factura(payload: GuardarFacturaRequest):
    """Guardado atómico: revertir → save/update → stock inicial → procesar, en una transacción."""
    with SessionLocal() as db:
        with db.begin():
            if payload.numero_opcional:
                _revertir_stock_factura_inner(db, payload.numero_opcional)
                numero = _update_factura_inner(db, payload.numero_opcional, payload.data)
            else:
                numero = _save_factura_inner(db, payload.data)
            for detalle, stock in payload.stocks_iniciales.items():
                if stock <= 0.0:
                    continue
                pid = _find_producto_id(db, detalle)
                if pid is not None:
                    _ajustar_stock_inner(db, pid, stock)
            ordenes = _procesar_stock_factura_inner(db, numero, payload.data.cliente, payload.data.items)
        return {"numero": numero, "ordenes": ordenes}