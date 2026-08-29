"""Recepción de eventos ANPR de la cámara Dahua y decisión de acceso.

La cámara Dahua ITC413 puede enviar cada lectura de placa por HTTP
(Configuración ▸ Red ▸ HTTP Listen / o "Cargar" a un servidor HTTP).
El formato varía por firmware, así que este endpoint es tolerante:
acepta JSON, form-data, query-string y multipart con imagen, y busca la
placa en las claves más comunes.
"""
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..gate import open_gate
from ..models import AccessLog, Vehicle
from ..security import normalize_plate

log = logging.getLogger("anpr")
router = APIRouter(prefix="/api/anpr", tags=["anpr"])

# Claves donde distintos firmwares Dahua ponen el texto de la placa.
PLATE_KEYS = [
    "plateNumber", "PlateNumber", "plate", "Plate",
    "text", "Text", "sPlateNumber",
    "Picture.Plate.PlateNumber", "Events[0].Plate.PlateNumber",
]


def _dig(data: dict, dotted: str):
    cur = data
    for part in dotted.replace("]", "").replace("[", ".").split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _extract_plate(payload: dict) -> str:
    for key in PLATE_KEYS:
        val = _dig(payload, key) if "." in key or "[" in key else payload.get(key)
        if val:
            return str(val)
    # búsqueda profunda por si viene anidado con otro nombre
    for k, v in payload.items():
        if isinstance(v, str) and "plate" in k.lower() and v.strip():
            return v
    return ""


async def _parse_request(request: Request) -> tuple[dict, bytes | None]:
    """Devuelve (campos, imagen_jpg opcional) de cualquier tipo de envío."""
    ctype = request.headers.get("content-type", "")
    fields: dict = dict(request.query_params)
    image: bytes | None = None

    if "application/json" in ctype:
        try:
            body = await request.json()
            if isinstance(body, dict):
                fields.update(body)
        except Exception:  # noqa: BLE001
            pass
    elif "multipart/form-data" in ctype or "form-urlencoded" in ctype:
        form = await request.form()
        for k, v in form.items():
            if hasattr(v, "read"):  # UploadFile
                content = await v.read()
                if content[:2] == b"\xff\xd8":  # JPEG
                    image = content
                else:
                    fields[k] = content.decode("utf-8", "ignore")
            else:
                fields[k] = v
    else:
        raw = await request.body()
        if raw[:2] == b"\xff\xd8":
            image = raw
        elif raw:
            try:
                import json
                fields.update(json.loads(raw))
            except Exception:  # noqa: BLE001
                fields["_raw"] = raw.decode("utf-8", "ignore")[:500]
    return fields, image


@router.post("/event")
async def anpr_event(request: Request, db: Session = Depends(get_db)):
    # Verificación opcional de token compartido con la cámara.
    if settings.anpr_ingest_token:
        supplied = request.query_params.get("token") or request.headers.get("x-anpr-token")
        if supplied != settings.anpr_ingest_token:
            return {"ok": False, "error": "token inválido"}

    fields, image = await _parse_request(request)
    raw_plate = _extract_plate(fields)
    plate = normalize_plate(raw_plate)
    log.info("Evento ANPR: placa=%r norm=%r campos=%s", raw_plate, plate, list(fields)[:8])

    # Guardar la foto si vino.
    snap_path = ""
    if image:
        os.makedirs(settings.snapshot_dir, exist_ok=True)
        fname = f"{datetime.utcnow():%Y%m%d-%H%M%S}-{plate or 'sin'}.jpg"
        with open(os.path.join(settings.snapshot_dir, fname), "wb") as f:
            f.write(image)
        snap_path = fname

    if not plate:
        db.add(AccessLog(kind="anpr", plate="", decision="denied",
                         reason="no se pudo leer la placa", snapshot=snap_path))
        db.commit()
        return {"ok": False, "error": "placa no reconocida"}

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.plate == plate, Vehicle.active == True)  # noqa: E712
        .first()
    )

    authorized = vehicle is not None
    reason = "vehículo autorizado" if authorized else "placa no registrada"
    resident_id = vehicle.resident_id if vehicle else None

    if not authorized and settings.open_on_unknown_plate:
        authorized = True
        reason = "placa no registrada (apertura abierta activada)"

    gate_opened = False
    if authorized:
        gate_opened, detail = open_gate()
        reason = f"{reason} — barrera: {detail}"

    db.add(AccessLog(
        kind="anpr", plate=plate,
        decision="authorized" if authorized else "denied",
        reason=reason, gate_opened=gate_opened,
        snapshot=snap_path, resident_id=resident_id,
    ))
    db.commit()
    return {"ok": True, "plate": plate, "authorized": authorized, "gate_opened": gate_opened}
