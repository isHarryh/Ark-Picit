"""Async HTTP JSON client built on QNetworkAccessManager (no extra dependencies)."""

from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from src.app.dist import app_version

_TIMEOUT_MS = 15000
_USER_AGENT = f"ArkPicit/{app_version()}"


class HttpResult:
    """Outcome of a network request."""

    def __init__(self, *, ok: bool, status: int = 0, data=None, error: str = "",
                 reason=None, code: str = ""):
        self.ok = ok
        self.status = status
        self.data = data
        self.error = error
        self.reason = reason  # structured cause, e.g. a NetworkDisabledReason
        self.code = code  # stable error code, e.g. "request_timeout"

    def detail(self) -> str:
        """Return a human-readable error message."""
        if isinstance(self.data, dict):
            detail = self.data.get("detail")
            if isinstance(detail, str):
                return detail
        if self.error:
            return self.error
        return f"HTTP {self.status}"

    def error_code(self) -> str:
        """Return the stable machine error code, or an empty string."""
        if self.code:
            return self.code
        if isinstance(self.data, dict):
            code = self.data.get("error_code")
            if isinstance(code, str):
                return code
        return ""


class NetworkClient(QObject):
    """Fire-and-forget JSON requests; results arrive via the ``on_done`` callback."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)

    def request_json(
        self,
        method: str,
        url: str,
        payload=None,
        headers: dict[str, str] | None = None,
        on_done: Callable[[HttpResult], None] | None = None,
    ) -> None:
        """Send *method* to *url*; *on_done* receives the HttpResult."""
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setRawHeader(b"User-Agent", _USER_AGENT.encode("ascii"))
        for key, value in (headers or {}).items():
            request.setRawHeader(key.encode("ascii"), value.encode("ascii"))

        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        if method == "GET":
            reply = self._manager.get(request)
        elif method == "POST":
            reply = self._manager.post(request, body)
        elif method == "PUT":
            reply = self._manager.put(request, body)
        elif method == "DELETE":
            reply = self._manager.sendCustomRequest(request, b"DELETE", body)
        else:
            raise ValueError(f"Unsupported method: {method}")
        self._track(reply, on_done or (lambda _result: None))

    def _track(self, reply: QNetworkReply, on_done: Callable[[HttpResult], None]) -> None:
        timer = QTimer(reply)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._timeout(reply))
        timer.start(_TIMEOUT_MS)

        def _finished() -> None:
            timer.stop()
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
            raw = bytes(reply.readAll())
            data = None
            if raw:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = raw.decode("utf-8", errors="replace")
            if reply.error() != QNetworkReply.NetworkError.NoError:
                timed_out = reply.property("timedOut")
                message = "Request timed out" if timed_out else reply.errorString()
                code = "request_timeout" if timed_out else ""
                on_done(HttpResult(ok=False, status=status, data=data,
                                   error=message, code=code))
                reply.deleteLater()
                return
            on_done(HttpResult(ok=200 <= status < 300, status=status, data=data))
            reply.deleteLater()

        reply.finished.connect(_finished)

    @staticmethod
    def _timeout(reply: QNetworkReply) -> None:
        reply.setProperty("timedOut", True)
        reply.abort()
