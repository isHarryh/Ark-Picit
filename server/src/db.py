"""Database engine setup and artwork queries."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, func
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from .models import (
    STATUS_DELETED_BY_USER,
    STATUS_NORMAL,
    Announcement,
    Artwork,
    Client,
    Rating,
    Report,
)

engine: Engine | None = None


def init_db(db_path: str | Path) -> Engine:
    """Create the SQLite engine (WAL mode) and all tables."""
    global engine
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    return engine


def get_client_by_token(session: Session, token: str) -> Client | None:
    return session.exec(select(Client).where(Client.token == token)).first()


def get_artwork_by_content(session: Session, content: str) -> Artwork | None:
    return session.exec(select(Artwork).where(Artwork.content == content)).first()


def get_announcements(session: Session) -> list[str]:
    """Return the current announcement list (empty when unset or malformed)."""
    row = session.get(Announcement, 1)
    if row is None:
        return []
    data = json.loads(row.content)
    return data if isinstance(data, list) else []


def set_announcements(session: Session, announcements: list[str]) -> None:
    """Replace the announcement list in the single-row store."""
    row = session.get(Announcement, 1)
    content = json.dumps(announcements, ensure_ascii=False)
    if row is None:
        session.add(Announcement(id=1, content=content))
    else:
        row.content = content
        row.updated_at = datetime.now()
    session.commit()


def _aggr_views():
    """Return per-artwork vote/report aggregate subqueries."""
    up = (
        select(
            Rating.artwork_id,
            func.count().label("up"),
        )
        .where(Rating.value == 1)
        .group_by(Rating.artwork_id)
        .subquery("up_votes")
    )
    down = (
        select(
            Rating.artwork_id,
            func.count().label("down"),
        )
        .where(Rating.value == 0)
        .group_by(Rating.artwork_id)
        .subquery("down_votes")
    )
    reports = (
        select(
            Report.artwork_id,
            func.count().label("count"),
        )
        .group_by(Report.artwork_id)
        .subquery("report_counts")
    )
    return up, down, reports


def _full_query():
    """Return a select joining artworks to their vote/report aggregates."""
    up, down, reports = _aggr_views()
    return (
        select(Artwork, up.c.up, down.c.down, reports.c.count)
        .outerjoin(up, up.c.artwork_id == Artwork.id)
        .outerjoin(down, down.c.artwork_id == Artwork.id)
        .outerjoin(reports, reports.c.artwork_id == Artwork.id),
        up,
        down,
        reports,
    )


def _exec_full(session: Session, stmt, *, limit: int, offset: int) -> list[dict]:
    return [_to_dto(*row, full=True) for row in session.exec(stmt.limit(limit).offset(offset))]


def list_artworks(
    session: Session,
    *,
    statuses: list[int],
    sort_by: str,
    order: str,
    limit: int,
    offset: int,
) -> list[dict]:
    """Return artworks matching *statuses* as DTO dicts (aggregates included)."""
    stmt, up, down, reports = _full_query()
    stmt = stmt.where(Artwork.status.in_(statuses))
    sort_col = {
        "created_at": Artwork.created_at,
        "updated_at": Artwork.updated_at,
        "positive_ratings": up.c.up,
        "negative_ratings": down.c.down,
        "reports_count": reports.c.count,
    }.get(sort_by, Artwork.created_at)
    stmt = stmt.order_by(sort_col.desc() if order == "desc" else sort_col.asc())
    return _exec_full(session, stmt, limit=limit, offset=offset)


def list_random(session: Session, limit: int) -> list[dict]:
    """Return random published artworks as minimal DTO dicts.

    Vote and report counts plus timestamps are admin-only data and are not
    exposed to regular explore requests.
    """
    stmt = (
        select(Artwork)
        .where(Artwork.status == STATUS_NORMAL)
        .order_by(func.random())
        .limit(limit)
    )
    return [_to_dto(row) for row in session.exec(stmt)]


def list_mine(session: Session, *, client_id: int, limit: int, offset: int) -> list[dict]:
    """Return the *client_id* uploads (newest first) excluding user-removed
    artworks, with full DTOs."""
    stmt, *_ = _full_query()
    stmt = stmt.where(
        Artwork.token_id == client_id, Artwork.status != STATUS_DELETED_BY_USER
    ).order_by(Artwork.created_at.desc())
    return _exec_full(session, stmt, limit=limit, offset=offset)


def _to_dto(
    artwork: Artwork,
    up: int | None = None,
    down: int | None = None,
    reports: int | None = None,
    *,
    full: bool = False,
) -> dict:
    dto = {
        "id": artwork.id,
        "content": artwork.content,
        "name": artwork.name,
        "description": artwork.description,
        "width": artwork.width,
        "height": artwork.height,
    }
    if full:
        dto.update(
            status=artwork.status,
            up_votes=up or 0,
            down_votes=down or 0,
            reports_count=reports or 0,
            created_at=artwork.created_at.isoformat(),
            updated_at=artwork.updated_at.isoformat(),
        )
    return dto
