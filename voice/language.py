"""Which language a reply is in, from its script, so text-to-speech uses the right voice and pronunciation."""

# Unicode blocks of Indian scripts -> language codes Sarvam understands
_BLOCKS = [
    (0x0900, 0x097F, "devanagari"), (0x0980, 0x09FF, "bn-IN"), (0x0A00, 0x0A7F, "pa-IN"),
    (0x0A80, 0x0AFF, "gu-IN"), (0x0B00, 0x0B7F, "od-IN"), (0x0B80, 0x0BFF, "ta-IN"),
    (0x0C00, 0x0C7F, "te-IN"), (0x0C80, 0x0CFF, "kn-IN"), (0x0D00, 0x0D7F, "ml-IN"),
]


def reply_language(text: str, caller_language: str | None) -> str:
    """
    The language to speak `text` in. Devanagari is Marathi when the caller
    speaks Marathi, otherwise Hindi. Text with no Indian script is English.
    """
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for lo, hi, lang in _BLOCKS:
            if lo <= cp <= hi:
                counts[lang] = counts.get(lang, 0) + 1
                break
    if not counts:
        return "en-IN"
    lang = max(counts, key=counts.get)
    if lang == "devanagari":
        return "mr-IN" if (caller_language or "").startswith("mr") else "hi-IN"
    return lang
