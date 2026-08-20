"""Router /clientes — port de commands/clientes.rs."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_api_key, login
from db_utils import exec_insert, now_dm_YHM

router = APIRouter(prefix="/clientes", tags=["clientes"], dependencies=[Depends(verify_api_key)])

CLIENTE_COLS = "id, nombre, domicilio, telefono, dni, provincia, sucursal_recibir, cp, taller, galeria"


class ClienteData(BaseModel):
    nombre: str
    domicilio: str = ""
    telefono: str = ""
    dni: str = ""
    provincia: str = ""
    sucursal_recibir: str = ""
    cp: str = ""
    taller: str = ""
    galeria: str = ""


class AjusteData(BaseModel):
    referencia: str
    monto: float
    motivo: str


def _row_cliente(row) -> dict:
    return {
        "id": row[0], "nombre": row[1], "domicilio": row[2], "telefono": row[3],
        "dni": row[4], "provincia": row[5], "sucursal_recibir": row[6], "cp": row[7],
        "taller": row[8], "galeria": row[9],
    }


@router.get("")
def get_clientes(db: Session = Depends(get_db)):
    rows = db.execute(text(f"SELECT {CLIENTE_COLS} FROM clientes ORDER BY nombre ASC LIMIT 500")).fetchall()
    return [_row_cliente(r) for r in rows]


@router.get("/con-saldo/all")
def get_clientes_con_saldo(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT c.id, c.nombre, c.domicilio, c.telefono, c.dni, c.provincia, "
            "c.sucursal_recibir, c.cp, "
            "COALESCE((SELECT SUM(cc.debe - cc.haber) FROM cuenta_corriente cc WHERE cc.cliente_id = c.id), 0) AS saldo "
            "FROM clientes c ORDER BY c.nombre ASC LIMIT 500"
        )
    ).fetchall()
    return [
        {
            "id": r[0], "nombre": r[1], "domicilio": r[2], "telefono": r[3], "dni": r[4],
            "provincia": r[5], "sucursal_recibir": r[6], "cp": r[7], "saldo": r[8],
        }
        for r in rows
    ]


@router.get("/{cliente_id}")
def get_cliente(cliente_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text(f"SELECT {CLIENTE_COLS} FROM clientes WHERE id = :id"), {"id": cliente_id}
    ).first()
    return _row_cliente(row) if row else None


@router.get("/by-nombre/{nombre}")
def get_cliente_by_nombre(nombre: str, db: Session = Depends(get_db)):
    row = db.execute(
        text(
            f"SELECT {CLIENTE_COLS} FROM clientes WHERE LOWER(TRIM(nombre)) = LOWER(TRIM(:nombre))"
        ),
        {"nombre": nombre},
    ).first()
    return _row_cliente(row) if row else None


@router.post("")
def save_cliente(data: ClienteData, db: Session = Depends(get_db)):
    existing = db.execute(
        text("SELECT id FROM clientes WHERE LOWER(TRIM(nombre)) = LOWER(TRIM(:nombre))"),
        {"nombre": data.nombre},
    ).first()
    if existing:
        db.execute(
            text(
                "UPDATE clientes SET domicilio=:domicilio, telefono=:telefono, dni=:dni, provincia=:provincia, "
                "sucursal_recibir=:sucursal_recibir, cp=:cp, taller=:taller, galeria=:galeria WHERE id=:id"
            ),
            {
                "id": existing[0], "domicilio": data.domicilio, "telefono": data.telefono,
                "dni": data.dni, "provincia": data.provincia, "sucursal_recibir": data.sucursal_recibir,
                "cp": data.cp, "taller": data.taller, "galeria": data.galeria,
            },
        )
        db.commit()
        return existing[0]
    new_id = exec_insert(
        db, "clientes",
        ["nombre", "domicilio", "telefono", "dni", "provincia", "sucursal_recibir", "cp", "taller", "galeria"],
        {
            "nombre": data.nombre, "domicilio": data.domicilio, "telefono": data.telefono,
            "dni": data.dni, "provincia": data.provincia, "sucursal_recibir": data.sucursal_recibir,
            "cp": data.cp, "taller": data.taller, "galeria": data.galeria,
        },
    )
    db.commit()
    return new_id


@router.post("/{cliente_id}")
def update_cliente(cliente_id: int, data: ClienteData, db: Session = Depends(get_db)):
    old = db.execute(text("SELECT nombre FROM clientes WHERE id = :id"), {"id": cliente_id}).first()
    if not old:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    old_nombre = old[0]
    db.execute(
        text(
            "UPDATE clientes SET nombre=:nombre, domicilio=:domicilio, telefono=:telefono, dni=:dni, "
            "provincia=:provincia, sucursal_recibir=:sucursal_recibir, cp=:cp, taller=:taller, galeria=:galeria "
            "WHERE id=:id"
        ),
        {
            "id": cliente_id, "nombre": data.nombre, "domicilio": data.domicilio,
            "telefono": data.telefono, "dni": data.dni, "provincia": data.provincia,
            "sucursal_recibir": data.sucursal_recibir, "cp": data.cp,
            "taller": data.taller, "galeria": data.galeria,
        },
    )
    db.execute(
        text(
            "UPDATE facturas SET cliente_nombre = :nuevo WHERE LOWER(TRIM(cliente_nombre)) = LOWER(TRIM(:viejo))"
        ),
        {"nuevo": data.nombre.strip(), "viejo": old_nombre},
    )
    db.commit()
    return {"status": "ok"}


@router.delete("/{cliente_id}")
def delete_cliente(cliente_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT nombre FROM clientes WHERE id = :id"), {"id": cliente_id}
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    nombre = row[0]
    ctas = db.execute(
        text("SELECT COUNT(*) FROM cuenta_corriente WHERE cliente_id = :id"), {"id": cliente_id}
    ).scalar() or 0
    fcts = db.execute(
        text("SELECT COUNT(*) FROM facturas WHERE LOWER(TRIM(cliente_nombre)) = LOWER(TRIM(:n))"),
        {"n": nombre},
    ).scalar() or 0
    db.execute(text("DELETE FROM clientes WHERE id = :id"), {"id": cliente_id})
    db.commit()
    return f"OK|{ctas}|{fcts}"


@router.get("/{cliente_id}/dependencies")
def get_cliente_dependencies(cliente_id: int, db: Session = Depends(get_db)):
    movimientos_count = db.execute(
        text("SELECT COUNT(*) FROM cuenta_corriente WHERE cliente_id = :id"), {"id": cliente_id}
    ).scalar() or 0
    saldo = db.execute(
        text("SELECT COALESCE(SUM(debe - haber), 0) FROM cuenta_corriente WHERE cliente_id = :id"),
        {"id": cliente_id},
    ).scalar() or 0.0
    facturas = db.execute(
        text(
            "SELECT f.id, f.numero FROM facturas f "
            "WHERE LOWER(TRIM(f.cliente_nombre)) = (SELECT LOWER(TRIM(nombre)) FROM clientes WHERE id = :id)"
        ),
        {"id": cliente_id},
    ).fetchall()
    return {
        "movimientos_count": movimientos_count,
        "saldo": saldo,
        "facturas": [{"id": r[0], "numero": r[1]} for r in facturas],
    }


@router.get("/{cliente_id}/discrepancias")
def detectar_discrepancias(cliente_id: int, cliente_nombre: str, db: Session = Depends(get_db)):
    facturas_propias = {
        r[0]
        for r in db.execute(
            text("SELECT numero FROM facturas WHERE cliente_nombre = :n"), {"n": cliente_nombre}
        ).fetchall()
    }
    discrepancias = []
    entradas = db.execute(
        text(
            "SELECT id, referencia, debe, fecha FROM cuenta_corriente "
            "WHERE cliente_id = :id AND tipo = 'Factura' AND debe > 0 ORDER BY id"
        ),
        {"id": cliente_id},
    ).fetchall()
    for _mov_id, ref_num, monto, fecha in entradas:
        if ref_num in facturas_propias:
            continue
        dueno = db.execute(
            text("SELECT cliente_nombre FROM facturas WHERE numero = :n"), {"n": ref_num}
        ).first()
        discrepancias.append(
            {
                "tipo": "factura_otro_cliente" if dueno else "factura_inexistente",
                "referencia": ref_num,
                "monto": monto,
                "cliente_real": dueno[0] if dueno else None,
                "fecha": fecha,
            }
        )
    return discrepancias


@router.post("/{cliente_id}/regularizar")
def regularizar_discrepancias(cliente_id: int, ajustes: list[AjusteData], db: Session = Depends(get_db)):
    count = 0
    for aj in ajustes:
        saldo_previo = db.execute(
            text("SELECT COALESCE(SUM(debe - haber), 0) FROM cuenta_corriente WHERE cliente_id = :id"),
            {"id": cliente_id},
        ).scalar() or 0.0
        nuevo_saldo = saldo_previo - aj.monto
        exec_insert(
            db, "cuenta_corriente",
            ["cliente_id", "fecha", "tipo", "referencia", "descripcion", "debe", "haber", "saldo"],
            {
                "cliente_id": cliente_id, "fecha": now_dm_YHM(), "tipo": "Ajuste",
                "referencia": aj.referencia, "descripcion": aj.motivo, "debe": 0.0,
                "haber": aj.monto, "saldo": nuevo_saldo,
            },
        )
        count += 1
    db.commit()
    return count