"""
Can the identification core recover every expected value in every scenario
from the caller's own words?

The agent will extract a span from each caller turn and hand it to a tool.
This check stands in for a perfect extractor: it tries every short span of
every turn and asks whether any of them resolves to the expected value. A
failure here means the core cannot get it right even when the LLM does its
part perfectly.

    python -m eval.scenario_entities
"""
import csv
from datetime import date
from pathlib import Path

import yaml

from identify import ids, resolve
from identify.dates import financial_year
from identify.result import LOW

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 18)

with open(ROOT / "data" / "generated" / "customers.csv", encoding="utf-8") as f:
    CUSTOMERS = list(csv.DictReader(f))
PEOPLE = [(c["customer_id"], c["full_name"]) for c in CUSTOMERS]


def spans(text: str, max_words: int = 9):
    words = text.replace("?", " ").replace(",", " ").split()
    for i in range(len(words)):
        for j in range(i + 1, min(len(words), i + max_words) + 1):
            yield " ".join(words[i:j])


SPAN_WORDS = {"phone": 14, "pincode": 9, "loan_id": 9, "ticket_id": 10, "dob": 9, "amount": 8,
              "date": 8, "customer_id": 3, "district": 3}


def resolver(kind: str, lang: str, persona: dict):
    # Customers verify with name + DOB/phone, so the name is matched among
    # customers who share the caller's DOB, as the verify tool does. Staff
    # look customers up by name alone.
    narrowed = [(c["customer_id"], c["full_name"]) for c in CUSTOMERS if c["dob"] == persona.get("dob")] or PEOPLE
    return {
        "customer_id": lambda s: resolve.name(s, narrowed if "dob" in persona else PEOPLE),
        "dob": lambda s: resolve.dob(s, lang, TODAY),
        "phone": lambda s: ids.phone(s, lang),
        "loan_id": lambda s: ids.loan_id(s, lang),
        "ticket_id": lambda s: ids.ticket_id(s, lang),
        "district": lambda s: resolve.district(s),
        "pincode": lambda s: resolve.pincode(s, lang),
        "amount": lambda s: resolve.amount(s, lang),
        "date": lambda s: resolve.event_date(s, TODAY, lang, tense="past"),
    }.get(kind)


def check(scenario: dict) -> list[tuple[str, str, str, str]]:
    """[(entity, expected, best span, confidence or 'MISSING')]"""
    out = []
    lang = scenario["language"]
    for kind, expected in scenario["expected"]["entities"].items():
        best = None
        for turn in scenario["turns"]:
            if kind == "financial_year":
                if financial_year(turn, TODAY) == expected:
                    best = (turn, "high")
                continue
            if kind == "month":
                if expected == f"{TODAY:%Y-%m}" and ("is mahine" in turn or "this month" in turn):
                    best = (turn, "high")
                continue
            fn = resolver(kind, lang, scenario["persona"])
            for span in spans(turn, SPAN_WORDS.get(kind, 9)):
                r = fn(span)
                if r.value == expected:
                    rank = {"high": 2, "medium": 1, LOW: 0}[r.confidence]
                    if best is None or rank > {"high": 2, "medium": 1, LOW: 0}[best[1]]:
                        best = (span, r.confidence)
        out.append((kind, str(expected), best[0] if best else "", best[1] if best else "MISSING"))
    return out


def main() -> None:
    files = sorted((ROOT / "data" / "scenarios").glob("*/*.yaml"))
    missing = 0
    for path in files:
        s = yaml.safe_load(path.read_text(encoding="utf-8"))
        for kind, expected, span, conf in check(s):
            flag = "" if conf in ("high", "medium") else "  <--"
            missing += conf in ("MISSING", LOW)
            print(f"{s['id']:4} {kind:15} {expected:22} {conf:8} {span!r}{flag}")
    print(f"\n{missing} expected values not recoverable with medium or high confidence")


if __name__ == "__main__":
    main()
