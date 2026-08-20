"""Auth: X-API-Key para transport + login admin/taller (roles validados en backend).

- Cada request (menos /health y /auth/login) exige X-API-Key si WASI_API_KEY está definida.
- POST /auth/login valida password contra WASI_ADMIN_PASSWORD / WASI_TALLER_PASSWORD
  y devuelve el rol. Endpoints de "taller" se restringen server-side vía require_role.
"""
from enum import Enum

from fastapi import Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from database import ADMIN_PASSWORD, API_KEY, TALLER_PASSWORD

_bearer = HTTPBearer(auto_error=False)


class Role(str, Enum):
    admin = "admin"
    taller = "taller"


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida")


def login(password: str) -> dict:
    if ADMIN_PASSWORD and password == ADMIN_PASSWORD:
        return {"role": Role.admin.value}
    if TALLER_PASSWORD and password == TALLER_PASSWORD:
        return {"role": Role.taller.value}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña incorrecta")