"""WASI API — FastAPI backend (patrón backend_gal).

Ejecución:
  uvicorn main:app --host 0.0.0.0 --port 8000

Endpoint de salud sin DB para keep-alive (Uptime Robot).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from database import API_KEY
from migrations import run_migrations
from auth import login
from routers import (
    clientes,
    productos,
    facturas,
    dashboard,
    gastos,
    produccion,
    proceso,
    metricas,
    cuenta_wasi,
    cuenta_corriente,
    maquinas,
    costos_medias,
    pagos,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


app = FastAPI(title="WASI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", include_in_schema=False)
@app.head("/health", include_in_schema=False)
def health():
    """Health check liviano para keep-alive. Sin DB, siempre 200."""
    return {"status": "ok"}


class _LoginBody:
    pass


@app.post("/auth/login")
def do_login(body: dict):
    password = (body or {}).get("password", "")
    return login(password)


@app.get("/auth/health")
def auth_health(x_api_key: str | None = Header(default=None)):
    if API_KEY and (not x_api_key or x_api_key != API_KEY):
        raise HTTPException(status_code=401, detail="API key inválida")
    return {"ok": True}


app.include_router(clientes.router)
app.include_router(productos.router)
app.include_router(facturas.router)
app.include_router(dashboard.router)
app.include_router(gastos.router)
app.include_router(produccion.router)
app.include_router(proceso.router)
app.include_router(metricas.router)
app.include_router(cuenta_wasi.router)
app.include_router(cuenta_corriente.router)
app.include_router(maquinas.router)
app.include_router(costos_medias.router)
app.include_router(pagos.router)