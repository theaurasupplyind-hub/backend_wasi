"""Router /proceso — port de commands/proceso.rs (kanban)."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_api_key

router = APIRouter(prefix="/proceso", tags=["proceso"], dependencies=[Depends(verify_api_key)])


def _get_ordenes(db, estado: str) -> list:
    rows = db.execute(
        text(
            "SELECT id, fecha, numero_factura, cliente_nombre, detalle, cantidad_pedida, "
            "stock_disponible, cantidad_a_producir, estado, notas "
            "FROM ordenes_produccion WHERE estado = :e ORDER BY id DESC LIMIT 500"
        ),
        {"e": estado},
    ).fetchall()
    return [
        {"id": r[0], "fecha": r[1], "numero_factura": r[2], "cliente_nombre": r[3], "detalle": r[4],
         "cantidad_pedida": r[5], "stock_disponible": r[6], "cantidad_a_producir": r[7], "estado": r[8], "notas": r[9]}
        for r in rows
    ]


def _get_facturas(db, where_clause: str) -> list:
    rows = db.execute(
        text(
            f"SELECT f.id, f.numero, f.fecha, f.cliente_nombre, f.total, f.estado, f.entrega_estado "
            f"FROM facturas f WHERE {where_clause} ORDER BY f.id DESC LIMIT 500"
        )
    ).fetchall()
    facturas = []
    for r in rows:
        factura_id, numero, fecha, cliente_nombre, total, estado, entrega_estado = r
        items = db.execute(
            text("SELECT id, cantidad, detalle FROM factura_items WHERE factura_id = :id"), {"id": factura_id}
        ).fetchall()
        lineas = db.execute(
            text(
                "SELECT id, detalle, cantidad_a_producir, estado "
                "FROM ordenes_produccion WHERE numero_factura = :n"
            ),
            {"n": numero},
        ).fetchall()
        facturas.append({
            "id": factura_id, "numero": numero, "fecha": fecha, "cliente_nombre": cliente_nombre,
            "total": total, "estado": estado, "entrega_estado": entrega_estado,
            "items": [{"id": it[0], "cantidad": it[1], "detalle": it[2]} for it in items],
            "lineas_produccion": [
                {"orden_id": ln[0], "detalle": ln[1], "cantidad_a_producir": ln[2], "estado": ln[3]}
                for ln in lineas
            ],
        })
    return facturas


@router.get("/kanban")
def get_proceso_kanban(db: Session = Depends(get_db)):
    return {
        "pedidos": _get_ordenes(db, "Pendiente"),
        "en_proceso": _get_ordenes(db, "En proceso"),
        "listo": _get_facturas(db, "f.entrega_estado != 'Entregado'"),
        "entregado": _get_facturas(db, "f.entrega_estado = 'Entregado'"),
    }