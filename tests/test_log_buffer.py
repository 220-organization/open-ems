"""In-memory log ring buffer for /api/server-logs."""

import logging

from app.log_buffer import RingBufferHandler, install_log_buffer


def test_ring_buffer_tail():
    h = RingBufferHandler(capacity=10)
    h.setFormatter(logging.Formatter("%(message)s"))
    record = logging.LogRecord("test", logging.INFO, "", 0, "line-a", (), None)
    h.emit(record)
    record2 = logging.LogRecord("test", logging.INFO, "", 0, "line-b", (), None)
    h.emit(record2)
    assert h.tail(1) == ["line-b"]
    assert h.tail(10) == ["line-a", "line-b"]


def test_install_and_tail():
    h = install_log_buffer(capacity=100)
    lg = logging.getLogger("test.openems.logbuf")
    lg.setLevel(logging.INFO)
    lg.info("hello-buffer-test")
    lines = h.tail(20)
    assert any("hello-buffer-test" in line for line in lines)
