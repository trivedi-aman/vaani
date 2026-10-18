"""
Three name matchers behind one interface, so they can be swapped and
compared on the same evaluation set (eval/matchers.py).

  levenshtein  letters only; the usual baseline
  metaphone    English phonetic codes; included as a known-weak baseline,
               since its rules are for English spelling, not Indian names
  phoneme      our weighted sound distance (identify/phonetic.py)

All three see the same input: native script is converted to Roman first,
so the comparison is about matching, not about transliteration.
"""
from abc import ABC, abstractmethod

import jellyfish
from rapidfuzz.distance import Levenshtein

from .phonetic import name_distance
from .translit import plain, to_roman


class NameMatcher(ABC):
    name: str

    @abstractmethod
    def distance(self, heard: str, reference: str) -> float: ...


class LevenshteinMatcher(NameMatcher):
    name = "levenshtein"

    def distance(self, heard, reference):
        return float(Levenshtein.distance(plain(to_roman(heard)), reference.lower()))


class MetaphoneMatcher(NameMatcher):
    name = "metaphone"

    def distance(self, heard, reference):
        a = " ".join(jellyfish.metaphone(w) for w in plain(to_roman(heard)).split())
        b = " ".join(jellyfish.metaphone(w) for w in reference.lower().split())
        return float(Levenshtein.distance(a, b))


class PhonemeMatcher(NameMatcher):
    name = "phoneme"

    def distance(self, heard, reference):
        return name_distance(heard, reference)


MATCHERS = {m.name: m for m in (LevenshteinMatcher(), MetaphoneMatcher(), PhonemeMatcher())}


def get_matcher(name: str = "phoneme") -> NameMatcher:
    if name not in MATCHERS:
        raise ValueError(f"unknown matcher {name!r}; choose from {sorted(MATCHERS)}")
    return MATCHERS[name]
