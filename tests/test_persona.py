"""Vaani's voice: gender agreement, fillers, and text that reads well aloud."""
import asyncio

import pytest

from agent.graph import Agent
from agent.persona import fix_self_gender, greeting, speakable, spoken_date, voice_gender
from agent.prompts import system_prompt
from core.config import Settings
from core.session import SessionManager
from core.store import Store
from tests.fakes import ScriptedModel, call, say


@pytest.mark.parametrize("male, female", [
    ("मैं आपकी मदद कर सकता हूँ।", "मैं आपकी मदद कर सकती हूँ।"),
    ("मैं अभी चेक कर रहा हूँ", "मैं अभी चेक कर रही हूँ"),
    ("मैं आपको OTP भेजूँगा।", "मैं आपको OTP भेजूँगी।"),
    ("main aapki madad kar sakta hoon", "main aapki madad kar sakti hoon"),
    ("main check karunga", "main check karungi"),
])
def test_first_person_verbs_follow_the_voice(male, female):
    assert fix_self_gender(male, "female") == female
    assert fix_self_gender(female, "male") == male


@pytest.mark.parametrize("text", [
    "आपकी EMI ₹19,499 है।", "वो करेगा", "Rahul ne kaha wo aa raha hai", "मैं यहाँ हूँ",
])
def test_other_people_and_plain_sentences_are_left_alone(text):
    assert fix_self_gender(text, "female") == text


def test_voice_gender():
    assert voice_gender("ritu") == "female" and voice_gender("shubh") == "male"
    assert voice_gender("aparna_hi_customer") == "female"


def test_greeting_and_prompt_match_the_voice():
    assert "सकती" in greeting("customer", "female") and "सकता" in greeting("customer", "male")
    s, _ = SessionManager(5, 5, 60).create("customer", "1.1.1.1", None)
    settings = Settings(_env_file=None)
    store = Store.load(settings.data_dir, settings.demo_today)
    prompt = system_prompt(s, store, "female")
    assert "woman" in prompt and "SHORT" in prompt and "समझ सकती हूँ" in prompt
    assert "समझ सकता हूँ" in system_prompt(s, store, "male")


def test_speakable_and_dates():
    assert speakable("**EMI** ₹19,499 😊\n- due soon") == "EMI ₹19,499 due soon"
    assert spoken_date("2026-11-05") == "5 November 2026"


def test_a_lookup_gets_one_filler_and_the_reply_is_gender_fixed(tmp_path):
    settings = Settings(_env_file=None, var_dir=tmp_path, sarvam_tts_voice="ritu")
    store = Store.load(settings.data_dir, settings.demo_today)
    s, _ = SessionManager(5, 5, 60).create("customer", "1.1.1.1", None)
    s.language = "hi-IN"
    spoken: list[str] = []

    async def hook(text):
        spoken.append(text)

    s.on_interim = hook
    model = ScriptedModel([
        call("find_branch", place_spoken="Jaipur"),                  # not a lookup: no filler
        call("verify_customer", name_spoken="Sultan Meena", id_type="dob", id_spoken="23 April 1987"),
        call("identify_value", kind="dob", spoken="23 April 1987"),
        say("मैंने आपको OTP भेज दिया है, मैं इंतज़ार कर रहा हूँ।"),
    ])
    reply = asyncio.run(Agent(model, store, settings).turn(s, "Sultan Meena, 23 April 1987"))
    assert len(spoken) == 1                                          # once per turn
    assert reply.endswith("कर रही हूँ।")


def test_replies_that_broke_the_voice_are_cleaned():
    # From a real call: brackets and " - " made Sarvam reject a letterless chunk.
    reply = ("धन्यवाद, महेश। अब कृपया आपकी जन्म तिथि बताएँ - दिन, महीना और साल। "
             "(मैं आपके खाते को देखने के लिए यह जानकारी चाहती हूँ।)")
    out = speakable(reply)
    assert not any(ch in out for ch in "()-\"")
    assert speakable("…") == "" and speakable("ठीक है। । ) बाय!") == "ठीक है। बाय!"
    assert speakable("जैसे १५ जून १९९०") == "जैसे 15 जून 1990"


def test_greeting_is_remembered_and_never_repeated(tmp_path):
    settings = Settings(_env_file=None, var_dir=tmp_path)
    store = Store.load(settings.data_dir, settings.demo_today)
    s, _ = SessionManager(5, 5, 60).create("customer", "1.1.1.1", None)
    agent = Agent(ScriptedModel([lambda msgs, offered: say(s.greeting + " जी हाँ, बताइए।")]), store, settings)
    hello = agent.greet(s)
    assert s.history[0].type == "human" and s.history[1].content == hello
    reply = asyncio.run(agent.turn(s, "हेलो"))
    assert reply == "जी हाँ, बताइए।"


def test_filler_follows_the_language_vaani_last_spoke(tmp_path):
    settings = Settings(_env_file=None, var_dir=tmp_path)
    store = Store.load(settings.data_dir, settings.demo_today)
    s, _ = SessionManager(5, 5, 60).create("staff", "1.1.1.1", None)
    s.language = "en-IN"                       # STT tagged "E. 1008" as English
    spoken = []

    async def hook(text):
        spoken.append(text)

    s.on_interim = hook
    agent = Agent(ScriptedModel([call("verify_staff", employee_id_spoken="E. 1008", pin_spoken="8472"), say("ठीक है।")]),
                  store, settings)
    agent.greet(s)
    asyncio.run(agent.turn(s, "जी मेरा एम्प्लॉई आईडी है ई। 1008, पिन 8472"))
    assert spoken and any("\u0900" <= ch <= "\u097F" for ch in spoken[0])
