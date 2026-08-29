"""Modelos de datos: unidades, residentes, vehículos, visitas y bitácora."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


def now():
    return datetime.utcnow()


class User(Base):
    """Usuario del panel (administrador o portería/guardia)."""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="guard")  # admin | guard
    created_at = Column(DateTime, default=now)


class Unit(Base):
    """Unidad del condominio (departamento / casa / lote)."""
    __tablename__ = "units"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)   # p.ej. "Torre A - 302"
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=now)

    residents = relationship("Resident", back_populates="unit", cascade="all, delete-orphan")


class Resident(Base):
    """Residente asociado a una unidad."""
    __tablename__ = "residents"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String, default="")
    email = Column(String, default="")
    unit_id = Column(Integer, ForeignKey("units.id"))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)

    unit = relationship("Unit", back_populates="residents")
    vehicles = relationship("Vehicle", back_populates="resident", cascade="all, delete-orphan")


class Vehicle(Base):
    """Vehículo en la lista blanca (placa autorizada)."""
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True)
    plate = Column(String, index=True, nullable=False)   # normalizada (sin guiones/espacios)
    plate_display = Column(String, default="")           # como la escribió el usuario
    description = Column(String, default="")             # p.ej. "Toyota Hilux gris"
    resident_id = Column(Integer, ForeignKey("residents.id"))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)

    resident = relationship("Resident", back_populates="vehicles")


class Visitor(Base):
    """Pase de visitante con QR firmado y ventana de validez."""
    __tablename__ = "visitors"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    plate = Column(String, default="")            # opcional
    unit_id = Column(Integer, ForeignKey("units.id"))
    token = Column(String, unique=True, index=True)
    valid_from = Column(DateTime, default=now)
    valid_until = Column(DateTime, nullable=False)
    max_uses = Column(Integer, default=1)
    uses = Column(Integer, default=0)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)

    unit = relationship("Unit")


class AccessLog(Base):
    """Bitácora de cada intento de acceso (placa o QR)."""
    __tablename__ = "access_logs"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=now, index=True)
    kind = Column(String)                 # anpr | qr | manual
    plate = Column(String, default="")
    decision = Column(String)             # authorized | denied
    reason = Column(String, default="")
    gate_opened = Column(Boolean, default=False)
    snapshot = Column(String, default="") # ruta relativa a la foto
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=True)
    visitor_id = Column(Integer, ForeignKey("visitors.id"), nullable=True)
