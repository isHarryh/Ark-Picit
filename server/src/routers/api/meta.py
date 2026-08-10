"""Service handshake endpoints: client-token issuance and admin verification."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from ... import db
from ...models import Client
from ..utils import SessionDep, _client_ip, clear_rate_limit, is_admin, limited

CLIENT_TOKEN_BYTES = 32
API_VERSION = 1

router = APIRouter()


class TokenPayload(BaseModel):
    token: str = Field(max_length=256)


@router.get("/api/meta/handshake")
@limited(1)
def handshake(request: Request, session: SessionDep,
              x_client_token: Annotated[str | None, Header()] = None) -> dict:
    """Issue or echo a client token; also reports the API version."""
    token = x_client_token
    if not token or db.get_client_by_token(session, token) is None:
        token = secrets.token_urlsafe(CLIENT_TOKEN_BYTES)
        session.add(Client(ip=_client_ip(request), token=token))
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
