import hashlib
import hmac
import secrets

from fastapi import Request, Response


COOKIE_NAME = "wrapcheck_session"


def signed_session_hash(settings, request: Request, response: Response) -> str:
    """Return a stable server-side key without storing a raw public session token."""
    raw = request.cookies.get(COOKIE_NAME, "")
    token = ""
    try:
        candidate, signature = raw.rsplit(".", 1)
        expected = hmac.new(settings.demo_quota_secret.encode(), candidate.encode(), hashlib.sha256).hexdigest()
        if candidate and hmac.compare_digest(signature, expected):
            token = candidate
    except ValueError:
        pass
    if not token:
        token = secrets.token_urlsafe(24)
        signature = hmac.new(settings.demo_quota_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        response.set_cookie(
            COOKIE_NAME,
            f"{token}.{signature}",
            httponly=True,
            secure=settings.app_mode == "live",
            samesite="lax",
            max_age=86400,
        )
    return hashlib.sha256(f"{settings.demo_quota_secret}:{token}".encode()).hexdigest()
