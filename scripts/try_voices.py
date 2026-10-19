"""
Listen to Sarvam's voices saying a real Vaani line, then pick one.

    python -m scripts.try_voices                 # all female bulbul:v3 voices
    python -m scripts.try_voices --male          # male voices
    python -m scripts.try_voices --pace 0.95 --voices ritu kavya

Writes one WAV per voice to var/voices/ and an index.html there that plays
them side by side. Set the one you like as SARVAM_TTS_VOICE in .env (and
SARVAM_TTS_PACE / SARVAM_TTS_TEMPERATURE if you changed them). Each voice
costs one short TTS request.
"""
import argparse
import base64
import html
import sys

import httpx

from agent.persona import FEMALE_VOICES, MALE_VOICES
from core.config import ROOT, get_settings
from pipecat.services.sarvam.tts import SarvamTTSSpeakerV3

V3 = [s.value for s in SarvamTTSSpeakerV3]
LINES = {
    "female": [
        ("hi-IN", "जी, आपकी आवाज़ बिल्कुल साफ़ आ रही है। बताइए, आज मैं आपकी क्या मदद कर सकती हूँ?"),
        ("hi-IN", "अरे, EMI bounce होना परेशानी वाली बात है। एक सेकंड, मैं आपका account देख लेती हूँ। आपकी ₹19,499 की EMI 5 अक्टूबर को bounce हुई थी।"),
        ("en-IN", "Sure, I can help with that. Could you tell me your full name first?"),
    ],
    "male": [
        ("hi-IN", "जी, आपकी आवाज़ बिल्कुल साफ़ आ रही है। बताइए, आज मैं आपकी क्या मदद कर सकता हूँ?"),
        ("hi-IN", "अरे, EMI bounce होना परेशानी वाली बात है। एक सेकंड, मैं आपका account देख लेता हूँ। आपकी ₹19,499 की EMI 5 अक्टूबर को bounce हुई थी।"),
        ("en-IN", "Sure, I can help with that. Could you tell me your full name first?"),
    ],
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--male", action="store_true", help="male voices instead of female")
    p.add_argument("--voices", nargs="*", help="only these voices")
    p.add_argument("--pace", type=float, default=None)
    p.add_argument("--temperature", type=float, default=None)
    args = p.parse_args()

    s = get_settings()
    if not s.voice_available:
        print("Set SARVAM_API_KEY in .env first.")
        return 1
    gender = "male" if args.male else "female"
    pool = MALE_VOICES if args.male else FEMALE_VOICES
    voices = args.voices or [v for v in V3 if v in pool]
    pace = args.pace if args.pace is not None else s.sarvam_tts_pace
    temperature = args.temperature if args.temperature is not None else s.sarvam_tts_temperature
    out = ROOT / "var" / "voices"
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    with httpx.Client(timeout=30) as client:
        for voice in voices:
            files = []
            for i, (lang, text) in enumerate(LINES[gender]):
                r = client.post("https://api.sarvam.ai/text-to-speech",
                                headers={"api-subscription-key": s.sarvam_api_key.get_secret_value()},
                                json={"text": text, "target_language_code": lang, "speaker": voice,
                                      "model": "bulbul:v3", "pace": pace, "temperature": temperature})
                if r.status_code != 200:
                    print(f"{voice}: failed ({r.status_code}) {r.text[:200]}")
                    break
                path = out / f"{voice}-{i + 1}.wav"
                path.write_bytes(base64.b64decode("".join(r.json()["audios"])))
                files.append(path.name)
            if files:
                print(f"{voice}: {', '.join(files)}")
                rows.append((voice, files))

    page = ["<!doctype html><meta charset=utf-8><title>Vaani voices</title>",
            "<style>body{font:15px system-ui;margin:24px;max-width:900px}td{padding:6px 10px}</style>",
            f"<h1>Voices (pace {pace}, temperature {temperature})</h1><table>"]
    for voice, files in rows:
        page.append(f"<tr><th>{html.escape(voice)}</th>" +
                    "".join(f'<td><audio controls src="{html.escape(f)}"></audio></td>' for f in files) + "</tr>")
    page.append("</table><p>Put your pick in .env as SARVAM_TTS_VOICE.</p>")
    (out / "index.html").write_text("\n".join(page), encoding="utf-8")
    print(f"\nOpen {out / 'index.html'} in your browser to compare.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
