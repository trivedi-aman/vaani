"""
Native script -> phonetic Roman.

Speech-to-text returns Hindi and Marathi in Devanagari and Tamil in Tamil
script, but customer records are stored in Roman letters. Everything is
compared in one phonetic Roman space, so this module converts native script
into it.

The output is plain lowercase Roman with long vowels doubled (aa, ee, oo)
and retroflex consonants marked with a dot below (ṭ ḍ ṇ ḷ ṛ). The phonetic
matcher reads those marks; `plain()` strips them for anything that wants
ordinary letters.

Hindi needs schwa deletion: the inherent "a" written in every consonant is
often silent (मोहन is "mohan", not "mohana"; बाड़मेर is "baaṛmer"). Tamil has
no silent schwa but voices stops between vowels and after nasals
(முருகன் is "murugan", not "murukan").
"""
import re
import unicodedata

# ---------------------------------------------------------------- Devanagari

_DEV_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "ṭ", "ठ": "ṭh", "ड": "ḍ", "ढ": "ḍh", "ण": "ṇ",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "ळ": "ḷ", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}
# consonant + nukta, as precomposed characters or base + U+093C
_DEV_NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "ṛ", "ढ": "ṛh", "फ": "f", "य": "y", "र": "r"}
_DEV_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ॲ": "e",
}
_DEV_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}
_VIRAMA, _NUKTA, _ANUSVARA, _CHANDRABINDU, _VISARGA = "्", "़", "ं", "ँ", "ः"
_DEV_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}


def _devanagari_word(word: str) -> str:
    # Split the word into units: (consonant cluster, vowel, vowel_is_inherent).
    word = unicodedata.normalize("NFD", word)
    units: list[list] = []
    cluster: list[str] = []
    i = 0
    while i < len(word):
        ch = word[i]
        nxt = word[i + 1] if i + 1 < len(word) else ""
        if ch in _DEV_CONS:
            sound = _DEV_NUKTA.get(ch, _DEV_CONS[ch]) if nxt == _NUKTA else _DEV_CONS[ch]
            if nxt == _NUKTA:
                i += 1
                nxt = word[i + 1] if i + 1 < len(word) else ""
            cluster.append(sound)
            if nxt == _VIRAMA:              # half consonant: joins the next one
                i += 2
                continue
            if nxt in _DEV_MATRAS:
                units.append([cluster, _DEV_MATRAS[nxt], False])
                i += 2
            else:
                units.append([cluster, "a", True])
                i += 1
            cluster = []
            continue
        if ch in _DEV_VOWELS:
            units.append([[], _DEV_VOWELS[ch], False])
        elif ch in (_ANUSVARA, _CHANDRABINDU):
            if units:
                units[-1][1] += "n"         # nasal after the vowel
        elif ch in _DEV_DIGITS:
            units.append([[], _DEV_DIGITS[ch], False])
        i += 1
    if cluster:                             # word ends in a half consonant
        units.append([cluster, "", False])

    # Schwa deletion, right to left (Ohala's rule, simplified):
    #  - a final inherent "a" is dropped unless it follows a conjunct (मिश्र)
    #  - a medial inherent "a" is dropped in V C _ C V, i.e. when it sits on a
    #    single consonant, between two syllables that keep their vowels.
    keep = [True] * len(units)
    for k in range(len(units) - 1, 0, -1):
        cons, vowel, inherent = units[k]
        if not inherent:
            continue
        if k == len(units) - 1:
            if len(cons) == 1:
                keep[k] = False
            continue
        nxt_cons, nxt_vowel, _ = units[k + 1]
        if len(cons) == 1 and len(nxt_cons) == 1 and keep[k + 1] and keep[k - 1] and nxt_vowel:
            keep[k] = False

    out = []
    for (cons, vowel, inherent), kept in zip(units, keep):
        out.append("".join(cons))
        if kept or not inherent:
            out.append(vowel)
        elif vowel.endswith("n") and vowel != "a":
            out.append("n")
    return "".join(out)


# ---------------------------------------------------------------- Tamil

_TA_CONS = {
    "க": "k", "ங": "ng", "ச": "ch", "ஞ": "nj", "ட": "ṭ", "ண": "ṇ",
    "த": "t", "ந": "n", "ப": "p", "ம": "m", "ய": "y", "ர": "r",
    "ல": "l", "வ": "v", "ழ": "zh", "ள": "ḷ", "ற": "r", "ன": "n",
    "ஜ": "j", "ஷ": "sh", "ஸ": "s", "ஹ": "h",
}
_TA_VOWELS = {
    "அ": "a", "ஆ": "aa", "இ": "i", "ஈ": "ee", "உ": "u", "ஊ": "oo",
    "எ": "e", "ஏ": "e", "ஐ": "ai", "ஒ": "o", "ஓ": "o", "ஔ": "au",
}
_TA_MATRAS = {
    "ா": "aa", "ி": "i", "ீ": "ee", "ு": "u", "ூ": "oo",
    "ெ": "e", "ே": "e", "ை": "ai", "ொ": "o", "ோ": "o", "ௌ": "au",
}
_TA_PULLI = "்"
_TA_VOICED = {"k": "g", "t": "d", "ṭ": "ḍ", "p": "b", "ch": "s"}
_NASALS = {"ng", "nj", "ṇ", "n", "m"}


def _tamil_word(word: str) -> str:
    # Tamil writes vowel signs (ொ ோ ௌ) as two code points in some input;
    # NFC folds them back into one.
    word = unicodedata.normalize("NFC", word)
    word = word.replace("ட்ச", "க்ஷ")       # Tamil spells क्ष as ட்ச (லட்சுமி = Lakshmi)
    sounds: list[tuple[str, str]] = []      # (consonant or "", vowel or "")
    i = 0
    while i < len(word):
        ch = word[i]
        nxt = word[i + 1] if i + 1 < len(word) else ""
        if ch in _TA_CONS:
            if nxt == _TA_PULLI:
                sounds.append((_TA_CONS[ch], ""))
                i += 2
            elif nxt in _TA_MATRAS:
                sounds.append((_TA_CONS[ch], _TA_MATRAS[nxt]))
                i += 2
            else:
                sounds.append((_TA_CONS[ch], "a"))
                i += 1
            continue
        if ch in _TA_VOWELS:
            sounds.append(("", _TA_VOWELS[ch]))
        i += 1

    out = []
    for idx, (cons, vowel) in enumerate(sounds):
        prev = sounds[idx - 1] if idx else ("", "")
        nxt = sounds[idx + 1] if idx + 1 < len(sounds) else ("", "")
        if cons in _TA_VOICED:
            after_vowel = idx > 0 and prev[1] != ""
            after_nasal = idx > 0 and prev[0] in _NASALS and prev[1] == ""
            geminate = (prev[0] == cons and prev[1] == "") or (vowel == "" and nxt[0] == cons)
            if idx == 0 and cons == "ch":
                cons = "s"                  # சரவணன் -> saravanan
            elif vowel and not geminate and (after_vowel or after_nasal):
                # a single stop between vowels or after a nasal is voiced
                cons = "j" if (cons == "ch" and after_nasal) else _TA_VOICED[cons]
        out.append(cons + vowel)
    return "".join(out)


# ---------------------------------------------------------------- public API

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_TAMIL = re.compile(r"[஀-௿]")


def script_of(text: str) -> str:
    if _DEVANAGARI.search(text):
        return "devanagari"
    if _TAMIL.search(text):
        return "tamil"
    return "latin"


def to_roman(text: str) -> str:
    """Convert any mix of Devanagari, Tamil and Latin to phonetic Roman."""
    words = []
    for word in text.split():
        script = script_of(word)
        if script == "devanagari":
            words.append(_devanagari_word(word))
        elif script == "tamil":
            words.append(_tamil_word(word))
        else:
            words.append(word.lower())
    return " ".join(w for w in words if w)


def plain(text: str) -> str:
    """Drop the retroflex marks: 'baaṛmer' -> 'baarmer'."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))
