"""Router /cuenta-corriente — port de commands/cuenta_corriente.rs."""
import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from auth import verify_api_key
from db_utils import exec_insert, now_dm_YHM

router = APIRouter(prefix="/cuenta-corriente", tags=["cuenta_corriente"], dependencies=[Depends(verify_api_key)])


class MovimientoClienteData(BaseModel):
    cliente_id: int
    tipo: str
    monto: float
    referencia: str = ""
    descripcion: str = ""
    es_pago: bool = False


class UpdateMovimientoClienteData(BaseModel):
    debe: float
    haber: float
    descripcion: str = ""
    tipo: str = ""


def _map_mov(row) -> dict:
    return {
        "id": row[0], "cliente_id": row[1], "fecha": row[2], "tipo": row[3], "referencia": row[4],
        "descripcion": row[5], "debe": row[6], "haber": row[7], "saldo": row[8],
    }


def _recalcular_saldos(db, cliente_id: int) -> None:
    movs = [r[0] for r in db.execute(
        text("SELECT id FROM cuenta_corriente WHERE cliente_id = :id ORDER BY id ASC"), {"id": cliente_id}
    ).fetchall()]
    saldo = 0.0
    for mid in movs:
        d, h = db.execute(text("SELECT debe, haber FROM cuenta_corriente WHERE id = :id"), {"id": mid}).first()
        saldo += d - h
        db.execute(text("UPDATE cuenta_corriente SET saldo = :s WHERE id = :id"), {"s": saldo, "id": mid})


@router.get("/clientes/{cliente_id}/movimientos")
def get_movimientos_cliente(cliente_id: int, limit: int = 100, offset: int = 0, mes: str = "", db: Session = Depends(get_db)):
    if mes:
        rows = db.execute(
            text(
                "SELECT id, cliente_id, fecha, tipo, referencia, descripcion, debe, haber, saldo "
                "FROM cuenta_corriente WHERE cliente_id = :id AND SUBSTR(fecha, 4, 7) = :mes "
                "ORDER BY id DESC LIMIT :lim OFFSET :off"
            ),
            {"id": cliente_id, "mes": mes, "lim": limit, "off": offset},
        ).fetchall()
    else:
        rows = db.execute(
            text(
                "SELECT id, cliente_id, fecha, tipo, referencia, descripcion, debe, haber, saldo "
                "FROM cuenta_corriente WHERE cliente_id = :id ORDER BY id DESC LIMIT :lim OFFSET :off"
            ),
            {"id": cliente_id, "lim": limit, "off": offset},
        ).fetchall()
    return [_map_mov(r) for r in rows]


@router.get("/clientes/{cliente_id}/saldo")
def get_saldo_cliente(cliente_id: int, db: Session = Depends(get_db)):
    return db.execute(
        text("SELECT COALESCE(SUM(debe - haber), 0) FROM cuenta_corriente WHERE cliente_id = :id"),
        {"id": cliente_id},
    ).scalar() or 0.0


@router.get("/resumen")
def get_resumen_cuentas(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT cl.id, cl.nombre, cl.telefono, COALESCE(SUM(cc.debe - cc.haber), 0) AS saldo "
            "FROM clientes cl LEFT JOIN cuenta_corriente cc ON cc.cliente_id = cl.id "
            "GROUP BY cl.id ORDER BY cl.nombre ASC LIMIT 500"
        )
    ).fetchall()
    return [{"id": r[0], "nombre": r[1], "telefono": r[2], "saldo": r[3]} for r in rows]


@router.post("/movimientos")
def registrar_movimiento_cliente(data: MovimientoClienteData):
    with SessionLocal() as db:
        with db.begin():
            _registrar_movimiento_cliente_inner(db, data)
    return {"status": "ok"}


def _registrar_movimiento_cliente_inner(db, data: MovimientoClienteData) -> None:
    if not isinstance(data.monto, float) or not math.isfinite(data.monto) or data.monto <= 0.0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor que cero")
    saldo_previo = db.execute(
        text("SELECT COALESCE(SUM(debe - haber), 0) FROM cuenta_corriente WHERE cliente_id = :id"),
        {"id": data.cliente_id},
    ).scalar() or 0.0
    debe = 0.0 if data.es_pago else data.monto
    haber = data.monto if data.es_pago else 0.0
    nuevo_saldo = saldo_previo + debe - haber
    now = now_dm_YHM()
    cc_id = exec_insert(
        db, "cuenta_corriente",
        ["cliente_id", "fecha", "tipo", "referencia", "descripcion", "debe", "haber", "saldo"],
        {"cliente_id": data.cliente_id, "fecha": now, "tipo": data.tipo, "referencia": data.referencia,
         "descripcion": data.descripcion, "debe": debe, "haber": haber, "saldo": nuevo_saldo},
    )
    if data.es_pago:
        factura = db.execute(text("SELECT id FROM facturas WHERE numero = :n"), {"n": data.referencia}).first()
        exec_insert(
            db, "movimientos_wasi",
            ["fecha", "tipo", "categoria", "concepto", "monto", "factura_id", "cuenta_corriente_id"],
            {"fecha": now, "tipo": "Ingreso", "categoria": "Cuenta corriente", "concepto": data.descripcion,
             "monto": data.monto, "factura_id": factura[0] if factura else None, "cuenta_corriente_id": cc_id},
        )


@router.post("/movimientos/{mov_id}")
def update_movimiento_cliente(mov_id: int, data: UpdateMovimientoClienteData, db: Session = Depends(get_db)):
    if not math.isfinite(data.debe) or not math.isfinite(data.haber) or data.debe < 0.0 or data.haber < 0.0:
        raise HTTPException(status_code=400, detail="Los importes contables deben ser válidos y no negativos")
    row = db.execute(
        text(
            "SELECT cliente_id, (SELECT id FROM movimientos_wasi WHERE cuenta_corriente_id = cc.id LIMIT 1) "
            "FROM cuenta_corriente cc WHERE cc.id = :id"
        ),
        {"id": mov_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    cliente_id, linked_wasi_id = row[0], row[1]
    db.execute(
        text("UPDATE cuenta_corriente SET debe=:debe, haber=:haber, descripcion=:descripcion, tipo=:tipo WHERE id=:id"),
        {"debe": data.debe, "haber": data.haber, "descripcion": data.descripcion, "tipo": data.tipo, "id": mov_id},
    )
    if linked_wasi_id:
        if data.tipo == "Pago" and data.haber > 0.0:
            db.execute(text("UPDATE movimientos_wasi SET monto = :m, concepto = :c WHERE id = :id"),
                       {"m": data.haber, "c": data.descripcion, "id": linked_wasi_id})
        else:
            db.execute(text("DELETE FROM movimientos_wasi WHERE id = :id"), {"id": linked_wasi_id})
    _recalcular_saldos(db, cliente_id)
    db.commit()
    return {"status": "ok"}


@router.delete("/movimientos/{mov_id}")
def delete_movimiento_cliente(mov_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text(
            "SELECT cliente_id, (SELECT id FROM movimientos_wasi WHERE cuenta_corriente_id = cc.id LIMIT 1) "
            "FROM cuenta_corriente cc WHERE cc.id = :id"
        ),
        {"id": mov_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    cliente_id, linked_wasi_id = row[0], row[1]
    if linked_wasi_id:
        db.execute(text("DELETE FROM movimientos_wasi WHERE id = :id"), {"id": linked_wasi_id})
    db.execute(text("DELETE FROM cuenta_corriente WHERE id = :id"), {"id": mov_id})
    _recalcular_saldos(db, cliente_id)
    db.commit()
    return {"status": "ok"}