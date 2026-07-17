"""
Session tokens and route authorization.

Before this existed, every student-scoped route simply trusted a caller-supplied
`student_id`, so anyone who learned or guessed a student UUID could read that
student's profile, matches, saved pipeline and OAuth status -- and `/auth/save-password`
would overwrite any account with no proof of ownership. Login was sessionless: it
returned the record and minted nothing, so "authenticated" was a client-side boolean.

This module mints a signed, expiring JWT at the points where identity is actually
established (login, profile creation, OAuth callback) and provides the dependency that
verifies it.

Two carve-outs, both deliberate:

1. The demo personas (Sarah/Elena) have NO students row -- their UUIDs are minted
   client-side in Onboarding.tsx -- so they can never hold a real token. Their decks are
   hardcoded fictional data with nothing private in them, so DEMO_STUDENT_IDS are allowed
   through unauthenticated. The carve-out is an exact UUID set, never a pattern or a
   fallback, because "auth failed -> serve the demo" is precisely the class of bug that
   put fabricated labs in front of real users.

2. Guests who never set a password still get a token from /profile/analyze. They own a
   real students row, so they are a real identity even without a credential.
"""
import time
from typing import Optional

import jwt
from fastapi import Header, HTTPException

from .config import settings

ALGORITHM = "HS256"

# Fictional ad-recording personas. Exact UUIDs only -- see the module docstring.
DEMO_STUDENT_IDS = frozenset({
    "11111111-1111-1111-1111-111111111111",  # Sarah Nguyen
    "33333333-3333-3333-3333-333333333333",  # Elena Rostova
})


def _require_secret() -> str:
    """Fail closed. An empty key would otherwise sign tokens anyone could forge."""
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=500,
            detail="Server auth is not configured (JWT_SECRET is unset).",
        )
    return settings.jwt_secret


def create_access_token(student_id: str) -> str:
    """Mint a session token for a student who has just proven their identity."""
    now = int(time.time())
    payload = {
        "sub": student_id,
        "iat": now,
        "exp": now + settings.jwt_ttl_seconds,
    }
    return jwt.encode(payload, _require_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    """Return the student_id from a valid token, else raise 401."""
    try:
        payload = jwt.decode(token, _require_secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token.")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid session token.")
    return sub


def get_optional_student_id(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Identity of the caller from a Bearer token, or None if no token was sent.

    Returns None rather than raising so routes can distinguish "anonymous" from
    "authenticated as someone else" -- the demo carve-out needs that distinction. A
    token that is present but malformed/expired still raises, because sending a bad
    token is an error, not anonymity.
    """
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization header.")
    return decode_access_token(token)


def authorize_student(requested_id: str, caller_id: Optional[str]) -> None:
    """Assert the caller may act on `requested_id`. Raises 401/403 otherwise.

    Call this in any route that takes a student_id from the client.
    """
    if requested_id in DEMO_STUDENT_IDS:
        return  # public fictional data; see module docstring
    if caller_id is None:
        raise HTTPException(status_code=401, detail="Sign in to access this.")
    if caller_id != requested_id:
        # 403, not 404: the caller is authenticated, just not the owner.
        raise HTTPException(status_code=403, detail="You can't access another student's data.")
