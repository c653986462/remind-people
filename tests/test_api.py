from datetime import timedelta
import re
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base, SessionLocal
from app.models import EmailReminderLog, User
from app.security import hash_password
from app.services import china_today


class ApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_engine = main.engine
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        SessionLocal.configure(bind=cls.engine)
        main.settings.session_cookie_secure = True
        main.COOKIE_NAME = "__Host-certificate_session"
        with SessionLocal() as db:
            db.add(User(username="testadmin", password_hash=hash_password("Correct-Horse-Battery-42!"), is_active=True))
            db.commit()
        main.engine = cls.engine
        SessionLocal.configure(bind=cls.engine)

        def get_test_db():
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[main.get_db] = get_test_db
        cls.client_context = TestClient(main.app, base_url="https://localhost")
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        SessionLocal.configure(bind=cls.original_engine)
        main.engine = cls.original_engine
        cls.engine.dispose()

    def test_client_crud_reminders_and_cors(self):
        client = self.client
        self.assertEqual(client.get("/health").json(), {"status": "ok"})
        self.assertEqual(client.get("/people").status_code, 401)
        self.assertEqual(client.get("/certificates").status_code, 401)
        self.assertEqual(client.get("/auth/me").status_code, 401)

        preflight = client.options(
            "/people",
            headers={
                "Origin": "http://localhost:5174",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers["access-control-allow-origin"], "http://localhost:5174")

        bad_login = client.post("/auth/login", json={"username": "testadmin", "password": "not-the-password"})
        self.assertEqual(bad_login.status_code, 401)
        for _ in range(4):
            self.assertEqual(client.post("/auth/login", json={"username": "testadmin", "password": "not-the-password"}).status_code, 401)
        self.assertEqual(client.post("/auth/login", json={"username": "testadmin", "password": "not-the-password"}).status_code, 429)
        main.login_failures.clear()
        login = client.post("/auth/login", json={"username": "testadmin", "password": "Correct-Horse-Battery-42!"})
        self.assertEqual(login.status_code, 200, login.text)
        session_cookie = login.headers.get("set-cookie", "").lower()
        self.assertIn("httponly", session_cookie)
        self.assertIn("secure", session_cookie)
        self.assertIn("samesite=strict", session_cookie)
        self.assertEqual(login.headers.get("x-content-type-options"), "nosniff")
        csrf = login.json()["csrf_token"]
        self.assertEqual(client.post("/people", json={"name": "missing csrf"}).status_code, 403)
        client.headers.update({"X-CSRF-Token": csrf})
        self.assertEqual(client.get("/auth/me").json()["user"]["username"], "testadmin")
        csrf = client.get("/auth/me").json()["csrf_token"]
        client.headers.update({"X-CSRF-Token": csrf})

        self.assertFalse(client.get("/settings/email").json()["smtp_configured"])
        main.settings.email_smtp_host = "smtp.example.test"
        main.settings.email_smtp_username = "sender@example.test"
        main.settings.email_smtp_password = "test-app-password"
        main.settings.email_smtp_from = "sender@example.test"
        with patch("app.main.send_email", new_callable=AsyncMock) as send_mail:
            sent_code = client.post("/settings/email/send-code", json={"email": " Owner@Example.test "})
            self.assertEqual(sent_code.status_code, 200, sent_code.text)
            self.assertEqual(sent_code.json()["expires_in"], 600)
            code_body = send_mail.await_args.args[2]
            code = re.search(r"(\d{6})", code_body).group(1)
            wrong_code = "000001" if code != "000001" else "000002"
            self.assertEqual(client.post("/settings/email/verify", json={"code": wrong_code}).status_code, 400)
            self.assertEqual(client.post("/settings/email/verify", json={"code": code}).status_code, 200)
            self.assertEqual(client.get("/settings/email").json()["email"], "owner@example.test")
            self.assertEqual(client.post("/settings/email/test").status_code, 200)

        person = client.post("/people", json={"name": "联调人员", "department": "测试部", "identity_number": "11010119900101123X"})
        self.assertEqual(person.status_code, 201)
        self.assertEqual(person.json()["identity_number"], "11010119900101123X")
        person_id = person.json()["id"]
        self.assertEqual(client.get("/people", params={"q": "11010119900101123X"}).json()[0]["id"], person_id)
        self.assertEqual(client.post("/people", json={"name": "身份证可选人员"}).status_code, 201)

        certificate = client.post("/certificates", json={"name": "联调证书", "issuer": "测试机构"})
        self.assertEqual(certificate.status_code, 201)
        certificate_id = certificate.json()["id"]
        self.assertEqual(client.post("/certificates", json={"name": "联调证书"}).status_code, 409)

        validity_start = (china_today() + timedelta(days=1)).isoformat()
        validity_end = (china_today() + timedelta(days=8)).isoformat()
        due_date = (china_today() + timedelta(days=3)).isoformat()
        renewal_date = (china_today() + timedelta(days=5)).isoformat()
        education_date = (china_today() + timedelta(days=4)).isoformat()
        record_payload = {
            "person_id": person_id,
            "certificate_id": certificate_id,
            "certificate_no": "TEST-001",
            "validity_start_date": validity_start,
            "validity_end_date": validity_end,
            "expiry_date": due_date,
            "renewal_date": renewal_date,
            "continuing_education_date": education_date,
            "certificate_url": "https://example.test/certificate",
            "education_url": "https://example.test/education",
            "renewal_url": "https://example.test/renewal",
            "remind_days": 30,
            "active": True,
        }
        invalid_url = client.post("/records", json={**record_payload, "certificate_url": "javascript:alert(1)"})
        self.assertEqual(invalid_url.status_code, 422)
        record = client.post("/records", json=record_payload)
        self.assertEqual(record.status_code, 201, record.text)
        record_id = record.json()["id"]
        self.assertEqual(record.json()["person"]["name"], "联调人员")
        self.assertEqual(record.json()["certificate"]["name"], "联调证书")
        self.assertEqual(record.json()["validity_start_date"], validity_start)
        self.assertEqual(record.json()["validity_end_date"], validity_end)
        self.assertNotIn("issue_date", record.json())

        listed = client.get("/records", params={"q": "TEST-001"})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

        reminders = client.get("/reminders/upcoming", params={"days": 30}).json()
        self.assertEqual({item["event_type"] for item in reminders}, {"expiry", "education", "renewal"})
        self.assertEqual({item["target_date"] for item in reminders}, {due_date, renewal_date, education_date})
        self.assertEqual({item["label"] for item in reminders}, {"延期", "更新", "继续教育"})
        self.assertNotIn(validity_start, {item["target_date"] for item in reminders})
        self.assertNotIn(validity_end, {item["target_date"] for item in reminders})

        update = client.put(
            f"/records/{record_id}",
            json={
                **record.json(),
                "person_id": person_id,
                "certificate_id": certificate_id,
                "education_url": "https://example.test/new-education-address",
            },
        )
        self.assertEqual(update.status_code, 200, update.text)
        self.assertEqual(update.json()["education_url"], "https://example.test/new-education-address")
        person_update = client.put(f"/people/{person_id}", json={"name": "联调人员已编辑", "identity_number": "110101199001011230"})
        self.assertEqual(person_update.status_code, 200)
        self.assertEqual(person_update.json()["identity_number"], "110101199001011230")

        with patch("app.services.send_email", new_callable=AsyncMock) as send_reminder:
            first_check = client.post("/reminders/check")
            self.assertEqual(send_reminder.await_count, 1)
            with SessionLocal() as db:
                self.assertEqual(db.query(EmailReminderLog).count(), 3)
        self.assertEqual(first_check.json()["created"], 3)
        with patch("app.services.send_email", new_callable=AsyncMock) as send_reminder:
            self.assertEqual(client.post("/reminders/check").json()["created"], 0)
            self.assertEqual(send_reminder.await_count, 0)
        main.settings.email_smtp_host = ""
        main.settings.email_smtp_username = ""
        main.settings.email_smtp_password = ""
        main.settings.email_smtp_from = ""
        self.assertEqual(len(client.get("/reminders/logs").json()), 3)

        self.assertEqual(client.delete(f"/people/{person_id}").status_code, 204)
        self.assertEqual(client.get("/records").json(), [])
        self.assertEqual(client.get("/reminders/logs").json(), [])

        change = client.post(
            "/auth/change-password",
            json={"current_password": "Correct-Horse-Battery-42!", "new_password": "New-Horse-Battery-84!Again"},
        )
        self.assertEqual(change.status_code, 204, change.text)
        self.assertEqual(client.get("/people").status_code, 401)
        self.assertEqual(client.post("/auth/login", json={"username": "testadmin", "password": "New-Horse-Battery-84!Again"}).status_code, 200)
        new_csrf = client.get("/auth/me").json()["csrf_token"]
        client.headers.update({"X-CSRF-Token": new_csrf})
        self.assertEqual(client.post("/auth/logout").status_code, 204)
        self.assertEqual(client.get("/people").status_code, 401)


if __name__ == "__main__":
    unittest.main()
