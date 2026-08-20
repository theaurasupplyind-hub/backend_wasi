"""Router /proceso — port de commands/proceso.rs (kanban)."""
from fastapi import APIRouter, Depends
from sqlalchemy import bindparam, text
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


def _get_facturas(db, where_clause: str, limit: int = 500) -> list:
    rows = db.execute(
        text(
            f"SELECT f.id, f.numero, f.fecha, f.cliente_nombre, f.total, f.estado, f.entrega_estado "
            f"FROM facturas f WHERE {where_clause} ORDER BY f.id DESC LIMIT :limit"
        ),
        {"limit": limit},
    ).fetchall()
    if not rows:
        return []
    facturas = [
        {"id": r[0], "numero": r[1], "fecha": r[2], "cliente_nombre": r[3],
         "total": r[4], "estado": r[5], "entrega_estado": r[6],
         "items": [], "lineas_produccion": []}
        for r in rows
    ]
    ids = [f["id"] for f in facturas]
    numeros = [f["numero"] for f in facturas]

    items_rows = db.execute(
        text(
            "SELECT factura_id, id, cantidad, detalle FROM factura_items "
            "WHERE factura_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).fetchall()
    items_by_factura: dict[int, list] = {}
    for factura_id, item_id, cantidad, detalle in items_rows:
        items_by_factura.setdefault(factura_id, []).append(
            {"id": item_id, "cantidad": cantidad, "detalle": detalle}
        )

    lineas_rows = db.execute(
        text(
            "SELECT numero_factura, id, detalle, cantidad_a_producir, estado "
            "FROM ordenes_produccion WHERE numero_factura IN :numeros"
        ).bindparams(bindparam("numeros", expanding=True)),
        {"numeros": numeros},
    ).fetchall()
    lineas_by_numero: dict[str, list] = {}
    for numero, orden_id, detalle, cap, estado in lineas_rows:
        lineas_by_numero.setdefault(numero, []).append(
            {"orden_id": orden_id, "detalle": detalle, "cantidad_a_producir": cap, "estado": estado}
        )

    for f in facturas:
        f["items"] = items_by_factura.get(f["id"], [])
        f["lineas_produccion"] = lineas_by_numero.get(f["numero"], [])
    return facturas


def _get_ordenes_huerfanas(db) -> list:
    rows = db.execute(
        text(
            "SELECT op.id, op.fecha, op.numero_factura, op.cliente_nombre, op.detalle, op.cantidad_pedida, "
            "op.stock_disponible, op.cantidad_a_producir, op.estado, op.notas "
            "FROM ordenes_produccion op "
            "LEFT JOIN facturas f ON f.numero = op.numero_factura "
            "WHERE f.id IS NULL ORDER BY op.id"
        )
    ).fetchall()
    return [
        {"id": r[0], "fecha": r[1], "numero_factura": r[2], "cliente_nombre": r[3], "detalle": r[4],
         "cantidad_pedida": r[5], "stock_disponible": r[6], "cantidad_a_producir": r[7], "estado": r[8], "notas": r[9]}
        for r in rows
    ]


@router.get("/kanban")
def get_proceso_kanban(db: Session = Depends(get_db)):
    return {
        "pedidos": _get_ordenes(db, "Pendiente"),
        "en_proceso": _get_ordenes(db, "En proceso"),
        "listo": _get_facturas(db, "f.entrega_estado != 'Entregado'"),
        "entregado": _get_facturas(db, "f.entrega_estado = 'Entregado'", limit=30),
        "ordenes_huerfanas": _get_ordenes_huerfanas(db),
    }