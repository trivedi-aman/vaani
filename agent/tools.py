"""
Tools the agent can call.

Rules every tool follows:

  1. Arguments are what the caller *said* ("teis April unnees sau sattaasi"),
     never values the model worked out. The identification core turns them
     into checked values and reports its confidence.
  2. Who the caller is comes from the CallSession, never from arguments. A
     customer tool only ever reads the verified customer's own loans.
  3. Each tool declares when it is available (before/after verification,
     which staff roles). The agent only sees available tools, and the
     executor checks again before running one.
  4. Customers get customer wording; internal notes exist only in staff tools.
"""
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from core import audit
from core.config import Settings
from core.masking import mask_phone, strip_secrets
from core.session import CallSession
from core.store import Store
from identify import ids, resolve
from identify.dates import financial_year
from identify.result import HIGH, LOW, EntityResult

from .persona import spoken_date

# ---- context and helpers -----------------------------------------------------


class ToolError(Exception):
    """A refusal or problem the agent should explain to the caller."""


@dataclass
class ToolContext:
    session: CallSession
    store: Store
    settings: Settings

    @property
    def today(self) -> date:
        return self.store.today

    @property
    def lang(self) -> str:
        return (self.session.language or "")[:2]

    def entity(self, result: EntityResult, field_name: str) -> dict:
        """Report what was heard and understood to the browser panel; return a compact copy for the model."""
        d = result.to_dict()
        self.session.emit("entity", field=field_name, **d)
        out = {"heard": result.heard, "value": result.value, "confidence": result.confidence, "action": result.action}
        if result.value and result.candidates and result.candidates[0].label not in ("", result.value):
            out["say_as"] = result.candidates[0].label      # "23 April 1987", "₹2,50,000"
        if result.issues:
            out["issues"] = result.issues
        if result.candidates and result.confidence != HIGH:
            out["candidates"] = [c.label for c in result.candidates[:3]]
        return out

    def write(self) -> None:
        if self.session.writes >= self.settings.max_writes_per_call:
            raise ToolError("This call has created as many requests as a demo call may. Please start a new call.")
        self.session.writes += 1


STAGE_FOR_CUSTOMER = {
    "Applied": "application received", "KYC": "KYC verification", "Credit_Check": "credit check",
    "Underwriting": "under review", "Approved": "approved, disbursal being scheduled",
    "Disbursal_Hold": "approved, disbursal on hold", "Active": "active (repaying)",
    "Closed": "closed", "Rejected": "not approved",
}

NEXT_STEPS = {
    "Address proof does not match Aadhaar address": "Ask the customer to re-upload an address proof matching Aadhaar.",
    "PAN and Aadhaar names differ": "Manual KYC review; request an updated PAN or Aadhaar.",
    "Selfie / photo verification pending": "Nudge the customer to take a selfie in the app.",
    "Bureau pull failed (timeout), retry needed": "Retry the bureau pull; escalate if it fails twice.",
    "Bureau score below auto-approve band, manual review": "Route to a senior underwriter for manual risk review.",
    "Undisclosed existing loan found in bureau report": "Request an updated bureau report and call the customer to clarify.",
    "Pending manual underwriter review": "Check the underwriter queue; it may only need prioritising.",
    "Income proof insufficient for requested amount": "Request the last 3 months' bank statements or salary slips.",
    "Co-applicant documents pending": "Follow up with the customer for co-applicant KYC documents.",
    "Penny-drop failed: bank account name mismatch": "Ask for a cancelled cheque and re-run penny drop.",
    "eMandate not registered": "Send the eMandate registration link again.",
}
# The name is a consistency check, not the security gate. Different people
# can sound almost the same (Anil Patel / Anil Patil: 0.35) and the same name
# in Devanagari or Tamil can drift past 3, so no threshold separates them.
# What verifies a caller is the exact identifier (DOB, phone or loan ID) plus
# the OTP sent to the registered mobile.
VERIFY_NAME_MAX = 2.0
MAX_OTPS_PER_CALL = 3            # stops the check being used to flood someone with SMS
OPEN_STAGES = ("Applied", "KYC", "Credit_Check", "Underwriting", "Approved", "Disbursal_Hold")
FORECLOSURE_RATE = 0.04


def rupees(n: float | int | str) -> str:
    n = int(round(float(n or 0)))
    return f"₹{resolve._indian_format(n)}"


def customer_loan_view(loan: dict) -> dict:
    """What a verified customer may hear about their own loan."""
    view = {
        "loan_ref": f"ending {loan['loan_id'][-3:]}", "loan_id": loan["loan_id"], "product": loan["product"],
        "status": STAGE_FOR_CUSTOMER.get(loan["stage"], loan["stage"]), "amount": rupees(loan["amount"]),
        "emi": rupees(loan["emi"]), "tenure_months": int(loan["tenure_months"]),
    }
    if loan["stage"] == "Active":
        view.update(next_due_date=spoken_date(loan["next_due_date"]), outstanding_principal=rupees(loan["outstanding_principal"]),
                    auto_debit=loan["nach_status"].lower() or "not set up")
        if float(loan["overdue_amount"] or 0) > 0:
            view["overdue"] = rupees(loan["overdue_amount"])
    if loan["stage"] == "Closed":
        view.update(closed_on=spoken_date(loan["closed_on"]), noc=loan["noc_status"].lower())
    if loan["customer_message"]:
        view["message_for_customer"] = loan["customer_message"]
    return view


def staff_loan_view(loan: dict, customer: dict) -> dict:
    return {
        "loan_id": loan["loan_id"], "customer": customer["full_name"], "customer_id": customer["customer_id"],
        "city": f"{customer['district']}, {customer['state']}", "dob_year": customer["dob"][:4],
        "phone": mask_phone(customer["phone"]), "product": loan["product"], "amount": rupees(loan["amount"]),
        "stage": loan["stage"], "internal_note": loan["internal_note"] or None, "assigned_to": loan["assigned_to"] or None,
        "priority": loan["priority"], "sla_due": spoken_date(loan["sla_due"]), "branch": loan["branch_code"],
    }


# ---- tool registry -----------------------------------------------------------

Access = Literal["any", "customer_pre", "customer_otp", "customer", "staff_pre", "staff"]


@dataclass
class ToolSpec:
    name: str
    description: str
    args: type[BaseModel]
    handler: Callable[[ToolContext, Any], dict]
    access: Access
    roles: tuple[str, ...] = ()
    writes: bool = False

    def allowed(self, s: CallSession) -> bool:
        if s.ended:
            return False
        if s.locked:
            return self.access == "any"
        if self.access == "any":
            return True
        if s.line == "customer":
            if self.access == "customer_pre":
                return s.customer_id is None
            if self.access == "customer_otp":
                return s.customer_id is None and s.pending_customer_id is not None
            return self.access == "customer" and s.customer_id is not None
        if self.access == "staff_pre":
            return s.staff_id is None
        return self.access == "staff" and s.staff_id is not None and (not self.roles or s.staff_role in self.roles)

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.args.model_json_schema()}}


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, access: Access, roles: tuple[str, ...] = (), writes: bool = False):
    def wrap(fn):
        REGISTRY[name] = ToolSpec(name, (fn.__doc__ or "").strip(), fn.__annotations__["a"], fn, access, roles, writes)
        return fn
    return wrap


def available(session: CallSession) -> list[ToolSpec]:
    return [t for t in REGISTRY.values() if t.allowed(session)]


def execute(ctx: ToolContext, name: str, raw_args: dict) -> dict:
    """Run one tool call: check access, validate arguments, run, audit, report."""
    spec = REGISTRY.get(name)
    s = ctx.session
    started = time.perf_counter()
    if spec is None or not spec.allowed(s):
        result: dict = {"error": "That action is not available right now."}
        outcome = "denied"
    else:
        try:
            args = spec.args.model_validate(raw_args or {})
            if spec.writes:
                ctx.write()
            result = spec.handler(ctx, args)
            outcome = "ok"
        except ValidationError as e:
            result = {"error": "invalid arguments", "details": [err["msg"] for err in e.errors()[:3]]}
            outcome = "invalid"
        except ToolError as e:
            result = {"error": str(e)}
            outcome = "refused"
    ms = round((time.perf_counter() - started) * 1000)
    audit.record(s.id, s.line, s.actor, name, raw_args or {}, outcome, result)
    s.emit("tool", name=name, args=strip_secrets(raw_args or {}), outcome=outcome, result=strip_secrets(result), ms=ms)
    return result


# ---- tools for everyone -----------------------------------------------------


class IdentifyArgs(BaseModel):
    kind: Literal["amount", "date", "pincode", "district", "phone", "financial_year", "loan_id", "ticket_id", "dob"]
    spoken: str = Field(..., max_length=200, description="The caller's exact words for the value")
    tense: Literal["past", "future", ""] = Field("", description="For dates: did it happen (past) or will it (future)?")


@tool("identify_value", "any")
def identify_value(ctx: ToolContext, a: IdentifyArgs) -> dict:
    """Turn a value the caller spoke (amount, date, pincode, city/district, phone, financial year, loan ID, ticket ID, date of birth) into a checked value with a confidence level. Use it to read values back before acting on them."""
    if a.kind == "financial_year":
        fy = financial_year(a.spoken, ctx.today)
        return {"heard": a.spoken, "value": fy, "confidence": HIGH if fy else LOW, "action": "read_back" if fy else "ask_again"}
    fn = {
        "amount": lambda: resolve.amount(a.spoken, ctx.lang),
        "date": lambda: resolve.event_date(a.spoken, ctx.today, ctx.lang, a.tense),
        "pincode": lambda: resolve.pincode(a.spoken, ctx.lang),
        "district": lambda: resolve.district(a.spoken),
        "phone": lambda: ids.phone(a.spoken, ctx.lang),
        "loan_id": lambda: ids.loan_id(a.spoken, ctx.lang),
        "ticket_id": lambda: ids.ticket_id(a.spoken, ctx.lang),
        "dob": lambda: resolve.dob(a.spoken, ctx.lang, ctx.today),
    }[a.kind]
    return ctx.entity(fn(), a.kind)


class PlaceArgs(BaseModel):
    place_spoken: str = Field(..., max_length=120, description="City, district or 6-digit pincode as the caller said it")


@tool("find_branch", "any")
def find_branch(ctx: ToolContext, a: PlaceArgs) -> dict:
    """Find the branch serving a city, district or pincode. No verification needed."""
    pin = resolve.pincode(a.place_spoken, ctx.lang)
    if pin.value:
        ctx.entity(pin, "pincode")
        district, state = resolve.pincodes()[pin.value]
        found = {"heard": a.place_spoken, "value": f"{district}|{state}", "confidence": pin.confidence}
    else:
        found = ctx.entity(resolve.district(a.place_spoken), "district")
        if not found["value"]:
            return {"place": found, "branch": None}
        district, state = found["value"].split("|")
    branch = ctx.store.branch_for_district(district, state)
    if not branch:
        return {"place": found, "district": f"{district}, {state}", "branch": None, "serviceable": False}
    return {"place": found, "district": f"{district}, {state}", "serviceable": True,
            "branch": {"name": branch["name"], "phone": branch["phone"], "pincode": branch["pincode"]}}


class ReasonArgs(BaseModel):
    reason: str = Field(..., max_length=300)


@tool("escalate_to_human", "any", writes=True)
def escalate_to_human(ctx: ToolContext, a: ReasonArgs) -> dict:
    """Book a callback from a human agent. Use when the caller asks for a person, is upset, verification fails, or the request is outside your tools."""
    r = ctx.store.add_request(ctx.session.customer_id, None, "human_callback", a.reason, ctx.session.actor or "unverified")
    return {"callback_reference": r["request_id"], "when": "within 4 working hours"}


@tool("report_fraud", "any", writes=True)
def report_fraud(ctx: ToolContext, a: ReasonArgs) -> dict:
    """Log a report of a suspicious call or message (someone asking for an OTP, PIN or payment). No verification needed; never ask for an OTP in response."""
    t = ctx.store.add_ticket(ctx.session.customer_id or "UNVERIFIED", None, "fraud_report", a.reason)
    return {"ticket_id": t["ticket_id"], "advice": "Never share OTPs, PINs or passwords. We never ask for them on a call."}


class EndArgs(BaseModel):
    reason: str = Field("caller finished", max_length=100)


@tool("end_call", "any")
def end_call(ctx: ToolContext, a: EndArgs) -> dict:
    """End the call after saying goodbye, when the caller is done."""
    ctx.session.end_requested = True
    return {"ending": True}


# ---- customer verification ----------------------------------------------------


class VerifyCustomerArgs(BaseModel):
    name_spoken: str = Field(..., max_length=120, description="The caller's full name as they said it")
    id_type: Literal["dob", "phone", "loan_id"] = Field(..., description="Which second identifier the caller gave")
    id_spoken: str = Field(..., max_length=200, description="The caller's exact words for that identifier")


@tool("verify_customer", "customer_pre")
def verify_customer(ctx: ToolContext, a: VerifyCustomerArgs) -> dict:
    """Check the caller's name plus date of birth, registered mobile number, or loan ID. On a match, a one-time password is sent to their registered mobile; then ask them to read it out and call check_otp."""
    s = ctx.session
    reader = {"dob": lambda: resolve.dob(a.id_spoken, ctx.lang, ctx.today),
              "phone": lambda: ids.phone(a.id_spoken, ctx.lang),
              "loan_id": lambda: ids.loan_id(a.id_spoken, ctx.lang)}[a.id_type]
    factor = reader()
    seen = ctx.entity(factor, a.id_type)
    if factor.value is None:
        # Not understood is not the same as wrong: ask again, no failure counted.
        return {"status": "unclear", "identifier": seen, "say": "Ask the caller to repeat it, slowly."}
    if a.id_type == "loan_id":
        loan = ctx.store.loans.get(factor.value)
        pool = [ctx.store.customers[loan["customer_id"]]] if loan else []
    else:
        pool = ctx.store.customers_with(a.id_type, factor.value)
    match = resolve.name(a.name_spoken, [(c["customer_id"], c["full_name"]) for c in pool]) if pool else None
    if match is not None:
        ctx.session.emit("entity", field="name", **{**match.to_dict(), "candidates": []})   # never show other customers
    close_enough = match is not None and match.value is not None and match.candidates[0].distance <= VERIFY_NAME_MAX
    if not close_enough or match.confidence == LOW:
        s.record_failure()
        left = max(0, 3 - s.verify_failures)
        return {"status": "not_verified", "attempts_left": left,
                "say": "Say the details did not match, without saying which one. " +
                       ("Offer a human callback." if left == 0 else "Ask them to try again.")}
    if s.otps_sent >= MAX_OTPS_PER_CALL:
        s.locked = True
        s.emit("state", locked=True, verified=False)
        return {"status": "locked", "say": "Too many attempts on this call. Offer a human callback."}
    customer = ctx.store.customers[match.value]
    code = s.issue_otp(customer["customer_id"])
    s.emit("otp", code=code, to=mask_phone(customer["phone"]))      # the simulated phone shows it as an SMS
    return {"status": "otp_sent", "to": f"registered mobile ending {customer['phone'][-2:]}",
            "say": "Ask the caller to read out the 6-digit OTP."}


class OtpArgs(BaseModel):
    otp_spoken: str = Field(..., max_length=120, description="The caller's exact words for the OTP")


@tool("check_otp", "customer_otp")
def check_otp(ctx: ToolContext, a: OtpArgs) -> dict:
    """Check the one-time password the caller reads out."""
    r = ids.otp(a.otp_spoken, ctx.lang)
    ctx.session.emit("entity", field="otp", **{**r.to_dict(), "value": "••••••" if r.value else None, "normalised": ""})
    if r.value is None:
        return {"status": "unclear", "say": "Ask them to read the 6 digits again."}
    outcome = ctx.session.check_otp(r.value)
    if outcome == "ok":
        c = ctx.store.customers[ctx.session.customer_id]
        loans = ctx.store.loans_of(c["customer_id"])
        return {"status": "verified", "customer_first_name": c["full_name"].split()[0],
                "loans": [{"loan_ref": f"ending {l['loan_id'][-3:]}", "product": l["product"],
                           "status": STAGE_FOR_CUSTOMER[l["stage"]]} for l in loans]}
    if outcome == "wrong":
        return {"status": "wrong", "say": "Say the OTP did not match." + (" Offer a callback." if ctx.session.locked else " Ask them to try once more.")}
    return {"status": outcome, "say": "Offer a human callback." if outcome == "locked" else "Start verification again."}


# ---- customer tools (verified) -------------------------------------------------


class LoanArgs(BaseModel):
    loan_spoken: str = Field("", max_length=120, description="Which loan, if the caller has more than one: loan ID or its last digits, or the product")


def own_loan(ctx: ToolContext, spoken: str) -> dict:
    """The verified customer's loan the caller means. Never another customer's."""
    loans = ctx.store.loans_of(ctx.session.customer_id)
    if spoken.strip():
        r = ids.loan_id(spoken, ctx.lang)
        if r.value:
            hit = next((l for l in loans if l["loan_id"] == r.value), None)
            if hit:
                return hit
        tail = "".join(ch for ch in spoken if ch.isdigit())[-3:]
        hits = [l for l in loans if tail and l["loan_id"].endswith(tail)] or \
               [l for l in loans if l["product"].split()[0].lower() in spoken.lower()]
        if len(hits) == 1:
            return hits[0]
        raise ToolError("I could not find that loan on your account. " + _which(loans))
    open_loans = [l for l in loans if l["stage"] not in ("Closed", "Rejected")] or loans
    if len(open_loans) == 1:
        return open_loans[0]
    raise ToolError("You have more than one loan. " + _which(loans))


def _which(loans: list[dict]) -> str:
    return "Ask which one: " + "; ".join(f"{l['product']} ending {l['loan_id'][-3:]} ({STAGE_FOR_CUSTOMER[l['stage']]})" for l in loans)


@tool("get_loan_status", "customer")
def get_loan_status(ctx: ToolContext, a: LoanArgs) -> dict:
    """Status of the caller's loan or application: stage, amounts, next due date, and what (if anything) they need to do."""
    return customer_loan_view(own_loan(ctx, a.loan_spoken))


@tool("get_emi_schedule", "customer")
def get_emi_schedule(ctx: ToolContext, a: LoanArgs) -> dict:
    """The caller's EMI amount, next due date, and recent EMIs including any that bounced and the bounce charges."""
    loan = own_loan(ctx, a.loan_spoken)
    rows = ctx.store.emis.get(loan["loan_id"], [])
    past = [r for r in rows if r["status"] != "upcoming"][-4:]
    return {
        "emi": rupees(loan["emi"]), "next_due_date": spoken_date(loan["next_due_date"]),
        "overdue": rupees(loan["overdue_amount"]) if float(loan["overdue_amount"] or 0) > 0 else None,
        "auto_debit": loan["nach_status"].lower() or "not set up",
        "recent": [{"due_date": spoken_date(r["due_date"]), "amount": rupees(r["amount"]), "status": r["status"],
                    "bounce_charge": rupees(r["bounce_charge"]) if int(r["bounce_charge"]) else None} for r in past],
        "bounce_charge_rule": "₹500 + 18% GST = ₹590 per bounced EMI",
    }


@tool("get_foreclosure_quote", "customer")
def get_foreclosure_quote(ctx: ToolContext, a: LoanArgs) -> dict:
    """How much the caller must pay today to close the loan early."""
    loan = own_loan(ctx, a.loan_spoken)
    if loan["stage"] != "Active":
        raise ToolError(f"This loan is {STAGE_FOR_CUSTOMER[loan['stage']]}, so there is nothing to foreclose.")
    principal = float(loan["outstanding_principal"])
    charge = round(principal * FORECLOSURE_RATE)
    overdue = float(loan["overdue_amount"] or 0)
    return {"principal_outstanding": rupees(principal), "foreclosure_charge_4_percent": rupees(charge),
            "overdue": rupees(overdue), "total_to_pay": rupees(principal + charge + overdue),
            "valid_until": spoken_date(ctx.today.replace(day=28).isoformat())}


@tool("list_pending_documents", "customer")
def list_pending_documents(ctx: ToolContext, a: LoanArgs) -> dict:
    """What documents or actions the caller still owes on their application."""
    loan = own_loan(ctx, a.loan_spoken)
    if loan["stage"] in ("KYC", "Underwriting", "Disbursal_Hold") and loan["customer_message"]:
        return {"pending": loan["customer_message"], "upload_via": "the app or the link sent by SMS"}
    return {"pending": None, "status": STAGE_FOR_CUSTOMER[loan["stage"]]}


@tool("explain_rejection", "customer")
def explain_rejection(ctx: ToolContext, a: LoanArgs) -> dict:
    """Why the caller's application was not approved, in the words we may share, and when they can reapply."""
    loan = own_loan(ctx, a.loan_spoken)
    if loan["stage"] != "Rejected":
        raise ToolError(f"This application is {STAGE_FOR_CUSTOMER[loan['stage']]}, not rejected.")
    return {"reason": loan["customer_message"]}


class ServiceRequestArgs(BaseModel):
    type: Literal["prepayment", "noc", "address_change", "mobile_change", "mandate_reregistration",
                  "interest_certificate", "top_up", "statement", "kyc_link"]
    details: str = Field("", max_length=300)
    loan_spoken: str = Field("", max_length=120)
    amount_spoken: str = Field("", max_length=120, description="For prepayment: the amount as the caller said it")
    financial_year_spoken: str = Field("", max_length=60, description="For interest certificates: e.g. 'pichhle saal ka'")
    place_spoken: str = Field("", max_length=120, description="For address change: the new city or district")
    pincode_spoken: str = Field("", max_length=120, description="For address change: the new pincode")


@tool("create_service_request", "customer", writes=True)
def create_service_request(ctx: ToolContext, a: ServiceRequestArgs) -> dict:
    """Create a service request (prepayment, NOC, address or mobile change, eMandate re-registration, interest certificate, top-up, statement, KYC link). Read back any amount, year or address first."""
    loan = own_loan(ctx, a.loan_spoken)
    out: dict[str, Any] = {}
    details = a.details
    if a.type == "prepayment":
        if not a.amount_spoken:
            raise ToolError("Ask how much they want to prepay.")
        amt = ctx.entity(resolve.amount(a.amount_spoken, ctx.lang), "amount")
        if amt["value"] is None:
            return {"status": "unclear_amount", "amount": amt}
        out["amount"] = rupees(amt["value"])
        principal = float(loan["outstanding_principal"] or 0)
        if float(amt["value"]) >= principal:
            out["note"] = "That is at least the whole outstanding principal; offer a foreclosure quote instead."
        details = f"{details} amount={amt['value']}".strip()
    if a.type == "interest_certificate":
        fy = financial_year(a.financial_year_spoken or "last year", ctx.today)
        out["financial_year"] = fy
        details = f"{details} FY {fy}".strip()
    if a.type == "address_change":
        if not (a.place_spoken and a.pincode_spoken):
            raise ToolError("Ask for the new city and the new pincode.")
        pin = resolve.pincode(a.pincode_spoken, ctx.lang)
        place = resolve.district(a.place_spoken, pincode=pin.value)
        out["pincode"] = ctx.entity(pin, "pincode")
        out["place"] = ctx.entity(place, "district")
        if pin.value is None or place.value is None or place.confidence == LOW:
            return {"status": "check_address", **out, "say": "Read back the city and pincode and ask them to confirm."}
        details = f"{details} new address {place.value} {pin.value}".strip()
    if a.type == "mobile_change":
        out["note"] = "Mobile change needs the OTP on the old number, already done on this call."
    r = ctx.store.add_request(ctx.session.customer_id, loan["loan_id"], a.type, details, ctx.session.actor)
    return {"status": "created", "request_id": r["request_id"], **out}


class ComplaintArgs(BaseModel):
    category: Literal["double_debit", "wrong_account", "service", "refund", "charges", "other"]
    details: str = Field(..., max_length=300)
    loan_spoken: str = Field("", max_length=120)
    amount_spoken: str = Field("", max_length=120)
    date_spoken: str = Field("", max_length=120)


@tool("raise_complaint", "customer", writes=True)
def raise_complaint(ctx: ToolContext, a: ComplaintArgs) -> dict:
    """Raise a complaint ticket (double debit, wrong account, charges, refund, service). Capture the amount and date when the caller gives them."""
    loan = own_loan(ctx, a.loan_spoken)
    out: dict[str, Any] = {}
    if a.amount_spoken:
        out["amount"] = ctx.entity(resolve.amount(a.amount_spoken, ctx.lang), "amount")
        if out["amount"]["value"] and a.category == "double_debit" and int(out["amount"]["value"]) == int(loan["emi"]):
            out["matches_emi"] = True
    if a.date_spoken:
        out["date"] = ctx.entity(resolve.event_date(a.date_spoken, ctx.today, ctx.lang, "past"), "date")
    t = ctx.store.add_ticket(ctx.session.customer_id, loan["loan_id"], a.category,
                             f"{a.details} {out.get('amount', {}).get('value') or ''}".strip())
    return {"ticket_id": t["ticket_id"], "resolution_time": "7 working days", **out}


class TicketArgs(BaseModel):
    ticket_spoken: str = Field(..., max_length=120, description="The ticket or complaint number as the caller said it")


@tool("check_ticket", "customer")
def check_ticket(ctx: ToolContext, a: TicketArgs) -> dict:
    """Status of one of the caller's complaints or tickets."""
    r = ctx.entity(ids.ticket_id(a.ticket_spoken, ctx.lang), "ticket_id")
    t = ctx.store.tickets.get(r["value"] or "")
    if not t or t["customer_id"] != ctx.session.customer_id:
        mine = ctx.store.tickets_of(ctx.session.customer_id)[:3]
        return {"found": False, "heard": r, "your_recent_tickets": [x["ticket_id"] for x in mine]}
    return {"found": True, "ticket_id": t["ticket_id"], "type": t["type"], "status": t["status"],
            "opened": spoken_date(t["created_on"]), "follow_ups": int(t["follow_ups"]),
            "should_escalate": int(t["follow_ups"]) >= 2 and t["status"] != "resolved"}


# ---- staff verification -------------------------------------------------------


class VerifyStaffArgs(BaseModel):
    employee_id_spoken: str = Field(..., max_length=120)
    pin_spoken: str = Field("", max_length=120, description="The PIN as said. Ask for it first if you don't have it.")


@tool("verify_staff", "staff_pre")
def verify_staff(ctx: ToolContext, a: VerifyStaffArgs) -> dict:
    """Log a staff member in with their employee ID and 4-digit PIN. Call it only when you have both."""
    import hmac
    s = ctx.session
    if not any(ch.isalnum() for ch in a.pin_spoken):
        return {"status": "need_pin", "say": "Ask for their 4-digit PIN, then call verify_staff again with both."}
    emp = ids.employee_id(a.employee_id_spoken, ctx.lang)
    ctx.entity(emp, "employee_id")
    pin = ids.pin(a.pin_spoken, ctx.lang)
    ctx.session.emit("entity", field="pin", **{**pin.to_dict(), "value": "••••" if pin.value else None, "normalised": ""})
    if emp.value is None or pin.value is None:
        return {"status": "unclear", "say": "Ask them to repeat the employee ID and PIN."}
    staff = ctx.store.staff.get(emp.value)
    expected = staff["pin"] if staff else "\0\0\0\0"
    if not hmac.compare_digest(pin.value, expected) or staff is None:
        s.record_failure()
        return {"status": "not_verified", "attempts_left": max(0, 3 - s.verify_failures),
                "say": "Say the details did not match, without saying which."}
    s.staff_id, s.staff_role = staff["employee_id"], staff["role"]
    s.emit("state", verified=True, locked=False, role=staff["role"])
    return {"status": "verified", "name": staff["name"], "role": staff["role"]}


# ---- staff tools ----------------------------------------------------------------


def staff_loan(ctx: ToolContext, spoken: str) -> tuple[dict, dict]:
    r = ids.loan_id(spoken, ctx.lang)
    heard = ctx.entity(r, "loan_id")
    if r.value is None:
        raise ToolError(f"Could not read a loan ID from '{spoken}'. Ask for it again.")
    loan = ctx.store.loans.get(r.value)
    if loan is None:
        near = ids.near_ids(r.value, set(ctx.store.loans), "LN")
        raise ToolError(f"No case {r.value}." + (f" Similar IDs: {', '.join(near[:3])}. Do not assume; ask." if near else ""))
    return loan, heard


class CaseLookupArgs(BaseModel):
    loan_spoken: str = Field("", max_length=120, description="Loan ID as said")
    customer_name_spoken: str = Field("", max_length=120, description="Customer name as said")
    phone_spoken: str = Field("", max_length=200, description="Customer mobile as said")


@tool("lookup_case", "staff")
def lookup_case(ctx: ToolContext, a: CaseLookupArgs) -> dict:
    """Find a case by loan ID, customer name or customer mobile. Name searches can return several customers; never assume they are the same person."""
    store = ctx.store
    if a.loan_spoken:
        loan, heard = staff_loan(ctx, a.loan_spoken)
        c = store.customers[loan["customer_id"]]
        return {"heard": heard, "case": staff_loan_view(loan, c),
                "other_loans": [l["loan_id"] for l in store.loans_of(c["customer_id"]) if l["loan_id"] != loan["loan_id"]],
                "open_tickets": [t["ticket_id"] for t in store.tickets_of(c["customer_id"]) if t["status"] != "resolved"]}
    if a.phone_spoken:
        p = ids.phone(a.phone_spoken, ctx.lang)
        heard = ctx.entity(p, "phone")
        people = store.customers_with("phone", p.value) if p.value else []
    elif a.customer_name_spoken:
        match = resolve.name(a.customer_name_spoken, store.people())
        heard = ctx.entity(match, "name")
        good = [c for c in match.candidates if c.distance <= resolve.NAME_MEDIUM]
        # everyone as close as the best match (same name twice) is shown, up to 3
        best = good[0].distance if good else None
        people = [store.customers[c.value] for c in good if best is not None and c.distance <= best + 0.5][:3]
    else:
        raise ToolError("Give a loan ID, customer name or mobile number.")
    return {"heard": heard, "matches": [{
        "customer_id": c["customer_id"], "name": c["full_name"], "city": f"{c['district']}, {c['state']}",
        "dob_year": c["dob"][:4], "phone": mask_phone(c["phone"]),
        "loans": [f"{l['loan_id']} {l['product']} ({l['stage']})" for l in store.loans_of(c["customer_id"])],
        "open_tickets": [f"{t['ticket_id']} {t['type']} follow-ups:{t['follow_ups']}" for t in store.tickets_of(c["customer_id"]) if t["status"] != "resolved"],
    } for c in people], "note": "Different customer IDs are different people." if len(people) > 1 else ""}


class StaffLoanArgs(BaseModel):
    loan_spoken: str = Field(..., max_length=120, description="Loan ID as said")


@tool("diagnose_case", "staff")
def diagnose_case(ctx: ToolContext, a: StaffLoanArgs) -> dict:
    """Why a case is stuck and the next step to unblock it, with the owner and SLA."""
    loan, heard = staff_loan(ctx, a.loan_spoken)
    c = ctx.store.customers[loan["customer_id"]]
    sla = date.fromisoformat(loan["sla_due"])
    stuck = loan["stage"] in OPEN_STAGES
    return {"heard": heard, "case": staff_loan_view(loan, c), "stuck": stuck,
            "next_step": NEXT_STEPS.get(loan["internal_note"], "Escalate to a supervisor for a manual check.") if stuck else None,
            "sla_breached": stuck and sla < ctx.today, "days_past_sla": max(0, (ctx.today - sla).days) if stuck else 0,
            "notes": ctx.store.notes.get(loan["loan_id"], [])[-3:]}


class NoteArgs(BaseModel):
    loan_spoken: str = Field(..., max_length=120)
    text: str = Field(..., max_length=600, description="The note, in the staff member's words")


@tool("add_case_note", "staff", writes=True)
def add_case_note(ctx: ToolContext, a: NoteArgs) -> dict:
    """Add a note to a case, exactly as the staff member said it."""
    loan, heard = staff_loan(ctx, a.loan_spoken)
    n = ctx.store.add_note(loan["loan_id"], a.text, ctx.session.staff_id)
    return {"heard": heard, "saved": True, "note": n["text"]}


@tool("retry_bureau_pull", "staff", roles=("ops", "credit", "supervisor"), writes=True)
def retry_bureau_pull(ctx: ToolContext, a: StaffLoanArgs) -> dict:
    """Retry a failed credit bureau pull (cases at the credit check stage)."""
    loan, heard = staff_loan(ctx, a.loan_spoken)
    if loan["stage"] != "Credit_Check":
        raise ToolError(f"{loan['loan_id']} is at {loan['stage']}, not credit check.")
    ok = ctx.store.bureau_retry(loan["loan_id"])
    return {"heard": heard, "retry_succeeded": ok, "next": None if ok else "Failed again: escalate to the bureau desk."}


class PriorityArgs(BaseModel):
    loan_spoken: str = Field(..., max_length=120)
    priority: Literal["urgent", "high", "normal"]
    reason: str = Field(..., max_length=300, description="The reason, in the staff member's words")


@tool("set_priority", "staff", roles=("ops", "supervisor"), writes=True)
def set_priority(ctx: ToolContext, a: PriorityArgs) -> dict:
    """Change a case's priority, with the reason recorded."""
    loan, heard = staff_loan(ctx, a.loan_spoken)
    ctx.store.set_priority(loan["loan_id"], a.priority, ctx.session.staff_id, a.reason)
    return {"heard": heard, "priority": a.priority, "reason_recorded": a.reason}


class EscalateArgs(BaseModel):
    loan_spoken: str = Field(..., max_length=120)
    reason: str = Field(..., max_length=300)


@tool("escalate_case", "staff", writes=True)
def escalate_case(ctx: ToolContext, a: EscalateArgs) -> dict:
    """Escalate a case to a supervisor or senior underwriter."""
    loan, heard = staff_loan(ctx, a.loan_spoken)
    target = "senior underwriter queue" if loan["stage"] in ("Credit_Check", "Underwriting") else "operations supervisor"
    ctx.store.add_note(loan["loan_id"], f"Escalated to {target}: {a.reason}", ctx.session.staff_id)
    return {"heard": heard, "escalated_to": target}


class NotifyArgs(BaseModel):
    loan_spoken: str = Field(..., max_length=120)
    message: Literal["kyc_link", "selfie_reminder", "documents_reminder", "emandate_link", "co_applicant_reminder"]


@tool("notify_customer", "staff", writes=True)
def notify_customer(ctx: ToolContext, a: NotifyArgs) -> dict:
    """Send the customer on a case an SMS link or reminder (KYC link, selfie reminder, documents, eMandate link, co-applicant documents)."""
    loan, heard = staff_loan(ctx, a.loan_spoken)
    c = ctx.store.customers[loan["customer_id"]]
    ctx.store.add_note(loan["loan_id"], f"Sent {a.message.replace('_', ' ')} by SMS", ctx.session.staff_id)
    return {"heard": heard, "sent": a.message, "to": f"{c['full_name']}, mobile ending {c['phone'][-2:]}"}


class EmptyArgs(BaseModel):
    pass


@tool("queue_status", "staff", roles=("ops", "credit", "supervisor"))
def queue_status(ctx: ToolContext, a: EmptyArgs) -> dict:
    """How many open cases are assigned to the logged-in staff member, and the oldest one."""
    mine = [l for l in ctx.store.loans.values() if l["assigned_to"] == ctx.session.staff_id and l["stage"] in OPEN_STAGES]
    mine.sort(key=lambda l: l["applied_on"])
    return {"open_cases": len(mine), "oldest": mine[0]["loan_id"] if mine else None,
            "oldest_since": spoken_date(mine[0]["applied_on"]) if mine else None,
            "by_stage": {st: sum(1 for l in mine if l["stage"] == st) for st in OPEN_STAGES if any(l["stage"] == st for l in mine)}}


class CountArgs(BaseModel):
    district_spoken: str = Field("", max_length=120)
    stage: Literal["", "open", "Applied", "KYC", "Credit_Check", "Underwriting", "Approved", "Disbursal_Hold", "Active", "Closed", "Rejected"] = ""
    bounced_this_month: bool = False


@tool("count_cases", "staff")
def count_cases(ctx: ToolContext, a: CountArgs) -> dict:
    """Count cases, optionally in one district, at one stage ('open' = all pending stages), or with an EMI bounced this month."""
    loans = list(ctx.store.loans.values())
    out: dict[str, Any] = {}
    if a.district_spoken:
        place = resolve.district(a.district_spoken)
        out["district"] = ctx.entity(place, "district")
        if place.value is None:
            return out
        d, s = place.value.split("|")
        ids_here = {c["customer_id"] for c in ctx.store.customers.values() if c["district"] == d and c["state"] == s}
        loans = [l for l in loans if l["customer_id"] in ids_here]
    if a.stage == "open":
        loans = [l for l in loans if l["stage"] in OPEN_STAGES]
    elif a.stage:
        loans = [l for l in loans if l["stage"] == a.stage]
    if a.bounced_this_month:
        month = ctx.today.strftime("%Y-%m")
        bounced = {e["loan_id"] for lid, rows in ctx.store.emis.items() for e in rows
                   if e["status"] == "bounced" and e["due_date"].startswith(month)}
        loans = [l for l in loans if l["loan_id"] in bounced]
        loans.sort(key=lambda l: float(l["overdue_amount"] or 0), reverse=True)
        out["top"] = [f"{l['loan_id']} overdue {rupees(l['overdue_amount'])}" for l in loans[:5]]
    out["count"] = len(loans)
    out["by_stage"] = {st: sum(1 for l in loans if l["stage"] == st) for st in sorted({l["stage"] for l in loans})}
    return out
