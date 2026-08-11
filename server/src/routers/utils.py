"""Shared FastAPI dependencies, admin auth and request helpers for the plaza routes."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlmodel import Session

from .. import config, db
from ..errors import ApiError
from ..models import Client

_RATE_IDLE_TIMEOUT = 7200.0  # drop IP budgets idle for 2 hours
_RATE_CLEANUP_EVERY = 1024  # sweep idle budgets every N requests


class _SlidingWindow:
    """Sliding-window counter tracking credits used in the last ``window`` seconds."""

    __slots__ = ("window", "limit", "start", "prev", "curr")

    def __init__(self, window: float, limit: int):
        self.window = window
        self.limit = limit
        self.start = 0
        self.prev = 0.0
        self.curr = 0.0

    def estimate(self, now: float) -> float:
        index = int(now // self.window)
        if index != self.start:
            self.prev = self.curr if index == self.start + 1 else 0.0
            self.curr = 0.0
            self.start = index
        weight = (now - index * self.window) / self.window
        return self.prev * (1.0 - weight) + self.curr

    def commit(self, cost: float) -> None:
        self.curr += cost


class _IpBudget:
    """Per-IP credit budgets for the per-minute and per-hour windows."""

    __slots__ = ("minute", "hour", "last_seen")

    def __init__(self, per_minute: int, per_hour: int):
        self.minute = _SlidingWindow(60.0, per_minute)
        self.hour = _SlidingWindow(3600.0, per_hour)
        self.last_seen = 0.0


class _RateLimiter:
    """In-memory per-IP limiter; each request spends a per-endpoint credit cost."""

    def __init__(self):
        self._budgets: dict[str, _IpBudget] = {}
        self._calls = 0

    def allow(self, ip: str, cost: int) -> bool:
        now = time.monotonic()
        budget = self._budgets.get(ip)
        if budget is None:
            settings = config.get_config()
            budget = _IpBudget(
                settings.max_rate_credits_per_ip_per_m,
                settings.max_rate_credits_per_ip_per_h,
            )
            self._budgets[ip] = budget
        budget.last_seen = now
        if budget.minute.estimate(now) + cost > budget.minute.limit:
            return False
        if budget.hour.estimate(now) + cost > budget.hour.limit:
            return False
        budget.minute.commit(cost)
        budget.hour.commit(cost)
        self._calls += 1
        if self._calls % _RATE_CLEANUP_EVERY == 0:
            self._sweep(now)
        return True

    def clear(self, ip: str) -> None:
        """Drop *ip*'s budget so its rate windows restart fresh."""
        self._budgets.pop(ip, None)

    def _sweep(self, now: float) -> None:
        for ip, budget in list(self._budgets.items()):
            if now - budget.last_seen > _RATE_IDLE_TIMEOUT:
                del self._budgets[ip]


_rate_limiter = _RateLimiter()


def limited(cost: int) -> Callable:
    """Reject requests that exceed the per-IP credit budget or the payload cap.

    Apply below the route decorator, e.g. ``@router.post(...)`` / ``@limited(2)``;
    the endpoint must declare a ``request: Request`` parameter. A valid admin
    token in ``X-Admin-Token`` clears the caller's credit budget up front, so
    admin traffic is never throttled.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            ip = _client_ip(request)
            if is_admin(request.headers.get("x-admin-token", "")):
                clear_rate_limit(ip)
            if not _rate_limiter.allow(ip, cost):
                raise ApiError(429, "too_many_requests", "Too many requests")
            if len(await request.body()) > config.get_config().max_payload_length:
                raise ApiError(
                    413, "payload_too_large",
                    "Request payload exceeds the configured limit",
                )
            return func(request, *args, **kwargs)

        return wrapper

    return decorator


def clear_rate_limit(ip: str) -> None:
    """Drop *ip*'s credit budget so its rate windows restart fresh."""
    _rate_limiter.clear(ip)


def is_admin(token: str) -> bool:
    """Return whether *token* matches the configured admin token."""
    return token == config.get_config().admin_token


def require_admin(
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    if not is_admin(x_admin_token or ""):
        raise ApiError(403, "admin_token_required", "Administrator token required")


def get_session():
    if db.engine is None:
        raise RuntimeError("Database not initialized")
    with Session(db.engine) as session:
        yield session


def require_client(
    session: Session,
    x_client_token: Annotated[str | None, Header()] = None,
) -> Client:
    """Return the client registered with *x_client_token* or raise 401."""
    if not x_client_token:
        raise ApiError(401, "client_token_required", "Client token required")
    client = db.get_client_by_token(session, x_client_token)
    if client is None:
        raise ApiError(401, "invalid_client_token", "Invalid client token")
    return client


SessionDep = Annotated[Session, Depends(get_session)]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
