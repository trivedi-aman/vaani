"""The generated data must be internally consistent, or every test built on it is meaningless."""
import csv
from datetime import date
from pathlib import Path

import pytest
import yaml

from identify import ids, resolve
from scripts.speak import digits, dob

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "generated"
TODAY = date(2026, 10, 18)


def rows(name):
    with open(GEN / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


CUSTOMERS, LOANS, EMIS = rows("customers.csv"), rows("loans.csv"), rows("emi_schedule.csv")


def test_pincode_district_state_agree():
    pins = resolve.pincodes()
    for c in CUSTOMERS:
        assert pins[c["pincode"]] == (c["district"], c["state"]), c["customer_id"]


def test_ids_unique_and_references_valid():
    assert len({c["customer_id"] for c in CUSTOMERS}) == len(CUSTOMERS)
    assert len({c["phone"] for c in CUSTOMERS}) == len(CUSTOMERS)
    assert len({l["loan_id"] for l in LOANS}) == len(LOANS)
    customer_ids = {c["customer_id"] for c in CUSTOMERS}
    branch_codes = {b["branch_code"] for b in rows("branches.csv")}
    for l in LOANS:
        assert l["customer_id"] in customer_ids
        assert l["branch_code"] in branch_codes


def test_only_planted_names_repeat():
    from collections import Counter
    repeated = {n for n, k in Counter(c["full_name"] for c in CUSTOMERS).items() if k > 1}
    assert repeated == {"Priya Sharma"}


def test_active_loans_have_a_future_due_date_and_closed_loans_owe_nothing():
    for l in LOANS:
        if l["stage"] == "Active":
            assert date.fromisoformat(l["next_due_date"]) > TODAY
        if l["stage"] == "Closed":
            assert l["outstanding_principal"] == "0" and l["overdue_amount"] == "0"


def test_internal_notes_never_double_as_customer_messages():
    for l in LOANS:
        if l["internal_note"]:
            assert l["customer_message"] and l["customer_message"] != l["internal_note"]


def test_every_customer_dob_and_phone_survive_being_spoken():
    """Speak each DOB and phone in every tier-1 language, parse it back."""
    for c in CUSTOMERS:
        for lang, style in [("en", "words"), ("hi", "words"), ("hi", "numbers"), ("mr", "words"), ("ta", "words")]:
            assert resolve.dob(dob(c["dob"], lang, style), lang, TODAY).value == c["dob"], (c["customer_id"], lang, style)
        for lang in ("en", "hi", "mr", "ta"):
            assert ids.phone(digits(c["phone"], lang), lang).value == c["phone"], (c["customer_id"], lang)


@pytest.mark.parametrize("path", sorted((ROOT / "data" / "scenarios").glob("*/*.yaml")), ids=lambda p: p.stem)
def test_scenario_points_at_real_records(path):
    s = yaml.safe_load(path.read_text(encoding="utf-8"))
    p = s["persona"]
    if s["line"] == "customer":
        c = next(c for c in CUSTOMERS if c["customer_id"] == p["customer_id"])
        assert (c["full_name"], c["dob"], c["phone"]) == (p["name"], p["dob"], p["phone"])
        assert any(l["loan_id"] == p["loan_id"] and l["customer_id"] == c["customer_id"] for l in LOANS)
    else:
        assert any(st["employee_id"] == p["employee_id"] and st["pin"] == p["pin"] for st in rows("staff.csv"))


def test_every_expected_value_is_recoverable_from_the_callers_words():
    from eval.scenario_entities import check
    failures = []
    for path in sorted((ROOT / "data" / "scenarios").glob("*/*.yaml")):
        s = yaml.safe_load(path.read_text(encoding="utf-8"))
        failures += [(s["id"], kind) for kind, _, _, conf in check(s) if conf not in ("high", "medium")]
    assert failures == []
