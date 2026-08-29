"""Dependencias de autenticación para el panel."""
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_session_token


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("session") or ""
    if not token and request.headers.get("authorization", "").startswith("Bearer "):
        token = request.headers["authorization"].split(" ", 1)[1]
    data = decode_session_token(token)
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    user = db.query(User).filter(User.username == data["sub"]).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario inválido")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requiere rol admin")
    return user
