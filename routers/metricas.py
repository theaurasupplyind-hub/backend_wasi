"""Router /metricas — port de commands/metricas.rs (solo datos; el PDF sigue en Rust)."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_api_key

router = APIRouter(prefix="/metricas", tags=["metricas"], dependencies=[Depends(verify_api_key)])


@router.get("/data")
def get_metricas_data(db: Session = Depends(get_db)):
    facturas_detalle = db.execute(
        text(
            "SELECT COALESCE(fecha, ''), COALESCE(total, 0), COALESCE(cliente_nombre, ''), "
            "COALESCE(numero, ''), COALESCE(estado, '') FROM facturas ORDER BY id ASC"
        )
    ).fetchall()
    facturas_detalle = [
        {"fecha": r[0], "total": r[1], "cliente_nombre": r[2], "numero": r[3], "estado": r[4]}
        for r in facturas_detalle
    ]
    facturas = [{"fecha": f["fecha"], "total": f["total"]} for f in facturas_detalle]

    movimientos_detalle = db.execute(
        text(
            "SELECT id, COALESCE(fecha, ''), COALESCE(monto, 0), COALESCE(tipo, ''), "
            "COALESCE(categoria, ''), COALESCE(concepto, '') FROM movimientos_wasi ORDER BY id ASC"
        )
    ).fetchall()
    movimientos_detalle = [
        {"id": r[0], "fecha": r[1], "monto": r[2], "tipo": r[3], "categoria": r[4], "concepto": r[5]}
        for r in movimientos_detalle
    ]
    movimientos = [{"fecha": m["fecha"], "monto": m["monto"], "tipo": m["tipo"]} for m in movimientos_detalle]

    return {
        "facturas": facturas,
        "movimientos": movimientos,
        "facturas_detalle": facturas_detalle,
        "movimientos_detalle": movimientos_detalle,
    }