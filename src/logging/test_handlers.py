"""Unit tests for src/logging/handlers.py"""

import logging
import queue
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Ensure flask_socketio is available (mock it if not installed)
if "flask_socketio" not in sys.modules:
    _fake = ModuleType("flask_socketio")
    _fake.SocketIO = MagicMock  # type: ignore[attr-defined]
    sys.modules["flask_socketio"] = _fake

from src.logging.handlers import QueueLogHandler, SocketIOHandler, _is_flask_noise


# ---------------------------------------------------------------------------
# _is_flask_noise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "msg",
    [
        "GET /status HTTP/1.1 200",
        "POST /api/run HTTP/1.1 200",
        "127.0.0.1 - - HTTP/1.1",
        "socket.io polling",
    ],
)
def test_is_flask_noise_true(msg):
    assert _is_flask_noise(msg) is True


@pytest.mark.parametrize(
    "msg",
    [
        "Engine started",
        "OnRtnOrder callback",
        "【重要信息】",
    ],
)
def test_is_flask_noise_false(msg):
    assert _is_flask_noise(msg) is False


# ---------------------------------------------------------------------------
# SocketIOHandler
# ---------------------------------------------------------------------------

class TestSocketIOHandler:
    def _make_record(self, msg: str, levelno: int = logging.INFO):
        record = logging.LogRecord(
            name="test", level=levelno, pathname="", lineno=0,
            msg=msg, args=(), exc_info=None,
        )
        return record

    def test_emit_normal_log(self):
        sio = MagicMock()
        handler = SocketIOHandler(sio)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(self._make_record("Engine started"))

        sio.emit.assert_called_once_with(
            "new_log", {"message": "Engine started", "color": "#cccccc"}
        )

    def test_emit_error_log_red(self):
        sio = MagicMock()
        handler = SocketIOHandler(sio)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(self._make_record("Something failed", logging.ERROR))

        sio.emit.assert_called_once()
        call_args = sio.emit.call_args
        assert call_args[0][1]["color"] == "#ff4d4d"

    def test_emit_filters_flask_noise(self):
        sio = MagicMock()
        handler = SocketIOHandler(sio)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(self._make_record("GET /status HTTP/1.1 200"))

        sio.emit.assert_not_called()


# ---------------------------------------------------------------------------
# QueueLogHandler
# ---------------------------------------------------------------------------

class TestQueueLogHandler:
    def _make_record(self, msg: str, levelno: int = logging.INFO):
        record = logging.LogRecord(
            name="test", level=levelno, pathname="", lineno=0,
            msg=msg, args=(), exc_info=None,
        )
        return record

    def test_emit_puts_to_queue(self):
        q = queue.Queue()
        handler = QueueLogHandler(q)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(self._make_record("OnRtnOrder callback"))

        event, data = q.get_nowait()
        assert event == "new_log"
        assert data["message"] == "OnRtnOrder callback"
        assert data["color"] == "#00ccff"  # CTP callback → blue

    def test_emit_warning_orange(self):
        q = queue.Queue()
        handler = QueueLogHandler(q)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(self._make_record("Low margin", logging.WARNING))

        _, data = q.get_nowait()
        assert data["color"] == "#ffbf00"

    def test_emit_filters_flask_noise(self):
        q = queue.Queue()
        handler = QueueLogHandler(q)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(self._make_record("POST /api/run HTTP/1.1 200"))

        assert q.empty()

    def test_emit_success_green(self):
        q = queue.Queue()
        handler = QueueLogHandler(q)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(self._make_record("连接成功"))

        _, data = q.get_nowait()
        assert data["color"] == "#00ff00"
