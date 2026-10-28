"""Logging setup with request-id correlation.

Rule: never log keys, tokens, transcripts or images. Log ids only.
"""

from __future__ import annotations

import contextvars
import logging
import sys

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_nishaan_configured", False):
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(RequestIdFilter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "aiosqlite", "sqlalchemy.engine", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._nishaan_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
