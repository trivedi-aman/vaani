"""
Phoneme-weighted distance for Indian names and places.

Plain edit distance treats every letter swap as equally bad. For speech that
is wrong in both directions:

  - "Barmer" vs "Baadmer" are the same place: a vowel-length change plus the
    retroflex flap (ड़) written two different ways. Should be cheap.
  - "Mohan" vs "Rohan" are different people: m and r sound nothing alike,
    even though only one letter differs. Should be expensive.

So each sound carries articulatory features (where and how it is made,
voicing, aspiration; vowel height, backness, length), and substituting one
sound for another costs the weighted difference of those features. A small
table of confusions specific to Indian languages (data/reference/confusions.csv)
overrides the feature cost where linguistics says two sounds are routinely
mixed up.
"""
import csv
import re
from functools import lru_cache
from pathlib import Path

from .translit import to_roman

# ---- sound inventory -------------------------------------------------------

# consonants: (place, manner, voiced, aspirated)
#   place: 0 bilabial, 1 labiodental, 2 dental/alveolar, 3 retroflex,
#          4 palatal, 5 velar, 6 glottal
#   manner: 0 stop, 1 nasal, 2 fricative, 3 approximant, 4 trill/flap, 5 affricate
CONSONANTS = {
    "p": (0, 0, 0, 0), "ph": (0, 0, 0, 1), "b": (0, 0, 1, 0), "bh": (0, 0, 1, 1), "m": (0, 1, 1, 0),
    "f": (1, 2, 0, 0), "v": (1, 3, 1, 0), "w": (0, 3, 1, 0),
    "t": (2, 0, 0, 0), "th": (2, 0, 0, 1), "d": (2, 0, 1, 0), "dh": (2, 0, 1, 1),
    "n": (2, 1, 1, 0), "s": (2, 2, 0, 0), "z": (2, 2, 1, 0), "l": (2, 3, 1, 0), "r": (2, 4, 1, 0),
    "ṭ": (3, 0, 0, 0), "ṭh": (3, 0, 0, 1), "ḍ": (3, 0, 1, 0), "ḍh": (3, 0, 1, 1),
    "ṇ": (3, 1, 1, 0), "ḷ": (3, 3, 1, 0), "ṛ": (3, 4, 1, 0), "ṛh": (3, 4, 1, 1), "zh": (3, 3, 1, 0),
    "ch": (4, 5, 0, 0), "chh": (4, 5, 0, 1), "j": (4, 5, 1, 0), "jh": (4, 5, 1, 1),
    "sh": (4, 2, 0, 0), "y": (4, 3, 1, 0),
    "k": (5, 0, 0, 0), "kh": (5, 0, 0, 1), "g": (5, 0, 1, 0), "gh": (5, 0, 1, 1),
    "h": (6, 2, 0, 0),
}
# vowels: (height 0 low..2 high, backness 0 front..2 back, length 0 short/1 long)
VOWELS = {
    "a": (0, 1, 0), "aa": (0, 1, 1),
    "i": (2, 0, 0), "ee": (2, 0, 1),
    "u": (2, 2, 0), "oo": (2, 2, 1),
    "e": (1, 0, 0), "ai": (1, 0, 1),
    "o": (1, 2, 0), "au": (1, 2, 1),
}

W_PLACE, W_MANNER, W_VOICE, W_ASP = 0.45, 0.45, 0.25, 0.15
W_HEIGHT, W_BACK, W_LEN = 0.35, 0.35, 0.25
CROSS_CLASS = 1.8          # a vowel replaced by a consonant
INDEL = 0.85               # a consonant missing or added
INDEL_CHEAP = {"a": 0.4, "h": 0.4, "y": 0.5}   # silent schwa, aspiration spellings
INDEL_VOWEL = 0.6

_TOKENS = sorted(set(CONSONANTS) | set(VOWELS), key=len, reverse=True)

_CONFUSIONS_CSV = Path(__file__).resolve().parent.parent / "data" / "reference" / "confusions.csv"


def _load_confusions() -> dict[frozenset, float]:
    with open(_CONFUSIONS_CSV, encoding="utf-8") as f:
        return {frozenset((r["a"], r["b"])): float(r["cost"]) for r in csv.DictReader(f)}


CONFUSIONS = _load_confusions()

# ---- tokenizer -------------------------------------------------------------

# English-style spellings of Indian names, folded before tokenizing.
_SPELLING = [
    ("ck", "k"), ("x", "ks"), ("q", "k"), ("ii", "ee"), ("uu", "oo"),
    ("ou", "au"),
]


def _fold(word: str) -> str:
    w = word.lower()
    for a, b in _SPELLING:
        w = w.replace(a, b)
    if w.endswith("ow"):                      # Lucknow
        w = w[:-2] + "au"
    if w.endswith("ey"):                      # Pandey, Dubey
        w = w[:-2] + "e"
    w = re.sub(r"ay(?=[^aeiou]|$)", "ai", w)   # Sanjay/संजय, Jaipur/जयपुर
    # c without h is k (Vincent, Deepcika); keep ch
    w = "".join("k" if c == "c" and not w[i + 1:i + 2] == "h" else c for i, c in enumerate(w))
    # doubled consonants are not contrastive in romanised names (Pillai/Pilai)
    out = []
    for c in w:
        if out and c == out[-1] and c not in "aeo":
            continue
        out.append(c)
    return "".join(out)


@lru_cache(maxsize=50_000)
def tokenize(word: str) -> tuple[str, ...]:
    """One word in any script -> tuple of sounds, greedy longest match."""
    s = _fold(to_roman(word))
    i, out = 0, []
    while i < len(s):
        for tok in _TOKENS:
            if s.startswith(tok, i):
                out.append(tok)
                i += len(tok)
                break
        else:
            i += 1                            # digits, punctuation, unknown marks
    return tuple(out)


# ---- costs -----------------------------------------------------------------

def sub_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    override = CONFUSIONS.get(frozenset((a, b)))
    if override is not None:
        return override
    a_vowel, b_vowel = a in VOWELS, b in VOWELS
    if a_vowel != b_vowel:
        return CROSS_CLASS
    if a_vowel:
        h1, k1, l1 = VOWELS[a]
        h2, k2, l2 = VOWELS[b]
        return W_HEIGHT * abs(h1 - h2) + W_BACK * abs(k1 - k2) + W_LEN * abs(l1 - l2)
    p1, m1, v1, s1 = CONSONANTS[a]
    p2, m2, v2, s2 = CONSONANTS[b]
    return W_PLACE * abs(p1 - p2) + W_MANNER * min(abs(m1 - m2), 2) + W_VOICE * abs(v1 - v2) + W_ASP * abs(s1 - s2)


def indel_cost(tok: str) -> float:
    if tok in INDEL_CHEAP:
        return INDEL_CHEAP[tok]
    return INDEL_VOWEL if tok in VOWELS else INDEL


def sequence_distance(pa: tuple[str, ...], pb: tuple[str, ...]) -> float:
    """Weighted edit distance between two sound sequences."""
    n, m = len(pa), len(pb)
    prev = [0.0] * (m + 1)
    for j in range(1, m + 1):
        prev[j] = prev[j - 1] + indel_cost(pb[j - 1])
    for i in range(1, n + 1):
        cur = [prev[0] + indel_cost(pa[i - 1])] + [0.0] * m
        for j in range(1, m + 1):
            cur[j] = min(
                prev[j - 1] + sub_cost(pa[i - 1], pb[j - 1]),
                prev[j] + indel_cost(pa[i - 1]),
                cur[j - 1] + indel_cost(pb[j - 1]),
            )
        prev = cur
    return prev[m]


SWAP_PENALTY = 0.2


def name_distance(a: str, b: str) -> float:
    """
    Distance between two names of one or more words.

    Word order may differ ("Meena Sultan" for "Sultan Meena"), so two-word
    names are compared both ways, with a small penalty for the swap. Names
    with a different number of words (a dropped surname, "Meenakshisundaram"
    as one word) are compared as one joined sequence, so every missing sound
    costs something.
    """
    wa = [tokenize(w) for w in a.split() if tokenize(w)]
    wb = [tokenize(w) for w in b.split() if tokenize(w)]
    if not wa or not wb:
        return float("inf")
    if len(wa) == len(wb):
        straight = sum(sequence_distance(x, y) for x, y in zip(wa, wb))
        if len(wa) == 2:
            swapped = sequence_distance(wa[0], wb[1]) + sequence_distance(wa[1], wb[0]) + SWAP_PENALTY
            return min(straight, swapped)
        return straight
    joined_a = tuple(t for w in wa for t in w)
    joined_b = tuple(t for w in wb for t in w)
    return sequence_distance(joined_a, joined_b)


@lru_cache(maxsize=50_000)
def length(text: str) -> int:
    """Number of sounds in a name or place, all words together."""
    return sum(len(tokenize(w)) for w in text.split())
