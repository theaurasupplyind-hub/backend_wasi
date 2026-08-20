"""Router /maquinas — port de commands/maquinas.rs."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_api_key
from db_utils import exec_insert, now_iso

router = APIRouter(prefix="/maquinas", tags=["maquinas"], dependencies=[Depends(verify_api_key)])


@router.get("")
def get_maquinas(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, nombre, descripcion FROM maquinas ORDER BY nombre ASC LIMIT 200")).fetchall()
    return [{"id": r[0], "nombre": r[1], "descripcion": r[2]} for r in rows]


@router.post("")
def save_maquina(nombre: str, descripcion: str = "", db: Session = Depends(get_db)):
    new_id = exec_insert(db, "maquinas", ["nombre", "descripcion"], {"nombre": nombre, "descripcion": descripcion})
    db.commit()
    return new_id


@router.post("/{maquina_id:int}")
def update_maquina(maquina_id: int, nombre: str, descripcion: str = "", db: Session = Depends(get_db)):
    db.execute(text("UPDATE maquinas SET nombre=:nombre, descripcion=:descripcion WHERE id=:id"),
               {"nombre": nombre, "descripcion": descripcion, "id": maquina_id})
    db.commit()
    return {"status": "ok"}


@router.delete("/{maquina_id:int}")
def delete_maquina(maquina_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM maquinas WHERE id = :id"), {"id": maquina_id})
    db.commit()
    return {"status": "ok"}


@router.get("/{maquina_id:int}/produccion")
def get_produccion_maquina(maquina_id: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, maquina_id, fecha, cantidad, unidad FROM produccion_maquina WHERE maquina_id = :id ORDER BY fecha DESC LIMIT 100"),
        {"id": maquina_id},
    ).fetchall()
    return [{"id": r[0], "maquina_id": r[1], "fecha": r[2], "cantidad": r[3], "unidad": r[4]} for r in rows]


@router.get("/produccion/all")
def get_all_produccion_maquina(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT id, maquina_id, fecha, cantidad, unidad FROM produccion_maquina "
            "ORDER BY substr(fecha,7,4)||substr(fecha,4,2)||substr(fecha,1,2) DESC LIMIT :lim"
        ),
        {"lim": limit},
    ).fetchall()
    return [{"id": r[0], "maquina_id": r[1], "fecha": r[2], "cantidad": r[3], "unidad": r[4]} for r in rows]


@router.post("/produccion")
def save_produccion_maquina(maquina_id: int, fecha: str, cantidad: float, unidad: str = "unidades", db: Session = Depends(get_db)):
    new_id = exec_insert(db, "produccion_maquina", ["maquina_id", "fecha", "cantidad", "unidad"],
                         {"maquina_id": maquina_id, "fecha": fecha, "cantidad": cantidad, "unidad": unidad})
    db.commit()
    return new_id


@router.delete("/produccion/{prod_id}")
def delete_produccion_maquina(prod_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM produccion_maquina WHERE id = :id"), {"id": prod_id})
    db.commit()
    return {"status": "ok"}


@router.get("/{maquina_id:int}/notas")
def get_notas_maquina(maquina_id: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, maquina_id, nota, fecha_hora FROM notas_maquina WHERE maquina_id = :id ORDER BY fecha_hora DESC LIMIT 100"),
        {"id": maquina_id},
    ).fetchall()
    return [{"id": r[0], "maquina_id": r[1], "nota": r[2], "fecha_hora": r[3]} for r in rows]


@router.post("/{maquina_id:int}/notas")
def save_nota_maquina(maquina_id: int, nota: str, db: Session = Depends(get_db)):
    exec_insert(db, "notas_maquina", ["maquina_id", "nota", "fecha_hora"],
                {"maquina_id": maquina_id, "nota": nota, "fecha_hora": now_iso()})
    db.commit()
    return {"status": "ok"}


# ── Cerrado ──

@router.get("/cerrado/all")
def get_cerrado_maquinas(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, nombre, descripcion FROM cerrado_maquinas ORDER BY nombre ASC LIMIT 200")).fetchall()
    return [{"id": r[0], "nombre": r[1], "descripcion": r[2]} for r in rows]


@router.post("/cerrado")
def save_cerrado_maquina(nombre: str, descripcion: str = "", db: Session = Depends(get_db)):
    new_id = exec_insert(db, "cerrado_maquinas", ["nombre", "descripcion"], {"nombre": nombre, "descripcion": descripcion})
    db.commit()
    return new_id


@router.post("/cerrado/{maquina_id:int}")
def update_cerrado_maquina(maquina_id: int, nombre: str, descripcion: str = "", db: Session = Depends(get_db)):
    db.execute(text("UPDATE cerrado_maquinas SET nombre=:nombre, descripcion=:descripcion WHERE id=:id"),
               {"nombre": nombre, "descripcion": descripcion, "id": maquina_id})
    db.commit()
    return {"status": "ok"}


@router.delete("/cerrado/{maquina_id:int}")
def delete_cerrado_maquina(maquina_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM cerrado_maquinas WHERE id = :id"), {"id": maquina_id})
    db.commit()
    return {"status": "ok"}


@router.get("/cerrado/{maquina_id:int}/notas")
def get_notas_cerrado_maquina(maquina_id: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, maquina_id, nota, fecha_hora FROM cerrado_notas WHERE maquina_id = :id ORDER BY fecha_hora DESC LIMIT 100"),
        {"id": maquina_id},
    ).fetchall()
    return [{"id": r[0], "maquina_id": r[1], "nota": r[2], "fecha_hora": r[3]} for r in rows]


@router.post("/cerrado/{maquina_id:int}/notas")
def save_nota_cerrado_maquina(maquina_id: int, nota: str, db: Session = Depends(get_db)):
    exec_insert(db, "cerrado_notas", ["maquina_id", "nota", "fecha_hora"],
                {"maquina_id": maquina_id, "nota": nota, "fecha_hora": now_iso()})
    db.commit()
    return {"status": "ok"}


@router.get("/cerrado/medias/all")
def get_cerrado_medias(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT id, maquina_id, fecha, cantidad FROM cerrado_medias "
            "ORDER BY substr(fecha,7,4)||substr(fecha,4,2)||substr(fecha,1,2) DESC LIMIT 500"
        )
    ).fetchall()
    return [{"id": r[0], "maquina_id": r[1], "fecha": r[2], "cantidad": r[3]} for r in rows]


@router.post("/cerrado/medias")
def save_cerrado_medias(maquina_id: int, fecha: str, cantidad: float, db: Session = Depends(get_db)):
    new_id = exec_insert(db, "cerrado_medias", ["maquina_id", "fecha", "cantidad"],
                         {"maquina_id": maquina_id, "fecha": fecha, "cantidad": cantidad})
    db.commit()
    return new_id


@router.delete("/cerrado/medias/{registro_id:int}")
def delete_cerrado_medias(registro_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM cerrado_medias WHERE id = :id"), {"id": registro_id})
    db.commit()
    return {"status": "ok"}


# ── Embolsado ──

@router.get("/embolsado/all")
def get_embolsado_empleados(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, nombre, descripcion FROM embolsado_empleados ORDER BY nombre ASC LIMIT 200")).fetchall()
    return [{"id": r[0], "nombre": r[1], "descripcion": r[2]} for r in rows]


@router.post("/embolsado")
def save_embolsado_empleado(nombre: str, descripcion: str = "", db: Session = Depends(get_db)):
    new_id = exec_insert(db, "embolsado_empleados", ["nombre", "descripcion"], {"nombre": nombre, "descripcion": descripcion})
    db.commit()
    return new_id


@router.post("/embolsado/{empleado_id:int}")
def update_embolsado_empleado(empleado_id: int, nombre: str, descripcion: str = "", db: Session = Depends(get_db)):
    db.execute(text("UPDATE embolsado_empleados SET nombre=:nombre, descripcion=:descripcion WHERE id=:id"),
               {"nombre": nombre, "descripcion": descripcion, "id": empleado_id})
    db.commit()
    return {"status": "ok"}


@router.delete("/embolsado/{empleado_id:int}")
def delete_embolsado_empleado(empleado_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM embolsado_empleados WHERE id = :id"), {"id": empleado_id})
    db.commit()
    return {"status": "ok"}


@router.get("/embolsado/{empleado_id:int}/notas")
def get_notas_embolsado_empleado(empleado_id: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, empleado_id, nota, fecha_hora FROM embolsado_notas WHERE empleado_id = :id ORDER BY fecha_hora DESC LIMIT 100"),
        {"id": empleado_id},
    ).fetchall()
    return [{"id": r[0], "empleado_id": r[1], "nota": r[2], "fecha_hora": r[3]} for r in rows]


@router.post("/embolsado/{empleado_id:int}/notas")
def save_nota_embolsado_empleado(empleado_id: int, nota: str, db: Session = Depends(get_db)):
    exec_insert(db, "embolsado_notas", ["empleado_id", "nota", "fecha_hora"],
                {"empleado_id": empleado_id, "nota": nota, "fecha_hora": now_iso()})
    db.commit()
    return {"status": "ok"}


@router.get("/embolsado/docenas/all")
def get_embolsado_docenas(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT id, maquina_id, fecha, docenas FROM embolsado_docenas "
            "ORDER BY substr(fecha,7,4)||substr(fecha,4,2)||substr(fecha,1,2) DESC LIMIT 500"
        )
    ).fetchall()
    return [{"id": r[0], "maquina_id": r[1], "fecha": r[2], "docenas": r[3]} for r in rows]


@router.post("/embolsado/docenas")
def save_embolsado_docenas(maquina_id: int, fecha: str, docenas: float, db: Session = Depends(get_db)):
    new_id = exec_insert(db, "embolsado_docenas", ["maquina_id", "fecha", "docenas"],
                         {"maquina_id": maquina_id, "fecha": fecha, "docenas": docenas})
    db.commit()
    return new_id


@router.delete("/embolsado/docenas/{registro_id:int}")
def delete_embolsado_docenas(registro_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM embolsado_docenas WHERE id = :id"), {"id": registro_id})
    db.commit()
    return {"status": "ok"}