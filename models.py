from __future__ import annotations
from datetime import datetime, date, time
from typing import Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from sqlalchemy import UniqueConstraint, Index, ForeignKey

db = SQLAlchemy()


# ----------------------------
# Helpers
# ----------------------------
class BaseModel:
    """__init__ flexível baseado em kwargs (compatível com SQLAlchemy)."""
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
# Empresas (opcional para multi-tenant)
# ----------------------------
class Company(db.Model, BaseModel):
    __tablename__ = "companies"

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    access_code = db.Column(db.String(50), unique=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("access_code", name="uq_companies_access_code"),
        Index("ix_companies_name", "name"),
    )


# ---------------------------
# Core
# ----------------------------
class User(db.Model, BaseModel):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  nullable=False, unique=True, index=True)
    email         = db.Column(db.String(120), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    clinic_phone  = db.Column(db.String(30), nullable=True)

    name          = db.Column(db.String(120))
    birthdate     = db.Column(db.Date)
    profile_image = db.Column(db.String(200), default="images/user-icon.png")

    company_id    = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True)
    company       = relationship("Company", backref="users")

    # plano / assinatura
    plan            = db.Column(db.String(20), default="standard")
    plan_status     = db.Column(db.String(20), default="inactive")
    plan_expiration = db.Column(db.DateTime)
    trial_expiration     = db.Column(db.DateTime)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relacionamentos úteis ao app
    suppliers        = relationship("Supplier", back_populates="user", cascade="all, delete-orphan")
    products         = relationship("Product",  back_populates="user", cascade="all, delete-orphan")
    agenda_events    = relationship("AgendaEvent", back_populates="user", cascade="all, delete-orphan")
    package_usage    = relationship("PackageUsage", back_populates="user", uselist=False, cascade="all, delete-orphan")
    secure_files     = relationship("SecureFile", back_populates="owner", cascade="all, delete-orphan")
    quotes           = relationship("Quote", back_populates="user")
    scheduled_emails = relationship(
        "ScheduledEmail",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True
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
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
    name           = db.Column(db.String(120), nullable=False)
    purchase_price = db.Column(db.Float, nullable=False, default=0.0)
    sale_price     = db.Column(db.Float, nullable=False, default=0.0)
    quantity       = db.Column(db.Integer, nullable=False, default=0)
    status         = db.Column(db.String(20), default="Ativo", nullable=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    code              = db.Column(db.String(64))
    category          = db.Column(db.String(80))
    application_route = db.Column(db.String(80))
    min_stock         = db.Column(db.Integer, default=0)

    user = db.relationship("User", back_populates="products")

    movements = db.relationship(
        "StockMovement",
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    __table_args__ = (
        Index("ix_products_status", "status"),
        Index("ix_products_created_at", "created_at"),
    )



class Doctor(db.Model, BaseModel):
    __tablename__ = "doctors"

    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=True)
    user      = relationship("User", backref="doctors")

    name      = db.Column(db.String(120), nullable=False)
    crm       = db.Column(db.String(40))
    email     = db.Column(db.String(120))
    phone     = db.Column(db.String(20))
    specialty = db.Column(db.String(120))

    patients  = relationship("Patient", back_populates="doctor", cascade="all, delete-orphan")
    consults  = relationship("Consult", back_populates="doctor", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_doctors_name", "name"),
        Index("ix_doctors_crm", "crm"),
        Index("ix_doctors_email", "email"),
        Index("ix_doctors_specialty", "specialty"),
    )


class Patient(db.Model, BaseModel):
    __tablename__ = "patients"

    id            = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    owner         = relationship("User", foreign_keys=[user_id])

    doctor_id    = db.Column(db.Integer, db.ForeignKey("doctors.id"), index=True)
    doctor       = relationship("Doctor", back_populates="patients")

    name           = db.Column(db.String(120), nullable=False)
    birthdate      = db.Column(db.Date)
    sex            = db.Column(db.String(20))
    email          = db.Column(db.String(120))
    cpf            = db.Column(db.String(20))
    notes          = db.Column(db.Text)
    profile_image  = db.Column(db.String(200), default="images/user-icon.png")

    phone_primary   = db.Column(db.String(20))
    phone_secondary = db.Column(db.String(20))

    address_cep        = db.Column(db.String(12))
    address_street     = db.Column(db.String(200))
    address_number     = db.Column(db.String(20))
    address_complement = db.Column(db.String(100))
    address_district   = db.Column(db.String(120))
    address_city       = db.Column(db.String(120))
    address_state      = db.Column(db.String(2))

    status       = db.Column(db.String(20), default="Ativo", nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    consults     = relationship("Consult", back_populates="patient", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_patients_status", "status"),
        Index("ix_patients_created_at", "created_at"),
        Index("ix_patients_phone_primary", "phone_primary"),
        Index("ix_patients_cpf", "cpf"),
        Index("ix_patients_email", "email"),
        Index("ix_patients_user_id", "user_id"),
    )

    # -------- Propriedades de compatibilidade com o template --------
    @property
    def document(self) -> Optional[str]:
        """Compat: usado no template como patient.document (mapeia para cpf)."""
        return self.cpf

    @property
    def phone(self) -> Optional[str]:
        """Compat: usado no template como patient.phone (mapeia para phone_primary)."""
        return self.phone_primary

    @property
    def street(self) -> Optional[str]:
        """Compat: usado no template como patient.street (mapeia para address_street)."""
        return self.address_street

    @property
    def number(self) -> Optional[str]:
        """Compat: usado no template como patient.number (mapeia para address_number)."""
        return self.address_number

    @property
    def zipcode(self) -> Optional[str]:
        """Compat: usado no template como patient.zipcode (mapeia para address_cep)."""
        return self.address_cep

    @property
    def city(self) -> Optional[str]:
        return self.address_city

    @property
    def state(self) -> Optional[str]:
        return self.address_state

    @property
    def profile_image_url(self) -> Optional[str]:
        """
        Compat: o template usa patient.profile_image_url.
        Retorna a string armazenada em profile_image (que já é um caminho válido,
        ex.: '/files/img/<id>' ou 'images/patient-icon.png').
        """
        return self.profile_image


class Consult(db.Model, BaseModel):
    __tablename__ = "consults"

    id         = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id  = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=True, index=True)

    notes      = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    date       = db.Column(db.Date, nullable=False)
    time       = db.Column(db.Time)

    patient    = relationship("Patient", back_populates="consults")
    doctor     = relationship("Doctor",  back_populates="consults")


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


class AgendaEvent(db.Model, BaseModel):
    __tablename__ = "agenda_events"

    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=True)
    title   = db.Column(db.String(200), nullable=False)
    phone   = db.Column(db.String(20), nullable=False)
    start   = db.Column(db.DateTime, nullable=False)
    end     = db.Column(db.DateTime, nullable=True)

    notes   = db.Column(db.Text)
    type    = db.Column(db.String(20))
    billing = db.Column(db.String(20))
    insurer = db.Column(db.String(120))

    user    = relationship("User", back_populates="agenda_events")

    __table_args__ = (
        Index("ix_agenda_events_start", "start"),
        Index("ix_agenda_events_end", "end"),
        Index("ix_agenda_events_type", "type"),
    )


quote_suppliers = db.Table(
    "quote_suppliers",
    db.Column("quote_id", db.Integer, db.ForeignKey("quotes.id", ondelete="CASCADE"), primary_key=True),
    db.Column("supplier_id", db.Integer, db.ForeignKey("suppliers.id", ondelete="CASCADE"), primary_key=True)
)

class Quote(db.Model, BaseModel):
    __tablename__ = "quotes"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=True)
    title      = db.Column(db.String(200), nullable=False)
    items      = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    suppliers  = db.relationship(
        "Supplier",
        secondary=quote_suppliers,
        backref=db.backref("quotes", lazy="dynamic")
    )

    user       = db.relationship("User", back_populates="quotes")
    responses  = db.relationship("QuoteResponse", back_populates="quote", cascade="all, delete-orphan")


class QuoteResponse(db.Model, BaseModel):
    __tablename__ = "quote_responses"

    id          = db.Column(db.Integer, primary_key=True)
    quote_id    = db.Column(db.Integer, db.ForeignKey("quotes.id"), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False, index=True)
    answers     = db.Column("answer", db.Text, nullable=False)
    submitted_at= db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    quote       = db.relationship("Quote", back_populates="responses")
    supplier    = db.relationship("Supplier")


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

    __table_args__ = (Index("ix_videos_created_at", "created_at"),)


class SecureFile(db.Model, BaseModel):
    __tablename__ = "secure_files"

    id            = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    kind          = db.Column(db.String(40),  nullable=False)
    filename      = db.Column(db.String(255), nullable=False)
    mime_type     = db.Column(db.String(100), nullable=False)
    size_bytes    = db.Column(db.Integer,     nullable=False)
    data          = db.Column(db.LargeBinary, nullable=False)
    created_at    = db.Column(db.DateTime,    default=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="secure_files", foreign_keys=[user_id])


class PdfFile(db.Model, BaseModel):
    __tablename__ = "pdf_files"

    id            = db.Column(db.Integer, primary_key=True)
    filename      = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    size_bytes    = db.Column(db.Integer, nullable=False, default=0)
    uploaded_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    secure_file_id = db.Column(db.Integer, db.ForeignKey("secure_files.id"), index=True, nullable=False)
    secure_file    = relationship("SecureFile", foreign_keys=[secure_file_id])

    patient_id     = db.Column(db.Integer, db.ForeignKey("patients.id"), index=True, nullable=True)
    consult_id     = db.Column(db.Integer, db.ForeignKey("consults.id"),  index=True, nullable=True)


class WaitlistItem(db.Model, BaseModel):
    __tablename__ = "waitlist_items"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    name       = db.Column(db.String(120), nullable=False)
    billing    = db.Column(db.String(50), default="Particular")
    email      = db.Column(db.String(120))
    phone1     = db.Column(db.String(20))
    phone2     = db.Column(db.String(20))
    notes      = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user       = relationship("User", backref="waitlist_items")

    __table_args__ = (
        Index("ix_waitlist_items_created_at", "created_at"),
    )


class ScheduledEmail(db.Model, BaseModel):
    __tablename__ = "scheduled_emails"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id",
            name="fk_scheduled_emails_user_id_users",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )
    template = db.Column(db.String(50), nullable=False)
    send_at  = db.Column(db.DateTime, nullable=False)
    sent     = db.Column(db.Boolean, default=False, nullable=False)

    user = relationship(
        "User",
        back_populates="scheduled_emails",
        passive_deletes=True
    )

    __table_args__ = (
        Index("ix_scheduled_emails_send_at", "send_at"),
    )

    def __init__(self, user_id: int, template: str, send_at: datetime, sent: bool = False) -> None:
        self.user_id = user_id
        self.template = template
        self.send_at = send_at
        self.sent = sent

class StockMovement(db.Model, BaseModel):
    __tablename__ = "stock_movements"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )
    quantity = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(10), nullable=False)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product", back_populates="movements")