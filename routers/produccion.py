"""Router /produccion — port de commands/produccion.rs."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_api_key
from db_utils import exec_insert, now_dm_YHM, now_dm_YHMS, scalar_max

router = APIRouter(prefix="/produccion", tags=["produccion"], dependencies=[Depends(verify_api_key)])


class OrdenProduccionUpdateData(BaseModel):
    detalle: str = ""
    cantidad_a_producir: float = 0
    cantidad_pedida: float = 0
    estado: str = ""
    notas: str = ""


def registrar_actividad(db, tipo, descripcion, referencia) -> None:
    exec_insert(
        db, "actividad_reciente",
        ["fecha", "tipo", "descripcion", "referencia"],
        {"fecha": now_dm_YHM(), "tipo": tipo, "descripcion": descripcion, "referencia": referencia},
    )


def registrar_movimiento_stock(db, producto_id, tipo, referencia, cantidad, stock_anterior, stock_nuevo, detalle) -> None:
    exec_insert(
        db, "stock_movements",
        ["producto_id", "fecha_hora", "tipo", "referencia", "cantidad", "stock_anterior", "stock_nuevo", "detalle"],
        {"producto_id": producto_id, "fecha_hora": now_dm_YHMS(), "tipo": tipo, "referencia": referencia,
         "cantidad": cantidad, "stock_anterior": stock_anterior, "stock_nuevo": stock_nuevo, "detalle": detalle},
    )


@router.get("/ordenes")
def get_ordenes_produccion(solo_pendientes: bool = False, db: Session = Depends(get_db)):
    sql = "SELECT id, fecha, numero_factura, cliente_nombre, detalle, cantidad_pedida, stock_disponible, cantidad_a_producir, estado, notas FROM ordenes_produccion"
    if solo_pendientes:
        sql += " WHERE estado = 'Pendiente'"
    sql += " ORDER BY id DESC LIMIT 500"
    rows = db.execute(text(sql)).fetchall()
    return [
        {"id": r[0], "fecha": r[1], "numero_factura": r[2], "cliente_nombre": r[3], "detalle": r[4],
         "cantidad_pedida": r[5], "stock_disponible": r[6], "cantidad_a_producir": r[7], "estado": r[8], "notas": r[9]}
        for r in rows
    ]


@router.post("/ordenes/{orden_id}/estado")
def update_orden_produccion_estado(orden_id: int, estado: str, db: Session = Depends(get_db)):
    db.execute(text("UPDATE ordenes_produccion SET estado = :e WHERE id = :id"), {"e": estado, "id": orden_id})
    db.commit()
    return {"status": "ok"}


@router.post("/ordenes/{orden_id}/completar")
def completar_orden_produccion(orden_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT detalle, cantidad_a_producir, numero_factura FROM ordenes_produccion WHERE id = :id"),
        {"id": orden_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    detalle, cantidad, numero_factura = row[0], row[1], row[2]
    if cantidad <= 0.0:
        db.execute(text("UPDATE ordenes_produccion SET estado = 'Completada' WHERE id = :id"), {"id": orden_id})
        db.commit()
        return {"status": "ok"}
    prod = db.execute(
        text("SELECT id, stock_actual FROM productos WHERE LOWER(TRIM(detalle)) = LOWER(TRIM(:d))"),
        {"d": detalle},
    ).first()
    if prod:
        pid, sa = prod[0], prod[1]
        db.execute(text("UPDATE productos SET stock_actual = stock_actual + :c WHERE id = :id"), {"c": cantidad, "id": pid})
        registrar_movimiento_stock(db, pid, "produccion_completada", f"orden:{orden_id}", cantidad, sa, sa + cantidad,
                                   f"Orden producción completada: +{cantidad:.0f} a stock")
        sa2 = sa + cantidad
        db.execute(
            text(f"UPDATE productos SET stock_actual = {scalar_max('0', 'stock_actual - :c')} WHERE id = :id"),
            {"c": cantidad, "id": pid},
        )
        registrar_movimiento_stock(db, pid, "produccion_consumo", numero_factura, -cantidad, sa2, max(sa2 - cantidad, 0.0),
                                   f"Consumido por factura {numero_factura}: -{cantidad:.0f}")
    db.execute(text("UPDATE ordenes_produccion SET estado = 'Completada' WHERE id = :id"), {"id": orden_id})
    registrar_actividad(db, "produccion_completada", f"Orden {orden_id} completada", f"orden:{orden_id}")
    db.commit()
    return {"status": "ok"}


@router.post("/ordenes/{orden_id}")
def update_orden_produccion(orden_id: int, data: OrdenProduccionUpdateData, db: Session = Depends(get_db)):
    db.execute(
        text(
            "UPDATE ordenes_produccion SET detalle=:detalle, cantidad_a_producir=:cap, cantidad_pedida=:cp, "
            "estado=:estado, notas=:notas WHERE id=:id"
        ),
        {"detalle": data.detalle, "cap": data.cantidad_a_producir, "cp": data.cantidad_pedida,
         "estado": data.estado or "Pendiente", "notas": data.notas, "id": orden_id},
    )
    db.commit()
    return {"status": "ok"}


@router.post("/ordenes/{orden_id}/revertir")
def revertir_orden_produccion(orden_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT estado, cantidad_a_producir, numero_factura FROM ordenes_produccion WHERE id = :id"),
        {"id": orden_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    estado, cantidad, numero_factura = row[0], row[1], row[2]
    if estado != "Completada":
        raise HTTPException(status_code=400, detail="Solo se puede revertir una orden en estado Completada")
    if cantidad > 0.0:
        mov = db.execute(
            text("SELECT producto_id, id FROM stock_movements WHERE tipo = 'produccion_completada' AND referencia = :ref"),
            {"ref": f"orden:{orden_id}"},
        ).first()
        if mov:
            pid = mov[0]
            db.execute(
                text("DELETE FROM stock_movements WHERE tipo = 'produccion_completada' AND referencia = :ref"),
                {"ref": f"orden:{orden_id}"},
            )
            db.execute(
                text("DELETE FROM stock_movements WHERE tipo = 'produccion_consumo' AND producto_id = :pid AND referencia = :n AND cantidad = :c"),
                {"pid": pid, "n": numero_factura, "c": -cantidad},
            )
    db.execute(text("UPDATE ordenes_produccion SET estado = 'Pendiente' WHERE id = :id"), {"id": orden_id})
    db.commit()
    return {"status": "ok"}


@router.get("/ordenes/{orden_id}/dependencies")
def get_orden_produccion_dependencies(orden_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT estado, detalle, cantidad_a_producir, numero_factura FROM ordenes_produccion WHERE id = :id"),
        {"id": orden_id},
    ).first()
    if not row:
        return None
    return {"estado": row[0], "detalle": row[1], "cantidad": row[2], "numero_factura": row[3]}


@router.delete("/ordenes/{orden_id}")
def delete_orden_produccion(orden_id: int, db: Session = Depends(get_db)):
    estado = db.execute(text("SELECT estado FROM ordenes_produccion WHERE id = :id"), {"id": orden_id}).first()
    if not estado:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if estado[0] == "Completada":
        raise HTTPException(status_code=400, detail="No se puede eliminar una orden completada")
    db.execute(text("DELETE FROM ordenes_produccion WHERE id = :id"), {"id": orden_id})
    db.commit()
    return {"status": "ok"}