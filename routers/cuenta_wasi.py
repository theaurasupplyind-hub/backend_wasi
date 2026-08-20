"""Router /cuenta-wasi — port de commands/cuenta_wasi.rs."""
import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_api_key
from db_utils import exec_insert, now_dm_YHM, where_fecha, fmt_date_for_sql

router = APIRouter(prefix="/cuenta-wasi", tags=["cuenta_wasi"], dependencies=[Depends(verify_api_key)])


class MovimientoWasiData(BaseModel):
    tipo: str
    categoria: str = ""
    concepto: str
    monto: float
    movimiento_gasto_id: int | None = None


class UpdateMovimientoWasiData(BaseModel):
    fecha: str = ""
    tipo: str
    categoria: str = ""
    concepto: str = ""
    monto: float


def _params_fecha(fecha_desde: str, fecha_hasta: str) -> dict:
    out = {}
    if fecha_desde:
        out["fecha_desde"] = fmt_date_for_sql(fecha_desde)
    if fecha_hasta:
        out["fecha_hasta"] = fmt_date_for_sql(fecha_hasta)
    return out


def _validate_tipo(tipo: str) -> None:
    if tipo not in ("Ingreso", "Egreso"):
        raise HTTPException(status_code=400, detail="El tipo de movimiento debe ser Ingreso o Egreso")


def _validate_monto(monto: float) -> None:
    if not isinstance(monto, float) or not math.isfinite(monto) or monto <= 0.0:
        raise HTTPException(status_code=400, detail="El monto del movimiento debe ser mayor que cero")


@router.get("/saldo")
def get_saldo_wasi(fecha_desde: str = "", fecha_hasta: str = "", db: Session = Depends(get_db)):
    where_clause, _ = where_fecha(fecha_desde, fecha_hasta)
    params = _params_fecha(fecha_desde, fecha_hasta)
    row = db.execute(
        text(
            f"SELECT COALESCE(SUM(CASE WHEN tipo = 'Ingreso' THEN monto ELSE 0 END), 0), "
            f"COALESCE(SUM(CASE WHEN tipo = 'Egreso' THEN monto ELSE 0 END), 0) "
            f"FROM movimientos_wasi WHERE {where_clause}"
        ),
        params,
    ).first()
    ingresos, egresos = row[0], row[1]
    return {"ingresos": ingresos, "egresos": egresos, "saldo": ingresos - egresos}


@router.get("/movimientos")
def get_movimientos_wasi(limit: int = 100, fecha_desde: str = "", fecha_hasta: str = "", db: Session = Depends(get_db)):
    where_clause, _ = where_fecha(fecha_desde, fecha_hasta)
    params = _params_fecha(fecha_desde, fecha_hasta)
    params["limit"] = limit
    rows = db.execute(
        text(
            f"SELECT id, fecha, tipo, categoria, concepto, monto, movimiento_gasto_id, factura_id, cuenta_corriente_id "
            f"FROM movimientos_wasi WHERE {where_clause} ORDER BY id DESC LIMIT :limit"
        ),
        params,
    ).fetchall()
    return [
        {"id": r[0], "fecha": r[1], "tipo": r[2], "categoria": r[3], "concepto": r[4], "monto": r[5],
         "movimiento_gasto_id": r[6], "factura_id": r[7], "cuenta_corriente_id": r[8]}
        for r in rows
    ]


@router.post("/movimientos")
def registrar_movimiento_wasi(data: MovimientoWasiData, db: Session = Depends(get_db)):
    _validate_tipo(data.tipo)
    _validate_monto(data.monto)
    now = now_dm_YHM()
    exec_insert(
        db, "movimientos_wasi",
        ["fecha", "tipo", "categoria", "concepto", "monto", "movimiento_gasto_id"],
        {"fecha": now, "tipo": data.tipo, "categoria": data.categoria, "concepto": data.concepto,
         "monto": data.monto, "movimiento_gasto_id": data.movimiento_gasto_id},
    )
    exec_insert(
        db, "actividad_reciente", ["fecha", "tipo", "descripcion", "referencia"],
        {"fecha": now_dm_YHM(), "tipo": "Movimiento WASI", "descripcion": f"{data.tipo}: {data.concepto}", "referencia": ""},
    )
    db.commit()
    return {"status": "ok"}


def _recalcular_saldos_gasto(db, entidad_id: int) -> None:
    movs = [r[0] for r in db.execute(
        text("SELECT id FROM movimientos_gastos WHERE entidad_id = :id ORDER BY id ASC"), {"id": entidad_id}
    ).fetchall()]
    saldo = 0.0
    for mid in movs:
        d, h = db.execute(text("SELECT debe, haber FROM movimientos_gastos WHERE id = :id"), {"id": mid}).first()
        saldo += d - h
        db.execute(text("UPDATE movimientos_gastos SET saldo = :s WHERE id = :id"), {"s": saldo, "id": mid})


@router.post("/movimientos/{mov_id}")
def update_movimiento_wasi(mov_id: int, data: UpdateMovimientoWasiData, db: Session = Depends(get_db)):
    _validate_tipo(data.tipo)
    _validate_monto(data.monto)
    gasto_id = db.execute(
        text("SELECT movimiento_gasto_id FROM movimientos_wasi WHERE id = :id"), {"id": mov_id}
    ).first()
    if not gasto_id:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    gasto_id = gasto_id[0]
    fecha = data.fecha.strip() or now_dm_YHM()
    db.execute(
        text("UPDATE movimientos_wasi SET fecha=:fecha, tipo=:tipo, categoria=:categoria, concepto=:concepto, monto=:monto WHERE id=:id"),
        {"fecha": fecha, "tipo": data.tipo, "categoria": data.categoria, "concepto": data.concepto, "monto": data.monto, "id": mov_id},
    )
    if gasto_id:
        db.execute(text("UPDATE movimientos_gastos SET haber=:haber, descripcion=:descripcion WHERE id=:id"),
                   {"haber": data.monto, "descripcion": data.concepto, "id": gasto_id})
        entidad = db.execute(text("SELECT entidad_id FROM movimientos_gastos WHERE id = :id"), {"id": gasto_id}).first()
        if entidad:
            _recalcular_saldos_gasto(db, entidad[0])
    db.commit()
    return {"status": "ok"}


@router.delete("/movimientos/{mov_id}")
def delete_movimiento_wasi(mov_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT factura_id, cuenta_corriente_id FROM movimientos_wasi WHERE id = :id"), {"id": mov_id}
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    if row[0] is not None or row[1] is not None:
        raise HTTPException(
            status_code=400,
            detail="El movimiento está vinculado a un cobro; modifíquelo desde la factura o cuenta corriente",
        )
    db.execute(text("DELETE FROM movimientos_wasi WHERE id = :id"), {"id": mov_id})
    db.commit()
    return {"status": "ok"}