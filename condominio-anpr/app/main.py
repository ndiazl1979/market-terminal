"""Punto de entrada FastAPI del sistema de condominio ANPR."""
import logging
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, engine
from .models import User
from .routers import anpr, auth, manage, qr
from .security import hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Condominio ANPR", version="1.0")

WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    os.makedirs(settings.snapshot_dir, exist_ok=True)
    # Crea el admin inicial si no hay usuarios.
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add(User(username=settings.admin_user,
                        password_hash=hash_password(settings.admin_password),
                        role="admin"))
            db.commit()
            logging.getLogger("startup").info("Usuario admin '%s' creado.", settings.admin_user)
    finally:
        db.close()


app.include_router(auth.router)
app.include_router(anpr.router)
app.include_router(qr.router)
app.include_router(manage.router)

# Fotos capturadas por la cámara.
app.mount("/snapshots", StaticFiles(directory=settings.snapshot_dir), name="snapshots")


@app.get("/health")
def health():
    return {"status": "ok", "gate_mode": settings.gate_mode}


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))
