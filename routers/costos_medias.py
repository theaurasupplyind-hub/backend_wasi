"""Router /costos-medias — migrado de JSON local a tabla (decisión Fase 2).

El JSON original (costos_medias.json) se vuelca a la tabla `costos_medias`
durante la migración de datos (Fase 3).
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_api_key
from db_utils import exec_insert

router = APIRouter(prefix="/costos-medias", tags=["costos_medias"], dependencies=[Depends(verify_api_key)])

DEFAULT_CALC = {
    "docenas": 1000,
    "pares_por_docena": 12,
    "peso_por_par_kg": 0.042,
    "algodon_total": 2785944.0,
    "lycra_base": 334660.0,
    "goma_base": 468220.0,
    "factor": 1.455,
    "descuento_efectivo_pct": 0.15,
    "mano_de_obra": 1700000.0,
    "otros_accesorios": 500000.0,
    "escenarios_precios": [13500.0, 13000.0, 12500.0, 12000.0, 11000.0, 10500.0, 10000.0],
}

COLS = [
    "docenas", "pares_por_docena", "peso_por_par_kg", "algodon_total", "lycra_base", "goma_base",
    "factor", "descuento_efectivo_pct", "mano_de_obra", "otros_accesorios", "escenarios_precios",
]


class CostosCalc(BaseModel):
    docenas: int = 1000
    pares_por_docena: int = 12
    peso_por_par_kg: float = 0.042
    algodon_total: float = 2785944.0
    lycra_base: float = 334660.0
    goma_base: float = 468220.0
    factor: float = 1.455
    descuento_efectivo_pct: float = 0.15
    mano_de_obra: float = 1700000.0
    otros_accesorios: float = 500000.0
    escenarios_precios: list[float] = Field(default_factory=lambda: list(DEFAULT_CALC["escenarios_precios"]))


def _row_to_calc(row) -> dict:
    vals = dict(row._mapping)
    calc = {k: vals[k] for k in COLS if k in vals}
    esc = calc.get("escenarios_precios")
    try:
        calc["escenarios_precios"] = json.loads(esc) if isinstance(esc, str) else (esc or [])
    except (ValueError, TypeError):
        calc["escenarios_precios"] = []
    return calc


@router.get("")
def costos_medias_listar(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT nombre FROM costos_medias ORDER BY nombre ASC")).fetchall()
    return [r[0] for r in rows]


@router.post("")
def costos_medias_guardar(nombre: str, calc: CostosCalc, db: Session = Depends(get_db)):
    nombre = nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="Ingresá un nombre para guardar.")
    values = {k: getattr(calc, k) for k in COLS}
    values["escenarios_precios"] = json.dumps(values["escenarios_precios"])
    values["nombre"] = nombre
    db.execute(
        text(
            "INSERT INTO costos_medias (nombre, docenas, pares_por_docena, peso_por_par_kg, algodon_total, "
            "lycra_base, goma_base, factor, descuento_efectivo_pct, mano_de_obra, otros_accesorios, escenarios_precios) "
            "VALUES (:nombre, :docenas, :pares_por_docena, :peso_por_par_kg, :algodon_total, :lycra_base, "
            ":goma_base, :factor, :descuento_efectivo_pct, :mano_de_obra, :otros_accesorios, :escenarios_precios) "
            "ON CONFLICT(nombre) DO UPDATE SET docenas=excluded.docenas, pares_por_docena=excluded.pares_por_docena, "
            "peso_por_par_kg=excluded.peso_por_par_kg, algodon_total=excluded.algodon_total, lycra_base=excluded.lycra_base, "
            "goma_base=excluded.goma_base, factor=excluded.factor, descuento_efectivo_pct=excluded.descuento_efectivo_pct, "
            "mano_de_obra=excluded.mano_de_obra, otros_accesorios=excluded.otros_accesorios, "
            "escenarios_precios=excluded.escenarios_precios"
        ),
        values,
    )
    db.commit()
    return {"status": "ok"}


@router.get("/{nombre}")
def costos_medias_cargar(nombre: str, db: Session = Depends(get_db)):
    row = db.execute(
        text(f"SELECT nombre, {', '.join(COLS)} FROM costos_medias WHERE nombre = :nombre"), {"nombre": nombre}
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Config no encontrada")
    calc = _row_to_calc(row)
    calc.pop("nombre", None)
    return calc


@router.delete("/{nombre}")
def costos_medias_eliminar(nombre: str, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM costos_medias WHERE nombre = :nombre"), {"nombre": nombre})
    db.commit()
    return {"status": "ok"}