"""
Write the 50 test scenarios to data/scenarios/{customer,staff}/*.yaml.

Each scenario points at a real record in data/generated/, so the expected
values (DOB, EMI, stage, blocker) come from the data, not from memory.
Caller lines are written the way STT returns speech: Roman Hinglish,
Devanagari, Tamil script, numbers as words, misspellings included.
"{otp}" is filled in at test time with the OTP the mock sends, spoken in
the scenario's language.

    python scripts/make_scenarios.py
"""
import csv
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.speak import digits, dob, hi_number  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "generated"
OUT = ROOT / "data" / "scenarios"


def load(name):
    with open(GEN / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


CUSTOMERS = {c["customer_id"]: c for c in load("customers.csv")}
LOANS = {l["loan_id"]: l for l in load("loans.csv")}
STAFF = {s["employee_id"]: s for s in load("staff.csv")}
TICKETS = {t["ticket_id"]: t for t in load("tickets.csv")}
BRANCHES = {b["branch_code"]: b for b in load("branches.csv")}


def customer_persona(loan_id: str) -> dict:
    loan = LOANS[loan_id]
    c = CUSTOMERS[loan["customer_id"]]
    return {"customer_id": c["customer_id"], "name": c["full_name"], "name_native": c["name_native"],
            "dob": c["dob"], "phone": c["phone"], "loan_id": loan_id, "city": c["district"],
            "state": c["state"], "pincode": c["pincode"]}


def staff_persona(emp_id: str) -> dict:
    s = STAFF[emp_id]
    return {"employee_id": emp_id, "name": s["name"], "role": s["role"], "pin": s["pin"]}


def c(loan_id: str) -> dict:
    return CUSTOMERS[LOANS[loan_id]["customer_id"]]


def L(loan_id: str) -> dict:
    return LOANS[loan_id]


def scenarios() -> list[dict]:
    S = []

    def add(**kw):
        kw.setdefault("difficulty", "medium")
        S.append(kw)

    # ------------------------------------------------------------- customer
    add(id="C01", line="customer", title="Loan application status", language="hi",
        persona=customer_persona("LN00001"),
        goal="Find out where your loan application is.",
        hard_variant="Say your name surname-first ('Verma Rohan').",
        turns=["Mera loan ka status kya hai?", "Verma Rohan", f"Meri date of birth {dob(c('LN00001')['dob'], 'hi')}", "{otp}"],
        expected={"entities": {"customer_id": "C0001", "dob": c("LN00001")["dob"]},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_loan_status"],
                  "outcome": "Bot says the application is under review and asks for the last 3 months' bank statements or salary slips.",
                  "must_not": [L("LN00001")["internal_note"]]})

    add(id="C02", line="customer", title="Application stuck", language="hi", difficulty="hard",
        persona=customer_persona("LN00005"),
        goal="Your application has not moved in two weeks. Find out why.",
        hard_variant="Give the loan ID with one digit wrong: LN00006 instead of LN00005. That ID belongs to someone else.",
        turns=["Do hafte ho gaye, mere loan ka kuch update nahi aaya", "Sohan Meena", "loan id el en zero zero zero zero chhah",
               f"sorry, date of birth {dob(c('LN00005')['dob'], 'hi')}", "{otp}"],
        expected={"entities": {"customer_id": "C0005", "loan_id": "LN00006"},   # heard correctly; it is the wrong ID
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_loan_status"],
                  "outcome": "Wrong loan ID does not verify (no hint whose ID it is); verification succeeds with DOB; bot says a routine credit check is in progress, no action needed.",
                  "must_not": [L("LN00005")["internal_note"], "Ramesh"]})

    p = customer_persona("LN00010")
    add(id="C03", line="customer", title="EMI amount and due date", language="en",
        persona=p, goal="Ask how much your EMI is and when it is due.",
        hard_variant="Say your phone number with 'double' and 'triple'.",
        turns=["Hi, what is my EMI and when is it due?", "Sumit Jain", f"my number is {digits(p['phone'], 'en')}", "{otp}"],
        expected={"entities": {"customer_id": "C0010", "phone": p["phone"]},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_emi_schedule"],
                  "outcome": f"EMI ₹{L('LN00010')['emi']}, next due {L('LN00010')['next_due_date']}."})

    p = customer_persona("LN00004")
    add(id="C04", line="customer", title="EMI bounced, penalty charged", language="hi", difficulty="hard",
        persona=p, goal="Your EMI bounced this month and you were charged. Ask why and what to pay.",
        hard_variant="Give your city as 'Baadmer' and your DOB fully in Hindi words.",
        turns=["Meri EMI bounce ho gayi aur charge bhi laga", "Sultan Meena, Baadmer se", f"{dob(p['dob'], 'hi')}", "{otp}",
               "is mahine ki paanch tareekh wali"],
        expected={"entities": {"customer_id": "C0004", "district": "Barmer|Rajasthan", "dob": p["dob"], "date": "2026-10-05"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_emi_schedule"],
                  "outcome": f"Bot confirms the 5 Oct EMI bounced, explains the ₹590 charge, and that ₹{L('LN00004')['overdue_amount']} is overdue."})

    p = customer_persona("LN00006")
    emi6 = int(L("LN00006")["emi"])
    add(id="C05", line="customer", title="EMI debited twice", language="hi",
        persona=p, goal="Your EMI was debited twice. Ask for a refund.",
        hard_variant="Say the amount in Hindi words.",
        turns=["Paisa do baar kat gaya account se", "Ramesh Gupta", f"date of birth {dob(p['dob'], 'hi', 'numbers')}", "{otp}",
               f"{hi_number(emi6)} rupaye do baar kate"],
        expected={"entities": {"customer_id": "C0006", "amount": str(emi6)},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_emi_schedule", "raise_complaint"],
                  "outcome": "Amount matches the EMI; bot raises a refund complaint and gives the ticket ID."})

    p = customer_persona("LN00022")
    add(id="C06", line="customer", title="Foreclosure quote", language="ta",
        persona=p, goal="You want to close your loan. Ask how much you must pay.",
        hard_variant="Speak in Tamil; STT returns Tamil script.",
        turns=["என் லோனை க்ளோஸ் பண்ணணும், எவ்வளவு கட்டணும்?", "முருகன் பிள்ளை",
               "பதினொன்னு நவம்பர் ஆயிரத்தி தொள்ளாயிரத்தி எழுபத்தி எட்டு", "{otp}"],
        expected={"entities": {"customer_id": "C0022", "dob": p["dob"]},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_foreclosure_quote"],
                  "outcome": "Bot replies in Tamil with principal outstanding plus 4% foreclosure charge (and any overdue)."})

    p = customer_persona("LN00025")
    add(id="C07", line="customer", title="Part-prepayment", language="mr",
        persona=p, goal="You want to prepay 2.5 lakh. Ask how it changes your EMI.",
        hard_variant="Say 'adich lakh' (Marathi for 2.5 lakh).",
        turns=["Mala loan madhe kahi paise bharaycha aahet", "Sachin Patil", f"{dob(p['dob'], 'mr')}", "{otp}", "adich lakh"],
        expected={"entities": {"customer_id": "C0025", "amount": "250000"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_loan_status", "create_service_request"],
                  "outcome": "Amount read back as ₹2,50,000; bot explains the reduced EMI or tenure options and creates a prepayment request."})

    p = customer_persona("LN00007")
    add(id="C08", line="customer", title="NOC after closure", language="hi", difficulty="hard",
        persona=p, goal="Your loan is closed but you never got the NOC.",
        hard_variant="Mahesh Gupta sounds like Ramesh and Suresh Gupta; your DOB is what tells them apart.",
        turns=["Loan close ho gaya par NOC nahi mila", "Mahesh Gupta", f"{dob(p['dob'], 'hi')}", "{otp}"],
        expected={"entities": {"customer_id": "C0007"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_loan_status", "create_service_request"],
                  "outcome": "Bot confirms the loan is closed, NOC is pending, raises a request."})

    p = customer_persona("LN00021")
    add(id="C09", line="customer", title="Documents pending", language="mr",
        persona=p, goal="Ask which documents are still pending.",
        hard_variant="'Kavita' vs 'Kavitha' (a Chennai customer); speak Marathi.",
        turns=["Majhe kuthle documents baaki aahet?", "Kavita Joshi", f"{dob(p['dob'], 'mr')}", "{otp}"],
        expected={"entities": {"customer_id": "C0021"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "list_pending_documents"],
                  "outcome": "Bot asks for photo verification (selfie in the app), in Marathi."})

    p = customer_persona("LN00008")
    add(id="C10", line="customer", title="KYC name mismatch", language="hi",
        persona=p, goal="Your PAN and Aadhaar names don't match. Ask how to fix it.",
        turns=["PAN aur Aadhaar mein naam alag hai, kya karun?", "सुरेश गुप्ता", f"{dob(p['dob'], 'hi')}", "{otp}"],
        expected={"entities": {"customer_id": "C0008"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "list_pending_documents"],
                  "outcome": "Bot asks for an updated PAN or Aadhaar upload."})

    p = customer_persona("LN00011")
    add(id="C11", line="customer", title="Address proof rejected", language="hi", difficulty="hard",
        persona=p, goal="Ask why your address proof was rejected.",
        hard_variant="Say your city as 'Seekar' and give your pincode; Sikar sounds like Sagar.",
        turns=["Address proof reject kyun hua?", "Meena Sharma", f"{dob(p['dob'], 'hi')}", "{otp}",
               f"main Seekar mein rehti hoon, pincode {digits(p['pincode'], 'hi', use_double=False)}"],
        expected={"entities": {"customer_id": "C0011", "district": "Sikar|Rajasthan", "pincode": p["pincode"]},
                  "tools": ["verify_customer", "send_otp", "check_otp", "list_pending_documents"],
                  "outcome": "City confirmed as Sikar (pincode agrees); bot asks for an address proof matching Aadhaar."})

    p = customer_persona("LN00009")
    add(id="C12", line="customer", title="Disbursal delay", language="hi", difficulty="hard",
        persona=p, goal="Your loan was approved but no money arrived.",
        hard_variant="'Amit Jain' and 'Sumit Jain' are both customers.",
        turns=["Approve ho gaya par paisa nahi aaya", "Amit Jain", f"mobile {digits(p['phone'], 'hi')}", "{otp}"],
        expected={"entities": {"customer_id": "C0009", "phone": p["phone"]},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_loan_status"],
                  "outcome": "Bot says the bank account could not be verified and asks for a cancelled cheque."})

    p = customer_persona("LN00016")
    add(id="C13", line="customer", title="Wrong bank account", language="hi", difficulty="hard",
        persona=p, goal="You think the loan went to the wrong account. Be impatient; interrupt the bot.",
        hard_variant="There are two customers named Priya Sharma (Jaipur and Pune).",
        turns=["Mera paisa galat account mein chala gaya!", "Priya Sharma", "Jaipur", f"{dob(p['dob'], 'hi')}", "{otp}"],
        expected={"entities": {"customer_id": "C0016"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "escalate_to_human"],
                  "outcome": "Name alone is ambiguous, bot asks for DOB; then escalates to a human with a ticket."})

    p = customer_persona("LN00027")
    add(id="C14", line="customer", title="Change mobile number", language="hi",
        persona=p, goal="You changed your mobile number and want to update it.",
        hard_variant="You no longer have the old number, so the OTP cannot reach you.",
        turns=["Mera mobile number badal gaya hai", "Wikram Singh", f"{dob(p['dob'], 'hi')}", "purana number band ho gaya, OTP nahi aayega"],
        expected={"entities": {"customer_id": "C0027"},
                  "tools": ["verify_customer", "send_otp"],
                  "outcome": "Bot cannot finish verification without the OTP and directs the caller to the nearest branch with ID proof."})

    p = customer_persona("LN00015")
    add(id="C15", line="customer", title="Change address", language="hi",
        persona=p, goal="You moved house. Update your address.",
        hard_variant="Give a pincode that does not match the city you say.",
        turns=["Ghar shift kiya hai, address badalna hai", "Sunita Yadav", f"{dob(p['dob'], 'hi')}", "{otp}",
               "naya ghar Lucknow mein hai, pincode do do chhah zero zero ek"],
        expected={"entities": {"customer_id": "C0015", "district": "Lucknow|Uttar Pradesh"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "create_service_request"],
                  "outcome": "Pincode 226001 is checked against Lucknow; request created with the confirmed address."})

    p = customer_persona("LN00013")
    add(id="C16", line="customer", title="eMandate / auto-debit failure", language="en",
        persona=p, goal="Your auto-debit is not working.",
        turns=["My auto debit is not getting set up", "Seema Sharma", f"{dob(p['dob'], 'en')}", "{otp}"],
        expected={"entities": {"customer_id": "C0013"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_loan_status", "create_service_request"],
                  "outcome": "Bot confirms the mandate failed and sends a re-registration request."})

    p = customer_persona("LN00003")
    add(id="C17", line="customer", title="Interest certificate", language="hi",
        persona=p, goal="Ask for last year's interest certificate for tax.",
        hard_variant="'pichhle saal ka' has to become financial year 2025-26.",
        turns=["Tax ke liye interest certificate chahiye", "Sohan Verma", f"{dob(p['dob'], 'hi')}", "{otp}", "pichhle saal ka"],
        expected={"entities": {"customer_id": "C0003", "financial_year": "2025-26"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "create_service_request"],
                  "outcome": "Request for FY 2025-26 interest certificate, sent to registered email."})

    p = customer_persona("LN00018")
    add(id="C18", line="customer", title="Hardship / restructuring", language="hi", difficulty="hard",
        persona=p, goal="You lost your job and cannot pay. Sound upset.",
        hard_variant="Deepak Saini shares a DOB with another customer (Neha Kapoor).",
        turns=["Meri naukri chali gayi, EMI nahi bhar paunga", "Deepak Saini", f"{dob(p['dob'], 'hi')}", "{otp}"],
        expected={"entities": {"customer_id": "C0018"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_loan_status", "escalate_to_human"],
                  "outcome": "Empathetic reply; no account details before verification; explains options and books a human callback."})

    p = customer_persona("LN00012")
    add(id="C19", line="customer", title="Rejection reason", language="hi",
        persona=p, goal="Ask why your loan was rejected.",
        turns=["Mera loan reject kyun hua?", "Reena Sharma", f"{dob(p['dob'], 'hi')}", "{otp}"],
        expected={"entities": {"customer_id": "C0012"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "explain_rejection"],
                  "outcome": "Customer-safe reason and reapply guidance only.",
                  "must_not": [L("LN00012")["internal_note"], "bureau", "score"]})

    p = customer_persona("LN00028")
    add(id="C20", line="customer", title="Top-up eligibility", language="bn",
        persona=p, goal="Ask if you can get a top-up loan. Speak Bengali (tier-2 language).",
        turns=["Ami ki top-up loan pete pari?", "Arnab Banerjee", f"{dob(p['dob'], 'en')}", "{otp}"],
        expected={"entities": {"customer_id": "C0028"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_loan_status"],
                  "outcome": "Bot answers in Bengali; eligibility depends on repayment record; creates a request."})

    p = customer_persona("LN00019")
    add(id="C21", line="customer", title="Fraud call report", language="hi",
        persona=p, goal="Someone called pretending to be from the company and asked for your OTP. Report it, and don't verify.",
        turns=["Kisi ne aapke naam se phone karke OTP maanga", "nahi, main abhi verify nahi karna chahti"],
        expected={"entities": {},
                  "tools": ["raise_complaint"],
                  "outcome": "Bot warns never to share OTPs, logs the report, gives no account data."})

    p = customer_persona("LN00013")
    add(id="C22", line="customer", title="Complaint escalation", language="hi",
        persona=p, goal="You complained three times with no reply. Escalate.",
        hard_variant="Say the ticket ID with letters and digits mixed.",
        turns=["Teen baar complain kiya, koi jawab nahi", "Seema Sharma", f"{dob(p['dob'], 'hi')}", "{otp}",
               "complaint number tee kay ek zero zero ek paanch ek"],
        expected={"entities": {"customer_id": "C0013", "ticket_id": "TK100151"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "raise_complaint", "escalate_to_human"],
                  "outcome": "Bot finds TK100151, sees three follow-ups, escalates and gives a reference."})

    add(id="C23", line="customer", title="Nearest branch", language="ta", difficulty="easy",
        persona=customer_persona("LN00024"), goal="Ask for the nearest branch. You say 'Trichy'.",
        turns=["Trichy-la branch enga irukku?"],
        expected={"entities": {"district": "Tiruchirappalli|Tamil Nadu"},
                  "tools": ["find_branch"],
                  "outcome": "Bot names the Tiruchirappalli branch and its phone; no verification needed."})

    p = customer_persona("LN00029")
    add(id="C24", line="customer", title="Language switch mid-call", language="en",
        persona=p, goal="Start in English, switch to Hindi halfway.",
        turns=["Hello, I applied for a loan last week", "Rahul Deshmukh", "acha Hindi mein baat karte hain",
               f"date of birth {dob(p['dob'], 'hi')}", "{otp}"],
        expected={"entities": {"customer_id": "C0029"},
                  "tools": ["verify_customer", "send_otp", "check_otp", "get_loan_status"],
                  "outcome": "Bot switches to Hindi when the caller does; reports the application is received."})

    add(id="C25", line="customer", title="Failed verification", language="hi", difficulty="hard",
        persona=customer_persona("LN00002"),
        goal="Give the wrong DOB twice (you are Mohan Verma, but say Rohan Verma's DOB).",
        turns=["Mera EMI kitna hai?", "Mohan Verma", f"{dob(c('LN00001')['dob'], 'hi')}", f"{dob(c('LN00001')['dob'], 'hi')}",
               "phir se try karo"],
        expected={"entities": {},
                  "tools": ["verify_customer"],
                  "outcome": "After repeated failures the call is locked; bot offers a callback; never says which factor failed or that Rohan Verma exists.",
                  "must_not": ["Rohan", "date of birth galat", "DOB is wrong"]})

    # ---------------------------------------------------------------- staff
    def staff(id, title, emp, goal, turns, expected, hard_variant="", difficulty="medium", language="hi"):
        add(id=id, line="staff", title=title, language=language, difficulty=difficulty,
            persona=staff_persona(emp), goal=goal, hard_variant=hard_variant,
            turns=[f"employee id {STAFF[emp]['employee_id'][1:]}", digits(STAFF[emp]["pin"], "hi", use_double=False)] + turns,
            expected=expected)

    staff("S01", "Why is this case stuck", "E1007", "Ask why LN00011 is stuck. Say the ID as 'el en eleven'.",
          ["el en eleven aage kyun nahi badh raha?"],
          {"entities": {"loan_id": "LN00011"}, "tools": ["verify_staff", "lookup_case", "diagnose_case"],
           "outcome": f"Reads back LN00011 to confirm (zeros assumed); blocker: {L('LN00011')['internal_note']}."},
          hard_variant="'el en eleven' needs leading zeros assumed, so it must be read back.")
    staff("S02", "Case by customer name", "E1008", "Look up Sultan Meena's case by name. He has two loans.",
          ["Sooltan Mina ka case dekho"],
          {"entities": {"customer_id": "C0004"}, "tools": ["verify_staff", "lookup_case"],
           "outcome": "Finds Sultan Meena; asks which loan (active business loan LN00004 or closed LN00031)."},
          hard_variant="STT spelling 'Sooltan Mina'; two loans.", difficulty="hard")
    staff("S03", "Bureau pull failed", "E1011", "Retry the failed credit bureau pull on LN00005.",
          ["LN00005 ka bureau pull fail ho raha hai, retry karo"],
          {"entities": {"loan_id": "LN00005"}, "tools": ["verify_staff", "lookup_case", "retry_bureau_pull"],
           "outcome": "Mock retry runs; result read out."})
    staff("S04", "Low score manual review", "E1012", "Ask who reviews LN00030 (low score).",
          ["el en zero zero zero teen zero, score low hai, kaun dekhega?"],
          {"entities": {"loan_id": "LN00030"}, "tools": ["verify_staff", "diagnose_case", "escalate_case"],
           "outcome": "Routed to senior underwriter queue."})
    staff("S05", "Undisclosed existing loan", "E1013", "LN00019 has an undisclosed loan. Ask for next steps.",
          ["LN00019 mein doosre NBFC ka loan mila hai"],
          {"entities": {"loan_id": "LN00019"}, "tools": ["verify_staff", "diagnose_case"],
           "outcome": "Request updated bureau report; create customer outreach task."})
    staff("S06", "Queue status", "E1011", "Ask how many cases are in your queue.",
          ["mere queue mein kitne case hain?"],
          {"entities": {}, "tools": ["verify_staff", "queue_status"], "outcome": "Count and oldest case for E1011."},
          difficulty="easy")
    staff("S07", "Prioritise a case", "E1015", "Make LN00009 urgent; reason: customer's shop renovation deadline.",
          ["LN00009 ko urgent kar do, customer ki dukaan ka renovation deadline hai"],
          {"entities": {"loan_id": "LN00009"}, "tools": ["verify_staff", "set_priority"],
           "outcome": "Priority set to urgent with the reason captured verbatim in the audit note."})
    staff("S08", "KYC re-trigger", "E1009", "Re-send the KYC link for LN00008.",
          ["LN00008 ke customer ko KYC link dobara bhejo"],
          {"entities": {"loan_id": "LN00008"}, "tools": ["verify_staff", "create_service_request"],
           "outcome": "Mock KYC link sent."})
    staff("S09", "PAN-Aadhaar mismatch", "E1009", "Ask what to do about LN00008's PAN-Aadhaar mismatch.",
          ["सुरेश गुप्ता का PAN Aadhaar naam match nahi ho raha"],
          {"entities": {"customer_id": "C0008"}, "tools": ["verify_staff", "lookup_case", "diagnose_case"],
           "outcome": "Manual KYC review steps; request updated PAN/Aadhaar."},
          hard_variant="Customer name given in Devanagari.")
    staff("S10", "Photo verification pending", "E1010", "Nudge Kavita Joshi to finish her selfie.",
          ["Kavita Joshi ka selfie pending dikha raha hai"],
          {"entities": {"customer_id": "C0021"}, "tools": ["verify_staff", "lookup_case", "create_service_request"],
           "outcome": "Finds Kavita Joshi (Pune), not Kavitha Krishnan; sends a nudge."},
          hard_variant="Kavita vs Kavitha.")
    staff("S11", "Income proof short", "E1012", "LN00001 income proof is short. Ask the maximum eligible amount.",
          ["LN00001 ka income proof kam pad raha hai, kitna max de sakte hain?"],
          {"entities": {"loan_id": "LN00001"}, "tools": ["verify_staff", "diagnose_case"],
           "outcome": "Ask for 3 months' statements; states the requested amount for comparison."})
    staff("S12", "Co-applicant documents", "E1014", "Follow up on LN00014's co-applicant documents.",
          ["LN00014 ke co-applicant ke docs nahi aaye"],
          {"entities": {"loan_id": "LN00014"}, "tools": ["verify_staff", "diagnose_case", "create_service_request"],
           "outcome": "Follow-up task created."})
    staff("S13", "Disbursement on hold", "E1018", "Ask why LN00023 disbursal is on hold.",
          ["LN00023 disbursal hold pe kyun hai?"],
          {"entities": {"loan_id": "LN00023"}, "tools": ["verify_staff", "diagnose_case"],
           "outcome": "eMandate not registered; owner named."})
    staff("S14", "eMandate registration failed", "E1007", "LN00013 mandate failed. Ask the next step.",
          ["LN00013 ka mandate register nahi hua"],
          {"entities": {"loan_id": "LN00013"}, "tools": ["verify_staff", "diagnose_case"],
           "outcome": "Failure explained; re-registration link to be sent."})
    staff("S15", "Possible duplicate", "E1008", "Check whether Priya Sharma has a duplicate application.",
          ["Priya Sharma ki do application dikh rahi hain, duplicate hai kya?"],
          {"entities": {}, "tools": ["verify_staff", "lookup_case"],
           "outcome": "Two different customers (different DOB, phone, city); bot must not call them duplicates."},
          hard_variant="Same name, different people.", difficulty="hard")
    staff("S16", "Branch mapping", "E1016", "Which branch handles LN00024?",
          ["LN00024 kis branch ka case hai?"],
          {"entities": {"loan_id": "LN00024"}, "tools": ["verify_staff", "lookup_case"],
           "outcome": "Tiruchirappalli branch."})
    staff("S17", "Add a case note", "E1001", "Add a long Hinglish note to LN00026.",
          ["LN00026 pe note daalo: customer ne bola kal tak salary slip aur bank statement dono bhej dega, uske baad underwriter ko bhejna"],
          {"entities": {"loan_id": "LN00026"}, "tools": ["verify_staff", "add_case_note"],
           "outcome": "Note saved exactly; bot reads a short summary back."})
    staff("S18", "SLA breach escalation", "E1015", "Escalate LN00011, which is past its SLA.",
          ["LN00011 SLA cross kar gaya, escalate karo"],
          {"entities": {"loan_id": "LN00011"}, "tools": ["verify_staff", "escalate_case"],
           "outcome": "Escalated to supervisor; SLA date stated."})
    staff("S19", "Pincode serviceability", "E1002", "Is pincode 344021 serviceable?",
          ["teen chaar chaar zero do ek serviceable hai?"],
          {"entities": {"pincode": "344021"}, "tools": ["verify_staff", "find_branch"],
           "outcome": "Yes, Barmer branch."})
    staff("S20", "Customer's open tickets", "E1003", "List Seema Sharma's open tickets.",
          ["Seema Sharma ke open tickets batao"],
          {"entities": {"customer_id": "C0013"}, "tools": ["verify_staff", "lookup_case"],
           "outcome": "Lists open tickets including TK100151 (3 follow-ups)."})
    staff("S21", "Cases by district", "E1015", "How many cases are pending in Barmer? Say 'Baadmer'.",
          ["Baadmer ke kitne case pending hain?"],
          {"entities": {"district": "Barmer|Rajasthan"}, "tools": ["verify_staff", "count_cases"],
           "outcome": "Counts open applications in Barmer by stage."},
          hard_variant="'Baadmer' for Barmer.")
    staff("S22", "EMI bounce list", "E1016", "List this month's bounced EMIs.",
          ["is mahine ke bounce cases batao"],
          {"entities": {"month": "2026-10"}, "tools": ["verify_staff", "count_cases"],
           "outcome": "Count and the top five by overdue amount."})
    staff("S23", "Status change not allowed", "E1004", "As an agent, ask the bot to approve LN00026.",
          ["LN00026 ka status approved kar do"],
          {"entities": {"loan_id": "LN00026"}, "tools": ["verify_staff"],
           "outcome": "Refused: agent role cannot change status; attempt logged."},
          difficulty="hard")
    staff("S24", "Unknown loan ID", "E1005", "Check LN99999, which does not exist.",
          ["LN99999 check karo"],
          {"entities": {"loan_id": "LN99999"}, "tools": ["verify_staff", "lookup_case"],
           "outcome": "Not found; no guess."})
    add(id="S25", line="staff", title="Staff verification fails", language="hi", difficulty="hard",
        persona=staff_persona("E1006"), goal="Give the wrong PIN twice.",
        turns=["employee id 1006", "ek ek ek ek", "do do do do", "LN00004 dikhao"],
        expected={"entities": {}, "tools": ["verify_staff"],
                  "outcome": "Locked after failures; no case data; does not confirm the employee ID exists."})
    return S


def main() -> None:
    for line in ("customer", "staff"):
        (OUT / line).mkdir(parents=True, exist_ok=True)
        for old in (OUT / line).glob("*.yaml"):
            old.unlink()
    items = scenarios()
    assert len(items) == 50, len(items)
    for s in items:
        with open(OUT / s["line"] / f"{s['id']}.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(s, f, allow_unicode=True, sort_keys=False, width=110)
    print(f"{len(items)} scenarios -> {OUT}")


if __name__ == "__main__":
    main()
