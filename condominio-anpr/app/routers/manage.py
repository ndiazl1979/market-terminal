"""CRUD de condominio: unidades, residentes, vehículos, bitácora y apertura manual."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..gate import open_gate
from ..models import AccessLog, Resident, Unit, Vehicle
from ..security import normalize_plate

router = APIRouter(prefix="/api", tags=["gestion"])


# ── Unidades ────────────────────────────────────────────────
class UnitIn(BaseModel):
    code: str
    notes: str = ""


@router.get("/units")
def list_units(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return [{"id": u.id, "code": u.code, "notes": u.notes,
             "residents": len(u.residents)} for u in db.query(Unit).all()]


@router.post("/units")
def create_unit(data: UnitIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    if db.query(Unit).filter(Unit.code == data.code).first():
        raise HTTPException(400, "código ya existe")
    u = Unit(code=data.code, notes=data.notes)
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"id": u.id, "code": u.code}


@router.delete("/units/{uid}")
def delete_unit(uid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    u = db.get(Unit, uid)
    if u:
        db.delete(u)
        db.commit()
    return {"ok": True}


# ── Residentes ──────────────────────────────────────────────
class ResidentIn(BaseModel):
    name: str
    unit_id: int
    phone: str = ""
    email: str = ""


@router.get("/residents")
def list_residents(db: Session = Depends(get_db), _=Depends(get_current_user)):
    out = []
    for r in db.query(Resident).all():
        out.append({"id": r.id, "name": r.name, "phone": r.phone, "email": r.email,
                    "active": r.active, "unit_id": r.unit_id,
                    "unit": r.unit.code if r.unit else None,
                    "vehicles": [v.plate_display or v.plate for v in r.vehicles]})
    return out


@router.post("/residents")
def create_resident(data: ResidentIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    r = Resident(name=data.name, unit_id=data.unit_id, phone=data.phone, email=data.email)
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": r.id}


@router.delete("/residents/{rid}")
def delete_resident(rid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    r = db.get(Resident, rid)
    if r:
        db.delete(r)
        db.commit()
    return {"ok": True}


# ── Vehículos / lista blanca ────────────────────────────────
class VehicleIn(BaseModel):
    plate: str
    resident_id: int
    description: str = ""


@router.get("/vehicles")
def list_vehicles(db: Session = Depends(get_db), _=Depends(get_current_user)):
    out = []
    for v in db.query(Vehicle).all():
        out.append({"id": v.id, "plate": v.plate, "plate_display": v.plate_display,
                    "description": v.description, "active": v.active,
                    "resident_id": v.resident_id,
                    "resident": v.resident.name if v.resident else None})
    return out


@router.post("/vehicles")
def create_vehicle(data: VehicleIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    norm = normalize_plate(data.plate)
    if not norm:
        raise HTTPException(400, "placa inválida")
    v = Vehicle(plate=norm, plate_display=data.plate.strip().upper(),
                description=data.description, resident_id=data.resident_id)
    db.add(v)
    db.commit()
    db.refresh(v)
    return {"id": v.id, "plate": v.plate}


@router.post("/vehicles/{vid}/toggle")
def toggle_vehicle(vid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    v = db.get(Vehicle, vid)
    if not v:
        raise HTTPException(404, "no existe")
    v.active = not v.active
    db.commit()
    return {"id": v.id, "active": v.active}


@router.delete("/vehicles/{vid}")
def delete_vehicle(vid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    v = db.get(Vehicle, vid)
    if v:
        db.delete(v)
        db.commit()
    return {"ok": True}


# ── Bitácora ────────────────────────────────────────────────
@router.get("/logs")
def list_logs(limit: int = 100, db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(AccessLog).order_by(AccessLog.ts.desc()).limit(min(limit, 500)).all()
    return [{"id": l.id, "ts": l.ts.isoformat(), "kind": l.kind, "plate": l.plate,
             "decision": l.decision, "reason": l.reason, "gate_opened": l.gate_opened,
             "snapshot": l.snapshot} for l in rows]


@router.get("/stats")
def stats(db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = db.query(AccessLog)
    return {
        "total": q.count(),
        "authorized": q.filter(AccessLog.decision == "authorized").count(),
        "denied": q.filter(AccessLog.decision == "denied").count(),
        "units": db.query(Unit).count(),
        "residents": db.query(Resident).count(),
        "vehicles": db.query(Vehicle).count(),
    }


# ── Apertura manual (guardia) ───────────────────────────────
@router.post("/gate/open")
def manual_open(db: Session = Depends(get_db), user=Depends(get_current_user)):
    ok, detail = open_gate()
    db.add(AccessLog(kind="manual", decision="authorized",
                     reason=f"apertura manual por {user.username} — {detail}",
                     gate_opened=ok))
    db.commit()
    return {"ok": ok, "detail": detail}
