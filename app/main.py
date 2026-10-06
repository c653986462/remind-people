from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import os
from pathlib import Path
import secrets
from threading import Lock
import time
from typing import Annotated
import uuid
from urllib.parse import quote

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from .config import settings
from .attachments import (CHUNK_SIZE, MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS_PER_KIND,
                          attachment_root, attachment_storage_lock, remove_storage_file,
                          storage_path)
from .database import Base, SessionLocal, engine, ensure_schema, get_db
from .email_service import email_smtp_configured, send_email
from .models import (Certificate, EmailReminderLog, Person, PersonCertificate, RecordAttachment,
                     ReminderLog, User, UserEmailBinding, UserSession)
from .schemas import (CertificateCreate, CertificateOut, CertificateUpdate, LoginRequest,
                      EmailAddressRequest, EmailVerificationRequest, PasswordChangeRequest,
                      PersonCertificateCreate, PersonCertificateOut,
                      PersonCertificateUpdate, PersonCreate, PersonOut, PersonUpdate,
                      RecordAttachmentOut, ReminderOut, UserOut)
from .security import hash_password, new_session_token, token_digest, validate_password, verify_password
from .services import check_and_notify, check_due_date_and_notify, china_today, upcoming

auth_logger = logging.getLogger("certificate_manager.auth")
email_logger = logging.getLogger("certificate_manager.email")
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
COOKIE_NAME = "__Host-certificate_session" if settings.session_cookie_secure else "certificate_session"
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 5
login_failures: dict[tuple[str, str], list[float]] = {}
login_failures_lock = Lock()


async def scheduled_check():
    db = SessionLocal()
    try:
        await check_and_notify(db)
    finally:
        db.close()


async def scheduled_due_date_check():
    db = SessionLocal()
    try:
        await check_due_date_and_notify(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    with SessionLocal() as db:
        if not db.scalar(select(User.id).where(User.is_active.is_(True)).limit(1)):
            raise RuntimeError("No active administrator exists. Create one first with `python -m app.admin create-admin`.")
    if settings.scheduler_enabled:
        scheduler.add_job(scheduled_due_date_check, "cron", hour=settings.wechat_due_reminder_hour, minute=0, id="certificate-due-date-wechat", replace_existing=True)
        scheduler.add_job(scheduled_check, "cron", hour=settings.check_hour, minute=0, id="certificate-check", replace_existing=True)
        # Catch up a due-date notification if the service starts after its configured hour.
        await scheduled_due_date_check()
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="个人证书管理系统",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=None if settings.session_cookie_secure else "/docs",
    redoc_url=None if settings.session_cookie_secure else "/redoc",
    openapi_url=None if settings.session_cookie_secure else "/openapi.json",
)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
DB = Annotated[Session, Depends(get_db)]


def verification_digest(user_id: int, email: str, code: str) -> str:
    key = settings.email_smtp_password.encode("utf-8")
    message = f"{user_id}:{email}:{code}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


@dataclass
class SessionIdentity:
    user: User
    session: UserSession


def session_identity(request: Request, db: DB) -> SessionIdentity:
    raw_token = request.cookies.get(COOKIE_NAME)
    if not raw_token:
        raise HTTPException(401, "请先登录")
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_digest(raw_token)))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if session is None or session.expires_at <= now or not session.user.is_active:
        if session is not None:
            db.delete(session)
            db.commit()
        raise HTTPException(401, "登录已过期，请重新登录")
    return SessionIdentity(user=session.user, session=session)


SessionAuth = Annotated[SessionIdentity, Depends(session_identity)]


def verify_csrf(request: Request, auth: SessionAuth) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not hmac.compare_digest(token_digest(supplied), auth.session.csrf_token_hash):
        raise HTTPException(403, "安全校验失败，请刷新页面后重试")


protected = APIRouter(dependencies=[Depends(session_identity), Depends(verify_csrf)])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    if settings.session_cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_login_rate(request: Request, username: str) -> None:
    now = time.monotonic()
    ip = client_key(request)
    keys = ((ip, username.lower()), (ip, "*"))
    with login_failures_lock:
        retry_after = 0
        for key in keys:
            times = [stamp for stamp in login_failures.get(key, []) if now - stamp < LOGIN_WINDOW_SECONDS]
            login_failures[key] = times
            if len(times) >= LOGIN_MAX_ATTEMPTS:
                retry_after = max(retry_after, int(LOGIN_WINDOW_SECONDS - (now - times[0])))
        if retry_after:
            auth_logger.warning("login_rate_limited client_ip=%s", ip)
            raise HTTPException(429, "登录尝试过多，请稍后再试", headers={"Retry-After": str(retry_after)})


def record_login_failure(request: Request, username: str) -> None:
    stamp = time.monotonic()
    ip = client_key(request)
    with login_failures_lock:
        for key in ((ip, username.lower()), (ip, "*")):
            recent = [value for value in login_failures.get(key, []) if stamp - value < LOGIN_WINDOW_SECONDS]
            recent.append(stamp)
            login_failures[key] = recent
    auth_logger.warning("login_failed client_ip=%s", ip)


_DUMMY_PASSWORD_HASH = hash_password("nonexistent-user-password-value")


def one_or_404(db: Session, model, item_id: int):
    obj = db.get(model, item_id)
    if not obj:
        raise HTTPException(404, "记录不存在")
    return obj


@app.get("/health")
def health(): return {"status": "ok"}


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 60 * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


@app.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response, db: DB):
    check_login_rate(request, payload.username)
    user = db.scalar(select(User).where(User.username == payload.username))
    encoded = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(payload.password, encoded)
    if user is None or not user.is_active or not password_matches:
        record_login_failure(request, payload.username)
        raise HTTPException(401, "用户名或密码错误")

    with login_failures_lock:
        login_failures.pop((client_key(request), payload.username.lower()), None)
        login_failures.pop((client_key(request), "*"), None)
    auth_logger.info("login_succeeded user_id=%s client_ip=%s", user.id, client_key(request))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.query(UserSession).filter(UserSession.expires_at <= now).delete(synchronize_session=False)
    raw_session = new_session_token()
    raw_csrf = new_session_token()
    db.add(UserSession(
        user_id=user.id,
        token_hash=token_digest(raw_session),
        csrf_token_hash=token_digest(raw_csrf),
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    ))
    db.commit()
    set_session_cookie(response, raw_session)
    return {"user": UserOut.model_validate(user).model_dump(), "csrf_token": raw_csrf}


@app.get("/auth/me")
def current_user(auth: SessionAuth, db: DB):
    csrf = new_session_token()
    auth.session.csrf_token_hash = token_digest(csrf)
    db.commit()
    return {"user": UserOut.model_validate(auth.user).model_dump(), "csrf_token": csrf}


@app.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, auth: SessionAuth, db: DB):
    verify_csrf(request, auth)
    db.delete(auth.session)
    db.commit()
    response.delete_cookie(COOKIE_NAME, httponly=True, secure=settings.session_cookie_secure, samesite="strict", path="/")


@app.post("/auth/change-password", status_code=204)
def change_password(payload: PasswordChangeRequest, request: Request, response: Response, auth: SessionAuth, db: DB):
    verify_csrf(request, auth)
    if not verify_password(payload.current_password, auth.user.password_hash):
        raise HTTPException(400, "当前密码不正确")
    try:
        validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if hmac.compare_digest(payload.current_password, payload.new_password):
        raise HTTPException(422, "新密码不能与当前密码相同")

    auth.user.password_hash = hash_password(payload.new_password)
    db.query(UserSession).filter(UserSession.user_id == auth.user.id).delete(synchronize_session=False)
    db.commit()
    response.delete_cookie(COOKIE_NAME, httponly=True, secure=settings.session_cookie_secure, samesite="strict", path="/")


@protected.get("/settings/email")
def get_email_settings(auth: SessionAuth, db: DB):
    binding = db.get(UserEmailBinding, auth.user.id)
    return {
        "smtp_configured": email_smtp_configured(),
        "email": binding.email if binding and binding.verified_at else None,
        "verified": bool(binding and binding.email and binding.verified_at),
        "pending_email": binding.pending_email if binding else None,
    }


@protected.post("/settings/email/send-code")
async def send_email_binding_code(payload: EmailAddressRequest, auth: SessionAuth, db: DB):
    if not email_smtp_configured():
        raise HTTPException(503, "服务器尚未配置发信邮箱，请联系管理员完成 SMTP 配置")
    already_bound = db.scalar(select(UserEmailBinding.user_id).where(
        UserEmailBinding.email == payload.email,
        UserEmailBinding.user_id != auth.user.id,
    ))
    if already_bound:
        raise HTTPException(409, "该邮箱已绑定其他系统账号")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    binding = db.get(UserEmailBinding, auth.user.id)
    if binding is None:
        binding = UserEmailBinding(user_id=auth.user.id)
        db.add(binding)
        db.flush()
    if binding.verification_sent_at and now - binding.verification_sent_at < timedelta(seconds=60):
        retry_after = max(1, 60 - int((now - binding.verification_sent_at).total_seconds()))
        raise HTTPException(429, "验证码发送过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
    if binding.send_window_started_at is None or now - binding.send_window_started_at >= timedelta(days=1):
        binding.send_window_started_at = now
        binding.daily_send_count = 0
    if binding.daily_send_count >= 5:
        raise HTTPException(429, "该账号今天的验证码邮件次数已达上限，请明天再试")

    code = f"{secrets.randbelow(1_000_000):06d}"
    binding.pending_email = payload.email
    binding.verification_hash = verification_digest(auth.user.id, payload.email, code)
    binding.verification_expires_at = now + timedelta(minutes=10)
    binding.verification_sent_at = now
    binding.daily_send_count += 1
    binding.failed_attempts = 0
    db.commit()

    try:
        await send_email(
            payload.email,
            "证事邮箱绑定验证码",
            f"你的证事邮箱绑定验证码是：{code}\n验证码 10 分钟内有效。若非本人操作，请忽略此邮件。",
            f"<div style=\"font-family:Arial,Microsoft YaHei,sans-serif;color:#26354d\"><h2>绑定邮箱</h2><p>你的验证码是：</p><p style=\"font-size:28px;font-weight:700;letter-spacing:6px;color:#456bdd\">{code}</p><p>验证码 10 分钟内有效。若非本人操作，请忽略此邮件。</p></div>",
        )
    except Exception as exc:
        email_logger.warning("Email verification delivery failed; user_id=%s error=%s", auth.user.id, type(exc).__name__)
        raise HTTPException(502, "验证码邮件发送失败，请检查邮箱地址或联系管理员检查 SMTP 配置") from exc
    return {"sent": True, "expires_in": 600, "cooldown_seconds": 60}


@protected.post("/settings/email/verify")
def verify_email_binding(payload: EmailVerificationRequest, auth: SessionAuth, db: DB):
    binding = db.get(UserEmailBinding, auth.user.id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not binding or not binding.pending_email or not binding.verification_hash or not binding.verification_expires_at:
        raise HTTPException(400, "请先获取邮箱验证码")
    if binding.verification_expires_at <= now:
        binding.verification_hash = None
        binding.verification_expires_at = None
        binding.failed_attempts = 0
        db.commit()
        raise HTTPException(400, "验证码已过期，请重新获取")
    if binding.failed_attempts >= 5:
        raise HTTPException(429, "验证码尝试次数过多，请重新获取")
    expected = verification_digest(auth.user.id, binding.pending_email, payload.code)
    if not hmac.compare_digest(binding.verification_hash, expected):
        binding.failed_attempts += 1
        db.commit()
        raise HTTPException(400, "验证码不正确")
    already_bound = db.scalar(select(UserEmailBinding.user_id).where(
        UserEmailBinding.email == binding.pending_email,
        UserEmailBinding.user_id != auth.user.id,
    ))
    if already_bound:
        raise HTTPException(409, "该邮箱已绑定其他系统账号")

    binding.email = binding.pending_email
    binding.verified_at = now
    binding.pending_email = None
    binding.verification_hash = None
    binding.verification_expires_at = None
    binding.failed_attempts = 0
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "该邮箱已绑定其他系统账号") from exc
    return {"verified": True, "email": binding.email}


@protected.post("/settings/email/test")
async def send_test_email(auth: SessionAuth, db: DB):
    binding = db.get(UserEmailBinding, auth.user.id)
    if not binding or not binding.email or not binding.verified_at:
        raise HTTPException(400, "请先验证并绑定接收邮箱")
    try:
        await send_email(
            binding.email,
            "证事邮件提醒测试",
            "这是一封测试邮件。邮箱绑定和服务器邮件发送配置正常。",
            "<div style=\"font-family:Arial,Microsoft YaHei,sans-serif;color:#26354d\"><h2>邮件提醒测试成功</h2><p>邮箱绑定和服务器邮件发送配置正常，后续证书事项提醒会发送到此邮箱。</p></div>",
        )
    except Exception as exc:
        email_logger.warning("Test email delivery failed; user_id=%s error=%s", auth.user.id, type(exc).__name__)
        raise HTTPException(502, "测试邮件发送失败，请稍后重试或检查服务器 SMTP 配置") from exc
    return {"sent": True}


@protected.delete("/settings/email", status_code=204)
def unbind_email(auth: SessionAuth, db: DB):
    binding = db.get(UserEmailBinding, auth.user.id)
    if binding:
        db.delete(binding)
        db.commit()


@protected.get("/people", response_model=list[PersonOut])
def list_people(db: DB, q: str = ""):
    stmt = select(Person).order_by(Person.id.desc())
    if q: stmt = stmt.where(or_(Person.name.contains(q), Person.department.contains(q), Person.phone.contains(q), Person.identity_number.contains(q)))
    return db.scalars(stmt).all()


@protected.post("/people", response_model=PersonOut, status_code=201)
def create_person(payload: PersonCreate, db: DB):
    item = Person(**payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item


@protected.put("/people/{item_id}", response_model=PersonOut)
def update_person(item_id: int, payload: PersonUpdate, db: DB):
    item = one_or_404(db, Person, item_id)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    db.commit(); db.refresh(item)
    return item


@protected.delete("/people/{item_id}", status_code=204)
def delete_person(item_id: int, db: DB):
    with attachment_storage_lock():
        item = one_or_404(db, Person, item_id)
        records = db.scalars(select(PersonCertificate).where(PersonCertificate.person_id == item_id).options(
            selectinload(PersonCertificate.attachments)
        )).all()
        paths = attachment_paths(records)
        db.delete(item)
        db.commit()
        remove_deleted_attachments(paths)


@protected.get("/certificates", response_model=list[CertificateOut])
def list_certificates(db: DB, q: str = ""):
    stmt = select(Certificate).order_by(Certificate.name)
    if q: stmt = stmt.where(or_(Certificate.name.contains(q), Certificate.issuer.contains(q)))
    return db.scalars(stmt).all()


@protected.post("/certificates", response_model=CertificateOut, status_code=201)
def create_certificate(payload: CertificateCreate, db: DB):
    item = Certificate(**payload.model_dump()); db.add(item)
    try: db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "证书名称已存在") from exc
    db.refresh(item); return item


@protected.put("/certificates/{item_id}", response_model=CertificateOut)
def update_certificate(item_id: int, payload: CertificateUpdate, db: DB):
    item = one_or_404(db, Certificate, item_id)
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    try: db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "证书名称已存在") from exc
    db.refresh(item); return item


@protected.delete("/certificates/{item_id}", status_code=204)
def delete_certificate(item_id: int, db: DB):
    with attachment_storage_lock():
        item = one_or_404(db, Certificate, item_id)
        records = db.scalars(select(PersonCertificate).where(PersonCertificate.certificate_id == item_id).options(
            selectinload(PersonCertificate.attachments)
        )).all()
        paths = attachment_paths(records)
        db.delete(item)
        db.commit()
        remove_deleted_attachments(paths)


def load_record(db: Session, item_id: int):
    item = db.scalar(select(PersonCertificate).options(
        joinedload(PersonCertificate.person), joinedload(PersonCertificate.certificate),
        selectinload(PersonCertificate.attachments),
    ).where(PersonCertificate.id == item_id))
    if not item: raise HTTPException(404, "关联记录不存在")
    return item


@protected.get("/records", response_model=list[PersonCertificateOut])
def list_records(db: DB, q: str = ""):
    stmt = select(PersonCertificate).options(
        joinedload(PersonCertificate.person), joinedload(PersonCertificate.certificate),
        selectinload(PersonCertificate.attachments),
    ).order_by(PersonCertificate.id.desc())
    if q: stmt = stmt.join(Person).join(Certificate).where(or_(Person.name.contains(q), Certificate.name.contains(q), PersonCertificate.certificate_no.contains(q)))
    return db.scalars(stmt).unique().all()


@protected.post("/records", response_model=PersonCertificateOut, status_code=201)
def create_record(payload: PersonCertificateCreate, db: DB):
    one_or_404(db, Person, payload.person_id); one_or_404(db, Certificate, payload.certificate_id)
    item = PersonCertificate(**payload.model_dump()); db.add(item); db.commit()
    return load_record(db, item.id)


@protected.put("/records/{item_id}", response_model=PersonCertificateOut)
def update_record(item_id: int, payload: PersonCertificateUpdate, db: DB):
    item = load_record(db, item_id)
    one_or_404(db, Person, payload.person_id); one_or_404(db, Certificate, payload.certificate_id)
    # Older clients do not send website credentials; preserve omitted values.
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    db.commit(); return load_record(db, item_id)


@protected.delete("/records/{item_id}", status_code=204)
def delete_record(item_id: int, db: DB):
    with attachment_storage_lock():
        item = load_record(db, item_id)
        paths = attachment_paths([item])
        db.delete(item)
        db.commit()
        remove_deleted_attachments(paths)


def attachment_paths(records: list[PersonCertificate]) -> list[Path]:
    base = attachment_root()
    return [storage_path(base, record.id, attachment.kind, attachment.storage_key)
            for record in records for attachment in record.attachments]


def remove_deleted_attachments(paths: list[Path]) -> None:
    logger = logging.getLogger("certificate_manager.attachments")
    for path in paths:
        try:
            remove_storage_file(path)
        except OSError:
            logger.exception("could_not_remove_deleted_attachment path=%s", path)


def content_type_and_extension(kind: str, prefix: bytes, suffix: bytes) -> tuple[str, str]:
    if kind == "pdf" and prefix.startswith(b"%PDF-") and b"%%EOF" in suffix:
        return "application/pdf", "pdf"
    if kind == "image":
        if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"
        if prefix.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpg"
        if len(prefix) >= 12 and prefix[0:4] == b"RIFF" and prefix[8:12] == b"WEBP":
            return "image/webp", "webp"
    raise HTTPException(415, "文件内容与所选的 PDF 或图片类别不符；图片支持 PNG、JPG、JPEG、WebP")


def safe_filename(filename: str | None, extension: str) -> str:
    raw = (filename or "").replace("\\", "/").split("/")[-1]
    safe = "".join(char for char in raw if char.isprintable() and char not in '"\\/<>:|?*')
    safe = safe.strip(" .")[:180]
    if not safe:
        raise HTTPException(422, "请为上传文件设置有效的文件名")
    stem = safe.rsplit(".", 1)[0] if "." in safe else safe
    stem = stem.strip(" .") or "证书附件"
    return f"{stem[:180 - len(extension) - 1]}.{extension}"


@protected.post("/records/{item_id}/attachments/{kind}", response_model=RecordAttachmentOut, status_code=201)
def upload_record_attachment(item_id: int, kind: str, db: DB, file: UploadFile = File(...)):
    if kind not in {"pdf", "image"}:
        raise HTTPException(404, "附件类型不存在")
    allowed_extensions = {".pdf"} if kind == "pdf" else {".png", ".jpg", ".jpeg", ".webp"}
    filename = (file.filename or "").replace("\\", "/").split("/")[-1]
    if not filename or Path(filename).suffix.lower() not in allowed_extensions:
        raise HTTPException(415, "PDF 栏请选择 .pdf；图片栏请选择 PNG、JPG、JPEG 或 WebP")

    temporary: Path | None = None
    destination: Path | None = None
    stored = False
    try:
        with attachment_storage_lock():
            record = one_or_404(db, PersonCertificate, item_id)
            count = db.scalar(select(func.count()).select_from(RecordAttachment).where(
                RecordAttachment.record_id == item_id, RecordAttachment.kind == kind
            )) or 0
            if count >= MAX_ATTACHMENTS_PER_KIND:
                raise HTTPException(409, f"每条持证记录最多上传 {MAX_ATTACHMENTS_PER_KIND} 个{kind.upper()}文件")

            base = attachment_root()
            kind_dir = base / str(item_id) / kind
            kind_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                kind_dir.parent.chmod(0o700)
                kind_dir.chmod(0o700)
            import tempfile
            fd, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=kind_dir)
            temporary = Path(temporary_name)
            prefix = b""
            tail = b""
            size = 0
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as output:
                while True:
                    chunk = file.file.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_ATTACHMENT_BYTES:
                        raise HTTPException(413, "单个文件不能超过 15 MB")
                    if len(prefix) < 16:
                        prefix += chunk[:16 - len(prefix)]
                    tail = (tail + chunk)[-1024:]
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())

            content_type, extension = content_type_and_extension(kind, prefix, tail)
            safe_name = safe_filename(filename, extension)
            storage_key = f"{uuid.uuid4().hex}.{extension}"
            destination = storage_path(base, item_id, kind, storage_key)
            os.replace(temporary, destination)
            stored = True
            attachment = RecordAttachment(
                record_id=record.id, kind=kind, filename=safe_name, content_type=content_type,
                storage_key=storage_key, size_bytes=size, sha256=digest.hexdigest(),
            )
            db.add(attachment)
            try:
                db.commit()
                db.refresh(attachment)
            except Exception:
                db.rollback()
                raise
            return attachment
    except Exception:
        if temporary and temporary.exists():
            temporary.unlink()
        if stored and destination:
            remove_storage_file(destination)
        raise
    finally:
        file.file.close()


@protected.get("/records/{item_id}/attachments/{attachment_id}")
def get_record_attachment(item_id: int, attachment_id: int, db: DB):
    one_or_404(db, PersonCertificate, item_id)
    attachment = db.scalar(select(RecordAttachment).where(
        RecordAttachment.id == attachment_id, RecordAttachment.record_id == item_id
    ))
    if attachment is None:
        raise HTTPException(404, "附件不存在")
    try:
        path = storage_path(attachment_root(), item_id, attachment.kind, attachment.storage_key)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError
        content = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise HTTPException(404, "服务器上的附件文件不存在") from exc
    expected_media, _ = content_type_and_extension(attachment.kind, content[:16], content[-1024:])
    if (expected_media != attachment.content_type or len(content) != attachment.size_bytes
            or hashlib.sha256(content).hexdigest() != attachment.sha256):
        raise HTTPException(409, "附件文件校验失败，请重新上传")
    safe_ascii = "".join(char if char.isascii() and char.isalnum() else "_" for char in attachment.filename)[:80]
    disposition = f"inline; filename=\"{safe_ascii or 'certificate-attachment'}\"; filename*=UTF-8''{quote(attachment.filename)}"
    return Response(content=content, media_type=attachment.content_type, headers={
        "Content-Disposition": disposition,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    })


@protected.delete("/records/{item_id}/attachments/{attachment_id}", status_code=204)
def delete_record_attachment(item_id: int, attachment_id: int, db: DB):
    with attachment_storage_lock():
        one_or_404(db, PersonCertificate, item_id)
        attachment = db.scalar(select(RecordAttachment).where(
            RecordAttachment.id == attachment_id, RecordAttachment.record_id == item_id
        ))
        if attachment is None:
            raise HTTPException(404, "附件不存在")
        path = storage_path(attachment_root(), item_id, attachment.kind, attachment.storage_key)
        db.delete(attachment)
        db.commit()
        remove_deleted_attachments([path])


@protected.get("/reminders/upcoming")
def upcoming_reminders(db: DB, days: int = Query(30, ge=0, le=3650)):
    today = china_today()
    return [{"record_id": x["record"].id, "person": x["record"].person.name, "certificate": x["record"].certificate.name, "event_type": x["event_type"], "label": x["label"], "target_date": x["target_date"], "days_left": (x["target_date"] - today).days} for x in upcoming(db, days)]


@protected.post("/reminders/check")
async def manual_check(db: DB): return {"created": await check_and_notify(db)}


@protected.get("/reminders/logs", response_model=list[ReminderOut])
def reminder_logs(db: DB): return db.scalars(select(ReminderLog).order_by(ReminderLog.created_at.desc())).all()


app.include_router(protected)
