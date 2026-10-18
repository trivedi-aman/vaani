"""
PII masking for logs, the audit trail and anything that leaves a session.

The data is synthetic, but the code treats it as if it were real: phone
numbers, dates of birth, OTPs and PINs are masked before they are written
anywhere persistent.
"""
import re
from typing import Any

_PHONE = re.compile(r"(?<!\d)([6-9]\d{5})(\d{4})(?!\d)")
_ISO_DATE = re.compile(r"\b(19|20)(\d{2})-(\d{2})-(\d{2})\b")

SECRET_KEYS = {"otp", "otp_spoken", "pin", "pin_spoken", "token", "access_code", "code"}
PII_KEYS = {"dob", "phone", "id_spoken", "phone_spoken", "dob_spoken"}


def mask_phone(phone: str) -> str:
    return f"{phone[:2]}••••••{phone[-2:]}" if len(phone) >= 4 else "••••"


def mask_text(text: str) -> str:
    """Mask phone numbers and full dates inside free text."""
    text = _PHONE.sub(lambda m: f"{m[1][:2]}••••{m[2][-2:]}", text)
    return _ISO_DATE.sub(lambda m: f"{m[1]}{m[2]}-••-••", text)


def mask(value: Any, key: str = "") -> Any:
    """Recursively mask a JSON-like value for logging."""
    k = key.lower()
    if k in SECRET_KEYS:
        return "•••"
    if isinstance(value, dict):
        return {kk: mask(vv, kk) for kk, vv in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask(v, key) for v in value]
    if isinstance(value, str):
        if k in PII_KEYS:
            return "•••" if len(value) < 6 else value[:2] + "•••"
        return mask_text(value)
    return value


def strip_secrets(value: Any, key: str = "") -> Any:
    """Hide only secrets (OTPs, PINs, tokens). For the caller's own screen, which may show their own details."""
    if key.lower() in SECRET_KEYS:
        return "•••"
    if isinstance(value, dict):
        return {k: strip_secrets(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [strip_secrets(v, key) for v in value]
    return value
