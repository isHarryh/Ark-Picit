"""Plaza database models (SQLModel)."""

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

STATUS_NORMAL = 0
STATUS_REVIEWING = 1
STATUS_DELETED_BY_USER = 2
STATUS_MODERATED = 3
ALL_STATUSES = (STATUS_NORMAL, STATUS_REVIEWING, STATUS_DELETED_BY_USER, STATUS_MODERATED)


class Client(SQLModel, table=True):
    """A device identity issued via the meta endpoint; tokens gate writes."""

    __tablename__ = "clients"

    id: int | None = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    token: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=datetime.now)


class Artwork(SQLModel, table=True):
    """A published painting (content is the ArkPicCode text)."""

    __tablename__ = "artworks"

    id: int | None = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    content: str = Field(unique=True, index=True)
    token_id: int = Field(foreign_key="clients.id", index=True)
    name: str = Field(default="")
    description: str = Field(default="")
    width: int = Field(default=0)
    height: int = Field(default=0)
    status: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Rating(SQLModel, table=True):
    """One thumbs up/down per IP per artwork."""

    __tablename__ = "ratings"

    id: int | None = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    artwork_id: int = Field(foreign_key="artworks.id", index=True)
    value: int  # 0 thumbs down, 1 thumbs up
    created_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (UniqueConstraint("ip", "artwork_id"),)


class Report(SQLModel, table=True):
    """One report per IP per artwork."""

    __tablename__ = "reports"

    id: int | None = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    artwork_id: int = Field(foreign_key="artworks.id", index=True)
    reason: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (UniqueConstraint("ip", "artwork_id"),)


class Announcement(SQLModel, table=True):
    """Single-row table holding the current announcement list (JSON in ``content``)."""

    __tablename__ = "announcements"

    id: int = Field(default=1, primary_key=True)
    content: str = Field(default="[]")
    updated_at: datetime = Field(default_factory=datetime.now)
