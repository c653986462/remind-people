from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PersonBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = None
    identity_number: str | None = Field(default=None, max_length=18)
    email: str | None = None
    department: str | None = None
    notes: str | None = None


class PersonCreate(PersonBase): pass
class PersonUpdate(PersonBase): pass
class PersonOut(PersonBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WebsiteDetails(BaseModel):
    certificate_url: str | None = Field(default=None, max_length=500)
    education_url: str | None = Field(default=None, max_length=500)
    renewal_url: str | None = Field(default=None, max_length=500)
    certificate_account: str | None = Field(default=None, max_length=200)
    certificate_password: str | None = Field(default=None, max_length=1024, repr=False)
    certificate_notes: str | None = Field(default=None, max_length=5000)
    education_account: str | None = Field(default=None, max_length=200)
    education_password: str | None = Field(default=None, max_length=1024, repr=False)
    education_notes: str | None = Field(default=None, max_length=5000)
    renewal_account: str | None = Field(default=None, max_length=200)
    renewal_password: str | None = Field(default=None, max_length=1024, repr=False)
    renewal_notes: str | None = Field(default=None, max_length=5000)

class CertificateBase(WebsiteDetails):
    name: str = Field(min_length=1, max_length=150)
    issuer: str | None = None
    description: str | None = None


class CertificateCreate(CertificateBase): pass
class CertificateUpdate(CertificateBase): pass
class CertificateOut(CertificateBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class PersonCertificateBase(WebsiteDetails):
    person_id: int
    certificate_id: int
    certificate_no: str | None = None
    validity_start_date: date | None = None
    validity_end_date: date | None = None
    expiry_date: date | None = None
    continuing_education_date: date | None = None
    renewal_date: date | None = None
    remind_days: int = Field(default=30, ge=1, le=3650)
    active: bool = True
    notes: str | None = None


class PersonCertificateCreate(PersonCertificateBase): pass
class PersonCertificateUpdate(PersonCertificateBase): pass
class RecordAttachmentOut(BaseModel):
    id: int
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PersonCertificateOut(PersonCertificateBase):
    id: int
    person: PersonOut
    certificate: CertificateOut
    attachments: list[RecordAttachmentOut] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class ReminderOut(BaseModel):
    id: int
    event_type: str
    target_date: date
    message: str
    sent_to_wechat: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=14, max_length=256)


class EmailAddressRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.rpartition("@")
        if (not separator or not local or len(local) > 64 or not domain or "." not in domain
                or any(char.isspace() for char in normalized) or len(domain) > 253
                or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                       or not all(c.isalnum() or c == "-" for c in label)
                       for label in domain.split("."))):
            raise ValueError("请输入有效的邮箱地址")
        return normalized


class EmailVerificationRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class UserOut(BaseModel):
    id: int
    username: str

    model_config = ConfigDict(from_attributes=True)
