"""The agent and its tools: who may see what, and what happens when things go wrong."""
import asyncio
import json

import pytest

from agent import tools as T
from agent.graph import Agent
from core import audit
from core.config import Settings
from core.session import SessionManager
from core.store import Store
from tests.fakes import ScriptedModel, call, say

WORDS = "zero one two three four five six seven eight nine".split()


@pytest.fixture
def settings(tmp_path):
    s = Settings(_env_file=None, var_dir=tmp_path)
    audit.configure(tmp_path)
    return s


@pytest.fixture
def store(settings):
    return Store.load(settings.data_dir, settings.demo_today)


def new_session(line="customer"):
    return SessionManager(50, 50, 600).create(line, "10.0.0.1", None)[0]


def run(ctx, name, **args):
    return T.execute(ctx, name, args)


def spoken(code):
    return " ".join(WORDS[int(d)] for d in code)


def otp_of(session):
    return next(e["code"] for e in reversed(session.events) if e["type"] == "otp")


def verified_customer(store, settings, name="Sultan Meena", dob="teis April unnees sau sattaasi"):
    s = new_session()
    ctx = T.ToolContext(s, store, settings)
    assert run(ctx, "verify_customer", name_spoken=name, id_type="dob", id_spoken=dob)["status"] == "otp_sent"
    assert run(ctx, "check_otp", otp_spoken=spoken(otp_of(s)))["status"] == "verified"
    return s, ctx


# ---- access before verification -----------------------------------------------

def test_account_tools_are_hidden_and_refused_before_verification(store, settings):
    s = new_session()
    names = {t.name for t in T.available(s)}
    assert "verify_customer" in names and "get_loan_status" not in names and "check_otp" not in names
    result = run(T.ToolContext(s, store, settings), "get_loan_status")
    assert result == {"error": "That action is not available right now."}


def test_customer_cannot_use_staff_tools_or_the_reverse(store, settings):
    s, _ = verified_customer(store, settings)
    assert "lookup_case" not in {t.name for t in T.available(s)}
    staff = new_session("staff")
    assert "get_loan_status" not in {t.name for t in T.available(staff)}


def test_wrong_details_lock_the_call_after_three_tries(store, settings):
    s = new_session()
    ctx = T.ToolContext(s, store, settings)
    for _ in range(3):
        r = run(ctx, "verify_customer", name_spoken="Sultan Meena", id_type="dob", id_spoken="1 January 1990")
        assert r["status"] in ("not_verified", "error") or "error" in r
    assert s.locked
    assert {t.name for t in T.available(s)} == {t.name for t in T.REGISTRY.values() if t.access == "any"}
    assert "error" in run(ctx, "verify_customer", name_spoken="Sultan Meena", id_type="dob",
                          id_spoken="teis April unnees sau sattaasi")


def test_unclear_identifier_is_not_counted_as_a_failure(store, settings):
    s = new_session()
    r = run(T.ToolContext(s, store, settings), "verify_customer", name_spoken="Sultan Meena", id_type="phone", id_spoken="nine eight")
    assert r["status"] == "unclear" and s.verify_failures == 0


def test_failure_message_does_not_say_which_detail_was_wrong(store, settings):
    s = new_session()
    r = run(T.ToolContext(s, store, settings), "verify_customer", name_spoken="Sultan Meena", id_type="dob", id_spoken="2 March 1990")
    text = json.dumps(r).lower()
    assert r["status"] == "not_verified" and "date of birth" not in text and "name" not in text.replace("_", " ").split("say")[0]


def test_wrong_otp_three_times_locks(store, settings):
    s = new_session()
    ctx = T.ToolContext(s, store, settings)
    run(ctx, "verify_customer", name_spoken="Sultan Meena", id_type="dob", id_spoken="teis April unnees sau sattaasi")
    real = otp_of(s)
    wrong = str((int(real) + 1) % 1_000_000).zfill(6)
    for _ in range(3):
        run(ctx, "check_otp", otp_spoken=spoken(wrong))
    assert s.customer_id is None and s.verify_failures == 1
    assert "check_otp" not in {t.name for t in T.available(s)}


def test_otp_is_stored_only_as_a_hash(store, settings):
    s = new_session()
    run(T.ToolContext(s, store, settings), "verify_customer", name_spoken="Sultan Meena", id_type="dob",
        id_spoken="teis April unnees sau sattaasi")
    code = otp_of(s)
    assert code.encode() not in s.otp_hash and len(s.otp_hash) == 32


def test_a_sound_alike_impostor_cannot_get_past_the_otp(store, settings):
    # Mohan Verma says Rohan Verma's DOB. The OTP goes to Rohan's phone, so
    # the impostor has to guess it, and three guesses use up the OTP.
    s = new_session()
    ctx = T.ToolContext(s, store, settings)
    r = run(ctx, "verify_customer", name_spoken="Mohan Verma", id_type="dob", id_spoken="fourteen March nineteen ninety one")
    assert r["status"] == "otp_sent" and r["to"].endswith(store.customers["C0001"]["phone"][-2:])
    for guess in ("123456", "000000", "999999"):
        run(ctx, "check_otp", otp_spoken=spoken(guess))
    assert s.customer_id is None


def test_otp_sends_per_call_are_capped(store, settings):
    s = new_session()
    ctx = T.ToolContext(s, store, settings)
    statuses = [run(ctx, "verify_customer", name_spoken="Sultan Meena", id_type="dob",
                    id_spoken="teis April unnees sau sattaasi").get("status") for _ in range(5)]
    assert statuses.count("otp_sent") == 3 and s.locked


# ---- after verification ---------------------------------------------------------

def test_a_customer_only_ever_sees_their_own_loans(store, settings):
    s, ctx = verified_customer(store, settings)
    assert run(ctx, "get_loan_status", loan_spoken="")["loan_id"] == "LN00004"
    someone_else = run(ctx, "get_loan_status", loan_spoken="LN00001")
    assert "error" in someone_else and "Rohan" not in json.dumps(someone_else)


def test_customer_views_never_contain_internal_notes(store, settings):
    s, ctx = verified_customer(store, settings, "Rohan Verma", "chaudah march unnees sau ikyaanave")
    r = run(ctx, "get_loan_status", loan_spoken="")
    assert store.loans["LN00001"]["internal_note"] not in json.dumps(r)
    assert r["message_for_customer"] == store.loans["LN00001"]["customer_message"]


def test_reply_guard_blocks_internal_notes_for_customers(store, settings):
    s, _ = verified_customer(store, settings)
    agent = Agent(ScriptedModel([]), store, settings)
    note = store.loans["LN00005"]["internal_note"]
    assert note.lower() not in agent._guard(s, f"Your case says: {note}").lower()


def test_writes_per_call_are_capped(store, settings):
    s, ctx = verified_customer(store, settings)
    for i in range(settings.max_writes_per_call):
        assert "ticket_id" in run(ctx, "raise_complaint", category="service", details=f"note {i}")
    assert "error" in run(ctx, "raise_complaint", category="service", details="one too many")


# ---- staff ---------------------------------------------------------------------

def staff_session(store, settings, emp="E1007"):
    s = new_session("staff")
    ctx = T.ToolContext(s, store, settings)
    pin = store.staff[emp]["pin"]
    r = run(ctx, "verify_staff", employee_id_spoken=f"employee id {emp[1:]}", pin_spoken=spoken(pin))
    assert r["status"] == "verified"
    return s, ctx


def test_staff_wrong_pin_does_not_reveal_whether_the_id_exists(store, settings):
    s = new_session("staff")
    ctx = T.ToolContext(s, store, settings)
    real = run(ctx, "verify_staff", employee_id_spoken="employee id 1007", pin_spoken="one one one one")
    fake = run(ctx, "verify_staff", employee_id_spoken="employee id 9999", pin_spoken="one one one one")
    assert real["status"] == fake["status"] == "not_verified" and real.keys() == fake.keys()


def test_staff_roles_limit_actions(store, settings):
    s, ctx = staff_session(store, settings, "E1004")                  # an agent
    assert "retry_bureau_pull" not in {t.name for t in T.available(s)}
    assert "error" in run(ctx, "retry_bureau_pull", loan_spoken="LN00005")
    s2, ctx2 = staff_session(store, settings, "E1011")                # credit
    assert "retry_succeeded" in run(ctx2, "retry_bureau_pull", loan_spoken="LN00005")


def test_same_name_customers_are_listed_as_different_people(store, settings):
    _, ctx = staff_session(store, settings)
    r = run(ctx, "lookup_case", customer_name_spoken="Priya Sharma")
    assert len(r["matches"]) == 2 and r["note"]
    assert {m["city"] for m in r["matches"]} == {"Jaipur, Rajasthan", "Pune, Maharashtra"}


def test_unknown_loan_id_is_not_guessed(store, settings):
    _, ctx = staff_session(store, settings)
    assert "No case LN99999" in run(ctx, "diagnose_case", loan_spoken="LN99999")["error"]


# ---- the loop ------------------------------------------------------------------

def test_agent_loop_verifies_then_answers(store, settings):
    s = new_session()
    model = ScriptedModel([
        call("verify_customer", name_spoken="Sooltan Meena", id_type="dob", id_spoken="teis April unnees sau sattaasi"),
        say("Please read the OTP."),
        lambda msgs, offered: call("check_otp", otp_spoken=spoken(otp_of(s))),
        call("get_emi_schedule"),
        say("Your EMI is ₹19,499."),
    ])
    agent = Agent(model, store, settings)
    asyncio.run(agent.turn(s, "Sultan Meena, 23 April 1987"))
    reply = asyncio.run(agent.turn(s, "the OTP is ..."))
    assert reply == "Your EMI is ₹19,499." and s.customer_id == "C0004"
    assert "get_emi_schedule" not in model.offered[0] and "get_emi_schedule" in model.offered[-1]


class FailingModel:
    def bind_tools(self, _):
        return self

    async def ainvoke(self, _):
        raise TimeoutError("bedrock throttled")


def test_model_failure_gives_a_spoken_fallback_not_a_crash(store, settings):
    s = new_session()
    s.language = "hi-IN"
    reply = asyncio.run(Agent(FailingModel(), store, settings).turn(s, "hello"))
    assert "माफ़" in reply
    assert any(e["type"] == "error" for e in s.events)


def test_turn_limit_ends_the_call(store, settings):
    s = new_session()
    agent = Agent(ScriptedModel([say("ok")] * 5), store, settings.model_copy(update={"max_turns_per_call": 2}))
    for _ in range(3):
        asyncio.run(agent.turn(s, "hi"))
    assert s.end_requested


def test_audit_log_masks_secrets_and_pii(store, settings):
    s = new_session()
    ctx = T.ToolContext(s, store, settings)
    run(ctx, "verify_customer", name_spoken="Sultan Meena", id_type="phone", id_spoken=store.customers["C0004"]["phone"])
    run(ctx, "check_otp", otp_spoken=spoken(otp_of(s)))
    log = (settings.var_dir / "audit.jsonl").read_text()
    assert store.customers["C0004"]["phone"] not in log
    assert otp_of(s) not in log


def test_staff_login_without_a_pin_asks_for_it_and_counts_no_failure(store, settings):
    s = new_session("staff")
    r = run(T.ToolContext(s, store, settings), "verify_staff", employee_id_spoken="E. 1008", pin_spoken="?")
    assert r["status"] == "need_pin" and s.verify_failures == 0


def test_an_unsure_identifier_is_read_back_before_anything_is_checked(store, settings):
    # From a live call: the panel said "read back" but the OTP went out without one.
    s = new_session()
    ctx = T.ToolContext(s, store, settings)
    said = "six two one nine jero nine jero five eight one"            # "jero" is a fuzzy zero
    r = run(ctx, "verify_customer", name_spoken="Sultan Meena", id_type="phone", id_spoken=said)
    assert r["status"] == "confirm_first" and r["read_back"] == "6 2 1 9 0 9 0 5 8 1"
    assert s.otp_hash is None and s.verify_failures == 0
    r = run(ctx, "verify_customer", name_spoken="Sultan Meena", id_type="phone", id_spoken=said, confirmed=True)
    assert r["status"] == "otp_sent"


def test_common_stt_spellings_of_digits_are_certain():
    from identify import ids
    for said in ["92, 97, 73. 8 4. छः सात", "naw do naw saat saat teen aath chaar chhah saat"]:
        r = ids.phone(said, "hi")
        assert (r.value, r.confidence) == ("9297738467", "high"), said
