"""Router /gastos — port de commands/gastos.rs (entidades, movimientos, empleados, asistencia)."""
import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_api_key
from db_utils import exec_insert, now_dm_YHM

router = APIRouter(prefix="/gastos", tags=["gastos"], dependencies=[Depends(verify_api_key)])


class MovimientoGastoData(BaseModel):
    entidad_id: int
    tipo_movimiento: str
    monto: float
    descripcion: str = ""
    tipo_entidad: str = ""
    fecha_vencimiento: str = ""
    categoria: str = ""


class UpdateMovimientoGastoData(BaseModel):
    debe: float
    haber: float
    descripcion: str = ""
    tipo_movimiento: str = ""
    fecha_vencimiento: str = ""


class AsistenciaData(BaseModel):
    entidad_id: int
    fecha: str
    estado: str
    hora: str = ""
    nota: str = ""


def registrar_actividad(db, tipo, descripcion, referencia) -> None:
    exec_insert(
        db, "actividad_reciente",
        ["fecha", "tipo", "descripcion", "referencia"],
        {"fecha": now_dm_YHM(), "tipo": tipo, "descripcion": descripcion, "referencia": referencia},
    )


def registrar_egreso_wasi(db, categoria: str, concepto: str, monto: float, movimiento_gasto_id: int) -> None:
    exec_insert(
        db, "movimientos_wasi",
        ["fecha", "tipo", "categoria", "concepto", "monto", "movimiento_gasto_id", "factura_id", "cuenta_corriente_id"],
        {"fecha": now_dm_YHM(), "tipo": "Egreso", "categoria": categoria, "concepto": concepto,
         "monto": monto, "movimiento_gasto_id": movimiento_gasto_id, "factura_id": None, "cuenta_corriente_id": None},
    )


def recalcular_saldos(db, entidad_id: int) -> None:
    movs = [r[0] for r in db.execute(
        text("SELECT id FROM movimientos_gastos WHERE entidad_id = :id ORDER BY id ASC"), {"id": entidad_id}
    ).fetchall()]
    saldo = 0.0
    for mid in movs:
        d, h = db.execute(
            text("SELECT debe, haber FROM movimientos_gastos WHERE id = :id"), {"id": mid}
        ).first()
        saldo += d - h
        db.execute(text("UPDATE movimientos_gastos SET saldo = :s WHERE id = :id"), {"s": saldo, "id": mid})


# ── Entidades ───────────────────────────────────────────────────────────────

@router.get("/entidades")
def get_entidades_gastos(tipo_filtro: str = "", db: Session = Depends(get_db)):
    sql = (
        "SELECT e.id, e.tipo, e.nombre, e.telefono, e.descripcion, "
        "COALESCE(SUM(m.debe - m.haber), 0) AS saldo "
        "FROM entidades_gastos e LEFT JOIN movimientos_gastos m ON m.entidad_id = e.id "
    )
    params = {}
    if tipo_filtro:
        sql += "WHERE e.tipo = :tipo "
        params["tipo"] = tipo_filtro
    sql += "GROUP BY e.id ORDER BY e.nombre ASC LIMIT 500"
    rows = db.execute(text(sql), params).fetchall()
    return [
        {"id": r[0], "tipo": r[1], "nombre": r[2], "telefono": r[3], "descripcion": r[4], "saldo": r[5]}
        for r in rows
    ]


@router.post("/entidades")
def save_entidad_gasto(tipo: str, nombre: str, telefono: str = "", descripcion: str = "", db: Session = Depends(get_db)):
    new_id = exec_insert(
        db, "entidades_gastos", ["tipo", "nombre", "telefono", "descripcion"],
        {"tipo": tipo, "nombre": nombre, "telefono": telefono, "descripcion": descripcion},
    )
    db.commit()
    return new_id


@router.post("/entidades/{entidad_id}")
def update_entidad_gasto(entidad_id: int, nombre: str, telefono: str = "", descripcion: str = "", db: Session = Depends(get_db)):
    db.execute(
        text("UPDATE entidades_gastos SET nombre=:nombre, telefono=:telefono, descripcion=:descripcion WHERE id=:id"),
        {"nombre": nombre, "telefono": telefono, "descripcion": descripcion, "id": entidad_id},
    )
    db.commit()
    return {"status": "ok"}


@router.delete("/entidades/{entidad_id}")
def delete_entidad_gasto(entidad_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM entidades_gastos WHERE id = :id"), {"id": entidad_id})
    db.commit()
    return {"status": "ok"}


@router.get("/entidades/{entidad_id}/dependencies")
def get_entidad_gasto_dependencies(entidad_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT nombre, tipo FROM entidades_gastos WHERE id = :id"), {"id": entidad_id}
    ).first()
    if not row:
        return None
    nombre, tipo = row[0], row[1]
    movs_count, saldo = db.execute(
        text("SELECT COUNT(*), COALESCE(SUM(debe - haber), 0) FROM movimientos_gastos WHERE entidad_id = :id"),
        {"id": entidad_id},
    ).first() or (0, 0.0)
    config_count = db.execute(
        text("SELECT COUNT(*) FROM empleados_config WHERE entidad_id = :id"), {"id": entidad_id}
    ).scalar() or 0
    asis_count = db.execute(
        text("SELECT COUNT(*) FROM asistencia_empleados WHERE entidad_id = :id"), {"id": entidad_id}
    ).scalar() or 0
    return {
        "nombre": nombre, "tipo": tipo, "movimientos_count": movs_count, "saldo": saldo,
        "config_sueldo": config_count > 0, "asistencias_count": asis_count,
    }


# ── Movimientos de gasto ────────────────────────────────────────────────────

@router.get("/entidades/{entidad_id}/movimientos")
def get_movimientos_gasto(entidad_id: int, limit: int = 100, db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT id, entidad_id, fecha, tipo_movimiento, descripcion, debe, haber, saldo, fecha_vencimiento "
            "FROM movimientos_gastos WHERE entidad_id = :id ORDER BY id DESC LIMIT :lim"
        ),
        {"id": entidad_id, "lim": limit},
    ).fetchall()
    return [
        {
            "id": r[0], "entidad_id": r[1], "fecha": r[2], "tipo_movimiento": r[3], "descripcion": r[4],
            "debe": r[5], "haber": r[6], "saldo": r[7], "fecha_vencimiento": r[8],
        }
        for r in rows
    ]


@router.post("/movimientos")
def registrar_movimiento_gasto(data: MovimientoGastoData, db: Session = Depends(get_db)):
    if not isinstance(data.monto, float) or not math.isfinite(data.monto) or data.monto <= 0.0:
        raise HTTPException(status_code=400, detail="El monto del gasto debe ser mayor que cero")
    saldo_previo = db.execute(
        text("SELECT COALESCE(SUM(debe - haber), 0) FROM movimientos_gastos WHERE entidad_id = :id"),
        {"id": data.entidad_id},
    ).scalar() or 0.0
    es_pago = data.tipo_movimiento == "Pago"
    es_multa = data.tipo_movimiento == "Multa"
    debe = 0.0 if (es_pago or es_multa) else data.monto
    haber = data.monto if (es_pago or es_multa) else 0.0
    nuevo_saldo = saldo_previo + debe - haber
    now = now_dm_YHM()
    gasto_id = exec_insert(
        db, "movimientos_gastos",
        ["entidad_id", "fecha", "tipo_movimiento", "descripcion", "debe", "haber", "saldo", "fecha_vencimiento"],
        {"entidad_id": data.entidad_id, "fecha": now, "tipo_movimiento": data.tipo_movimiento,
         "descripcion": data.descripcion, "debe": debe, "haber": haber, "saldo": nuevo_saldo,
         "fecha_vencimiento": data.fecha_vencimiento},
    )

    # FIFO pagos_proveedores
    if es_pago:
        registros = db.execute(
            text(
                "SELECT id, monto FROM pagos_proveedores "
                "WHERE entidad_gasto_id = :id AND pagado = 0 "
                "ORDER BY fecha_vencimiento ASC, id ASC"
            ),
            {"id": data.entidad_id},
        ).fetchall()
        restante = data.monto
        for pid, monto_r in registros:
            if restante <= 0.0:
                break
            if restante >= monto_r:
                db.execute(text("UPDATE pagos_proveedores SET pagado = 1 WHERE id = :id"), {"id": pid})
                restante -= monto_r
            else:
                db.execute(text("UPDATE pagos_proveedores SET monto = :m WHERE id = :id"), {"m": monto_r - restante, "id": pid})
                restante = 0.0

    # Calendario de pagos (fecha de vencimiento y no pago/multa)
    if data.fecha_vencimiento and not es_pago and not es_multa:
        proveedor = db.execute(
            text("SELECT nombre FROM entidades_gastos WHERE id = :id"), {"id": data.entidad_id}
        ).first()
        proveedor = proveedor[0] if proveedor else "Desconocido"
        exec_insert(
            db, "pagos_proveedores",
            ["entidad_gasto_id", "proveedor", "fecha_vencimiento", "monto", "pagado", "notas", "movimiento_gasto_id"],
            {"entidad_gasto_id": data.entidad_id, "proveedor": proveedor, "fecha_vencimiento": data.fecha_vencimiento,
             "monto": debe, "pagado": 0, "notas": data.descripcion, "movimiento_gasto_id": gasto_id},
        )

    # Impacto en Cuenta WASI
    if es_pago:
        cat = data.categoria or ("Proveedores" if data.tipo_entidad == "Proveedor" else "Sueldos")
        registrar_egreso_wasi(db, cat, f"Pago a {data.tipo_entidad.lower()}: {data.descripcion}", data.monto, gasto_id)
        registrar_actividad(db, "Pago", data.descripcion, f"gasto:{gasto_id}")
    else:
        registrar_actividad(db, "Gasto", data.descripcion, f"gasto:{gasto_id}")
    db.commit()
    return gasto_id


@router.get("/movimientos/{mov_id}/dependencies")
def get_movimiento_gasto_dependencies(mov_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text(
            "SELECT mg.entidad_id, mg.descripcion, mg.debe, mg.haber, e.nombre, e.tipo "
            "FROM movimientos_gastos mg JOIN entidades_gastos e ON e.id = mg.entidad_id WHERE mg.id = :id"
        ),
        {"id": mov_id},
    ).first()
    if not row:
        return None
    _entidad_id, descripcion, debe, haber, entidad_nombre, entidad_tipo = row
    wasi_count = db.execute(
        text("SELECT COUNT(*) FROM movimientos_wasi WHERE movimiento_gasto_id = :id"), {"id": mov_id}
    ).scalar() or 0
    return {
        "descripcion": descripcion, "entidad_nombre": entidad_nombre, "entidad_tipo": entidad_tipo,
        "debe": debe, "haber": haber, "tiene_wasi_vinculado": wasi_count > 0,
    }


@router.post("/movimientos/{mov_id}")
def update_movimiento_gasto(mov_id: int, data: UpdateMovimientoGastoData, db: Session = Depends(get_db)):
    if not math.isfinite(data.debe) or not math.isfinite(data.haber) or data.debe < 0.0 or data.haber < 0.0:
        raise HTTPException(status_code=400, detail="Los importes del gasto deben ser válidos y no negativos")
    row = db.execute(
        text(
            "SELECT entidad_id, (SELECT id FROM movimientos_wasi WHERE movimiento_gasto_id = mg.id LIMIT 1) "
            "FROM movimientos_gastos mg WHERE mg.id = :id"
        ),
        {"id": mov_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    entidad_id, linked_wasi_id = row[0], row[1]
    db.execute(
        text(
            "UPDATE movimientos_gastos SET debe=:debe, haber=:haber, descripcion=:descripcion, "
            "tipo_movimiento=:tipo, fecha_vencimiento=:fv WHERE id=:id"
        ),
        {"debe": data.debe, "haber": data.haber, "descripcion": data.descripcion,
         "tipo": data.tipo_movimiento, "fv": data.fecha_vencimiento, "id": mov_id},
    )
    es_pago = data.tipo_movimiento == "Pago"
    pp_row = db.execute(
        text("SELECT id FROM pagos_proveedores WHERE movimiento_gasto_id = :id"), {"id": mov_id}
    ).first()
    if pp_row:
        pp_id = pp_row[0]
        if es_pago or not data.fecha_vencimiento:
            db.execute(text("DELETE FROM pagos_proveedores WHERE id = :id"), {"id": pp_id})
        else:
            db.execute(
                text("UPDATE pagos_proveedores SET fecha_vencimiento=:fv, monto=:m, notas=:notas WHERE id=:id"),
                {"fv": data.fecha_vencimiento, "m": data.debe, "notas": data.descripcion, "id": pp_id},
            )
    elif data.fecha_vencimiento and not es_pago:
        proveedor = db.execute(
            text("SELECT nombre FROM entidades_gastos WHERE id = :id"), {"id": entidad_id}
        ).first()
        proveedor = proveedor[0] if proveedor else "Desconocido"
        exec_insert(
            db, "pagos_proveedores",
            ["entidad_gasto_id", "proveedor", "fecha_vencimiento", "monto", "pagado", "notas", "movimiento_gasto_id"],
            {"entidad_gasto_id": entidad_id, "proveedor": proveedor, "fecha_vencimiento": data.fecha_vencimiento,
             "monto": data.debe, "pagado": 0, "notas": data.descripcion, "movimiento_gasto_id": mov_id},
        )
    recalcular_saldos(db, entidad_id)
    es_pago_valido = data.tipo_movimiento == "Pago" and data.haber > 0.0
    if linked_wasi_id:
        if es_pago_valido:
            ent_tipo = db.execute(
                text("SELECT tipo FROM entidades_gastos WHERE id = :id"), {"id": entidad_id}
            ).first()
            categoria = "Sueldos" if (ent_tipo and ent_tipo[0] == "Empleado") else "Proveedores"
            db.execute(
                text("UPDATE movimientos_wasi SET monto=:m, concepto=:c, categoria=:cat WHERE id=:id"),
                {"m": data.haber, "c": data.descripcion, "cat": categoria, "id": linked_wasi_id},
            )
        else:
            db.execute(text("DELETE FROM movimientos_wasi WHERE id = :id"), {"id": linked_wasi_id})
    elif es_pago_valido:
        ent_tipo = db.execute(
            text("SELECT tipo FROM entidades_gastos WHERE id = :id"), {"id": entidad_id}
        ).first()
        categoria = "Sueldos" if (ent_tipo and ent_tipo[0] == "Empleado") else "Proveedores"
        registrar_egreso_wasi(db, categoria, data.descripcion, data.haber, mov_id)
    db.commit()
    return {"status": "ok"}


@router.delete("/movimientos/{mov_id}")
def delete_movimiento_gasto(mov_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT entidad_id FROM movimientos_gastos WHERE id = :id"), {"id": mov_id}).first()
    entidad_id = row[0] if row else 0
    db.execute(text("DELETE FROM movimientos_gastos WHERE id = :id"), {"id": mov_id})
    db.execute(text("DELETE FROM pagos_proveedores WHERE movimiento_gasto_id = :id"), {"id": mov_id})
    db.execute(text("DELETE FROM movimientos_wasi WHERE movimiento_gasto_id = :id"), {"id": mov_id})
    if entidad_id > 0:
        recalcular_saldos(db, entidad_id)
    db.commit()
    return {"status": "ok"}


# ── Empleados ───────────────────────────────────────────────────────────────

@router.get("/empleados/{entidad_id}/config")
def get_empleado_config(entidad_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT id, entidad_id, sueldo_base, modalidad, multa_monto FROM empleados_config WHERE entidad_id = :id"),
        {"id": entidad_id},
    ).first()
    if not row:
        return None
    return {"id": row[0], "entidad_id": row[1], "sueldo_base": row[2], "modalidad": row[3], "multa_monto": row[4]}


@router.post("/empleados/{entidad_id}/config")
def save_empleado_config(entidad_id: int, sueldo_base: float, modalidad: str = "Mensual", multa_monto: float = 0.0, db: Session = Depends(get_db)):
    db.execute(
        text(
            "INSERT INTO empleados_config (entidad_id, sueldo_base, modalidad, multa_monto) "
            "VALUES (:eid, :sueldo, :modalidad, :multa) "
            "ON CONFLICT(entidad_id) DO UPDATE SET sueldo_base=excluded.sueldo_base, "
            "modalidad=excluded.modalidad, multa_monto=excluded.multa_monto"
        ),
        {"eid": entidad_id, "sueldo": sueldo_base, "modalidad": modalidad, "multa": multa_monto},
    )
    db.commit()
    return {"status": "ok"}


@router.get("/empleados/{entidad_id}/asistencia")
def get_asistencia_empleado(entidad_id: int, limit: int = 31, db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT id, entidad_id, fecha, estado, nota, hora FROM asistencia_empleados "
            "WHERE entidad_id = :id ORDER BY id DESC LIMIT :lim"
        ),
        {"id": entidad_id, "lim": limit},
    ).fetchall()
    return [
        {"id": r[0], "entidad_id": r[1], "fecha": r[2], "estado": r[3], "nota": r[4], "hora": r[5]}
        for r in rows
    ]


@router.post("/empleados/asistencia")
def registrar_asistencia_empleado(data: AsistenciaData, db: Session = Depends(get_db)):
    exec_insert(
        db, "asistencia_empleados", ["entidad_id", "fecha", "estado", "nota", "hora"],
        {"entidad_id": data.entidad_id, "fecha": data.fecha, "estado": data.estado, "nota": data.nota, "hora": data.hora},
    )
    db.commit()
    return {"status": "ok"}


@router.post("/asistencia/{asistencia_id}")
def update_asistencia_empleado(asistencia_id: int, estado: str, hora: str = "", nota: str = "", db: Session = Depends(get_db)):
    db.execute(
        text("UPDATE asistencia_empleados SET estado=:e, hora=:h, nota=:n WHERE id=:id"),
        {"e": estado, "h": hora, "n": nota, "id": asistencia_id},
    )
    db.commit()
    return {"status": "ok"}


@router.delete("/asistencia/{asistencia_id}")
def delete_asistencia_empleado(asistencia_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM asistencia_empleados WHERE id = :id"), {"id": asistencia_id})
    db.commit()
    return {"status": "ok"}


@router.get("/empleados/{entidad_id}/pagado-mes")
def empleado_pagado_mes(entidad_id: int, mes: int, anio: int, db: Session = Depends(get_db)):
    sueldo_base = db.execute(
        text("SELECT sueldo_base FROM empleados_config WHERE entidad_id = :id"), {"id": entidad_id}
    ).scalar() or 0.0
    if sueldo_base <= 0.0:
        return False
    patron = f"%/{mes:02d}/{anio}%"
    total_pagado = db.execute(
        text("SELECT COALESCE(SUM(haber), 0) FROM movimientos_gastos WHERE entidad_id = :id AND tipo_movimiento = 'Pago' AND fecha LIKE :p"),
        {"id": entidad_id, "p": patron},
    ).scalar() or 0.0
    total_multas = db.execute(
        text("SELECT COALESCE(SUM(haber), 0) FROM movimientos_gastos WHERE entidad_id = :id AND tipo_movimiento = 'Multa' AND fecha LIKE :p"),
        {"id": entidad_id, "p": patron},
    ).scalar() or 0.0
    return total_pagado >= sueldo_base - total_multas


@router.get("/empleados/estado-mes")
def get_estado_empleados_mes(mes: int, anio: int, db: Session = Depends(get_db)):
    patron = f"%/{mes:02d}/{anio}%"
    rows = db.execute(
        text(
            "SELECT e.id, "
            "COALESCE(ec.sueldo_base, 0) > 0 "
            "AND COALESCE((SELECT SUM(haber) FROM movimientos_gastos WHERE entidad_id = e.id AND tipo_movimiento = 'Pago' AND fecha LIKE :p), 0) "
            ">= COALESCE(ec.sueldo_base, 0) - COALESCE((SELECT SUM(haber) FROM movimientos_gastos "
            "WHERE entidad_id = e.id AND tipo_movimiento = 'Multa' AND fecha LIKE :p), 0) "
            "FROM entidades_gastos e LEFT JOIN empleados_config ec ON ec.entidad_id = e.id "
            "WHERE e.tipo = 'Empleado' ORDER BY e.nombre ASC"
        ),
        {"p": patron},
    ).fetchall()
    return [{"id": r[0], "pagado": bool(r[1])} for r in rows]


@router.get("/empleados/no-pagados-mes")
def get_empleados_no_pagados_mes(mes: int, anio: int, db: Session = Depends(get_db)):
    patron = f"%/{mes:02d}/{anio}%"
    rows = db.execute(
        text(
            "SELECT e.id, e.nombre, ec.sueldo_base, "
            "COALESCE((SELECT SUM(haber) FROM movimientos_gastos WHERE entidad_id = e.id AND tipo_movimiento = 'Pago' AND fecha LIKE :p), 0) AS total_pagado, "
            "COALESCE((SELECT SUM(haber) FROM movimientos_gastos WHERE entidad_id = e.id AND tipo_movimiento = 'Multa' AND fecha LIKE :p), 0) AS total_multas "
            "FROM entidades_gastos e JOIN empleados_config ec ON ec.entidad_id = e.id "
            "WHERE e.tipo = 'Empleado' AND ec.sueldo_base > 0 ORDER BY e.nombre ASC"
        ),
        {"p": patron},
    ).fetchall()
    result = []
    for r in rows:
        emp = {"id": r[0], "nombre": r[1], "sueldo_base": r[2], "total_pagado": r[3], "total_multas": r[4]}
        if emp["total_pagado"] < emp["sueldo_base"] - emp["total_multas"]:
            result.append(emp)
    return result