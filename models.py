# models.py
from __future__ import annotations
from datetime import datetime, date, time
from typing import Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from sqlalchemy import UniqueConstraint, Index

db = SQLAlchemy()

# ----------------------------
# Helpers
# ----------------------------
class BaseModel:
    """Fornece um __init__ flexível baseado em kwargs (compatível com SQLAlchemy)."""
    def __init__(self, **kwargs):
        super().__init__()
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self) -> str:
        cls = self.__class__.__name__
        if hasattr(self, "id"):
            return f"<{cls} id={getattr(self, 'id', None)}>"
        return f"<{cls}>"

# ----------------------------
# Core
# ----------------------------
class User(db.Model, BaseModel):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  nullable=False, unique=True, index=True)
    email         = db.Column(db.String(120), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(128), nullable=False)

    name          = db.Column(db.String(120))
    birthdate     = db.Column(db.Date)
    profile_image = db.Column(db.String(200), default="images/user-icon.png")

    # plano / assinatura (se quiser usar no futuro)
    plan            = db.Column(db.String(20), default="standard")
    plan_status     = db.Column(db.String(20), default="inactive")
    plan_expires_at = db.Column(db.DateTime)
    trial_until     = db.Column(db.DateTime)

    # Relacionamentos
    suppliers      = relationship("Supplier", back_populates="user", cascade="all, delete-orphan")
    products       = relationship("Product",  back_populates="user", cascade="all, delete-orphan")
    agenda_events  = relationship("AgendaEvent", back_populates="user", cascade="all, delete-orphan")
    package_usage  = relationship("PackageUsage", back_populates="user", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email",    name="uq_users_email"),
    )

class Supplier(db.Model, BaseModel):
    __tablename__ = "suppliers"

    id      = db.Column(db.Integer, primary_key=True)
    name    = db.Column(db.String(120), nullable=False)
    email   = db.Column(db.String(120))
    phone   = db.Column(db.String(20))

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    user    = relationship("User", back_populates="suppliers")

    __table_args__ = (
        Index("ix_suppliers_email", "email"),
        Index("ix_suppliers_phone", "phone"),
    )

class Product(db.Model, BaseModel):
    __tablename__ = "products"

    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(120), nullable=False)
    purchase_price = db.Column(db.Float, nullable=False, default=0.0)
    sale_price     = db.Column(db.Float, nullable=False, default=0.0)
    quantity       = db.Column(db.Integer, nullable=False, default=0)
    status         = db.Column(db.String(20), default="Ativo", nullable=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    user           = relationship("User", back_populates="products")

    __table_args__ = (
        Index("ix_products_status", "status"),
        Index("ix_products_created_at", "created_at"),
    )

class Doctor(db.Model, BaseModel):
    __tablename__ = "doctors"

    id    = db.Column(db.Integer, primary_key=True)
    name  = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))

    patients = relationship("Patient", back_populates="doctor", cascade="all, delete-orphan")
    consults = relationship("Consult", back_populates="doctor", cascade="all, delete-orphan")

class Patient(db.Model, BaseModel):
    __tablename__ = "patients"

    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(120), nullable=False)
    age          = db.Column(db.Integer)
    cpf          = db.Column(db.String(20))
    gender       = db.Column(db.String(20))
    phone        = db.Column(db.String(20))

    doctor_id    = db.Column(db.Integer, db.ForeignKey("doctors.id"), index=True)
    doctor       = relationship("Doctor", back_populates="patients")

    prescription = db.Column(db.Text)
    status       = db.Column(db.String(20), default="Ativo", nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    consults     = relationship("Consult", back_populates="patient", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_patients_status", "status"),
        Index("ix_patients_created_at", "created_at"),
        Index("ix_patients_phone", "phone"),
        Index("ix_patients_cpf", "cpf"),
    )

class Consult(db.Model, BaseModel):
    __tablename__ = "consults"

    id         = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id  = db.Column(db.Integer, db.ForeignKey("doctors.id"),  nullable=False, index=True)

    notes      = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    date       = db.Column(db.Date, nullable=False)
    time       = db.Column(db.Time)  # pode ser NULL em eventos "dia todo"

    patient    = relationship("Patient", back_populates="consults")
    doctor     = relationship("Doctor",  back_populates="consults")

# ----------------------------
# Pacotes / Créditos de Análise
# ----------------------------
class PackageUsage(db.Model, BaseModel):
    __tablename__ = "package_usage"

    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)
    total   = db.Column(db.Integer, nullable=False, default=50)
    used    = db.Column(db.Integer, nullable=False, default=0)

    user    = relationship("User", back_populates="package_usage")

    @property
    def remaining(self) -> int:
        try:
            return max(0, int(self.total) - int(self.used))
        except Exception:
            return 0

# ----------------------------
# Agenda simples (para o calendário)
# ----------------------------
class AgendaEvent(db.Model, BaseModel):
    __tablename__ = "agenda_events"

    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=True)  # pode ser global (None)
    title   = db.Column(db.String(200), nullable=False)
    start   = db.Column(db.DateTime, nullable=False)
    end     = db.Column(db.DateTime, nullable=True)

    user    = relationship("User", back_populates="agenda_events")

    __table_args__ = (
        Index("ix_agenda_events_start", "start"),
        Index("ix_agenda_events_end", "end"),
    )

# ----------------------------
# Cotações
# ----------------------------
class Quote(db.Model, BaseModel):
    __tablename__ = "quotes"

    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.String(200), nullable=False)
    items      = db.Column(db.Text, nullable=False)   # exemplo: itens por linha ou JSON string
    suppliers  = db.Column(db.Text, nullable=False)   # ids separados por vírgula (ou JSON string)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_quotes_created_at", "created_at"),
    )

class Reference(db.Model, BaseModel):
    __tablename__ = "references"

    id    = db.Column(db.Integer, primary_key=True)
    key   = db.Column(db.String(120), nullable=False, unique=True, index=True)
    value = db.Column(db.Text, nullable=True)

class Video(db.Model, BaseModel):
    __tablename__ = "videos"

    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.String(200), nullable=False)
    url        = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_videos_created_at", "created_at"),
    )
