"""
Spoken dates -> ISO dates.

Two jobs:

  parse_dob()    "23 April 87", "teis chaar unnees sau sattaasi",
                 "23/04/1987", "இருபத்தி மூணு ஏப்ரல் ..." -> 1987-04-23.
                 Day-month-year order (Indian convention). Two-digit years
                 get the century that makes the caller an adult.

  parse_event()  dates of things that happened or will happen, relative to
                 the call: "pichhle mahine ki paanch tareekh", "kal",
                 "nethu", "agle somvar", "3 din pehle".

Both return a DateReading that says what was understood and what was not,
so the caller can lower confidence or ask again. "kal" means both yesterday
and tomorrow in Hindi; without a tense hint both candidates are returned.
"""
import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .numbers import Tok, lookup, parse_year, tokens
from .phonetic import sequence_distance, tokenize
from .translit import to_roman

_MONTHS_TEXT = """
1 january jan janvari janavari janwari
2 february feb farvari pharvari pebravari febravari
3 march mar maarch
4 april apr aprail epral eprail
5 may mai mee
6 june jun joon
7 july jul julai julaai joolai
8 august aug agast aagast
9 september sep sept sitambar septembar
10 october oct aktoobar aktobar
11 november nov navambar
12 december dec disambar
"""
MONTHS: dict[str, int] = {}
for _line in _MONTHS_TEXT.strip().splitlines():
    _n, *_words = _line.split()
    for _w in _words:
        MONTHS[_w] = int(_n)
_MONTH_TOKENS = {w: tokenize(w) for w in MONTHS if len(w) > 3}

_DAY_WORDS = {"tareekh", "tarikh", "taarikh", "tarik", "taareekh", "date", "tedi", "taareek"}
_ORDINAL = re.compile(r"^(\d{1,2})(st|nd|rd|th)$")


def month_of(word: str) -> int | None:
    w = word.lower()
    if w in MONTHS:
        return MONTHS[w]
    if len(w) <= 3:
        return None                      # "me", "mar" in Hindi mean other things
    toks = tokenize(w)
    best = sorted((sequence_distance(toks, t), MONTHS[m]) for m, t in _MONTH_TOKENS.items())
    if best and best[0][0] <= 0.6 and (len(best) == 1 or best[1][1] == best[0][1] or best[1][0] - best[0][0] >= 0.3):
        return best[0][1]
    return None


@dataclass
class DateReading:
    iso: str | None
    candidates: list[str] = field(default_factory=list)   # when ambiguous
    missing: list[str] = field(default_factory=list)      # day / month / year
    fuzzy: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    note: str = ""


def _valid(y: int, m: int, d: int) -> bool:
    return 1 <= m <= 12 and 1 <= d <= calendar.monthrange(y, m)[1] if 1900 <= y <= 2100 else False


def _dob_century(yy: int, today: date) -> int:
    """87 -> 1987, 03 -> 2003, unless that would make the caller a minor."""
    year = 2000 + yy
    if year > today.year - 18:
        year -= 100
    return year


def parse_dob(text: str, lang: str = "", today: date | None = None) -> DateReading:
    today = today or date.today()
    raw = to_roman(text).lower()

    # 1. written dates: 23/04/1987, 23-4-87, 23.04.1987, 1987-04-23
    m = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", raw)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})\b", raw)
        if m:
            d, mo, y = int(m[1]), int(m[2]), int(m[3])
            if y < 100:
                y = _dob_century(y, today)
    if m:
        if _valid(y, mo, d):
            return DateReading(date(y, mo, d).isoformat())
        return DateReading(None, unknown=[m[0]], note="not a real date")

    # 2. spoken: find the month word, day before it, year after it
    words = re.split(r"[\s,]+", raw)
    month_idx, month = None, None
    for i, w in enumerate(words):
        mo = month_of(w)
        if mo:
            month_idx, month = i, mo
            break

    fuzzy: list[str] = []
    unknown: list[str] = []
    day = year = None
    if month_idx is not None:
        before = [w for w in words[:month_idx] if w not in _DAY_WORDS]
        after = [w for w in words[month_idx + 1:] if w not in _DAY_WORDS]
        day = _day_from(before, lang, fuzzy, unknown)
        if after:
            y, reading = parse_year(" ".join(after), lang)
            fuzzy += reading.fuzzy
            unknown += reading.unknown
            year = y
    else:
        # 3. all numbers: "teis chaar unnees sau sattaasi" = 23 / 4 / 1987
        found = _numbers_only(words, lang, fuzzy, unknown, today)
        if len(found) > 1:
            return DateReading(None, candidates=[date(y, m, d).isoformat() for d, m, y in found],
                               fuzzy=fuzzy, unknown=unknown, note="numbers can be split more than one way")
        if found:
            day, month, year = found[0]

    if year is not None and year < 100:
        year = _dob_century(year, today)
    missing = [name for name, v in (("day", day), ("month", month), ("year", year)) if v is None]
    if missing:
        return DateReading(None, missing=missing, fuzzy=fuzzy, unknown=unknown)
    if not _valid(year, month, day):
        return DateReading(None, fuzzy=fuzzy, unknown=unknown, note=f"{day}/{month}/{year} is not a real date")
    dob = date(year, month, day)
    age = (today - dob).days // 365
    note = "" if 18 <= age <= 100 else f"implies age {age}"
    return DateReading(dob.isoformat(), fuzzy=fuzzy, unknown=unknown, note=note)


def _day_from(words: list[str], lang: str, fuzzy: list, unknown: list) -> int | None:
    if not words:
        return None
    m = _ORDINAL.match(words[-1])
    if m:
        return int(m[1])
    toks = [t for t in tokens(" ".join(words), lang) if t.kind in ("num", "digits", "unknown")]
    value = 0
    for t in toks:
        if t.kind == "unknown":
            unknown.append(t.raw)
            continue
        if not t.exact:
            fuzzy.append(t.raw)
        value += int(t.value)
    return value if 1 <= value <= 31 else None


def _numbers_only(words: list[str], lang: str, fuzzy: list, unknown: list, today: date) -> list[tuple]:
    """
    Day, month and year said as plain numbers: "teis chaar unnees sau sattaasi".
    Speech has no separators, so "bees chhah ..." is either day 26 or day 20
    and month 6. Every split is tried; the valid dates are returned.
    """
    toks: list[Tok] = []
    for t in tokens(" ".join(w for w in words if w not in _DAY_WORDS), lang):
        if t.kind == "unknown":
            unknown.append(t.raw)
        elif t.kind in ("num", "digits", "mult"):
            if not t.exact:
                fuzzy.append(t.raw)
            toks.append(t)

    def small_numbers(i: int) -> list[tuple[int, int]]:
        """(value, next index) for the number starting at toks[i], with and without joining tens + unit."""
        if i >= len(toks) or toks[i].kind == "mult":
            return []
        v = int(toks[i].value)
        out = [(v, i + 1)]
        if 20 <= v < 100 and v % 10 == 0 and i + 1 < len(toks) and toks[i + 1].kind == "num" and 1 <= toks[i + 1].value <= 9:
            out.append((v + int(toks[i + 1].value), i + 2))
        return out

    found = []
    for day, j in small_numbers(0):
        for month, k in small_numbers(j):
            if not (1 <= day <= 31 and 1 <= month <= 12) or k >= len(toks):
                continue
            year, _ = parse_year(" ".join(t.raw for t in toks[k:]), lang)
            if year is not None and year < 100:
                year = _dob_century(year, today)
            if year and _valid(year, month, day):
                found.append((day, month, year))
    plausible = [f for f in found if today.year - 100 <= f[2] <= today.year - 18]   # an adult's birth year
    return plausible or found


# ---- relative dates --------------------------------------------------------

_TODAY = {"aaj", "today", "inniki", "indru", "innaikku", "aaja"}
_YESTERDAY = {"yesterday", "nethu", "netru"}
_TOMORROW = {"tomorrow", "naalai", "naale", "udya"}
_KAL = {"kal", "kaal"}                                   # yesterday OR tomorrow
_DAY_BEFORE = {"parso", "parson", "parva"}               # also ambiguous in Hindi
_PAST = {"pichhle", "pichle", "pichhla", "pichla", "last", "previous", "pona", "poyina", "maagchya", "magchya", "gaye", "gayi", "gaya"}
_NEXT = {"agle", "agla", "next", "adutha", "aduththa", "pudhchya", "pudchya", "aane"}
_THIS = {"is", "this", "intha", "ya", "ha", "hya"}
_MONTH_WORDS = {"mahine", "mahina", "mahinyat", "mahinyaat", "month", "maasam", "masam"}
_WEEK_WORDS = {"hafte", "hafta", "week", "aathavda", "vaaram"}
_DAYS_AGO = {"din", "days", "day", "divas", "naal", "naalukku"}
_AGO = {"pehle", "pahle", "ago", "back", "aadhi", "purvi", "munnaadi", "munnadi", "munbu"}
_WEEKDAYS = {
    0: {"monday", "somvar", "somvaar", "thingal", "thingalkizhamai"},
    1: {"tuesday", "mangalvar", "mangalvaar", "sevvai", "sevvaikizhamai"},
    2: {"wednesday", "budhvar", "budhvaar", "budhan", "budhankizhamai"},
    3: {"thursday", "guruvar", "guruvaar", "brihaspativar", "viyazhan", "viyazhakizhamai"},
    4: {"friday", "shukravar", "shukravaar", "velli", "vellikizhamai"},
    5: {"saturday", "shanivar", "shanivaar", "sani", "sanikizhamai"},
    6: {"sunday", "ravivar", "ravivaar", "itvaar", "itwar", "nyayiru", "nyaayitrukizhamai"},
}


def _shift_month(d: date, months: int, day: int | None) -> date | None:
    y, m = d.year, d.month + months
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    day = day or d.day
    if day > calendar.monthrange(y, m)[1]:
        return None
    return date(y, m, day)


def parse_event(text: str, today: date, lang: str = "", tense: str = "") -> DateReading:
    """
    tense: "past" (an EMI that bounced), "future" (a payment promised), or ""
    when unknown; it resolves "kal" and "parso".
    """
    absolute = parse_dob(text, lang, today) if any(month_of(w) for w in to_roman(text).lower().split()) else None
    if absolute and absolute.iso:
        return absolute
    words = [w for w in re.split(r"[\s,]+", to_roman(text).lower()) if w]
    ws = set(words)

    if ws & _TODAY:
        return DateReading(today.isoformat())
    if ws & _YESTERDAY:
        return DateReading((today - timedelta(days=1)).isoformat())
    if ws & _TOMORROW:
        return DateReading((today + timedelta(days=1)).isoformat())
    for words_set, offset in ((_KAL, 1), (_DAY_BEFORE, 2)):
        if ws & words_set and not ws & (_MONTH_WORDS | _WEEK_WORDS):
            past, future = today - timedelta(days=offset), today + timedelta(days=offset)
            if tense == "past":
                return DateReading(past.isoformat())
            if tense == "future":
                return DateReading(future.isoformat())
            return DateReading(None, candidates=[past.isoformat(), future.isoformat()],
                               note=f"'{(ws & words_set).pop()}' can mean either")

    # "3 din pehle", "teen din pehle", "three days ago"
    if ws & _DAYS_AGO and ws & _AGO:
        idx = next(i for i, w in enumerate(words) if w in _DAYS_AGO)
        n = _number_before(words, idx, lang)
        if n:
            return DateReading((today - timedelta(days=n)).isoformat())

    # "pichhle mahine ki paanch tareekh", "next month 5th", "is mahine ki 10"
    if ws & _MONTH_WORDS:
        shift = -1 if ws & _PAST else 1 if ws & _NEXT else 0
        day = _day_in(words, lang)
        target = _shift_month(today, shift, day)
        if target is None:
            return DateReading(None, note="that day does not exist in that month")
        if day is None:
            return DateReading(None, missing=["day"], note=f"month is {target:%B %Y}")
        return DateReading(target.isoformat())

    # weekdays: "agle somvar", "last friday", "shukravar ko"
    for wd, names in _WEEKDAYS.items():
        if ws & names:
            delta = (wd - today.weekday()) % 7
            if ws & _PAST or tense == "past":
                delta = delta - 7 if delta else -7
            elif delta == 0:
                delta = 7
            return DateReading((today + timedelta(days=delta)).isoformat())

    # a bare day number: "paanch tareekh" -> this month, or last month if past
    day = _day_in(words, lang)
    if day and ws & _DAY_WORDS:
        target = _shift_month(today, 0, day)
        if target and target > today and tense == "past":
            target = _shift_month(today, -1, day)
        if target:
            return DateReading(target.isoformat())
    return DateReading(None, unknown=words, note="no date found")


def _number_before(words: list[str], idx: int, lang: str) -> int | None:
    for w in reversed(words[:idx]):
        if w.isdigit():
            return int(w)
        hit = lookup(w, lang)
        if hit and hit[1] == "num":
            return hit[0]
    return None


def _day_in(words: list[str], lang: str) -> int | None:
    for w in words:
        m = _ORDINAL.match(w)
        if m:
            return int(m[1])
    for i, w in enumerate(words):
        if w in _DAY_WORDS:
            n = _number_before(words, i, lang)
            if n and 1 <= n <= 31:
                return n
    for w in words:
        if w.isdigit() and 1 <= int(w) <= 31:
            return int(w)
        if w in _THIS | _PAST | _NEXT | _MONTH_WORDS:
            continue
        hit = lookup(w, lang)
        if hit and hit[1] == "num" and hit[2] and 1 <= hit[0] <= 31:
            return hit[0]
    return None


# ---- financial years -------------------------------------------------------

_LAST_YEAR = {"pichhle", "pichle", "last", "previous", "pona", "maagchya", "magil"}
_YEAR_WORDS = {"saal", "sal", "year", "varsh", "varsha", "varusham", "fy"}


def financial_year(text: str, today: date) -> str | None:
    """
    Indian financial year (April-March) as "2025-26".
    "pichhle saal ka" / "last year" -> the FY before the current one;
    "is saal" / "this year" -> the current FY; "2025-26", "FY26", "2025" also work.
    """
    raw = to_roman(text).lower()
    current_start = today.year if today.month >= 4 else today.year - 1
    m = re.search(r"\b(20\d\d)\s*[-/]\s*(\d\d)\b", raw)
    if m:
        start = int(m[1])
    elif (m := re.search(r"\bfy\s*'?(\d\d)\b", raw)):
        start = 2000 + int(m[1]) - 1          # FY26 = 2025-26
    elif (m := re.search(r"\b(20\d\d)\b", raw)):
        start = int(m[1])
    else:
        words = set(raw.split())
        if not words & _YEAR_WORDS:
            return None
        start = current_start - 1 if words & _LAST_YEAR else current_start
    return f"{start}-{(start + 1) % 100:02d}"
