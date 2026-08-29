"""Pases de visitante por QR: generar, mostrar imagen y validar en la barrera."""
import io
from datetime import datetime, timedelta

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..gate import open_gate
from ..models import AccessLog, Visitor
from ..security import new_visitor_token, normalize_plate

router = APIRouter(prefix="/api/qr", tags=["qr"])


class VisitorIn(BaseModel):
    name: str
    plate: str = ""
    unit_id: int | None = None
    hours_valid: int = 24
    max_uses: int = 1


@router.post("/visitors")
def create_visitor(data: VisitorIn, db: Session = Depends(get_db),
                   _=Depends(get_current_user)):
    v = Visitor(
        name=data.name,
        plate=normalize_plate(data.plate),
        unit_id=data.unit_id,
        token=new_visitor_token(),
        valid_from=datetime.utcnow(),
        valid_until=datetime.utcnow() + timedelta(hours=data.hours_valid),
        max_uses=max(1, data.max_uses),
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return _serialize(v)


@router.get("/visitors")
def list_visitors(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(Visitor).order_by(Visitor.created_at.desc()).limit(200).all()
    return [_serialize(v) for v in rows]


@router.post("/visitors/{vid}/revoke")
def revoke_visitor(vid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    v = db.get(Visitor, vid)
    if not v:
        raise HTTPException(404, "no existe")
    v.revoked = True
    db.commit()
    return {"ok": True}


@router.get("/visitors/{vid}/image")
def qr_image(vid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    v = db.get(Visitor, vid)
    if not v:
        raise HTTPException(404, "no existe")
    img = qrcode.make(v.token)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


class QRValidateIn(BaseModel):
    token: str


@router.post("/validate")
def validate_qr(data: QRValidateIn, db: Session = Depends(get_db)):
    """Lo llama el lector/guardia en la barrera. NO requiere login para que
    un lector de QR de red o el celular del guardia lo puedan invocar
    (protégelo por red o añade un token si lo expones a internet)."""
    v = db.query(Visitor).filter(Visitor.token == data.token).first()
    now = datetime.utcnow()

    def deny(reason):
        db.add(AccessLog(kind="qr", decision="denied", reason=reason,
                         plate=v.plate if v else "", visitor_id=v.id if v else None))
        db.commit()
        return {"ok": False, "authorized": False, "reason": reason}

    if not v:
        return deny("QR desconocido")
    if v.revoked:
        return deny("pase revocado")
    if now < v.valid_from or now > v.valid_until:
        return deny("pase fuera de vigencia")
    if v.uses >= v.max_uses:
        return deny("pase sin usos disponibles")

    v.uses += 1
    gate_opened, detail = open_gate()
    db.add(AccessLog(kind="qr", decision="authorized",
                     reason=f"visita {v.name} — barrera: {detail}",
                     plate=v.plate, gate_opened=gate_opened, visitor_id=v.id))
    db.commit()
    return {"ok": True, "authorized": True, "visitor": v.name,
            "gate_opened": gate_opened, "uses_left": v.max_uses - v.uses}


def _serialize(v: Visitor) -> dict:
    return {
        "id": v.id, "name": v.name, "plate": v.plate, "unit_id": v.unit_id,
        "token": v.token,
        "valid_from": v.valid_from.isoformat(),
        "valid_until": v.valid_until.isoformat(),
        "max_uses": v.max_uses, "uses": v.uses, "revoked": v.revoked,
    }
