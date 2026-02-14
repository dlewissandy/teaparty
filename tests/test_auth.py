import unittest
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from jose import jwt

from teaparty_app.auth import ALGORITHM, create_access_token, decode_access_token
from teaparty_app.config import settings


class AuthTokenTests(unittest.TestCase):
    def test_create_and_decode_access_token_round_trip(self) -> None:
        token = create_access_token("user-123")
        self.assertEqual(decode_access_token(token), "user-123")

    def test_decode_access_token_rejects_invalid_token(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            decode_access_token("not-a-valid-jwt")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "Invalid session token")

    def test_decode_access_token_requires_sub_claim(self) -> None:
        exp = int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())
        token = jwt.encode({"exp": exp}, settings.app_secret, algorithm=ALGORITHM)
        with self.assertRaises(HTTPException) as ctx:
            decode_access_token(token)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "Token missing user id")

