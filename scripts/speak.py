"""
Render values the way a caller says them, for scenario scripts and
evaluation data: numbers, digit strings and dates in English, Hindi,
Marathi and Tamil (Roman letters, as STT often returns them).

The word lists come from identify/numbers.py, so whatever is spoken here
can be read back by the parser: this checks the round trip, it does not
replace testing with real speech.
"""
from datetime import date

from identify.numbers import _EN, _HI, _MR, _TA


def _table(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for line in text.strip().splitlines():
        v, word, *_ = line.split()
        out.setdefault(int(v), word)
    return out


EN, HI, MR, TA = _table(_EN), _table(_HI), _table(_MR), _table(_TA)
# Marathi uses the Hindi form where the two are the same word
MR = {**HI, **MR}
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]
MONTHS_HI = ["janvari", "farvari", "march", "aprail", "mai", "joon", "julai", "agast",
             "sitambar", "aktoobar", "navambar", "disambar"]


def en_number(n: int) -> str:
    if n < 20:
        return EN[n]
    if n < 100:
        return EN[n - n % 10] + ("" if n % 10 == 0 else " " + EN[n % 10])
    for size, word in ((10_000_000, "crore"), (100_000, "lakh"), (1000, "thousand"), (100, "hundred")):
        if n >= size:
            head, rest = divmod(n, size)
            return f"{en_number(head)} {word}" + (f" {en_number(rest)}" if rest else "")
    raise ValueError(n)


def hi_number(n: int, table: dict[int, str] = HI) -> str:
    if n < 100:
        return table[n]
    for size, word in ((10_000_000, "crore"), (100_000, "lakh"), (1000, "hazaar"), (100, "sau")):
        if n >= size:
            head, rest = divmod(n, size)
            return f"{hi_number(head, table)} {word}" + (f" {hi_number(rest, table)}" if rest else "")
    raise ValueError(n)


def ta_number(n: int) -> str:
    """Tamil, for the ranges our scripts need (days, years 1950-2009, small amounts)."""
    if n in TA and n < 20:
        return TA[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        combining = {2: "irupatti", 3: "muppatti", 4: "naarpatti", 5: "aimbatti", 6: "arubatti",
                     7: "ezhubatti", 8: "enbatti", 9: "tonnootti"}
        plain = {2: "irubadhu", 3: "muppadhu", 4: "naarpadhu", 5: "aimbadhu", 6: "arubadhu",
                 7: "ezhubadhu", 8: "enbadhu", 9: "tonnooru"}
        return plain[tens] if unit == 0 else f"{combining[tens]} {TA[unit]}"
    if 1900 <= n < 2000:
        return "aayiratti tollaayiratti " + ta_number(n - 1900) if n > 1900 else "aayiratti tollaayiram"
    if 2000 <= n < 2100:
        return "rendaayiratti " + ta_number(n - 2000) if n > 2000 else "rendaayiram"
    raise ValueError(n)


def digits(s: str, lang: str = "en", use_double: bool = True) -> str:
    """Say a digit string one digit at a time, with "double" for repeats."""
    table = {"en": EN, "hi": HI, "mr": MR, "ta": TA}[lang]
    words, i = [], 0
    while i < len(s):
        d = s[i]
        if use_double and i + 1 < len(s) and s[i + 1] == d and (i + 2 >= len(s) or s[i + 2] != d):
            words += ["double", table[int(d)]]
            i += 2
            continue
        words.append(table[int(d)])
        i += 1
    return " ".join(words)


def dob(iso: str, lang: str = "en", style: str = "words") -> str:
    d = date.fromisoformat(iso)
    if style == "numeric":
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    if lang == "en":
        return f"{en_number(d.day)} {MONTHS_EN[d.month - 1]} {en_number(d.year // 100)} {en_number(d.year % 100)}"
    if lang in ("hi", "mr"):
        table = HI if lang == "hi" else MR
        year = f"{table[d.year // 100]} {'sau' if lang == 'hi' else 'she'} {table[d.year % 100]}" if d.year < 2000 \
            else hi_number(d.year, table)
        month = MONTHS_HI[d.month - 1] if style == "words" else table[d.month]
        return f"{table[d.day]} {month} {year}"
    if lang == "ta":
        return f"{ta_number(d.day)} {MONTHS_EN[d.month - 1].lower()} {ta_number(d.year)}"
    raise ValueError(lang)
