"""
How Vaani sounds: her gender (taken from the TTS voice), the words she uses
for herself, small fillers while she looks something up, and text cleaned
up so it reads naturally aloud.

Hindi marks the speaker's gender on verbs ("main kar sakti hoon" for a
woman, "sakta hoon" for a man). The model sometimes gets this wrong even
when told, and a female voice saying "sakta hoon" sounds broken, so
first-person forms are corrected in code after the model replies.
"""
import random
import re
from datetime import date

# Sarvam voices by gender. v4 IDs look like "aparna_hi_customer": the first
# part is the persona name. Unknown voices fall back to ASSISTANT_GENDER.
FEMALE_VOICES = {
    "ritu", "priya", "neha", "pooja", "simran", "kavya", "ishita", "shreya", "roopa", "amelia", "sophia",
    "tanya", "shruti", "suhani", "kavitha", "rupali", "anushka", "manisha", "vidya", "arya",
    "aparna", "aarti", "sanchita", "zarina",
}
MALE_VOICES = {
    "shubh", "aditya", "rahul", "rohan", "amit", "dev", "ratan", "varun", "manan", "sumit", "kabir", "aayan",
    "ashutosh", "advait", "anand", "tarun", "sunny", "mani", "gokul", "vijay", "mohit", "rehan", "soham",
    "abhilash", "karun", "hitesh",
}


def voice_gender(voice: str, fallback: str = "female") -> str:
    name = voice.split("_")[0].lower()
    if name in FEMALE_VOICES:
        return "female"
    if name in MALE_VOICES:
        return "male"
    return fallback


# ---- first-person gender agreement --------------------------------------------

# Devanagari: a word ending in ा / ी right before हूँ/हूं is the speaker's own
# verb or participle ("सकता हूँ", "रहा हूँ", "गया हूँ"); future forms
# "करूँगा / करूँगी" are first person by their ending.
_HI_PRESENT = {"female": (re.compile(r"(\S+)ा(\s+)(हूँ|हूं)"), r"\1ी\2\3"),
               "male": (re.compile(r"(\S+)ी(\s+)(हूँ|हूं)"), r"\1ा\2\3")}
_END = r"(?=[\s।,.!?]|$)"      # \b does not work after Devanagari vowel signs
_HI_FUTURE = {"female": (re.compile(r"(ूँ|ूं|ऊँ|ऊं)गा" + _END), r"\1गी"),
              "male": (re.compile(r"(ूँ|ूं|ऊँ|ऊं)गी" + _END), r"\1गा")}
# Romanised Hindi, in case the model writes Hinglish in Latin letters
_RO_PRESENT = {"female": (re.compile(r"\b(\w*(?:t|h|y|k))a(\s+)(hoon|hun|hu)\b", re.I), r"\1i\2\3"),
               "male": (re.compile(r"\b(\w*(?:t|h|y|k))i(\s+)(hoon|hun|hu)\b", re.I), r"\1a\2\3")}
_RO_FUTURE = {"female": (re.compile(r"\b(\w+u)nga\b", re.I), r"\1ngi"),
              "male": (re.compile(r"\b(\w+u)ngi\b", re.I), r"\1nga")}
# Words that end in ा/ी before हूँ but are not about the speaker's gender
_HI_KEEP = {"यहाँ", "वहाँ"}


def fix_self_gender(text: str, gender: str) -> str:
    for table in (_HI_PRESENT, _HI_FUTURE, _RO_PRESENT, _RO_FUTURE):
        pattern, repl = table[gender]
        text = pattern.sub(lambda m, r=repl: m.group(0) if m.group(1) in _HI_KEEP else m.expand(r), text)
    return text


# ---- speaking style -------------------------------------------------------------

_MARKDOWN = re.compile(r"[*_#`>|~]+")
_BULLET = re.compile(r"^\s*(?:[-•]|\d+[.)])\s+", re.M)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")
_BRACKETS = re.compile(r"[()\[\]{}\"“”‘’«»]")
_DASH = re.compile(r"\s+[-–—]+\s+|\s*[–—]+\s*|\s+-(?=\s*\S)")    # " - " used as a separator, not 2-3 or e-mail
_SENTENCE = re.compile(r"(?<=[.!?।])\s+")
_LETTER_OR_DIGIT = re.compile(r"[^\W_]", re.UNICODE)
# Indian-script digits -> 0-9: the voice reads ASCII digits more reliably
_DIGITS = str.maketrans({chr(base + i): str(i) for base in (0x0966, 0x09E6, 0x0BE6, 0x0C66, 0x0CE6, 0x0D66, 0x0AE6, 0x0A66, 0x0B66)
                         for i in range(10)})


def speakable(text: str) -> str:
    """
    Make text safe and natural to speak: no markdown, bullets, emoji,
    brackets, quotes or dash separators, and no sentence without a single
    letter or digit (Sarvam rejects those, and the call hears silence).
    """
    text = _BULLET.sub("", text)
    text = _MARKDOWN.sub("", text)
    text = _EMOJI.sub("", text)
    text = _BRACKETS.sub("", text)
    text = _DASH.sub(", ", text)
    text = text.replace(":", ",").translate(_DIGITS)
    text = re.sub(r"\s*,\s*(,\s*)+", ", ", text)           # ", ," -> ","
    text = re.sub(r"\s+([,.!?।])", r"\1", text)
    text = re.sub(r"([.!?।])[\s.!?।]*(?=[.!?।])", "", text)  # "।।" or "। ।" -> "।"
    sentences = [x.strip(" ,") for x in _SENTENCE.split(" ".join(text.split()))]
    return " ".join(x for x in sentences if _LETTER_OR_DIGIT.search(x))


def spoken_date(iso: str | None) -> str | None:
    """"2026-11-05" -> "5 November 2026": what a person would say."""
    if not iso:
        return None
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {d:%B %Y}"


# Said while a lookup runs, so the caller isn't left in silence.
FILLERS = {
    "hi": {"female": ["एक सेकंड, मैं देख रही हूँ।", "जी, अभी चेक करती हूँ।", "ठीक है, एक पल रुकिए।"],
           "male": ["एक सेकंड, मैं देख रहा हूँ।", "जी, अभी चेक करता हूँ।", "ठीक है, एक पल रुकिए।"]},
    "mr": {"female": ["एक सेकंद, मी बघते.", "हो, लगेच तपासते."], "male": ["एक सेकंद, मी बघतो.", "हो, लगेच तपासतो."]},
    "ta": {"female": ["ஒரு நிமிடம், பார்க்கிறேன்.", "சரி, இப்போதே பார்க்கிறேன்."],
           "male": ["ஒரு நிமிடம், பார்க்கிறேன்.", "சரி, இப்போதே பார்க்கிறேன்."]},
    "bn": {"female": ["এক সেকেন্ড, দেখে নিচ্ছি।"], "male": ["এক সেকেন্ড, দেখে নিচ্ছি।"]},
    "te": {"female": ["ఒక్క క్షణం, చూస్తాను."], "male": ["ఒక్క క్షణం, చూస్తాను."]},
    "en": {"female": ["One moment, let me check.", "Sure, just a second.", "Okay, let me look that up."],
           "male": ["One moment, let me check.", "Sure, just a second.", "Okay, let me look that up."]},
}
# Tools that look something up; quick checks like identify_value need no filler.
LOOKUP_TOOLS = {
    "verify_customer", "check_otp", "get_loan_status", "get_emi_schedule", "get_foreclosure_quote",
    "list_pending_documents", "explain_rejection", "check_ticket", "verify_staff", "lookup_case",
    "diagnose_case", "count_cases", "queue_status", "retry_bureau_pull",
}


def filler(language: str | None, gender: str) -> str:
    lang = (language or "hi")[:2]
    return random.choice(FILLERS.get(lang, FILLERS["en"])[gender])


def greeting(line: str, gender: str) -> str:
    f = gender == "female"
    if line == "customer":
        return ("नमस्ते! मैं वाणी बोल रही हूँ, आपकी AI सहायक। ये कॉल रिकॉर्ड हो रही है। बताइए, आज मैं आपकी क्या मदद कर सकती हूँ?"
                if f else
                "नमस्ते! मैं वाणी बोल रहा हूँ, आपका AI सहायक। ये कॉल रिकॉर्ड हो रही है। बताइए, आज मैं आपकी क्या मदद कर सकता हूँ?")
    return ("नमस्ते, स्टाफ़ हेल्पडेस्क से वाणी बोल रही हूँ। ये कॉल रिकॉर्ड हो रही है। शुरू करने के लिए अपना employee ID बताइए।"
            if f else
            "नमस्ते, स्टाफ़ हेल्पडेस्क से वाणी बोल रहा हूँ। ये कॉल रिकॉर्ड हो रही है। शुरू करने के लिए अपना employee ID बताइए।")
