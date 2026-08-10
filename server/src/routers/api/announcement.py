"""Announcement endpoints: read and publish the plaza announcement list."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ... import db
from ..utils import SessionDep, limited, require_admin

router = APIRouter()


@router.get("/api/meta/announcement")
@limited(1)
def get_announcements(request: Request, session: SessionDep) -> dict:
    """Return the current announcement list."""
    return {"announcements": db.get_announcements(session)}


@router.post("/api/meta/announcement")
@limited(2)
def publish_announcements(request: Request, payload: list[str],
                          session: SessionDep,
                          _admin=Depends(require_admin)) -> dict:
    """Replace the announcement list; requires an admin token."""
    db.set_announcements(session, payload)
    return {"ok": True}
