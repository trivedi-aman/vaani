"""
Append-only audit trail of every tool call: who (session, persona), what
(tool, masked arguments), result summary, and when. One JSON object per
line, rotated by size so a busy demo cannot fill the disk.
"""
import json
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .masking import mask

_logger: logging.Logger | None = None


def configure(var_dir: Path) -> None:
    global _logger
    var_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("vaani.audit")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
    handler = RotatingFileHandler(var_dir / "audit.jsonl", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    _logger = logger


def record(session_id: str, line: str, actor: str | None, action: str, args: dict[str, Any], outcome: str, detail: Any = None) -> None:
    if _logger is None:
        return
    _logger.info(json.dumps({
        "ts": round(time.time(), 3), "session": session_id, "line": line, "actor": actor,
        "action": action, "args": mask(args), "outcome": outcome, "detail": mask(detail),
    }, ensure_ascii=False, default=str))
