"""Plaza API client: handshake, announcements, browse, rate, report, publish."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Callable

from PySide6.QtCore import QCoreApplication, QObject, Signal
from qfluentwidgets import qconfig

from src.app.config import cfg
from src.app.network import HttpResult, NetworkClient

API_VERSION = 1  # client API version; must match the server's meta "version"

#: Protocol keys sent to the plaza API; never translated.
REASONS = ("pornographic", "violent", "subversive", "abusive", "infringing", "other")

#: Semantic catalog keys for protocol labels (the English text lives in the
#: translation catalogs; the key is the TS source).
_STATUS_SOURCES = ("StatusNormal", "StatusReviewing", "StatusRemovedByUser", "StatusRemovedByModeration")
STATUS_COUNT = len(_STATUS_SOURCES)
_REASON_SOURCES = {
    "pornographic": "ReasonPornographic",
    "violent": "ReasonViolent",
    "subversive": "ReasonSubversive",
    "abusive": "ReasonAbusive",
    "infringing": "ReasonInfringing",
    "other": "ReasonOther",
}
_SORT_SOURCES = {
    "created_at": "SortCreatedTime",
    "updated_at": "SortUpdatedTime",
    "positive_ratings": "SortThumbsUp",
    "negative_ratings": "SortThumbsDown",
    "reports_count": "SortReports",
}

DEFAULT_SORT = "created_at"
SORT_OPTIONS = (
    "created_at",
    "updated_at",
    "positive_ratings",
    "negative_ratings",
    "reports_count",
)


def status_label(status: int) -> str:
    """Return the localized label for an artwork status code."""
    if 0 <= status < len(_STATUS_SOURCES):
        return QCoreApplication.translate("ArtworkStatus", _STATUS_SOURCES[status])
    return str(status)


def reason_label(reason: str) -> str:
    """Return the localized label for a report reason key."""
    source = _REASON_SOURCES.get(reason, reason)
    return QCoreApplication.translate("ReportReason", source)


def sort_label(sort_by: str) -> str:
    """Return the localized label for a sort key."""
    source = _SORT_SOURCES.get(sort_by, sort_by)
    return QCoreApplication.translate("ExploreSort", source)


def _mark_label_sources() -> None:
    """Keep the protocol label keys in the translation catalogs.

    lupdate only extracts literal arguments; the keys above are repeated
    here as literal ``translate()`` calls. Never executed.
    """
    QCoreApplication.translate("ArtworkStatus", "StatusNormal")
    QCoreApplication.translate("ArtworkStatus", "StatusReviewing")
    QCoreApplication.translate("ArtworkStatus", "StatusRemovedByUser")
    QCoreApplication.translate("ArtworkStatus", "StatusRemovedByModeration")
    QCoreApplication.translate("ReportReason", "ReasonPornographic")
    QCoreApplication.translate("ReportReason", "ReasonViolent")
    QCoreApplication.translate("ReportReason", "ReasonSubversive")
    QCoreApplication.translate("ReportReason", "ReasonAbusive")
    QCoreApplication.translate("ReportReason", "ReasonInfringing")
    QCoreApplication.translate("ReportReason", "ReasonOther")
    QCoreApplication.translate("ExploreSort", "SortCreatedTime")
    QCoreApplication.translate("ExploreSort", "SortUpdatedTime")
    QCoreApplication.translate("ExploreSort", "SortThumbsUp")
    QCoreApplication.translate("ExploreSort", "SortThumbsDown")
    QCoreApplication.translate("ExploreSort", "SortReports")


class NetworkDisabledReason(Enum):
    """Why network communication is currently blocked."""

    USER_DISABLED = "user_disabled"
    VERSION_MISMATCH = "version_mismatch"


class PlazaClient(QObject):
    """Single plaza client instance shared across the GUI."""

    adminChanged = Signal(bool)  # admin mode toggled by token verification
    serverChanged = Signal()  # server URL edited in settings
    networkDisabledChanged = Signal()  # network enabled/disabled state changed
    newAnnouncements = Signal()  # an announcement set new to this device was fetched

    def __init__(self, parent=None):
        super().__init__(parent)
        self._net = NetworkClient(self)
        self.is_admin = False
        self._verified_token = ""  # remembered after a successful verification
        self._client_token = str(qconfig.get(cfg().exploreClientToken)).strip()
        self._meta_ok = False  # a meta round-trip succeeded this session
        self._meta_in_flight = False
        self._meta_waiters: list[Callable[[bool], None]] = []
        self._rated: dict[str, int] = {}
        self._reported: set[str] = set()
        self._admin_changes: dict[str, int] = {}
        self._announcements: list = []
        self._disabled_reason: NetworkDisabledReason | None = (
            None if qconfig.get(cfg().networkEnabled) else NetworkDisabledReason.USER_DISABLED
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def base_url(self) -> str:
        return str(qconfig.get(cfg().exploreServerUrl)).strip().rstrip("/")

    def token(self) -> str:
        return self._verified_token or str(qconfig.get(cfg().exploreToken)).strip()

    def set_server_url(self, url: str) -> None:
        if qconfig.get(cfg().exploreServerUrl) != url:
            qconfig.set(cfg().exploreServerUrl, url)
            self.serverChanged.emit()

    def is_network_enabled(self) -> bool:
        return self._disabled_reason is None

    def disabled_reason(self) -> NetworkDisabledReason | None:
        return self._disabled_reason

    def set_network_enabled(self, enabled: bool) -> None:
        """Set the user-controlled network switch; a version mismatch locks it."""
        if self._disabled_reason == NetworkDisabledReason.VERSION_MISMATCH:
            return
        reason = None if enabled else NetworkDisabledReason.USER_DISABLED
        qconfig.set(cfg().networkEnabled, enabled)
        if self._disabled_reason != reason:
            self._disabled_reason = reason
            self.networkDisabledChanged.emit()

    def announcements(self) -> list:
        return self._announcements

    def rating_value(self, content: str) -> int | None:
        return self._rated.get(content)

    def is_reported(self, content: str) -> bool:
        return content in self._reported

    def mark_rated(self, content: str, value: int) -> None:
        self._rated[content] = value

    def mark_reported(self, content: str) -> None:
        self._reported.add(content)

    def record_admin_change(self, content: str, new_status: int) -> None:
        """Remember a status change set from the admin dialog."""
        self._admin_changes[content] = new_status

    def admin_change(self, content: str) -> int | None:
        return self._admin_changes.get(content)

    def clear_admin_changes(self) -> None:
        """Forget admin status changes (called on every list refresh)."""
        self._admin_changes.clear()

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _reject(
        self,
        on_done: Callable[[HttpResult], None] | None,
        reason: NetworkDisabledReason,
    ) -> None:
        """Deliver the network-disabled error to *on_done*, if any."""
        if on_done is not None:
            on_done(HttpResult(ok=False, error="Network service disabled", reason=reason))

    def _disable(self, reason: NetworkDisabledReason) -> None:
        if self._disabled_reason != reason:
            self._disabled_reason = reason
            self.networkDisabledChanged.emit()

    def _headers(self, admin: bool) -> dict[str, str]:
        if admin and self.is_admin and self.token():
            return {"X-Admin-Token": self.token()}
        return {}

    def _call(
        self,
        method: str,
        path: str,
        payload=None,
        *,
        admin: bool = False,
        client_auth: bool = False,
        headers: dict[str, str] | None = None,
        on_done: Callable[[HttpResult], None] | None = None,
    ) -> None:
        """Send a request; client-authenticated calls wait for a meta round-trip.

        Auth-writes wait for the in-flight meta request (or retry it after a
        failure) so the device token exists before it is sent; if the server
        stays unreachable the call is aborted with an error instead. Requests
        are rejected up front while network communication is disabled.
        """
        if self._disabled_reason is not None:
            self._reject(on_done, self._disabled_reason)
            return

        def _send() -> None:
            merged = {**self._headers(admin), **(headers or {})}
            if client_auth and self._client_token:
                merged["X-Client-Token"] = self._client_token
            self._net.request_json(
                method,
                self.base_url() + path,
                payload=payload,
                headers=merged,
                on_done=on_done,
            )

        if client_auth:
            def _gate(ok: bool) -> None:
                if ok:
                    _send()
                elif on_done is not None:
                    on_done(HttpResult(ok=False, error="Server unavailable"))

            self._ensure_meta(_gate)
        else:
            _send()

    # ------------------------------------------------------------------
    # Meta lifecycle: at most one meta request in flight; API calls queue up.
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """Start the startup meta request (idempotent).

        The first handshake carries ``is_start=1`` so the server can record
        a visit for this launch.
        """
        if not self._meta_ok and not self._meta_in_flight:
            self._start_meta(is_start=True)

    def _ensure_meta(self, on_done: Callable[[bool], None]) -> None:
        if self._meta_ok:
            on_done(True)
            return
        self._meta_waiters.append(on_done)
        if not self._meta_in_flight:
            self._start_meta()

    def _start_meta(self, is_start: bool = False) -> None:
        self._meta_in_flight = True
        self.fetch_handshake(self._finish_meta, is_start=is_start)

    def _finish_meta(self, result: HttpResult) -> None:
        self._meta_in_flight = False
        if result.ok:
            self._meta_ok = True
            self.fetch_announcements()
        waiters, self._meta_waiters = self._meta_waiters, []
        for waiter in waiters:
            waiter(result.ok)

    def fetch_handshake(
        self,
        on_done: Callable[[HttpResult], None],
        *,
        is_start: bool = False,
    ) -> None:
        """GET the handshake; stores the issued client token and checks the API version.

        *is_start* marks the launch handshake (``?is_start=1``), which the
        server uses to record an activity visit.
        """
        reason = self._disabled_reason
        if reason is not None:
            self._reject(on_done, reason)
            return
        headers = {"X-Client-Token": self._client_token} if self._client_token else {}

        def _handle(result: HttpResult) -> None:
            if result.ok and result.data:
                data = result.data
                if data.get("token"):
                    token = data["token"]
                    if token != self._client_token:
                        self._client_token = token
                        qconfig.set(cfg().exploreClientToken, token)
                server_version = data.get("version")
                if isinstance(server_version, int) and server_version != API_VERSION:
                    self._disable(NetworkDisabledReason.VERSION_MISMATCH)
            on_done(result)

        suffix = "?is_start=1" if is_start else ""
        self._net.request_json(
            "GET",
            self.base_url() + "/api/meta/handshake" + suffix,
            headers=headers,
            on_done=_handle,
        )

    def fetch_announcements(self) -> None:
        """GET the announcement list; emits ``newAnnouncements`` when it is new."""
        if self._disabled_reason is not None:
            return

        def _handle(result: HttpResult) -> None:
            if not (result.ok and result.data):
                return
            announcements = result.data.get("announcements") or []
            self._announcements = announcements
            if self._record_announcement_hash(announcements):
                self.newAnnouncements.emit()

        self._net.request_json(
            "GET",
            self.base_url() + "/api/meta/announcement",
            on_done=_handle,
        )

    def _record_announcement_hash(self, announcements: list) -> bool:
        """Persist the hash of the whole announcement set; True when it is new."""
        digest = hashlib.sha256(
            json.dumps(announcements, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if digest == str(qconfig.get(cfg().announcementHash)):
            return False
        qconfig.set(cfg().announcementHash, digest)
        return True

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    def verify_token(self, token: str, on_done: Callable[[HttpResult], None]) -> None:
        """POST the mystery code to the handshake endpoint; unlocks admin on match."""
        def _handle(result: HttpResult) -> None:
            admin = bool(result.ok and result.data and result.data.get("admin"))
            self._verified_token = token if admin else ""
            if admin != self.is_admin:
                self.is_admin = admin
                self.adminChanged.emit(admin)
            on_done(result)

        self._call("POST", "/api/meta/handshake", {"token": token}, on_done=_handle)

    def publish_announcements(
        self,
        announcements: list[str],
        on_done: Callable[[HttpResult], None],
    ) -> None:
        """Replace the server announcement list; requires verified admin access."""
        def _handle(result: HttpResult) -> None:
            if result.ok:
                self._announcements = list(announcements)
                self._record_announcement_hash(self._announcements)
            on_done(result)

        self._call(
            "POST",
            "/api/meta/announcement",
            announcements,
            admin=True,
            on_done=_handle,
        )

    def explore_list(
        self,
        mode: str,
        *,
        page_size: int = 50,
        page_number: int = 1,
        include_status: str = "",
        sort_by: str = DEFAULT_SORT,
        order: str = "desc",
        on_done: Callable[[HttpResult], None] | None = None,
    ) -> None:
        """List artworks in the given *mode* (random/mine/admin)."""
        if mode == "random":
            url = f"/api/explore/list?mode=random&page_size={page_size}"
        elif mode == "mine":
            url = f"/api/explore/list?mode=mine&page_size={page_size}&page_number={page_number}"
        elif mode == "admin":
            url = (
                f"/api/explore/list?mode=admin&page_size={page_size}&page_number={page_number}"
                f"&include_status={include_status}&sort_by={sort_by}&order={order}"
            )
        else:
            raise ValueError(f"Unknown explore mode: {mode}")
        self._call(
            "GET",
            url,
            admin=(mode == "admin"),
            client_auth=(mode == "mine"),
            on_done=on_done,
        )

    def rate(self, content: str, value: int, on_done: Callable[[HttpResult], None]) -> None:
        self._call("POST", "/api/explore/rating", {"content": content, "value": value}, on_done=on_done)

    def report(self, content: str, reason: str, on_done: Callable[[HttpResult], None]) -> None:
        self._call("POST", "/api/explore/report", {"content": content, "reason": reason}, on_done=on_done)

    def audit(self, content: str, new_status: int, on_done: Callable[[HttpResult], None]) -> None:
        self._call(
            "POST",
            "/api/explore/audit",
            {"content": content, "new_status": new_status},
            admin=True,
            on_done=on_done,
        )

    def upload(self, content: str, on_done: Callable[[HttpResult], None]) -> None:
        """Publish *content*; the client token gates the write."""
        self._call(
            "PUT",
            "/api/explore/work",
            {"content": content},
            client_auth=True,
            on_done=on_done,
        )

    def unpublish(self, content: str, on_done: Callable[[HttpResult], None]) -> None:
        """Remove the *content* artwork; only the uploading client may do so."""
        self._call(
            "DELETE",
            "/api/explore/work",
            {"content": content},
            client_auth=True,
            on_done=on_done,
        )


plaza = PlazaClient()
