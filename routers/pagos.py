"""Router /pagos — port de commands/pagos.rs (pagos proveedores + categorías)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_api_key
from db_utils import exec_insert, now_dm_YHM

router = APIRouter(prefix="/pagos", tags=["pagos"], dependencies=[Depends(verify_api_key)])


@router.get("/proveedores")
def get_pagos_proveedores(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT pp.id, pp.entidad_gasto_id, pp.proveedor, pp.fecha_vencimiento, pp.monto, pp.pagado, "
            "pp.notas, pp.movimiento_gasto_id, eg.tipo AS entidad_tipo "
            "FROM pagos_proveedores pp LEFT JOIN entidades_gastos eg ON eg.id = pp.entidad_gasto_id "
            "ORDER BY pp.fecha_vencimiento ASC LIMIT 200"
        )
    ).fetchall()
    return [
        {
            "id": r[0], "entidad_gasto_id": r[1], "proveedor": r[2], "fecha_vencimiento": r[3],
            "monto": r[4], "pagado": r[5], "notas": r[6], "movimiento_gasto_id": r[7], "entidad_tipo": r[8],
        }
        for r in rows
    ]


@router.post("/proveedores/{pago_id}/marcar")
def marcar_pago_proveedor(pago_id: int, pagado: bool, db: Session = Depends(get_db)):
    val = 1 if pagado else 0
    info = db.execute(
        text("SELECT proveedor, fecha_vencimiento FROM pagos_proveedores WHERE id = :id"), {"id": pago_id}
    ).first()
    db.execute(text("UPDATE pagos_proveedores SET pagado = :p WHERE id = :id"), {"p": val, "id": pago_id})
    if info:
        estado = "pagado" if pagado else "desmarcado"
        exec_insert(
            db, "actividad_reciente", ["fecha", "tipo", "descripcion", "referencia"],
            {"fecha": now_dm_YHM(), "tipo": "Pago", "descripcion": f"Pago {estado} {info[0]} ({info[1]})",
             "referencia": str(pago_id)},
        )
    db.commit()
    return {"status": "ok"}


@router.get("/categorias")
def get_categorias_gasto(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, nombre FROM categorias_gasto ORDER BY nombre ASC")).fetchall()
    return [{"id": r[0], "nombre": r[1]} for r in rows]


@router.post("/categorias")
def save_categoria_gasto(nombre: str, db: Session = Depends(get_db)):
    try:
        new_id = exec_insert(db, "categorias_gasto", ["nombre"], {"nombre": nombre.strip()})
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        return None


@router.delete("/categorias/{cat_id}")
def delete_categoria_gasto(cat_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM categorias_gasto WHERE id = :id"), {"id": cat_id})
    db.commit()
    return {"status": "ok"}