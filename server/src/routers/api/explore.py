"""Explore endpoints: browse, rate, report, audit and publish artworks."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from ... import config, db
from ...code import CodeError, parse_code
from ...errors import ApiError
from ...models import (
    ALL_STATUSES,
    STATUS_DELETED_BY_USER,
    STATUS_NORMAL,
    Artwork,
    Rating,
    Report,
)
from ..utils import (
    SessionDep,
    _client_ip,
    limited,
    require_admin,
    require_client,
)

router = APIRouter()


class ContentPayload(BaseModel):
    content: str = Field(min_length=1)


class RatingPayload(ContentPayload):
    value: Literal[0, 1]


class ReportPayload(ContentPayload):
    reason: Literal["pornographic", "violent", "subversive", "abusive", "infringing", "other"]


class AuditPayload(ContentPayload):
    new_status: int = Field(ge=0, le=3)


@router.get("/api/explore/list")
@limited(4)
def explore_list(
    request: Request,
    session: SessionDep,
    mode: str = "random",
    page_size: int = 50,
    page_number: int = 1,
    include_status: str = "",
    sort_by: str = "created_at",
    order: str = "desc",
    x_admin_token: Annotated[str | None, Header()] = None,
    x_client_token: Annotated[str | None, Header()] = None,
) -> dict:
    """List artworks; each mode carries its own permission flags.

    ``can_feedback`` gates rating/reporting, ``can_edit`` gates deletion and
    ``can_manage`` gates status changes in the client UI.
    """
    page_size = max(1, min(page_size, config.get_config().max_page_size))
    permissions = {"can_feedback": True, "can_edit": False, "can_manage": False}

    if mode == "random":
        # Non-admin mode ignores every admin-only query parameter.
        artworks = db.list_random(session, limit=page_size)
        return {"artworks": artworks, "total": len(artworks), **permissions}

    if mode == "mine":
        # Only the requesting client's own artworks, pagination only.
        client = require_client(session, x_client_token)
        page_number = max(1, page_number)
        artworks = db.list_mine(
            session,
            client_id=client.id,
            limit=page_size,
            offset=(page_number - 1) * page_size,
        )
        permissions["can_edit"] = True
        return {"artworks": artworks, "total": len(artworks), **permissions}

    if mode == "admin":
        require_admin(x_admin_token)
        statuses = [int(raw) for raw in include_status.split(",") if raw.strip().isdigit()]
        statuses = [status for status in statuses if status in ALL_STATUSES]
        if not statuses:
            statuses = list(ALL_STATUSES)
        if sort_by not in (
            "created_at",
            "updated_at",
            "positive_ratings",
            "negative_ratings",
            "reports_count",
        ):
            raise ApiError(400, "invalid_sort", "Invalid sort_by")
        if order not in ("asc", "desc"):
            raise ApiError(400, "invalid_order", "Invalid order")
        page_number = max(1, page_number)
        artworks = db.list_artworks(
            session,
            statuses=statuses,
            sort_by=sort_by,
            order=order,
            limit=page_size,
            offset=(page_number - 1) * page_size,
        )
        permissions["can_manage"] = True
        return {"artworks": artworks, "total": len(artworks), **permissions}

    raise ApiError(400, "invalid_mode", "Invalid mode")


@router.post("/api/explore/rating")
@limited(8)
def rate(request: Request, payload: RatingPayload, session: SessionDep) -> dict:
    artwork = _require_visible(session, payload.content)
    try:
        session.add(
            Rating(ip=_client_ip(request), artwork_id=artwork.id, value=payload.value)
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiError(409, "already_rated", "Already rated")
    return {"ok": True}


@router.post("/api/explore/report")
@limited(8)
def report(request: Request, payload: ReportPayload, session: SessionDep) -> dict:
    artwork = _require_visible(session, payload.content)
    try:
        session.add(
            Report(ip=_client_ip(request), artwork_id=artwork.id, reason=payload.reason)
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiError(409, "already_reported", "Already reported")
    return {"ok": True}


@router.post("/api/explore/audit")
@limited(2)
def audit(request: Request, payload: AuditPayload, session: SessionDep,
          _admin=Depends(require_admin)) -> dict:
    artwork = _require_artwork(session, payload.content)
    artwork.status = payload.new_status
    artwork.updated_at = datetime.now()
    session.add(artwork)
    session.commit()
    return {"ok": True}


@router.put("/api/explore/work")
@limited(16)
def publish(request: Request, payload: ContentPayload, session: SessionDep,
            x_client_token: Annotated[str | None, Header()] = None) -> dict:
    client = require_client(session, x_client_token)
    try:
        parsed = parse_code(
            payload.content,
            max_length=config.get_config().max_payload_length,
        )
    except CodeError as e:
        raise ApiError(400, "invalid_content", str(e))
    artwork = Artwork(
        ip=_client_ip(request),
        content=payload.content,
        token_id=client.id,
        name=parsed.name,
        description=parsed.description,
        width=parsed.width,
        height=parsed.height,
        status=config.get_config().upload_default_status,
    )
    session.add(artwork)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiError(409, "already_published", "Already published")
    return {"ok": True}


@router.delete("/api/explore/work")
@limited(2)
def unpublish(request: Request, payload: ContentPayload, session: SessionDep,
              x_client_token: Annotated[str | None, Header()] = None) -> dict:
    """Delete by content; only the uploading client's token may remove it."""
    client = require_client(session, x_client_token)
    artwork = _require_artwork(session, payload.content)
    if artwork.status == STATUS_DELETED_BY_USER:
        raise ApiError(404, "artwork_not_found", "Artwork not found")
    if artwork.token_id != client.id:
        raise ApiError(403, "not_uploading_client", "Not the uploading client")
    artwork.status = STATUS_DELETED_BY_USER
    artwork.updated_at = datetime.now()
    session.add(artwork)
    session.commit()
    return {"ok": True}


def _require_artwork(session: Session, content: str) -> Artwork:
    artwork = db.get_artwork_by_content(session, content)
    if artwork is None:
        raise ApiError(404, "artwork_not_found", "Artwork not found")
    return artwork


def _require_visible(session: Session, content: str) -> Artwork:
    artwork = _require_artwork(session, content)
    if artwork.status != STATUS_NORMAL:
        raise ApiError(404, "artwork_not_found", "Artwork not found")
    return artwork
