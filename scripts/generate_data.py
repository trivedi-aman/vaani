"""
Generate the synthetic NBFC dataset in data/generated/.

Every record is fake, but the parts that matter for identification are
real: names from data/reference/names.csv, pincodes, districts and states
from India Post. Pincode, district and state always agree with each other.

A set of planted records sits on top of the random ones. They exist to make
matching hard on purpose (sound-alike names, shared DOBs, same name in two
cities, districts that sound alike) and to give every scenario a record to
point at. Planted customers get the first IDs so scenarios stay stable.

    python scripts/generate_data.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

from indic_transliteration import sanscript

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"
OUT = ROOT / "data" / "generated"
AS_OF = date(2026, 10, 18)          # the "today" the data is consistent with
rng = random.Random(20261018)

# ---- reference data ----------------------------------------------------------

with open(REF / "names.csv", encoding="utf-8") as f:
    NAMES = list(csv.DictReader(f))
with open(REF / "pincodes.csv", encoding="utf-8") as f:
    PINCODES = list(csv.DictReader(f))
PINS_BY_DISTRICT: dict[tuple[str, str], list[str]] = {}
for r in PINCODES:
    PINS_BY_DISTRICT.setdefault((r["district"], r["state"]), []).append(r["pincode"])

STATE_REGION = {
    "Rajasthan": "north", "Uttar Pradesh": "north", "Madhya Pradesh": "north", "Delhi": "north",
    "Bihar": "north", "Haryana": "north", "Punjab": "north", "Uttarakhand": "north", "Jharkhand": "north",
    "Chhattisgarh": "north", "Himachal Pradesh": "north",
    "Maharashtra": "west", "Gujarat": "west", "Goa": "west",
    "Tamil Nadu": "south", "Kerala": "south", "Karnataka": "south", "Andhra Pradesh": "south", "Telangana": "south",
    "West Bengal": "east", "Odisha": "east", "Assam": "east",
}
STATE_WEIGHTS = {
    "Rajasthan": 14, "Uttar Pradesh": 14, "Maharashtra": 14, "Tamil Nadu": 12, "Madhya Pradesh": 8,
    "Delhi": 6, "Gujarat": 6, "Karnataka": 6, "Bihar": 5, "West Bengal": 5, "Telangana": 4, "Haryana": 4,
    "Kerala": 2,
}
# preferred language by state; tier-1 languages are hi, mr, ta, en (spec, Scope)
STATE_LANG = {
    "Maharashtra": "mr", "Tamil Nadu": "ta", "Karnataka": "en", "Kerala": "en", "Telangana": "te",
    "West Bengal": "bn", "Gujarat": "hi", "Andhra Pradesh": "te",
}
DEVANAGARI_STATES = {s for s, r in STATE_REGION.items() if r == "north"} | {"Maharashtra", "Gujarat"}


def native_name(first: dict, last: dict, state: str) -> str:
    if state == "Tamil Nadu":
        if first["tamil"] and last["tamil"]:
            return f"{first['tamil']} {last['tamil']}"
        return ""
    if state in DEVANAGARI_STATES:
        return " ".join(sanscript.transliterate(n["itrans"], sanscript.ITRANS, sanscript.DEVANAGARI) for n in (first, last))
    return ""


def pick_name(kind: str, region: str, need_tamil: bool = False) -> dict:
    pool = [n for n in NAMES if n["kind"] == kind and n["region"] in (region, "all")]
    if need_tamil:
        pool = [n for n in pool if n["tamil"]]
    return rng.choice(pool)


def by_roman(roman: str, kind: str) -> dict:
    return next(n for n in NAMES if n["roman"] == roman and n["kind"] == kind)


def random_dob() -> date:
    return date(rng.randint(1966, 2003), rng.randint(1, 12), rng.randint(1, 28))


def random_phone(used: set) -> str:
    while True:
        p = rng.choice("6789") + "".join(rng.choice("0123456789") for _ in range(9))
        if p not in used:
            used.add(p)
            return p


def pin_in(district: str, state: str) -> str:
    return rng.choice(PINS_BY_DISTRICT[(district, state)])


def random_place() -> tuple[str, str, str]:
    state = rng.choices(list(STATE_WEIGHTS), weights=list(STATE_WEIGHTS.values()))[0]
    district = rng.choice([d for d, s in PINS_BY_DISTRICT if s == state])
    return pin_in(district, state), district, state


# ---- planted customers ---------------------------------------------------------
# (first, last, gender, dob, district, state, language, why)

PLANTED = [
    ("Rohan", "Verma", "M", "1991-03-14", "Jaipur", "Rajasthan", "hi", "sound-alike: Mohan/Sohan Verma"),
    ("Mohan", "Verma", "M", "1984-11-02", "Jaipur", "Rajasthan", "hi", "sound-alike: Rohan/Sohan Verma"),
    ("Sohan", "Verma", "M", "1979-07-21", "Lucknow", "Uttar Pradesh", "hi", "sound-alike: Rohan/Mohan Verma"),
    ("Sultan", "Meena", "M", "1987-04-23", "Barmer", "Rajasthan", "hi", "Barmer/Baadmer; DOB said many ways"),
    ("Sohan", "Meena", "M", "1990-09-09", "Dausa", "Rajasthan", "hi", "close to Sultan Meena"),
    ("Ramesh", "Gupta", "M", "1975-01-30", "Kanpur Nagar", "Uttar Pradesh", "hi", "sound-alike: Mahesh/Suresh Gupta"),
    ("Mahesh", "Gupta", "M", "1982-06-18", "Agra", "Uttar Pradesh", "hi", "sound-alike: Ramesh/Suresh Gupta"),
    ("Suresh", "Gupta", "M", "1988-12-05", "Bhopal", "Madhya Pradesh", "hi", "sound-alike: Ramesh/Mahesh Gupta"),
    ("Amit", "Jain", "M", "1993-08-27", "Indore", "Madhya Pradesh", "hi", "sound-alike: Sumit Jain"),
    ("Sumit", "Jain", "M", "1995-02-11", "Udaipur", "Rajasthan", "hi", "sound-alike: Amit Jain"),
    ("Meena", "Sharma", "F", "1986-05-19", "Sikar", "Rajasthan", "hi", "sound-alike: Reena/Seema Sharma"),
    ("Reena", "Sharma", "F", "1989-10-03", "Sagar", "Madhya Pradesh", "hi", "sound-alike; Sagar/Sikar"),
    ("Seema", "Sharma", "F", "1992-12-24", "New Delhi", "Delhi", "hi", "sound-alike: Meena/Reena Sharma"),
    ("Anita", "Yadav", "F", "1983-03-08", "Patna", "Bihar", "hi", "sound-alike: Sunita Yadav"),
    ("Sunita", "Yadav", "F", "1980-07-15", "Varanasi", "Uttar Pradesh", "hi", "sound-alike: Anita Yadav"),
    ("Priya", "Sharma", "F", "1994-06-02", "Jaipur", "Rajasthan", "hi", "same name, two cities"),
    ("Priya", "Sharma", "F", "1997-01-26", "Pune", "Maharashtra", "mr", "same name, two cities"),
    ("Deepak", "Saini", "M", "1990-05-14", "Gurugram", "Haryana", "hi", "same DOB as Neha Kapoor"),
    ("Neha", "Kapoor", "F", "1990-05-14", "New Delhi", "Delhi", "hi", "same DOB as Deepak Saini"),
    ("Kavitha", "Krishnan", "F", "1985-09-17", "Chennai", "Tamil Nadu", "ta", "Kavitha/Kavita"),
    ("Kavita", "Joshi", "F", "1987-02-28", "Pune", "Maharashtra", "mr", "Kavita/Kavitha"),
    ("Murugan", "Pillai", "M", "1978-11-11", "Madurai", "Tamil Nadu", "ta", "Tamil-script name"),
    ("Meenakshi", "Sundaram", "F", "1991-04-04", "Coimbatore", "Tamil Nadu", "ta", "Meenakshi/Minakshi"),
    ("Saravanan", "Natarajan", "M", "1983-08-08", "Tiruchirappalli", "Tamil Nadu", "ta", "Trichy alias"),
    ("Sachin", "Patil", "M", "1989-01-19", "Pune", "Maharashtra", "mr", "Marathi caller"),
    ("Sachin", "Pawar", "M", "1992-03-03", "Nashik", "Maharashtra", "mr", "Patil/Pawar"),
    ("Vikram", "Singh", "M", "1981-12-12", "Jodhpur", "Rajasthan", "hi", "Vikram/Wikram"),
    ("Arnab", "Banerjee", "M", "1986-10-29", "Kolkata", "West Bengal", "bn", "tier-2 language"),
    ("Rahul", "Deshmukh", "M", "1996-07-07", "Mumbai", "Maharashtra", "en", "language switch"),
    ("Bhavna", "Rathore", "F", "1993-09-25", "Barmer", "Rajasthan", "hi", "second Barmer customer"),
]

# ---- loans -------------------------------------------------------------------

PRODUCTS = {
    "Personal Loan": (50_000, 800_000, (12, 24, 36, 48), (13.5, 22.0)),
    "Two-Wheeler Loan": (40_000, 200_000, (12, 18, 24, 36), (10.5, 16.0)),
    "Business Loan": (200_000, 1_500_000, (24, 36, 48, 60), (15.0, 21.0)),
    "Gold Loan": (25_000, 400_000, (6, 12), (9.0, 14.0)),
    "Home Improvement Loan": (100_000, 1_000_000, (24, 36, 60), (11.0, 15.0)),
}

# internal note (staff only) -> what the customer may be told
BLOCKERS = {
    "KYC": [
        ("Address proof does not match Aadhaar address", "Your address proof does not match the address on your Aadhaar. Please upload a matching document in the app."),
        ("PAN and Aadhaar names differ", "The name on your PAN and Aadhaar is different. Please upload an updated PAN or Aadhaar."),
        ("Selfie / photo verification pending", "We still need your photo verification. Please take a selfie in the app."),
    ],
    "Credit_Check": [
        ("Bureau pull failed (timeout), retry needed", "We are completing a routine credit check. No action is needed from you."),
        ("Bureau score below auto-approve band, manual review", "Your application is with our credit team for review."),
        ("Undisclosed existing loan found in bureau report", "We need a little more information about your existing loans. Our team will call you."),
    ],
    "Underwriting": [
        ("Pending manual underwriter review", "Your application is under review by our team."),
        ("Income proof insufficient for requested amount", "Please share your last 3 months' bank statements or salary slips."),
        ("Co-applicant documents pending", "Please upload your co-applicant's KYC documents in the app."),
    ],
    "Disbursal_Hold": [
        ("Penny-drop failed: bank account name mismatch", "We could not verify your bank account. Please share a cancelled cheque."),
        ("eMandate not registered", "Please complete the auto-debit (eMandate) registration using the link we sent you."),
    ],
}
REJECTION = [
    ("Bureau score below policy minimum", "Your application did not meet our credit policy this time. You can apply again after 6 months."),
    ("FOIR above policy limit", "Your current loan repayments are too high compared to your income for this amount. You can apply for a smaller amount."),
    ("Negative pincode as per policy", "We are unable to offer this loan in your area at present."),
]
STAGES = ["Applied", "KYC", "Credit_Check", "Underwriting", "Approved", "Disbursal_Hold", "Active", "Closed", "Rejected"]
STAGE_WEIGHTS = [6, 10, 10, 10, 5, 5, 35, 12, 7]
BOUNCE_CHARGE = 590           # ₹500 + 18% GST
FORECLOSURE_RATE = 0.04       # 4% of principal outstanding


def emi(principal: int, annual_rate: float, months: int) -> int:
    r = annual_rate / 1200
    return round(principal * r * (1 + r) ** months / ((1 + r) ** months - 1))


def schedule(principal: int, rate: float, months: int, first_due: date):
    """Amortisation rows: (n, due_date, emi, principal_part, interest_part, balance_after)."""
    e = emi(principal, rate, months)
    balance = principal
    rows = []
    for n in range(1, months + 1):
        interest = round(balance * rate / 1200)
        principal_part = e - interest if n < months else balance
        balance = max(balance - principal_part, 0)
        y, m = first_due.year + (first_due.month - 1 + n - 1) // 12, (first_due.month - 1 + n - 1) % 12 + 1
        rows.append((n, date(y, m, 5), e if n < months else principal_part + interest, principal_part, interest, balance))
    return rows


# ---- main --------------------------------------------------------------------

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    used_phones: set[str] = set()
    customers = []

    for i, (first, last, gender, dob, district, state, lang, why) in enumerate(PLANTED, start=1):
        f, l = by_roman(first, "first_m" if gender == "M" else "first_f"), by_roman(last, "last")
        customers.append({
            "customer_id": f"C{i:04d}", "full_name": f"{first} {last}", "name_native": native_name(f, l, state),
            "gender": gender, "dob": dob, "phone": random_phone(used_phones),
            "pincode": pin_in(district, state), "district": district, "state": state,
            "language": lang, "planted": why,
        })

    while len(customers) < 300:
        pin, district, state = random_place()
        region = STATE_REGION.get(state, "north")
        gender = rng.choice("MF")
        f = pick_name("first_m" if gender == "M" else "first_f", region, need_tamil=state == "Tamil Nadu")
        l = pick_name("last", region, need_tamil=state == "Tamil Nadu")
        full = f"{f['roman']} {l['roman']}"
        if any(c["full_name"] == full for c in customers):
            continue                                   # duplicates only where planted
        lang = STATE_LANG.get(state, "hi")
        if lang == "hi" and rng.random() < 0.15:
            lang = "en"
        customers.append({
            "customer_id": f"C{len(customers) + 1:04d}", "full_name": full, "name_native": native_name(f, l, state),
            "gender": gender, "dob": random_dob().isoformat(), "phone": random_phone(used_phones),
            "pincode": pin, "district": district, "state": state, "language": lang, "planted": "",
        })

    # branches: one per district that has customers
    districts = sorted({(c["district"], c["state"]) for c in customers}, key=lambda d: (d[1], d[0]))
    branches = []
    for i, (d, s) in enumerate(districts, start=1):
        branches.append({"branch_code": f"BR{i:03d}", "name": f"{d} Branch", "district": d, "state": s,
                         "pincode": pin_in(d, s), "phone": f"1800-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"})
    branch_of = {(b["district"], b["state"]): b["branch_code"] for b in branches}

    staff_names = [("Anjali Mehta", "agent"), ("Rakesh Tiwari", "agent"), ("Farhan Qureshi", "agent"),
                   ("Pooja Kulkarni", "agent"), ("Senthil Kumar", "agent"), ("Divya Nair", "agent"),
                   ("Vinod Rathore", "ops"), ("Shalini Bose", "ops"), ("Karthik Iyer", "ops"),
                   ("Neeraj Saxena", "ops"), ("Ritu Arora", "credit"), ("Prakash Reddy", "credit"),
                   ("Harish Desai", "credit"), ("Usha Pandey", "credit"), ("Manoj Bishnoi", "supervisor"),
                   ("Lakshmi Natarajan", "supervisor"), ("Sagar Jadhav", "agent"), ("Megha Chauhan", "ops"),
                   ("Arun Pillai", "credit"), ("Gaurav Mathur", "supervisor")]
    staff = []
    for i, (n, role) in enumerate(staff_names, start=1):
        staff.append({"employee_id": f"E{1000 + i}", "name": n, "role": role,
                      "branch_code": rng.choice(branches)["branch_code"],
                      "pin": f"{rng.randint(0, 9999):04d}"})
    owners = {role: [s["employee_id"] for s in staff if s["role"] == role] for role in ("agent", "ops", "credit", "supervisor")}

    loans, emis = [], []
    loan_no = 0

    def add_loan(cust: dict, stage: str, product: str | None = None, **overrides) -> dict:
        nonlocal loan_no
        loan_no += 1
        product = product or rng.choice(list(PRODUCTS))
        lo, hi, tenures, (r_lo, r_hi) = PRODUCTS[product]
        amount = round(rng.randint(lo, hi), -3)
        tenure = rng.choice(tenures)
        rate = round(rng.uniform(r_lo, r_hi), 2)
        applied = AS_OF - timedelta(days=rng.randint(5, 40) if stage not in ("Active", "Closed") else rng.randint(200, 900))
        if stage == "Active" and cust["planted"]:
            # scenario loans must still be running today
            tenure = max(tenures)
            applied = AS_OF - timedelta(days=rng.randint(150, 300))
        loan = {
            "loan_id": f"LN{loan_no:05d}", "customer_id": cust["customer_id"], "product": product,
            "amount": amount, "tenure_months": tenure, "interest_rate": rate, "emi": emi(amount, rate, tenure),
            "stage": stage, "applied_on": applied.isoformat(), "internal_note": "", "customer_message": "",
            "disbursed_on": "", "first_due": "", "closed_on": "", "outstanding_principal": "", "next_due_date": "",
            "nach_status": "", "noc_status": "", "bounces": 0, "overdue_amount": 0,
            "branch_code": branch_of[(cust["district"], cust["state"])],
            "assigned_to": "", "priority": "normal",
            "sla_due": (applied + timedelta(days=7)).isoformat(),
        }
        if stage in BLOCKERS:
            loan["internal_note"], loan["customer_message"] = rng.choice(BLOCKERS[stage])
            loan["assigned_to"] = rng.choice(owners["credit"] if stage in ("Credit_Check", "Underwriting") else owners["ops"])
        if stage == "Rejected":
            loan["internal_note"], loan["customer_message"] = rng.choice(REJECTION)
        if stage in ("Active", "Closed"):
            disbursed = applied + timedelta(days=rng.randint(5, 15))
            y, m = (disbursed.year, disbursed.month + 1) if disbursed.month < 12 else (disbursed.year + 1, 1)
            first_due = date(y, m, 5)
            loan.update(disbursed_on=disbursed.isoformat(), first_due=first_due.isoformat(), nach_status="Registered")
        loan.update(overrides)

        if loan["stage"] in ("Active", "Closed"):
            rows = schedule(loan["amount"], loan["interest_rate"], loan["tenure_months"], date.fromisoformat(loan["first_due"]))
            force_bounce = overrides.get("bounces", 0)
            due_rows = [r for r in rows if r[1] <= AS_OF]
            bounce_ns = set(n for n, *_ in due_rows[-force_bounce:]) if force_bounce else set()
            if not force_bounce and loan["stage"] == "Active":
                bounce_ns = {n for n, *_ in due_rows if rng.random() < 0.05}
            outstanding, next_due, overdue = None, None, 0
            if loan["stage"] == "Closed":
                # closed early (foreclosed) or at the end of tenure, some time before today
                closed_on = min(rows[-1][1], AS_OF - timedelta(days=rng.randint(15, 90)))
                rows = [r for r in rows if r[1] <= closed_on] or rows[:1]
                loan["closed_on"] = closed_on.isoformat()
            for n, due, amt, p_part, i_part, bal in rows:
                if loan["stage"] == "Closed":
                    status, paid_on = "paid", due.isoformat()
                elif due > AS_OF:
                    status, paid_on = "upcoming", ""
                    if next_due is None:
                        next_due = due
                        outstanding = bal + p_part
                elif n in bounce_ns:
                    # a bounce in the last cycle is still unpaid; older ones were paid late
                    recent = due >= AS_OF - timedelta(days=31)
                    status, paid_on = ("bounced", "") if recent else ("paid_late", (due + timedelta(days=9)).isoformat())
                    if recent:
                        overdue += amt + BOUNCE_CHARGE
                else:
                    status, paid_on = "paid", due.isoformat()
                emis.append({"loan_id": loan["loan_id"], "installment": n, "due_date": due.isoformat(), "amount": amt,
                             "principal": p_part, "interest": i_part, "balance_after": bal, "status": status,
                             "paid_on": paid_on, "bounce_charge": BOUNCE_CHARGE if n in bounce_ns else 0})
            if loan["stage"] == "Active":
                if next_due is None:          # schedule already finished: it is a closed loan
                    loan["stage"] = "Closed"
                    loan["closed_on"] = rows[-1][1].isoformat()
                else:
                    loan.update(outstanding_principal=outstanding, next_due_date=next_due.isoformat(),
                                bounces=len(bounce_ns), overdue_amount=overdue)
            if loan["stage"] == "Closed":
                loan.update(outstanding_principal=0, next_due_date="", overdue_amount=0,
                            noc_status=overrides.get("noc_status", "Dispatched"))
        loans.append(loan)
        return loan

    cust = {c["full_name"] + "|" + c["district"]: c for c in customers}

    def planted(name_city: str) -> dict:
        return cust[name_city]

    # loans that scenarios rely on (see scripts/make_scenarios.py)
    add_loan(planted("Rohan Verma|Jaipur"), "Underwriting", "Personal Loan",
             internal_note="Income proof insufficient for requested amount",
             customer_message=BLOCKERS["Underwriting"][1][1])
    add_loan(planted("Mohan Verma|Jaipur"), "Active", "Two-Wheeler Loan")
    add_loan(planted("Sohan Verma|Lucknow"), "Active", "Personal Loan")
    add_loan(planted("Sultan Meena|Barmer"), "Active", "Business Loan", bounces=1)
    add_loan(planted("Sohan Meena|Dausa"), "Credit_Check", "Personal Loan",
             internal_note=BLOCKERS["Credit_Check"][0][0], customer_message=BLOCKERS["Credit_Check"][0][1])
    add_loan(planted("Ramesh Gupta|Kanpur Nagar"), "Active", "Home Improvement Loan")
    add_loan(planted("Mahesh Gupta|Agra"), "Closed", "Two-Wheeler Loan", noc_status="Pending")
    add_loan(planted("Suresh Gupta|Bhopal"), "KYC", "Personal Loan",
             internal_note=BLOCKERS["KYC"][1][0], customer_message=BLOCKERS["KYC"][1][1])
    add_loan(planted("Amit Jain|Indore"), "Disbursal_Hold", "Business Loan",
             internal_note=BLOCKERS["Disbursal_Hold"][0][0], customer_message=BLOCKERS["Disbursal_Hold"][0][1])
    add_loan(planted("Sumit Jain|Udaipur"), "Active", "Personal Loan")
    add_loan(planted("Meena Sharma|Sikar"), "KYC", "Gold Loan",
             internal_note=BLOCKERS["KYC"][0][0], customer_message=BLOCKERS["KYC"][0][1])
    add_loan(planted("Reena Sharma|Sagar"), "Rejected", "Personal Loan",
             internal_note=REJECTION[0][0], customer_message=REJECTION[0][1])
    add_loan(planted("Seema Sharma|New Delhi"), "Active", "Personal Loan", nach_status="Failed", bounces=1)
    add_loan(planted("Anita Yadav|Patna"), "Underwriting", "Business Loan",
             internal_note=BLOCKERS["Underwriting"][2][0], customer_message=BLOCKERS["Underwriting"][2][1])
    add_loan(planted("Sunita Yadav|Varanasi"), "Active", "Gold Loan")
    add_loan(planted("Priya Sharma|Jaipur"), "Active", "Personal Loan")
    add_loan(planted("Priya Sharma|Pune"), "Approved", "Two-Wheeler Loan")
    add_loan(planted("Deepak Saini|Gurugram"), "Active", "Personal Loan", bounces=2)
    add_loan(planted("Neha Kapoor|New Delhi"), "Credit_Check", "Personal Loan",
             internal_note=BLOCKERS["Credit_Check"][2][0], customer_message=BLOCKERS["Credit_Check"][2][1])
    add_loan(planted("Kavitha Krishnan|Chennai"), "Active", "Personal Loan")
    add_loan(planted("Kavita Joshi|Pune"), "KYC", "Personal Loan",
             internal_note=BLOCKERS["KYC"][2][0], customer_message=BLOCKERS["KYC"][2][1])
    add_loan(planted("Murugan Pillai|Madurai"), "Active", "Gold Loan")
    add_loan(planted("Meenakshi Sundaram|Coimbatore"), "Disbursal_Hold", "Personal Loan",
             internal_note=BLOCKERS["Disbursal_Hold"][1][0], customer_message=BLOCKERS["Disbursal_Hold"][1][1])
    add_loan(planted("Saravanan Natarajan|Tiruchirappalli"), "Active", "Business Loan")
    add_loan(planted("Sachin Patil|Pune"), "Active", "Home Improvement Loan")
    add_loan(planted("Sachin Pawar|Nashik"), "Underwriting", "Personal Loan",
             internal_note=BLOCKERS["Underwriting"][0][0], customer_message=BLOCKERS["Underwriting"][0][1])
    add_loan(planted("Vikram Singh|Jodhpur"), "Active", "Two-Wheeler Loan")
    add_loan(planted("Arnab Banerjee|Kolkata"), "Active", "Personal Loan")
    add_loan(planted("Rahul Deshmukh|Mumbai"), "Applied", "Personal Loan")
    add_loan(planted("Bhavna Rathore|Barmer"), "Credit_Check", "Gold Loan",
             internal_note=BLOCKERS["Credit_Check"][1][0], customer_message=BLOCKERS["Credit_Check"][1][1])
    # a second, closed loan for Sultan Meena, so "which loan?" can come up
    add_loan(planted("Sultan Meena|Barmer"), "Closed", "Two-Wheeler Loan")

    for c in customers[len(PLANTED):]:
        n = rng.choices([1, 2], weights=[85, 15])[0]
        for _ in range(n):
            add_loan(c, rng.choices(STAGES, weights=STAGE_WEIGHTS)[0])

    # tickets
    ticket_types = [
        ("double_debit", "EMI debited twice"), ("wrong_account", "Disbursed to wrong account"),
        ("noc_pending", "NOC not received after closure"), ("address_change", "Address change request"),
        ("mobile_change", "Mobile number change request"), ("complaint", "Complaint about service"),
        ("refund", "Refund of excess payment"), ("interest_certificate", "Interest certificate request"),
    ]
    tickets = []
    for i in range(1, 151):
        loan = rng.choice(loans)
        t, summary = rng.choice(ticket_types)
        created = AS_OF - timedelta(days=rng.randint(1, 60))
        status = rng.choices(["open", "in_progress", "resolved"], weights=[3, 3, 4])[0]
        tickets.append({"ticket_id": f"TK{100000 + i:06d}", "customer_id": loan["customer_id"], "loan_id": loan["loan_id"],
                        "type": t, "summary": summary, "status": status, "created_on": created.isoformat(),
                        "updated_on": (created + timedelta(days=rng.randint(0, 10))).isoformat(),
                        "follow_ups": rng.randint(0, 3)})
    # planted: an unresolved complaint chased three times (scenario C22)
    tickets.append({"ticket_id": "TK100151", "customer_id": planted("Seema Sharma|New Delhi")["customer_id"],
                    "loan_id": next(l["loan_id"] for l in loans if l["customer_id"] == planted("Seema Sharma|New Delhi")["customer_id"]),
                    "type": "complaint", "summary": "Auto-debit failed, charged bounce fee anyway", "status": "open",
                    "created_on": (AS_OF - timedelta(days=21)).isoformat(), "updated_on": (AS_OF - timedelta(days=20)).isoformat(),
                    "follow_ups": 3})

    write("customers.csv", customers)
    write("loans.csv", loans)
    write("emi_schedule.csv", emis)
    write("tickets.csv", tickets)
    write("staff.csv", staff)
    write("branches.csv", branches)
    print(f"{len(customers)} customers, {len(loans)} loans, {len(emis)} EMI rows, {len(tickets)} tickets, "
          f"{len(staff)} staff, {len(branches)} branches -> {OUT}")


def write(name: str, rows: list[dict]) -> None:
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
