"""Logging that never writes a phone number, a full date of birth, an OTP or a token."""
import logging
import sys

from loguru import logger

from core.masking import mask_text


class _MaskingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record = logging.makeLogRecord(record.__dict__)
        record.msg, record.args = mask_text(record.getMessage()), None   # mask the message, not the timestamp
        return super().format(record)


def configure(level: str) -> None:
    # standard logging (our modules, uvicorn)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_MaskingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True

    # loguru (Pipecat). At DEBUG Pipecat logs transcripts, so production stays at INFO.
    logger.remove()
    logger.add(sys.stderr, level=level, format="{time:YYYY-MM-DD HH:mm:ss} {level} {name}: {message}",
               filter=_mask_loguru)


def _mask_loguru(record) -> bool:
    record["message"] = mask_text(record["message"])
    return True
