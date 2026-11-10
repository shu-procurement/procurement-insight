from __future__ import annotations

import os
from datetime import datetime, timedelta

import jwt
from django.conf import settings


DEFAULT_FASTAPI_SECRET_KEY = os.environ.get("FASTAPI_SECRET_KEY", "dev-only-change-me")
DEFAULT_FASTAPI_JWT_ALGORITHM = "HS256"


def build_fastapi_access_token(user=None) -> str:
    if user is not None and getattr(user, "is_authenticated", False):
        user_id = str(user.id)
        username = user.username
    else:
        user_id = "anonymous"
        username = "Guest"

    payload = {
        "sub": user_id,
        "username": username,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(days=7),
    }
    secret_key = getattr(settings, "FASTAPI_SECRET_KEY", DEFAULT_FASTAPI_SECRET_KEY)
    algorithm = getattr(settings, "FASTAPI_JWT_ALGORITHM", DEFAULT_FASTAPI_JWT_ALGORITHM)
    return jwt.encode(payload, secret_key, algorithm=algorithm)
