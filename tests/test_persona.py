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
    assert "woman" in prompt and "Listen first" in prompt


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
