"""
Compare the three name matchers on names and places as STT hears them.

Three sources of test items, reported separately because they test
different things:

  handwritten  ~110 variants written by hand: STT-style misspellings,
               surname-first, old city names, native script.
  native       every customer's name in Devanagari or Tamil script, as STT
               returns Hindi, Marathi and Tamil speech.
  rules        Roman spelling variants made by rules (vowel length, v/w,
               sh/s, dropped final a, doubled letters...). These rules
               describe the same confusions the phoneme matcher was built
               around, so this set flatters it; it is here to check the
               matcher does what it was designed to do, not to prove it
               is better.

Names are matched against all 300 customers, places against all 745
districts plus aliases. Reported: top-1 and top-3 accuracy per matcher, and
for the phoneme matcher how often each confidence level is right, which is
what the thresholds in identify/resolve.py are set from.

    python -m eval.matchers            # writes eval/results/matchers.md
"""
import csv
import random
import re
from collections import defaultdict
from pathlib import Path

from identify import resolve
from identify.matchers import MATCHERS
from identify.resolve import _grade, _rank
from identify.result import HIGH, LOW, MEDIUM

ROOT = Path(__file__).resolve().parent.parent
rng = random.Random(7)

with open(ROOT / "data" / "generated" / "customers.csv", encoding="utf-8") as f:
    CUSTOMERS = list(csv.DictReader(f))
NAME_COUNT = defaultdict(int)
for c in CUSTOMERS:
    NAME_COUNT[c["full_name"]] += 1
PEOPLE = [(c["full_name"], c["full_name"]) for c in CUSTOMERS]          # key = name: duplicates are equally right
PLACES = [((d, s), spoken) for spoken, d, s in resolve.place_names()]
DISTRICT_OF = {d: (d, s) for d, s in resolve.districts()}

RULES = [
    (r"aa", "a"), (r"ee", "i"), (r"oo", "u"), (r"i(?!i)", "ee"), (r"u(?!u)", "oo"),
    (r"(?<=[^aeiou])a(?=[^aeiou])", "aa"), (r"v", "w"), (r"w", "v"), (r"sh", "s"),
    (r"th", "t"), (r"(?<!h)t(?!h)", "th"), (r"dh", "d"), (r"ph", "f"), (r"a$", ""),
    (r"([bcdfgjklmnprstvz])$", r"\1a"), (r"ai", "ay"), (r"ay", "ai"), (r"kh", "k"),
    (r"bh", "b"), (r"(.)\1", r"\1"), (r"([lnt])(?!\1)", r"\1\1"), (r"ksh", "x"), (r"z", "j"),
]


def rule_variant(text: str) -> str | None:
    words = text.lower().split()
    out = []
    changed = False
    for w in words:
        for _ in range(rng.choice([1, 1, 2])):
            options = [(p, r) for p, r in RULES if re.search(p, w)]
            if options and rng.random() < 0.8:
                p, r = rng.choice(options)
                new = re.sub(p, r, w, count=1)
                changed |= new != w
                w = new
        out.append(w)
    if not changed:
        return None
    return " ".join(out).title()


def items() -> list[tuple[str, str, str, str]]:
    """(source, kind, heard, expected)"""
    out = []
    with open(ROOT / "eval" / "data" / "handwritten_variants.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            expected = r["expected"]
            if r["kind"] == "place":
                if expected not in DISTRICT_OF:
                    raise SystemExit(f"handwritten place {expected!r} is not a district")
            out.append(("handwritten", r["kind"], r["heard"], expected))
    for c in CUSTOMERS:
        if c["name_native"]:
            out.append(("native", "name", c["name_native"], c["full_name"]))
    for c in rng.sample(CUSTOMERS, 250):
        v = rule_variant(c["full_name"])
        if v:
            out.append(("rules", "name", v, c["full_name"]))
    for d, _ in rng.sample(resolve.districts(), 200):
        v = rule_variant(d)
        if v:
            out.append(("rules", "place", v, d))
    # people who are not customers: the right answer is "no confident match"
    with open(ROOT / "data" / "reference" / "names.csv", encoding="utf-8") as f:
        names = list(csv.DictReader(f))
    firsts = [n["roman"] for n in names if n["kind"].startswith("first")]
    lasts = [n["roman"] for n in names if n["kind"] == "last"]
    absent = set()
    while len(absent) < 200:
        full = f"{rng.choice(firsts)} {rng.choice(lasts)}"
        if full not in NAME_COUNT:
            absent.add(full)
    out += [("absent", "name", n, "") for n in sorted(absent)]
    return out


def ranked(kind: str, heard: str, matcher) -> list[tuple[float, str]]:
    if kind == "name":
        return [(d, key) for d, key, _ in _rank(heard, PEOPLE, matcher, keep=4)]
    best: dict[str, float] = {}
    for d, (district, _), _ in _rank(heard, PLACES, matcher, keep=8):
        best[district] = min(d, best.get(district, float("inf")))
    return sorted(((d, k) for k, d in best.items()), key=lambda x: x[0])


def phoneme_confidence(kind: str, scored: list[tuple[float, str]]) -> str:
    d1 = scored[0][0]
    d2 = next((d for d, k in scored[1:] if k != scored[0][1]), float("inf"))
    if kind == "name":
        return _grade(d1, d2 - d1, resolve.NAME_HIGH, resolve.NAME_MEDIUM, resolve.NAME_HIGH_MARGIN, resolve.NAME_MEDIUM_MARGIN)
    return _grade(d1, d2 - d1, resolve.PLACE_HIGH, resolve.PLACE_MEDIUM, resolve.PLACE_HIGH_MARGIN, resolve.PLACE_MEDIUM_MARGIN)


def main() -> None:
    data = items()
    stats = defaultdict(lambda: [0, 0, 0])                 # (source, kind, matcher) -> [n, top1, top3]
    calib = defaultdict(lambda: [0, 0])                    # (kind, confidence) -> [n, correct]
    misses = []
    absent = defaultdict(int)                              # confidence -> count, for non-customers
    for source, kind, heard, expected in data:
        if source == "absent":
            scored = ranked(kind, heard, MATCHERS["phoneme"])
            conf = phoneme_confidence(kind, scored)
            absent[conf] += 1
            if conf == HIGH:
                misses.append((source, kind, heard, "(not a customer)", [k for _, k in scored[:3]], conf))
            continue
        for name, matcher in MATCHERS.items():
            scored = ranked(kind, heard, matcher)
            keys = [k for _, k in scored]
            # dedupe keys (two customers with the same name count once)
            seen, top = set(), []
            for k in keys:
                if k not in seen:
                    seen.add(k)
                    top.append(k)
            s = stats[(source, kind, name)]
            s[0] += 1
            s[1] += bool(top) and top[0] == expected
            s[2] += expected in top[:3]
            if name == "phoneme" and scored:
                conf = phoneme_confidence(kind, scored)
                calib[(kind, conf)][0] += 1
                calib[(kind, conf)][1] += top[0] == expected
                if top[0] != expected:
                    misses.append((source, kind, heard, expected, top[:3], conf))

    lines = ["# Matcher evaluation", "",
             f"{len(data)} test items. Names are matched against {len(PEOPLE)} customers; "
             f"places against {len(resolve.districts())} districts plus aliases.", "",
             "| Source | Kind | Items | Levenshtein top-1 | Metaphone top-1 | Phoneme top-1 | Phoneme top-3 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for source in ("handwritten", "native", "rules"):
        for kind in ("name", "place"):
            if (source, kind, "phoneme") not in stats:
                continue
            n = stats[(source, kind, "phoneme")][0]

            def pct(m: str, i: int = 1, source=source, kind=kind, n=n) -> str:
                return f"{100 * stats[(source, kind, m)][i] / n:.1f}%"
            lines.append(f"| {source} | {kind} | {n} | {pct('levenshtein')} | {pct('metaphone')} | {pct('phoneme')} | {pct('phoneme', 2)} |")
    lines += ["", "Levenshtein and Metaphone compare letters of the romanised text; for native-script input "
              "they get the same romanisation the phoneme matcher gets.", "",
              "## Phoneme matcher: how often each confidence level is right", "",
              "| Kind | Confidence | Items | Top-1 correct | What the agent does |", "| --- | --- | --- | --- | --- |"]
    action = {HIGH: "accepts", MEDIUM: "reads it back", LOW: "asks again"}
    for kind in ("name", "place"):
        for conf in (HIGH, MEDIUM, LOW):
            n, ok = calib[(kind, conf)]
            if n:
                lines.append(f"| {kind} | {conf} | {n} | {100 * ok / n:.1f}% | {action[conf]} |")
    n_abs = sum(absent.values())
    lines += ["", "## Callers who are not customers", "",
              f"{n_abs} random full names built from the same name lists, none of them a customer. "
              "The right outcome is anything but a confident match.", "",
              "| Phoneme confidence | Items | Meaning |", "| --- | --- | --- |",
              f"| high | {absent[HIGH]} | wrongly accepted as a customer |",
              f"| medium | {absent[MEDIUM]} | read back; the caller must confirm, and DOB/phone still has to match |",
              f"| low | {absent[LOW]} | asked again |"]
    lines += ["", "## Phoneme matcher misses", "", "| Source | Kind | Heard | Expected | Top 3 | Confidence |",
              "| --- | --- | --- | --- | --- | --- |"]
    for source, kind, heard, expected, top, conf in misses:
        lines.append(f"| {source} | {kind} | {heard} | {expected} | {', '.join(top)} | {conf} |")
    out = ROOT / "eval" / "results" / "matchers.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"... full report with {len(misses)} misses: {out}")


if __name__ == "__main__":
    main()
