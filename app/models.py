from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    identity_number: Mapped[str | None] = mapped_column(String(18), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    certificates: Mapped[list["PersonCertificate"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    issuer: Mapped[str | None] = mapped_column(String(150), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    holders: Mapped[list["PersonCertificate"]] = relationship(
        back_populates="certificate", cascade="all, delete-orphan"
    )


class PersonCertificate(Base):
    __tablename__ = "person_certificates"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    certificate_id: Mapped[int] = mapped_column(ForeignKey("certificates.id"), index=True)
    certificate_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    validity_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    validity_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    continuing_education_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    certificate_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    education_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    renewal_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    remind_days: Mapped[int] = mapped_column(Integer, default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    person: Mapped[Person] = relationship(back_populates="certificates")
    certificate: Mapped[Certificate] = relationship(back_populates="holders")
    reminders: Mapped[list["ReminderLog"]] = relationship(
        back_populates="person_certificate", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["RecordAttachment"]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class RecordAttachment(Base):
    __tablename__ = "record_attachments"
    __table_args__ = (CheckConstraint("kind IN ('pdf', 'image')", name="ck_record_attachment_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("person_certificates.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(32))
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    record: Mapped[PersonCertificate] = relationship(back_populates="attachments")


class ReminderLog(Base):
    __tablename__ = "reminder_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_certificate_id: Mapped[int] = mapped_column(ForeignKey("person_certificates.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    target_date: Mapped[date] = mapped_column(Date)
    message: Mapped[str] = mapped_column(Text)
    sent_to_wechat: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    person_certificate: Mapped[PersonCertificate] = relationship(back_populates="reminders")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    user: Mapped[User] = relationship(back_populates="sessions")


class UserEmailBinding(Base):
    __tablename__ = "user_email_bindings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pending_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    verification_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verification_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    send_window_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    daily_send_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)


class EmailReminderLog(Base):
    __tablename__ = "email_reminder_logs"
    __table_args__ = (
        UniqueConstraint("user_id", "record_id", "event_type", "target_date", "timing", name="uq_email_reminder_delivery"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    record_id: Mapped[int] = mapped_column(Integer, index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    target_date: Mapped[date] = mapped_column(Date)
    timing: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

