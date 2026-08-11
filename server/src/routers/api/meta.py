"""Service handshake endpoints: client-token issuance and admin verification."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field

from ... import db
from ...models import Client, Visit
from ..utils import SessionDep, _client_ip, clear_rate_limit, is_admin, limited

CLIENT_TOKEN_BYTES = 32
API_VERSION = 1
UA_MAX_LENGTH = 32

router = APIRouter()


class TokenPayload(BaseModel):
    token: str = Field(max_length=256)


@router.get("/api/meta/handshake")
@limited(1)
def handshake(request: Request, session: SessionDep,
              x_client_token: Annotated[str | None, Header()] = None,
              user_agent: Annotated[str | None, Header()] = None,
              is_start: Annotated[int, Query()] = 0) -> dict:
    """Issue or echo a client token; also reports the API version.

    When ``is_start=1`` (the launch handshake), the visit is recorded with
    the client's IP and a truncated User-Agent for activity tracking.
    """
    token = x_client_token
    if not token or db.get_client_by_token(session, token) is None:
        token = secrets.token_urlsafe(CLIENT_TOKEN_BYTES)
        session.add(Client(ip=_client_ip(request), token=token))
        session.commit()
    if is_start == 1:
        session.add(Visit(
            ip=_client_ip(request),
            ua=(user_agent or "")[:UA_MAX_LENGTH],
        ))
        session.commit()
    return {
        "version": API_VERSION,
        "token": token,
    }


@router.post("/api/meta/handshake")
@limited(2)
def verify_token(request: Request, payload: TokenPayload) -> dict:
    """Verify a mystery-code token; unlocks admin features when it matches."""
    admin = is_admin(payload.token)
    if admin:
        clear_rate_limit(_client_ip(request))
    return {"admin": admin}
