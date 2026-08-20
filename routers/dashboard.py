"""Router /dashboard — port de commands/dashboard.rs."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from auth import verify_api_key
from db_utils import now_dm_YHM, scalar_max, exec_insert, where_fecha, fmt_date_for_sql

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(verify_api_key)])


def registrar_actividad(db, tipo, descripcion, referencia) -> None:
    exec_insert(
        db, "actividad_reciente",
        ["fecha", "tipo", "descripcion", "referencia"],
        {"fecha": now_dm_YHM(), "tipo": tipo, "descripcion": descripcion, "referencia": referencia},
    )


class CobroRequest(BaseModel):
    factura_id: int
    numero_factura: str
    cliente_id: int | None = None
    cliente_nombre: str = ""
    monto: float
    medio_pago: str
    nota: str = ""


@router.get("/stats")
def get_dashboard_stats(fecha_desde: str = "", fecha_hasta: str = "", db: Session = Depends(get_db)):
    clauses, _ = where_fecha(fecha_desde, fecha_hasta, "f")
    params = _params_fecha(fecha_desde, fecha_hasta)
    total_facturado = db.execute(
        text(f"SELECT COALESCE(SUM(total), 0) FROM facturas f WHERE {clauses}"), params
    ).scalar() or 0.0
    total_cobrado = db.execute(
        text(f"SELECT COALESCE(SUM(total), 0) FROM facturas f WHERE f.estado = 'Pagado' AND {clauses}"), params
    ).scalar() or 0.0
    total_pendiente = db.execute(
        text(f"SELECT COALESCE(SUM(total), 0) FROM facturas f WHERE f.estado = 'Pendiente' AND {clauses}"), params
    ).scalar() or 0.0
    count_facturas = db.execute(
        text(f"SELECT COUNT(*) FROM facturas f WHERE {clauses}"), params
    ).scalar() or 0
    count_pendiente = db.execute(
        text(f"SELECT COUNT(*) FROM facturas f WHERE f.estado = 'Pendiente' AND {clauses}"), params
    ).scalar() or 0
    stock_bajo_count = db.execute(
        text("SELECT COUNT(*) FROM productos WHERE stock_minimo > 0 AND stock_actual <= stock_minimo")
    ).scalar() or 0
    count_ordenes = db.execute(
        text("SELECT COUNT(*) FROM ordenes_produccion WHERE estado IN ('Pendiente', 'En proceso')")
    ).scalar() or 0
    return {
        "total_facturado": total_facturado, "total_cobrado": total_cobrado,
        "total_pendiente": total_pendiente, "count_facturas": count_facturas,
        "count_pendiente": count_pendiente, "stock_bajo_count": stock_bajo_count,
        "count_ordenes_produccion": count_ordenes,
    }


def _params_fecha(fecha_desde: str, fecha_hasta: str) -> dict:
    out = {}
    if fecha_desde:
        out["fecha_desde"] = fmt_date_for_sql(fecha_desde)
    if fecha_hasta:
        out["fecha_hasta"] = fmt_date_for_sql(fecha_hasta)
    return out


@router.get("/facturas-recientes")
def get_facturas_recientes(fecha_desde: str = "", fecha_hasta: str = "", db: Session = Depends(get_db)):
    where_clause, _ = where_fecha(fecha_desde, fecha_hasta, "f")
    params = _params_fecha(fecha_desde, fecha_hasta)
    rows = db.execute(
        text(
            f"SELECT f.id, f.numero, f.fecha, f.cliente_nombre, f.total, f.estado, f.entrega_estado, "
            f"COALESCE((SELECT SUM(cc.haber) FROM cuenta_corriente cc "
            f"JOIN clientes cl ON cl.id = cc.cliente_id "
            f"WHERE cl.nombre = f.cliente_nombre AND cc.referencia = f.numero AND cc.tipo = 'Pago'), 0) AS cobrado "
            f"FROM facturas f WHERE {where_clause} ORDER BY f.id DESC LIMIT 50"
        ),
        params,
    ).fetchall()
    return [
        {
            "id": r[0], "numero": r[1], "fecha": r[2], "cliente_nombre": r[3], "total": r[4],
            "estado": r[5], "entrega_estado": r[6], "cobrado": r[7],
        }
        for r in rows
    ]


@router.get("/actividad-reciente")
def get_actividad_reciente(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT fecha, tipo, descripcion, referencia FROM actividad_reciente "
            "WHERE tipo <> 'Gasto' ORDER BY id DESC LIMIT 10"
        )
    ).fetchall()
    return [{"fecha": r[0], "tipo": r[1], "descripcion": r[2], "referencia": r[3]} for r in rows]


@router.get("/facturas-all")
def get_facturas_all(desde: str, hasta: str, limit: int, offset: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT f.id, f.numero, f.fecha, f.cliente_nombre, f.total, f.estado, f.entrega_estado, "
            "COALESCE((SELECT SUM(cc.haber) FROM cuenta_corriente cc "
            "WHERE cc.referencia = f.numero AND cc.tipo = 'Pago'), 0) AS cobrado "
            "FROM facturas f "
            "WHERE (SUBSTR(f.fecha, 7, 4) || SUBSTR(f.fecha, 4, 2) || SUBSTR(f.fecha, 1, 2)) >= :desde "
            "AND (SUBSTR(f.fecha, 7, 4) || SUBSTR(f.fecha, 4, 2) || SUBSTR(f.fecha, 1, 2)) <= :hasta "
            "ORDER BY f.id DESC LIMIT :limit OFFSET :offset"
        ),
        {"desde": fmt_date_for_sql(desde), "hasta": fmt_date_for_sql(hasta), "limit": limit, "offset": offset},
    ).fetchall()
    return [
        {
            "id": r[0], "numero": r[1], "fecha": r[2], "cliente_nombre": r[3], "total": r[4],
            "estado": r[5], "entrega_estado": r[6], "cobrado": r[7],
        }
        for r in rows
    ]


@router.post("/entrega-estado")
def update_entrega_estado(factura_id: int, entrega_estado: str, db: Session = Depends(get_db)):
    db.execute(
        text("UPDATE facturas SET entrega_estado = :e WHERE id = :id"),
        {"e": entrega_estado, "id": factura_id},
    )
    db.commit()
    return {"status": "ok"}


@router.post("/actividad")
def registrar_actividad_endpoint(tipo: str, descripcion: str, referencia: str, db: Session = Depends(get_db)):
    registrar_actividad(db, tipo, descripcion, referencia)
    db.commit()
    return {"status": "ok"}


@router.post("/confirmar-despacho")
def confirmar_despacho(factura_id: int, nota: str = "", db: Session = Depends(get_db)):
    notas_previas = db.execute(
        text("SELECT COALESCE(notas, '') FROM facturas WHERE id = :id"), {"id": factura_id}
    ).scalar() or ""
    fecha_despacho = now_dm_YHM()
    nueva_nota = f"[Despachado {fecha_despacho}]" if not nota.strip() else f"[Despacho {fecha_despacho}] {nota.strip()}"
    notas_final = f"{notas_previas.strip()}\n{nueva_nota}".strip()
    db.execute(
        text("UPDATE facturas SET entrega_estado = 'Entregado', fecha_despacho = :fd, notas = :notas WHERE id = :id"),
        {"fd": fecha_despacho, "notas": notas_final, "id": factura_id},
    )
    _liberar_stock_factura_inner(db, factura_id)
    num = db.execute(text("SELECT numero FROM facturas WHERE id = :id"), {"id": factura_id}).first()
    if num:
        registrar_actividad(db, "despacho", f"Despacho {num[0]} — {fecha_despacho}", num[0])
    db.commit()
    return {"status": "ok"}


@router.post("/revertir-despacho")
def revertir_despacho(factura_id: int, db: Session = Depends(get_db)):
    db.execute(
        text("UPDATE facturas SET entrega_estado = 'No entregado' WHERE id = :id"), {"id": factura_id}
    )
    num = db.execute(text("SELECT numero FROM facturas WHERE id = :id"), {"id": factura_id}).first()
    if num:
        registrar_actividad(db, "despacho", f"Despacho revertido — {num[0]}", num[0])
    db.commit()
    return {"status": "ok"}


def _liberar_stock_factura_inner(db, factura_id: int) -> None:
    items = db.execute(
        text("SELECT fi.producto_id, fi.cantidad FROM factura_items fi WHERE fi.factura_id = :id AND fi.producto_id IS NOT NULL"),
        {"id": factura_id},
    ).fetchall()
    for producto_id, cantidad in items:
        db.execute(
            text(f"UPDATE productos SET stock_reservado_factura = {scalar_max('0', 'stock_reservado_factura - :c')} WHERE id = :id"),
            {"c": cantidad, "id": producto_id},
        )


@router.post("/liberar-stock")
def liberar_stock_factura(factura_id: int, db: Session = Depends(get_db)):
    _liberar_stock_factura_inner(db, factura_id)
    db.commit()
    return {"status": "ok"}


@router.get("/tiene-produccion-pendiente")
def tiene_produccion_pendiente(factura_id: int, db: Session = Depends(get_db)):
    count = db.execute(
        text(
            "SELECT COUNT(*) FROM ordenes_produccion op JOIN facturas f ON f.numero = op.numero_factura "
            "WHERE f.id = :id AND op.estado = 'Pendiente'"
        ),
        {"id": factura_id},
    ).scalar() or 0
    return count > 0


@router.post("/cancelar-ordenes-produccion")
def cancelar_ordenes_produccion_de_factura(numero_factura: str, db: Session = Depends(get_db)):
    db.execute(
        text("UPDATE ordenes_produccion SET estado = 'Cancelada' WHERE numero_factura = :n AND estado = 'Pendiente'"),
        {"n": numero_factura},
    )
    db.commit()
    return {"status": "ok"}


@router.post("/cobro")
def registrar_cobro_factura(payload: CobroRequest):
    with SessionLocal() as db:
        with db.begin():
            result = _registrar_cobro_factura_inner(db, payload)
        return result


def _registrar_cobro_factura_inner(db, payload: CobroRequest) -> dict:
    monto = payload.monto
    if not isinstance(monto, float) or not __import__("math").isfinite(monto) or monto <= 0.0:
        raise HTTPException(status_code=400, detail="El monto del cobro debe ser mayor que cero")
    row = db.execute(
        text("SELECT COALESCE(total, 0), COALESCE(cliente_nombre, '') FROM facturas WHERE id = :id AND numero = :n"),
        {"id": payload.factura_id, "n": payload.numero_factura},
    ).first()
    if not row:
        raise HTTPException(status_code=400, detail="La factura no existe o el número no coincide")
    total, factura_cliente = row[0], row[1]
    if not isinstance(total, float) or not __import__("math").isfinite(total) or total <= 0.0:
        raise HTTPException(status_code=400, detail="La factura no tiene un total cobrable")

    if payload.cliente_id is not None:
        cli = db.execute(text("SELECT id FROM clientes WHERE id = :id"), {"id": payload.cliente_id}).first()
        if not cli:
            raise HTTPException(status_code=400, detail="Cliente no encontrado")
        cid = cli[0]
    else:
        lookup = factura_cliente if factura_cliente.strip() else payload.cliente_nombre
        cli = db.execute(
            text("SELECT id FROM clientes WHERE LOWER(TRIM(nombre)) = LOWER(TRIM(:n))"), {"n": lookup}
        ).first()
        if not cli:
            raise HTTPException(status_code=400, detail="Cliente no encontrado")
        cid = cli[0]

    cobrado_previo = db.execute(
        text("SELECT COALESCE(SUM(haber), 0) FROM cuenta_corriente WHERE cliente_id = :cid AND referencia = :n AND tipo = 'Pago'"),
        {"cid": cid, "n": payload.numero_factura},
    ).scalar() or 0.0
    saldo_antes = max(total - cobrado_previo, 0.0)
    saldo_restante = max(saldo_antes - monto, 0.0)

    cc_saldo = db.execute(
        text("SELECT COALESCE(SUM(debe - haber), 0) FROM cuenta_corriente WHERE cliente_id = :cid"),
        {"cid": cid},
    ).scalar() or 0.0
    nuevo_cc_saldo = cc_saldo - monto
    now = now_dm_YHM()
    desc = f"Cobro {payload.numero_factura} — {payload.medio_pago} — {payload.nota}"

    cc_id = exec_insert(
        db, "cuenta_corriente",
        ["cliente_id", "fecha", "tipo", "referencia", "descripcion", "debe", "haber", "saldo"],
        {"cliente_id": cid, "fecha": now, "tipo": "Pago", "referencia": payload.numero_factura,
         "descripcion": desc, "debe": 0.0, "haber": monto, "saldo": nuevo_cc_saldo},
    )

    estado_nuevo = "Pendiente"
    if saldo_restante <= 0.0:
        estado_nuevo = "Pagado"
        db.execute(text("UPDATE facturas SET estado = 'Pagado' WHERE id = :id"), {"id": payload.factura_id})

    concepto = f"Cobro {payload.medio_pago} — Factura {payload.numero_factura} — {factura_cliente}"
    if payload.nota.strip():
        concepto += f" — {payload.nota.strip()}"
    exec_insert(
        db, "movimientos_wasi",
        ["fecha", "tipo", "categoria", "concepto", "monto", "factura_id", "cuenta_corriente_id"],
        {"fecha": now, "tipo": "Ingreso", "categoria": payload.medio_pago, "concepto": concepto,
         "monto": monto, "factura_id": payload.factura_id, "cuenta_corriente_id": cc_id},
    )
    registrar_actividad(db, "cobro", f"Cobro {payload.numero_factura} — {payload.medio_pago}", payload.numero_factura)
    return {"saldo_restante": saldo_restante, "estado_nuevo": estado_nuevo}