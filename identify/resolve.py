"""
Turn a heard span into an EntityResult: normalise, match, score.

These are the functions the agent's tools call. Each one takes the raw text
the caller spoke (as STT returned it) and returns the normalised value, the
best candidates with their distances, a confidence level and any issues, so
the agent knows whether to accept, read back, or ask again.

Thresholds for names and places were set on the evaluation set in
eval/matchers.py; see the README for the numbers behind them.
"""
import csv
from datetime import date
from functools import lru_cache
from pathlib import Path

from . import ids
from .dates import parse_dob, parse_event
from .matchers import NameMatcher, PhonemeMatcher, get_matcher
from .phonetic import INDEL_CHEAP, length
from .numbers import parse_value
from .result import HIGH, LOW, MEDIUM, Candidate, EntityResult
from .translit import to_roman

REFERENCE = Path(__file__).resolve().parent.parent / "data" / "reference"

# phoneme-distance thresholds (see eval/matchers.py)
NAME_HIGH, NAME_MEDIUM = 0.8, 1.8          # best distance
NAME_HIGH_MARGIN, NAME_MEDIUM_MARGIN = 1.0, 0.4   # lead over the next candidate
PLACE_HIGH, PLACE_MEDIUM = 0.8, 1.6
PLACE_HIGH_MARGIN, PLACE_MEDIUM_MARGIN = 0.8, 0.3


@lru_cache(maxsize=1)
def districts() -> list[tuple[str, str]]:
    with open(REFERENCE / "districts.csv", encoding="utf-8") as f:
        return [(r["district"], r["state"]) for r in csv.DictReader(f)]


@lru_cache(maxsize=1)
def place_names() -> list[tuple[str, str, str]]:
    """(name as spoken, district, state): every district plus common city names (Bangalore, Trichy)."""
    names = [(d, d, s) for d, s in districts()]
    with open(REFERENCE / "place_aliases.csv", encoding="utf-8") as f:
        names += [(r["alias"], r["district"], r["state"]) for r in csv.DictReader(f)]
    return names


@lru_cache(maxsize=1)
def pincodes() -> dict[str, tuple[str, str]]:
    with open(REFERENCE / "pincodes.csv", encoding="utf-8") as f:
        return {r["pincode"]: (r["district"], r["state"]) for r in csv.DictReader(f)}


def _grade(d1: float, margin: float, high: float, medium: float, high_margin: float, medium_margin: float) -> str:
    if d1 <= high and margin >= high_margin:
        return HIGH
    if d1 <= medium and margin >= medium_margin:
        return MEDIUM
    return LOW


def _rank(heard: str, refs: list[tuple[object, str]], matcher: NameMatcher, keep: int = 6) -> list[tuple[float, object, str]]:
    """
    Distances from `heard` to every (key, text) in refs, best first.

    For the phoneme matcher every missing sound costs at least the cheapest
    insertion, so references much longer or shorter than what was heard can
    be skipped once `keep` closer ones are known. Exact same result, far
    fewer distance computations against 780 place names.
    """
    if not isinstance(matcher, PhonemeMatcher):
        return sorted(((matcher.distance(heard, t), k, t) for k, t in refs), key=lambda x: x[0])
    n = length(heard)
    if n == 0:
        return []
    floor = min(INDEL_CHEAP.values())
    by_bound = sorted(refs, key=lambda kt: abs(length(kt[1]) - n))
    scored: list[tuple[float, object, str]] = []
    for key, text in by_bound:
        bound = floor * abs(length(text) - n)
        if len(scored) >= keep and bound > scored[keep - 1][0]:
            break
        scored.append((matcher.distance(heard, text), key, text))
        scored.sort(key=lambda x: x[0])
    return scored


# ---- names -----------------------------------------------------------------

def name(heard: str, people: list[tuple[str, str]], matcher: NameMatcher | None = None, top: int = 3) -> EntityResult:
    """
    people: (id, full name) pairs to match against, already narrowed by any
    exact identifier the caller gave (DOB, phone, loan ID) when available.
    The value returned is the id of the best match.
    """
    matcher = matcher or get_matcher("phoneme")
    if not people:
        return EntityResult("name", heard, None, LOW, to_roman(heard), issues=["no one to match against"])
    scored = _rank(heard, list(people), matcher)
    if not scored:
        return EntityResult("name", heard, None, LOW, to_roman(heard), issues=["no name heard"])
    d1 = scored[0][0]
    d2 = scored[1][0] if len(scored) > 1 else float("inf")
    confidence = _grade(d1, d2 - d1, NAME_HIGH, NAME_MEDIUM, NAME_HIGH_MARGIN, NAME_MEDIUM_MARGIN)
    candidates = [Candidate(pid, full, round(d, 2)) for d, pid, full in scored[:top]]
    issues = []
    if d2 - d1 < NAME_HIGH_MARGIN and len(scored) > 1:
        issues.append(f"close to {scored[1][2]} too")
    value = scored[0][1] if d1 <= NAME_MEDIUM else None
    if value is None:
        issues.append("no close match")
    return EntityResult("name", heard, value, confidence, to_roman(heard), candidates, issues)


# ---- places ----------------------------------------------------------------

def district(heard: str, state: str | None = None, pincode: str | None = None, top: int = 3) -> EntityResult:
    """
    Match a spoken district against the India Post list. A pincode, if the
    caller gave one, is used as a cross-check: agreement raises confidence,
    disagreement lowers it and is reported.
    """
    matcher = get_matcher("phoneme")
    pool = place_names()
    if state:
        same_state = [p for p in pool if p[2].lower() == state.lower()]
        pool = same_state or pool
    # best distance per district (a district can be reached by its name or an alias)
    best_by_district: dict[tuple[str, str], float] = {}
    for dist, key, _ in _rank(heard, [((d, s), spoken) for spoken, d, s in pool], matcher, keep=8):
        if dist < best_by_district.get(key, float("inf")):
            best_by_district[key] = dist
    scored = sorted(((dist, key) for key, dist in best_by_district.items()), key=lambda x: x[0])
    if not scored:
        return EntityResult("district", heard, None, LOW, to_roman(heard), issues=["no place name heard"])
    d1 = scored[0][0]
    d2 = scored[1][0] if len(scored) > 1 else float("inf")
    confidence = _grade(d1, d2 - d1, PLACE_HIGH, PLACE_MEDIUM, PLACE_HIGH_MARGIN, PLACE_MEDIUM_MARGIN)
    candidates = [Candidate(f"{n}|{s}", f"{n}, {s}", round(d, 2)) for d, (n, s) in scored[:top]]
    issues = []
    best = scored[0][1]

    if pincode:
        at_pin = pincodes().get(pincode)
        if at_pin is None:
            issues.append(f"pincode {pincode} not found")
        elif at_pin == best:
            confidence = HIGH if d1 <= PLACE_MEDIUM else confidence
        elif any(c.value == f"{at_pin[0]}|{at_pin[1]}" for c in candidates):
            best = at_pin                       # the pincode settles a close call
            confidence = MEDIUM
            issues.append(f"pincode {pincode} points to {at_pin[0]}, not {scored[0][1][0]}")
        else:
            confidence = LOW
            issues.append(f"pincode {pincode} is in {at_pin[0]}, {at_pin[1]}")

    value = f"{best[0]}|{best[1]}" if d1 <= PLACE_MEDIUM or pincode else None
    return EntityResult("district", heard, value, confidence, to_roman(heard), candidates, issues)


def pincode(heard: str, lang: str = "") -> EntityResult:
    result = ids.pincode(heard, lang, known=set(pincodes()))
    if result.value and result.value in pincodes():
        d, s = pincodes()[result.value]
        result.candidates = [Candidate(result.value, f"{result.value}, {d}, {s}")]
    return result


# ---- dates and amounts -----------------------------------------------------

def dob(heard: str, lang: str = "", today: date | None = None) -> EntityResult:
    r = parse_dob(heard, lang, today)
    issues = []
    if r.missing:
        issues.append(f"missing {', '.join(r.missing)}")
    if r.fuzzy:
        issues.append(f"approximate words: {', '.join(r.fuzzy)}")
    if r.unknown:
        issues.append(f"not understood: {', '.join(r.unknown)}")
    if r.note:
        issues.append(r.note)
    if r.iso is None:
        return EntityResult("dob", heard, None, LOW, to_roman(heard), issues=issues)
    confidence = HIGH if not issues else MEDIUM
    d = date.fromisoformat(r.iso)
    return EntityResult("dob", heard, r.iso, confidence, r.iso, [Candidate(r.iso, f"{d.day} {d:%B %Y}")], issues)


def event_date(heard: str, today: date, lang: str = "", tense: str = "") -> EntityResult:
    r = parse_event(heard, today, lang, tense)
    if r.iso:
        d = date.fromisoformat(r.iso)
        return EntityResult("date", heard, r.iso, HIGH if not r.fuzzy else MEDIUM, r.iso,
                            [Candidate(r.iso, f"{d.day} {d:%B %Y}")], [r.note] if r.note else [])
    candidates = [Candidate(c, f"{date.fromisoformat(c):%d %B %Y}") for c in r.candidates]
    issues = [x for x in (r.note, f"missing {', '.join(r.missing)}" if r.missing else "") if x]
    return EntityResult("date", heard, None, LOW, "", candidates, issues)


def amount(heard: str, lang: str = "") -> EntityResult:
    value, reading = parse_value(heard, lang)
    issues = []
    if reading.fuzzy:
        issues.append(f"approximate words: {', '.join(reading.fuzzy)}")
    if reading.unknown:
        issues.append(f"not understood: {', '.join(reading.unknown)}")
    if value is None or value <= 0:
        return EntityResult("amount", heard, None, LOW, "", issues=issues or ["no amount found"])
    rupees = round(value)
    confidence = HIGH if not issues else MEDIUM
    return EntityResult("amount", heard, str(rupees), confidence, str(rupees),
                        [Candidate(str(rupees), f"₹{_indian_format(rupees)}")], issues)


def _indian_format(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail
