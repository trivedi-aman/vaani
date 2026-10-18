"""
Spoken identifiers: phone numbers, pincodes, OTPs, PINs, loan IDs,
employee IDs and ticket IDs.

All of these are exact-match fields, so the job is only to turn speech into
the right string and to say how sure we are. Confidence is high when every
word was understood exactly and the result has the right shape; medium when
a word was matched approximately or a part had to be assumed (leading zeros
in a loan ID); low when the shape is wrong.
"""
import re

from .numbers import parse_digits
from .result import HIGH, LOW, MEDIUM, Candidate, EntityResult
from .translit import to_roman

# spoken letter names that appear in our ID formats
_LETTERS = {
    "l": "L", "el": "L", "ell": "L",
    "n": "N", "en": "N", "enn": "N",
    "e": "E", "ee": "E", "i": "E", "emp": "E", "employee": "E",
    "t": "T", "tee": "T", "ti": "T",
    "k": "K", "kay": "K", "ke": "K", "kei": "K",
}
_NOISE = {"id", "number", "no", "nambar", "namber", "hai", "he", "is", "my", "mera", "meri", "code", "otp", "pin", "loan", "account", "ticket", "complaint"}


def _split_letters(text: str, prefix: str) -> tuple[str, str]:
    """
    Separate a spoken prefix ("el en", "LN", "tee kay") from the number words.
    Letters are only taken while they spell the expected prefix, so "ek"
    (Hindi for one) is never read as the letters E and K.
    """
    words = re.split(r"[\s\-:,]+", to_roman(text).lower())
    letters, rest = "", []

    def extends(new: str) -> bool:
        return prefix.startswith(letters + new)

    for w in words:
        if not w or w in _NOISE:
            continue
        m = re.fullmatch(r"([a-z]{1,3})(\d+)", w)               # "ln00123", "e1042"
        if m and not rest and all(c in _LETTERS for c in m[1]) and extends("".join(_LETTERS[c] for c in m[1])):
            letters += "".join(_LETTERS[c] for c in m[1])
            rest.append(m[2])
        elif not rest and w in _LETTERS and extends(_LETTERS[w]):
            letters += _LETTERS[w]
        elif not rest and len(w) <= 3 and all(c in _LETTERS for c in w) and extends("".join(_LETTERS[c] for c in w)):
            letters += "".join(_LETTERS[c] for c in w)            # "ln", "tk"
        else:
            rest.append(w)
    return letters, " ".join(rest)


def _digits_result(kind: str, heard: str, lang: str, length: int, check=None, prefix_strip=()) -> EntityResult:
    reading = parse_digits(heard, lang)
    digits = reading.value or ""
    for p in prefix_strip:
        if len(digits) == length + len(p) and digits.startswith(p):
            digits = digits[len(p):]
    issues = []
    if reading.fuzzy:
        issues.append(f"approximate words: {', '.join(reading.fuzzy)}")
    if reading.unknown:
        issues.append(f"not understood: {', '.join(reading.unknown)}")
    if len(digits) != length:
        issues.append(f"got {len(digits)} digits, expected {length}")
        return EntityResult(kind, heard, None, LOW, digits, issues=issues)
    if check and not check(digits):
        issues.append(f"{digits} is not a valid {kind}")
        return EntityResult(kind, heard, None, LOW, digits, issues=issues)
    confidence = HIGH if not (reading.fuzzy or reading.unknown) else MEDIUM
    return EntityResult(kind, heard, digits, confidence, digits, [Candidate(digits, " ".join(digits))], issues)


def phone(heard: str, lang: str = "") -> EntityResult:
    """Indian mobile: 10 digits starting 6-9; a spoken +91 or 0 is removed."""
    return _digits_result("phone", heard, lang, 10, lambda d: d[0] in "6789", prefix_strip=("91", "0"))


def pincode(heard: str, lang: str = "", known: set[str] | None = None) -> EntityResult:
    result = _digits_result("pincode", heard, lang, 6, lambda d: d[0] != "0")
    if result.value and known is not None and result.value not in known:
        result.issues.append(f"{result.value} is not an India Post pincode")
        result.confidence = LOW
    return result


def otp(heard: str, lang: str = "") -> EntityResult:
    return _digits_result("otp", heard, lang, 6)


def pin(heard: str, lang: str = "") -> EntityResult:
    return _digits_result("pin", heard, lang, 4)


def last_digits(heard: str, lang: str = "", n: int = 4) -> EntityResult:
    return _digits_result(f"last_{n}", heard, lang, n)


def _prefixed_id(kind: str, heard: str, lang: str, prefix: str, width: int) -> EntityResult:
    letters, rest = _split_letters(heard, prefix)
    reading = parse_digits(rest, lang)
    digits = reading.value or ""
    issues = []
    if not letters and len(digits) < 3:
        # a bare "aath" is not a loan ID
        return EntityResult(kind, heard, None, LOW, digits, issues=[f"only {len(digits)} digits and no {prefix} prefix"])
    if reading.fuzzy:
        issues.append(f"approximate words: {', '.join(reading.fuzzy)}")
    if reading.unknown:
        issues.append(f"not understood: {', '.join(reading.unknown)}")
    if letters and letters != prefix:
        issues.append(f"heard only {letters} of the {prefix} prefix")
    if not digits or len(digits) > width:
        issues.append(f"got {len(digits)} digits, expected {width}")
        return EntityResult(kind, heard, None, LOW, letters + digits, issues=issues)
    confidence = HIGH
    if len(digits) < width:
        issues.append(f"assumed leading zeros ({digits} -> {digits.zfill(width)})")
        confidence = MEDIUM
    if reading.fuzzy or reading.unknown or (letters and letters != prefix):
        confidence = MEDIUM
    value = prefix + digits.zfill(width)
    return EntityResult(kind, heard, value, confidence, letters + digits, [Candidate(value, value)], issues)


def loan_id(heard: str, lang: str = "") -> EntityResult:
    """LN + 5 digits. "el en zero zero one two three", "LN 123", "ln00123"."""
    return _prefixed_id("loan_id", heard, lang, "LN", 5)


def employee_id(heard: str, lang: str = "") -> EntityResult:
    """E + 4 digits. "E one zero four two", "employee id 1042"."""
    return _prefixed_id("employee_id", heard, lang, "E", 4)


def ticket_id(heard: str, lang: str = "") -> EntityResult:
    """TK + 6 digits."""
    return _prefixed_id("ticket_id", heard, lang, "TK", 6)


def near_ids(value: str, known: set[str], prefix: str) -> list[str]:
    """IDs one digit away from `value`: offered back, never auto-accepted."""
    digits = value[len(prefix):]
    out = []
    for i, ch in enumerate(digits):
        for d in "0123456789":
            if d != ch:
                cand = prefix + digits[:i] + d + digits[i + 1:]
                if cand in known:
                    out.append(cand)
    return sorted(out)
