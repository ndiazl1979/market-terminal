"""Utilidades: hash de contraseñas, tokens de sesión, normalización de placas."""
import re
import secrets
from datetime import datetime, timedelta

import bcrypt
import jwt

from .config import settings


def hash_password(raw: str) -> str:
    # bcrypt trabaja sobre bytes y limita a 72; truncamos de forma segura.
    return bcrypt.hashpw(raw.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def make_session_token(username: str, role: str) -> str:
    exp = datetime.utcnow() + timedelta(hours=settings.token_ttl_hours)
    payload = {"sub": username, "role": role, "exp": exp}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_session_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def new_visitor_token() -> str:
    """Token opaco y aleatorio para el QR de visita."""
    return secrets.token_urlsafe(24)


def normalize_plate(plate: str) -> str:
    """Deja la placa comparable: mayúsculas, solo alfanumérico."""
    return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())
