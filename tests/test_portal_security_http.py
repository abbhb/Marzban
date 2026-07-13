"""HTTP-boundary tests for invitations and automatic IP blocking."""

from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

from app import app
from app.db import GetDB
from app.db.base import Base, engine
from app.db.models import PortalIPBlock, PortalInvitationCode, PortalInvitationUse
from app.services import portal_security


@dataclass
class ASGIResult:
    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body)


class PortalSecurityHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(engine)

    @staticmethod
    def request(
        source_ip: str,
        method: str,
        path: str,
        *,
        payload: Optional[dict] = None,
        form: Optional[dict] = None,
    ) -> ASGIResult:
        body = (
            json.dumps(payload).encode()
            if payload is not None
            else urlencode(form).encode()
            if form is not None
            else b""
        )
        response_start = {}
        response_body = bytearray()
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                response_start.update(message)
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        headers = [(b"host", b"testserver")]
        if payload is not None:
            headers.extend(
                [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ]
            )
        elif form is not None:
            headers.extend(
                [
                    (b"content-type", b"application/x-www-form-urlencoded"),
                    (b"content-length", str(len(body)).encode()),
                ]
            )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": (source_ip, 50000),
            "server": ("testserver", 80),
        }
        asyncio.run(app(scope, receive, send))
        return ASGIResult(
            status_code=response_start["status"],
            headers={key.decode().lower(): value.decode() for key, value in response_start["headers"]},
            body=bytes(response_body),
        )

    def test_invitation_registration_and_persistent_auto_blocking(self) -> None:
        with GetDB() as db:
            _invitation, code = portal_security.create_invitation(
                db,
                created_by="root",
                note="http test",
                max_uses=1,
            )

        response = self.request(
            "198.51.100.10",
            "POST",
            "/api/portal/register",
            payload={
                "username": "alice",
                "password": "correct-horse-battery",
                "invitation_code": code,
            },
        )
        self.assertEqual(201, response.status_code, response.body)
        exhausted = self.request(
            "198.51.100.10",
            "POST",
            "/api/portal/register",
            payload={
                "username": "bob",
                "password": "correct-horse-battery",
                "invitation_code": code,
            },
        )
        self.assertEqual(403, exhausted.status_code)
        self.assertEqual("portal.registrationUnavailable", exhausted.json()["detail"])
        with GetDB() as db:
            self.assertEqual(1, db.query(PortalInvitationUse).count())

        login_attacker = "203.0.113.9"
        for _index in range(8):
            failed_login = self.request(
                login_attacker,
                "POST",
                "/api/portal/token",
                form={
                    "username": "alice",
                    "password": "wrong-password",
                    "grant_type": "password",
                },
            )
            self.assertIn(failed_login.status_code, (401, 429))
        login_blocked = self.request(
            login_attacker,
            "POST",
            "/api/portal/token",
            form={
                "username": "alice",
                "password": "wrong-password",
                "grant_type": "password",
            },
        )
        self.assertEqual(403, login_blocked.status_code)
        self.assertEqual("portal.accessDenied", login_blocked.json()["detail"])

        admin_attacker = "203.0.113.10"
        for _index in range(8):
            malformed_admin_login = self.request(
                admin_attacker,
                "POST",
                "/api/admin/token",
                form={"username": "root"},
            )
            self.assertEqual(422, malformed_admin_login.status_code)
        self.assertEqual(
            "portal.accessDenied",
            self.request(
                admin_attacker,
                "POST",
                "/api/admin/token",
                form={"username": "root"},
            ).json()["detail"],
        )

        for index in range(5):
            denied = self.request(
                "203.0.113.8",
                "POST",
                "/api/portal/register",
                payload={
                    "username": f"attacker{index}",
                    "password": "correct-horse-battery",
                    "invitation_code": "MGMA-this-is-not-a-valid-invitation-code",
                },
            )
            self.assertEqual(403, denied.status_code)

        blocked = self.request(
            "203.0.113.8",
            "POST",
            "/api/portal/register",
            payload={
                "username": "attacker-final",
                "password": "correct-horse-battery",
                "invitation_code": "MGMA-this-is-not-a-valid-invitation-code",
            },
        )
        self.assertEqual(403, blocked.status_code)
        self.assertEqual("portal.accessDenied", blocked.json()["detail"])
        self.assertIn("retry-after", blocked.headers)
        self.assertEqual(403, self.request("203.0.113.8", "GET", "/api/portal/me").status_code)
        self.assertEqual(403, self.request("203.0.113.8", "GET", "/sub/random-token").status_code)
        # Sudo recovery endpoints deliberately remain outside the public-IP
        # middleware; without a token they fail auth rather than blacklist.
        self.assertEqual(
            401,
            self.request(
                "203.0.113.8",
                "GET",
                "/api/commerce/admin/security/blocks",
            ).status_code,
        )
        with GetDB() as db:
            row = db.query(PortalIPBlock).filter(PortalIPBlock.source == "portal_registration").one()
            self.assertEqual("203.0.113.8/32", row.network)
            self.assertIn("portal registration/invitation", row.reason)
            login_row = db.query(PortalIPBlock).filter(PortalIPBlock.source == "portal_login").one()
            self.assertEqual("203.0.113.9/32", login_row.network)
            self.assertIn("8 failed portal login", login_row.reason)
            admin_row = db.query(PortalIPBlock).filter(PortalIPBlock.source == "admin_login").one()
            self.assertEqual("203.0.113.10/32", admin_row.network)

    def test_repeated_username_probing_is_treated_as_registration_abuse(self) -> None:
        with GetDB() as db:
            invitation, code = portal_security.create_invitation(
                db,
                created_by="root",
                max_uses=None,
            )

        created = self.request(
            "198.51.100.12",
            "POST",
            "/api/portal/register",
            payload={
                "username": "existing-user",
                "password": "correct-horse-battery",
                "invitation_code": code,
            },
        )
        self.assertEqual(201, created.status_code, created.body)

        hidden_conflict = self.request(
            "203.0.113.12",
            "POST",
            "/api/portal/register",
            payload={
                "username": "existing-user",
                "password": "correct-horse-battery",
                "invitation_code": "MGMA-this-is-not-a-valid-invitation-code",
            },
        )
        self.assertEqual(403, hidden_conflict.status_code)
        self.assertEqual("portal.registrationUnavailable", hidden_conflict.json()["detail"])

        attacker_ip = "203.0.113.11"
        for _index in range(5):
            conflict = self.request(
                attacker_ip,
                "POST",
                "/api/portal/register",
                payload={
                    "username": "existing-user",
                    "password": "correct-horse-battery",
                    "invitation_code": code,
                },
            )
            self.assertEqual(409, conflict.status_code, conflict.body)

        blocked = self.request(
            attacker_ip,
            "POST",
            "/api/portal/register",
            payload={
                "username": "another-user",
                "password": "correct-horse-battery",
                "invitation_code": code,
            },
        )
        self.assertEqual(403, blocked.status_code)
        self.assertEqual("portal.accessDenied", blocked.json()["detail"])
        with GetDB() as db:
            stored_invitation = db.query(PortalInvitationCode).filter(
                PortalInvitationCode.id == invitation.id
            ).one()
            self.assertEqual(1, stored_invitation.use_count)
            abuse_block = db.query(PortalIPBlock).filter(
                PortalIPBlock.source == "portal_registration"
            ).one()
            self.assertIn("registration/invitation", abuse_block.reason)


if __name__ == "__main__":
    unittest.main()
