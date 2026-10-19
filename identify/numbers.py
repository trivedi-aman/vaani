"""
Spoken numbers -> digits, in English, Hindi, Marathi and Tamil.

Callers say numbers the way they say them: "nine eight double six", "unnees
sau sattaasi", "do lakh pachaas hazaar", "aayiratti tollaayiratti enbatti
ezhu". STT may return these as words, in Roman or native script, or as
digits, or a mix. Two readings are needed:

  - digit strings (phone, pincode, OTP, loan ID): each word gives digits,
    "double/triple" repeat, "ninety eight" is "98".
  - values (amounts, years): words compose with multipliers, so
    "do lakh pachaas hazaar" is 250000.

Hindi and Marathi numbers from 1 to 100 are irregular (sattaasi is 87, not
"eighty-seven"), so they are listed in full. Words are matched exactly first,
then by phonetic distance, so STT spellings like "unnis" for "unnees" still
work; a fuzzy match is reported so confidence can drop.

The Marathi table was written from standard references and has not been
checked by a native speaker yet.
"""
import re
from dataclasses import dataclass, field
from functools import lru_cache

from .phonetic import sequence_distance, tokenize
from .translit import to_roman

# ---- lexicons --------------------------------------------------------------

_HI = """
0 shunya shoonya sunya zero
1 ek
2 do
3 teen tin
4 chaar char
5 paanch panch
6 chhah chhe chah che chheh chha chhai
7 saat sat
8 aath ath
9 nau nao naw nav
10 das dus
11 gyaarah gyarah gyara
12 baarah barah bara
13 terah tera
14 chaudah chauda
15 pandrah pandra
16 solah sola
17 satrah satra
18 athaarah atharah athara
19 unnees unnis
20 bees bis
21 ikkees ikkis
22 baaees bais baees
23 teis teees teyees
24 chaubees chaubis
25 pachchees pachees pachis
26 chhabbees chhabbis
27 sattaaees sattais
28 atthaaees atthais athais
29 unatees untees untis
30 tees tis
31 ikatees iktees iktis
32 battees battis
33 taintees taintis tetees
34 chauntees chauntis
35 paintees paintis
36 chhattees chhattis
37 saintees saintis
38 adatees adtees artees
39 untaalees untalis
40 chaalees chalis
41 iktaalees iktalis
42 bayaalees bayalis
43 taintaalees taintalis
44 chavaalees chavalis chauvalis
45 paintaalees paintalis
46 chhiyaalees chhiyalis
47 saintaalees saintalis
48 adtaalees artalis
49 unchaas unchas
50 pachaas pachas
51 ikyaavan ikyavan
52 baavan bavan
53 tirpan tirepan
54 chauvan chauwan
55 pachpan
56 chhappan
57 sattaavan sattavan
58 atthaavan atthavan
59 unsath unsaath
60 saath sath
61 iksath
62 baasath
63 tirsath tiresath
64 chausath chaunsath
65 painsath
66 chhiyaasath chhiyasath
67 sadsath sarsath
68 adsath arsath
69 unhattar
70 sattar
71 ikhattar
72 bahattar
73 tihattar
74 chauhattar
75 pachhattar
76 chhihattar
77 satattar sathattar
78 athhattar
79 unaasi unasi
80 assi
81 ikyaasi
82 bayaasi
83 tiraasi
84 chauraasi
85 pachaasi
86 chhiyaasi
87 sattaasi sattasi
88 athaasi atthasi
89 navaasi nawasi
90 nabbe
91 ikyaanave
92 baanave
93 tiraanave
94 chauraanave
95 pachaanave
96 chhiyaanave
97 sattaanave
98 atthaanave
99 ninyaanave
"""

_MR = """
2 don
5 paach
6 saha
10 daha
11 akra
12 baara
14 chauda
15 pandhra
16 sola
17 satra
18 athra
19 ekonis
20 vees
21 ekvees
22 baavees
23 tevees
24 chovees
25 panchvees
26 savvees
27 sattavees
28 atthavees
29 ekontees
31 ekatees
32 battees
33 tettees
34 chautees
35 pastees
36 chhattees
37 sadotees
38 adotees
39 ekonchaalees
40 chaalees
41 ekechaalees
42 betaalees
43 tretaalees
44 chavvechaalees
45 panchechaalees
46 sehechaalees
47 sattechaalees
48 atthechaalees
49 ekonpannaas
50 pannaas
51 ekkyaavanna
52 baavanna
53 trepanna
54 chopanna
55 panchavanna
56 chhappanna
57 sattaavanna
58 atthaavanna
59 ekonsaath
61 eksashta
62 baasashta
63 tresashta
64 chausashta
65 pasashta
66 sahasashta
67 sadusashta
68 adusashta
69 ekonsattar
71 ekaahattar
72 bahattar
73 tryaahattar
74 chauryaahattar
75 panchyaahattar
76 shahattar
77 sattyaahattar
78 atthyaahattar
79 ekonaaeshi
80 ainshi aishi
81 ekyaayshi
82 byaayshi
83 tryaayshi
84 chauryaayshi
85 panchyaayshi
86 shahaayshi
87 sattyaayshi
88 atthyaayshi
89 ekonnavvad
90 navvad
91 ekyaannav
92 byaannav
93 tryaannav
94 chauryaannav
95 panchyaannav
96 shahaannav
97 sattyaannav
98 atthyaannav
99 navvyaannav
"""

# Tamil: units, teens, tens, and the combining forms used before another
# number ("irupatti moonu" = 23, "aayiratti tollaayiratti..." = 19xx).
_TA = """
0 poojyam sunyam
1 onnu ondru oru
2 rendu irandu
3 moonu moondru
4 naalu naangu
5 anju aindhu
6 aaru
7 ezhu
8 ettu
9 onbadhu ombadhu ombodhu
10 pattu padhu pathu
11 padinonnu padhinonnu
12 panniranndu pannendu
13 padimoonu padhimoonu
14 padinaalu padhinaalu
15 padinanju padhinanju
16 padinaaru padhinaaru
17 padinezhu padhinezhu
18 padinettu padhinettu
19 pattombadhu
20 irubadhu irupathu irubatti irupatti irupathi
30 muppadhu muppathu muppatti muppathi
40 naarpadhu narpathu naarpatti naarpathi
50 aimbadhu aimbathu aimbatti aimbathi
60 arubadhu arubathu arubatti arubathi
70 ezhubadhu ezhupathu ezhubatti ezhupathi
80 enbadhu enbathu enbatti enbathi
90 tonnooru thonnooru tonnootti
200 irunooru
300 munnooru
400 naanooru
500 ainooru
600 aranooru
700 ezhunooru
800 ennooru
900 tollaayiram thollaayiram tollaayiratti thollaayirathi
1000 aayiratti aayirathi
2000 rendaayiram rendaayiratti
"""

_EN = """
0 zero oh nil
1 one
2 two
3 three
4 four
5 five
6 six
7 seven
8 eight
9 nine
10 ten
11 eleven
12 twelve
13 thirteen
14 fourteen
15 fifteen
16 sixteen
17 seventeen
18 eighteen
19 nineteen
20 twenty
30 thirty
40 forty fourty
50 fifty
60 sixty
70 seventy
80 eighty
90 ninety
1 first
2 second
3 third
4 fourth
5 fifth
6 sixth
7 seventh
8 eighth
9 ninth
10 tenth
11 eleventh
12 twelfth
13 thirteenth
14 fourteenth
15 fifteenth
16 sixteenth
17 seventeenth
18 eighteenth
19 nineteenth
20 twentieth
30 thirtieth
"""

# multipliers, by value
_MULT = """
100 hundred sau shambhar she nooru
1000 thousand hazaar hajaar hazar hajar aayiram
100000 lakh laakh lac laksham
10000000 crore karod kodi
1000000 million
"""

# words that change the next number (Hindi amounts: "saadhe teen lakh" = 3.5 lakh)
_MODIFIERS = {"saadhe": 0.5, "sadhe": 0.5, "saade": 0.5, "sawa": 0.25, "savva": 0.25, "paune": -0.25}
_FRACTIONS = {"dedh": 1.5, "derh": 1.5, "deedh": 1.5, "dhai": 2.5, "dhaai": 2.5, "adhai": 2.5, "adich": 2.5, "adeech": 2.5}
_REPEAT = {"double": 2, "triple": 3, "dabal": 2, "tripal": 3}
_FILLER = {"and", "aur", "ani", "rupees", "rupaye", "rupaiye", "rs", "only", "bas", "ka", "ki", "ke"}
_POINT = {"point", "dashamlav"}


def _parse_table(text: str, lang: str, kind: str, table: dict) -> None:
    for line in text.strip().splitlines():
        value, *words = line.split()
        for w in words:
            table[w] = (int(value), lang, kind)


WORDS: dict[str, tuple[int, str, str]] = {}
for _lang, _text in (("en", _EN), ("hi", _HI), ("mr", _MR), ("ta", _TA)):
    _parse_table(_text, _lang, "num", WORDS)
_parse_table(_MULT, "any", "mult", WORDS)

_TOKENIZED = {w: tokenize(w) for w in WORDS}
EXACT_MAX = 0.3        # vowel length or retroflex marks only: same word
FUZZY_MAX = 0.5        # max phonetic distance for a fuzzy number word
FUZZY_MARGIN = 0.15    # best match must beat the next different value by this


@lru_cache(maxsize=20_000)
def lookup(word: str, lang: str = "") -> tuple[int, str, bool] | None:
    """word -> (value, kind, exact) or None. Prefers the caller's language."""
    w = word.lower()
    if w in WORDS:
        value, _, kind = WORDS[w]
        return value, kind, True
    toks = tokenize(w)
    if not toks:
        return None
    scored = []
    for cand, ctoks in _TOKENIZED.items():
        d = sequence_distance(toks, ctoks)
        if d <= FUZZY_MAX + FUZZY_MARGIN:
            value, cand_lang, kind = WORDS[cand]
            bonus = 0.05 if cand_lang == lang else 0.0
            scored.append((d - bonus, value, kind))
    if not scored:
        return None
    scored.sort()
    best_d, best_v, best_k = scored[0]
    if best_d > FUZZY_MAX:
        return None
    rival = next((d for d, v, _ in scored[1:] if v != best_v), None)
    if rival is not None and rival - best_d < FUZZY_MARGIN:
        return None                     # two different numbers sound alike
    return best_v, best_k, best_d <= EXACT_MAX


# ---- splitting input into tokens ------------------------------------------

@dataclass
class Tok:
    kind: str            # num, mult, digits, frac, mod, repeat, point, filler, unknown
    value: float = 0
    raw: str = ""
    exact: bool = True


def _split(text: str) -> list[str]:
    text = to_roman(text.replace("₹", " rs "))
    text = re.sub(r"(\d),(\d)", r"\1\2", text)               # 2,50,000
    text = re.sub(r"(\d)([a-z])", r"\1 \2", text)             # 25k, 2lakh
    text = re.sub(r"([a-z])(\d)", r"\1 \2", text)             # ln00123
    return [w for w in re.split(r"[\s\-/,;:]+|\.(?!\d)", text) if w]


def tokens(text: str, lang: str = "") -> list[Tok]:
    out = []
    for w in _split(text):
        if re.fullmatch(r"\d+(\.\d+)?", w):
            out.append(Tok("digits", float(w), w))
        elif w in _REPEAT:
            out.append(Tok("repeat", _REPEAT[w], w))
        elif w in _MODIFIERS:
            out.append(Tok("mod", _MODIFIERS[w], w))
        elif w in _FRACTIONS:
            out.append(Tok("frac", _FRACTIONS[w], w))
        elif w in _POINT:
            out.append(Tok("point", 0, w))
        elif w == "k":
            out.append(Tok("mult", 1000, w))
        elif w in _FILLER:
            out.append(Tok("filler", 0, w))
        else:
            hit = lookup(w, lang)
            if hit:
                value, kind, exact = hit
                out.append(Tok(kind, value, w, exact))
            else:
                out.append(Tok("unknown", 0, w, False))

    # An approximate match only counts next to a sure number word: "raha"
    # sounds like Marathi "daha" (10), but in "aage nahi badh raha" it is a verb.
    def sure(j: int) -> bool:
        return 0 <= j < len(out) and out[j].kind in _NUMERIC and out[j].exact
    for i, t in enumerate(out):
        if t.kind in ("num", "mult") and not t.exact and not (sure(i - 1) or sure(i + 1)):
            out[i] = Tok("unknown", 0, t.raw, False)
    return out


_NUMERIC = {"num", "digits", "mult", "repeat", "frac", "mod", "point"}


def _span(toks: list[Tok]) -> list[Tok]:
    """Keep the run from the first to the last number word; words around it are context."""
    idx = [i for i, t in enumerate(toks) if t.kind in _NUMERIC]
    if not idx:
        return []
    return [t for t in toks[idx[0]: idx[-1] + 1] if t.kind != "filler"]


# ---- readings --------------------------------------------------------------

@dataclass
class Reading:
    value: str | None                       # digits as a string, or None
    fuzzy: list[str] = field(default_factory=list)     # words matched approximately
    unknown: list[str] = field(default_factory=list)   # words not understood


def parse_digits(text: str, lang: str = "") -> Reading:
    """
    Digit-string reading: phone numbers, pincodes, OTPs, IDs.
    "nine eight double six" -> "9866"; "ninety eight" -> "98";
    "nau sau" -> "900". Words around the number are ignored; words inside it
    that are not numbers are reported.
    """
    toks = _span(tokens(text, lang))
    out: list[str] = []
    fuzzy, unknown = [], []
    repeat = 1
    i = 0
    while i < len(toks):
        t = toks[i]
        if not t.exact and t.kind != "unknown":
            fuzzy.append(t.raw)
        if t.kind == "repeat":
            repeat = int(t.value)
        elif t.kind == "digits":
            out.append(t.raw.replace(".", "") * repeat)
            repeat = 1
        elif t.kind == "num":
            v = int(t.value)
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if v >= 20 and v % 10 == 0 and v < 100 and nxt and nxt.kind == "num" and 1 <= nxt.value <= 9:
                v += int(nxt.value)           # "ninety eight" -> 98
                if not nxt.exact:
                    fuzzy.append(nxt.raw)
                i += 1
            out.append(str(v) * repeat)
            repeat = 1
        elif t.kind == "mult" and out:
            out[-1] = str(int(out[-1]) * int(t.value))   # "nau sau" -> 900
        elif t.kind == "unknown":
            unknown.append(t.raw)
        i += 1
    return Reading("".join(out) or None, fuzzy, unknown)


def parse_value(text: str, lang: str = "") -> tuple[float | None, Reading]:
    """
    Value reading: amounts and counts.
    "do lakh pachaas hazaar" -> 250000; "2.5 lakh" -> 250000;
    "dhai lakh" -> 250000; "saadhe teen hazaar" -> 3500; "25k" -> 25000.
    """
    toks = _span(tokens(text, lang))
    # Words that are not numbers split the speech into separate numbers
    # ("do baar kat gaya, pachchees hazaar"). The amount is the largest one;
    # the others are reported so the agent can check.
    groups: list[list[Tok]] = [[]]
    for t in toks:
        if t.kind == "unknown":
            groups.append([])
        else:
            groups[-1].append(t)
    scored = [(v, r) for v, r in (_value_of(g) for g in groups if g) if v is not None]
    if not scored:
        return None, Reading(None)
    scored.sort(key=lambda vr: vr[0], reverse=True)
    value, reading = scored[0]
    reading.unknown += [f"also heard {r.value}" for _, r in scored[1:]]
    return value, reading


def _value_of(toks: list[Tok]) -> tuple[float | None, Reading]:
    total, current = 0.0, 0.0
    pending_mod = 0.0
    decimal_next = False
    seen = False
    fuzzy, unknown = [], []
    for t in toks:
        if not t.exact and t.kind != "unknown":
            fuzzy.append(t.raw)
        if t.kind in ("num", "digits", "frac"):
            v = t.value + pending_mod
            pending_mod = 0.0
            if decimal_next:
                current += v / (10 ** len(str(int(t.value))))
                decimal_next = False
            else:
                current += v
            seen = True
        elif t.kind == "mod":
            pending_mod = t.value
        elif t.kind == "point":
            decimal_next = True
        elif t.kind == "mult":
            current = (current or 1) * t.value
            if t.value >= 1000:
                total += current
                current = 0.0
            seen = True
        elif t.kind == "unknown":
            unknown.append(t.raw)
    if not seen:
        return None, Reading(None, fuzzy, unknown)
    value = total + current
    return value, Reading(str(int(value)) if value == int(value) else str(value), fuzzy, unknown)


def parse_year(text: str, lang: str = "") -> tuple[int | None, Reading]:
    """
    Years: "1987", "87", "nineteen eighty seven", "unnees sau sattaasi",
    "unnees sattaasi", "aayiratti tollaayiratti enbatti ezhu", "do hazaar teen".
    Two-digit years are returned as-is (< 100); the caller decides the century.
    """
    toks = _span(tokens(text, lang))
    fuzzy = [t.raw for t in toks if not t.exact and t.kind != "unknown"]
    unknown = [t.raw for t in toks if t.kind == "unknown"]
    if any(t.kind == "mult" for t in toks) or any(t.kind == "num" and t.value >= 200 for t in toks):
        value, reading = parse_value(text, lang)
        return (int(value) if value else None), reading
    # Without a multiplier, a year is spoken as two groups: "19 | 87".
    groups: list[int] = []
    for t in toks:
        if t.kind == "digits":
            groups.append(int(t.value))
        elif t.kind == "num":
            v = int(t.value)
            if groups and groups[-1] >= 20 and groups[-1] % 10 == 0 and groups[-1] < 100 and 1 <= v <= 9 and len(groups) > 1:
                groups[-1] += v                  # "eighty seven"
            else:
                groups.append(v)
    if not groups:
        return None, Reading(None, fuzzy, unknown)
    if len(groups) == 1:
        return groups[0], Reading(str(groups[0]), fuzzy, unknown)
    if len(groups) == 3 and groups[1] % 10 == 0 and groups[2] < 10:
        groups = [groups[0], groups[1] + groups[2]]
    if len(groups) == 2 and groups[0] < 100 and groups[1] < 100:
        year = groups[0] * 100 + groups[1]
        return year, Reading(str(year), fuzzy, unknown)
    return None, Reading(None, fuzzy, unknown + [str(g) for g in groups])
