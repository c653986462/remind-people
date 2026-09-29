from datetime import date, datetime, timedelta
from html import escape
import logging
from zoneinfo import ZoneInfo
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .config import settings
from .email_service import email_smtp_configured, send_email
from .models import EmailReminderLog, PersonCertificate, ReminderLog, UserEmailBinding

EVENTS = {
    # Keep these keys aligned with the frontend mock client and desktop reminder keys.
    "expiry": ("延期", "expiry_date"),
    "education": ("继续教育", "continuing_education_date"),
    "renewal": ("更新", "renewal_date"),
}
LEGACY_EVENT_TYPES = {
    "expiry": "certificate_expiry",
    "education": "continuing_education",
    "renewal": "certificate_renewal",
}
DUE_DAY_EVENT_TYPES = {event_type: f"{event_type}_due_day" for event_type in EVENTS}
CHINA_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger("certificate_manager.reminders")


def china_today() -> date:
    return datetime.now(CHINA_TZ).date()


def upcoming(db: Session, days: int = 30, overdue_days: int | None = 30):
    today = china_today()
    limit = today + timedelta(days=days)
    earliest = today - timedelta(days=overdue_days) if overdue_days is not None else None
    records = db.scalars(
        select(PersonCertificate).options(joinedload(PersonCertificate.person), joinedload(PersonCertificate.certificate))
        .where(PersonCertificate.active.is_(True))
    ).unique().all()
    result = []
    for item in records:
        for event_type, (label, field) in EVENTS.items():
            target = getattr(item, field)
            if target and target <= limit and (earliest is None or target >= earliest):
                result.append({"record": item, "event_type": event_type, "label": label, "target_date": target})
    return sorted(result, key=lambda item: (item["target_date"], item["record"].id, item["event_type"]))


async def send_wechat(message: str) -> bool:
    if not settings.wechat_work_webhook_url:
        return False
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(settings.wechat_work_webhook_url, json={"msgtype": "text", "text": {"content": message}})
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError:
            result = None
        if isinstance(result, dict) and result.get("errcode", 0) != 0:
            return False
    return True


def _event_url(record: PersonCertificate, event_type: str) -> str | None:
    field = {"expiry": "certificate_url", "education": "education_url", "renewal": "renewal_url"}[event_type]
    return getattr(record, field)


async def send_email_reminders(db: Session, items: list[dict], timing: str) -> int:
    """Send a consolidated per-user email and record each successful delivery for deduplication."""
    if not items or not email_smtp_configured():
        return 0
    recipients = db.scalars(select(UserEmailBinding).where(
        UserEmailBinding.email.is_not(None), UserEmailBinding.verified_at.is_not(None),
    )).all()
    sent_count = 0
    today = china_today()
    for binding in recipients:
        pending = []
        for item in items:
            record, event_type, label, target = item["record"], item["event_type"], item["label"], item["target_date"]
            exists = db.scalar(select(EmailReminderLog.id).where(
                EmailReminderLog.user_id == binding.user_id,
                EmailReminderLog.record_id == record.id,
                EmailReminderLog.event_type == event_type,
                EmailReminderLog.target_date == target,
                EmailReminderLog.timing == timing,
            ))
            if not exists:
                pending.append((record, event_type, label, target))
        if not pending:
            continue

        rows = []
        for record, event_type, label, target in pending:
            days_left = (target - today).days
            timing_text = "今天到期" if days_left == 0 else f"{days_left} 天后" if days_left > 0 else f"已逾期 {abs(days_left)} 天"
            url = _event_url(record, event_type)
            rows.append((record.person.name, record.certificate.name, label, target.isoformat(), timing_text, url))
        subject_prefix = "今日到期" if timing == "due_day" else "证书事项提醒"
        subject = f"【证事】{subject_prefix}：{len(rows)} 项待处理"
        text_lines = [f"你好，以下有 {len(rows)} 项证书事务需要关注：", ""]
        html_rows = []
        for person, certificate, label, target, timing_text, url in rows:
            text_lines.extend([f"{person} · {certificate}", f"事项：{label}", f"日期：{target}（{timing_text}）"])
            if url:
                text_lines.append(f"办理入口：{url}")
            text_lines.append("")
            link = f'<a href="{escape(url, quote=True)}">打开办理入口</a>' if url else "—"
            html_rows.append(
                "<tr>"
                f"<td>{escape(person)}</td><td>{escape(certificate)}</td><td>{escape(label)}</td>"
                f"<td>{escape(target)}<br><small>{escape(timing_text)}</small></td><td>{link}</td>"
                "</tr>"
            )
        text_lines.append("— 证事证书事务管理")
        html_body = (
            '<div style="font-family:Arial,Microsoft YaHei,sans-serif;color:#26354d;max-width:760px;margin:auto">'
            f"<h2 style=\"font-size:20px\">{escape(subject_prefix)}</h2>"
            f"<p>以下有 <b>{len(rows)}</b> 项证书事务需要关注。</p>"
            '<table style="width:100%;border-collapse:collapse;font-size:14px">'
            '<thead><tr style="background:#f4f6fa;text-align:left">'
            '<th style="padding:10px;border-bottom:1px solid #e5e9f0">持证人</th>'
            '<th style="padding:10px;border-bottom:1px solid #e5e9f0">证书</th>'
            '<th style="padding:10px;border-bottom:1px solid #e5e9f0">事项</th>'
            '<th style="padding:10px;border-bottom:1px solid #e5e9f0">日期</th>'
            '<th style="padding:10px;border-bottom:1px solid #e5e9f0">入口</th></tr></thead>'
            f"<tbody>{''.join(html_rows)}</tbody></table>"
            '<p style="margin-top:22px;color:#8994a6;font-size:12px">— 证事证书事务管理</p></div>'
        )
        try:
            await send_email(binding.email, subject, "\n".join(text_lines), html_body)
        except Exception as exc:
            logger.warning("Email reminder failed; user_id=%s timing=%s error=%s", binding.user_id, timing, type(exc).__name__)
            continue

        for record, event_type, _label, target in pending:
            db.add(EmailReminderLog(
                user_id=binding.user_id,
                record_id=record.id,
                event_type=event_type,
                target_date=target,
                timing=timing,
            ))
            sent_count += 1
        db.commit()
        logger.info("Email reminders sent; user_id=%s count=%s timing=%s", binding.user_id, len(pending), timing)
    return sent_count


async def check_and_notify(db: Session) -> int:
    created = 0
    # The scheduler must also catch reminders missed while the service was offline.
    candidates = upcoming(db, 3650, overdue_days=None)
    email_candidates = [item for item in candidates if (item["target_date"] - china_today()).days <= item["record"].remind_days]
    await send_email_reminders(db, email_candidates, "advance")
    for item in candidates:
        record, event_type, label, target = item["record"], item["event_type"], item["label"], item["target_date"]
        days_left = (target - china_today()).days
        if days_left > record.remind_days:
            continue
        exists = db.scalar(select(ReminderLog.id).where(
            ReminderLog.person_certificate_id == record.id,
            ReminderLog.event_type.in_((event_type, LEGACY_EVENT_TYPES[event_type])),
            ReminderLog.target_date == target,
        ))
        if exists:
            continue
        timing = f"{days_left} 天后" if days_left > 0 else "今天" if days_left == 0 else f"已逾期 {abs(days_left)} 天"
        message = f"【证书提醒】{record.person.name}的{record.certificate.name}：{label}日期为 {target.isoformat()}（{timing}）"
        try:
            sent = await send_wechat(message)
        except httpx.HTTPError:
            sent = False
        db.add(ReminderLog(person_certificate_id=record.id, event_type=event_type, target_date=target, message=message, sent_to_wechat=sent))
        created += 1
    db.commit()
    return created


async def check_due_date_and_notify(db: Session) -> int:
    """Send separate due-day reminders on the configured date, once per event/date."""
    now = datetime.now(CHINA_TZ)
    if now.hour < settings.wechat_due_reminder_hour:
        return 0

    created = 0
    today = now.date()
    due_items = upcoming(db, 0, overdue_days=0)
    await send_email_reminders(db, due_items, "due_day")
    for item in due_items:
        record = item["record"]
        event_type = item["event_type"]
        label = item["label"]
        target = item["target_date"]
        due_event_type = DUE_DAY_EVENT_TYPES[event_type]
        exists = db.scalar(select(ReminderLog.id).where(
            ReminderLog.person_certificate_id == record.id,
            ReminderLog.event_type == due_event_type,
            ReminderLog.target_date == target,
        ))
        if exists:
            continue

        if not settings.wechat_work_webhook_url:
            logger.warning("Due-date WeChat reminder skipped: webhook is not configured; record_id=%s event=%s date=%s", record.id, event_type, target.isoformat())
            continue

        message = f"【证书到期提醒】{record.person.name}的{record.certificate.name}：{label}日期为今天（{today.isoformat()}）"
        try:
            sent = await send_wechat(message)
        except httpx.HTTPError as exc:
            sent = False
            logger.warning("Due-date WeChat reminder failed; record_id=%s event=%s date=%s error=%s", record.id, event_type, target.isoformat(), type(exc).__name__)
        if not sent:
            logger.warning("Due-date WeChat reminder was not accepted; record_id=%s event=%s date=%s", record.id, event_type, target.isoformat())
        # Keep failures retryable on the next scheduler/startup check.
        if sent:
            db.add(ReminderLog(
                person_certificate_id=record.id,
                event_type=due_event_type,
                target_date=target,
                message=message,
                sent_to_wechat=True,
            ))
            created += 1
            logger.info("Due-date WeChat reminder sent; record_id=%s event=%s date=%s", record.id, event_type, target.isoformat())
    if created:
        db.commit()
    return created

