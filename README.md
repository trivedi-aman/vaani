# Vaani: multilingual voice agent for NBFC support

A browser-based voice agent for a lending company (NBFC) with two lines: a
customer helpline and an internal staff helpdesk. Callers speak Hindi,
Hinglish, Indian English, Marathi, Tamil and other Indian languages. The
focus is getting the facts right: names, dates, numbers, loan IDs and
places, heard through noisy speech-to-text.

Testers use a simulated phone in the browser (no real telephony, so the TRAI
rules on automated calling don't apply), pick one of 50 scenarios, get a
made-up identity, and call. A panel beside the phone shows every value as it
is heard, normalised, matched and scored.

| Part | Built with |
| --- | --- |
| Speech-to-text, text-to-speech | Sarvam (Saaras v4, Bulbul v3), 10 Indian languages + English, code-mixing |
| Agent | LangGraph tool-calling loop on Amazon Nova 2 Lite (Bedrock) |
| Real-time voice | Pipecat over WebRTC: voice activity detection, turn-taking, barge-in |
| Identification core | Our own: transliteration, phonetic matching, spoken numbers and dates (`identify/`) |
| Frontend | React + Vite phone simulator and live panel (`web/`) |

## Run it locally

You need Python 3.12+, Node 20+, a Sarvam API key (optional), and an AWS
IAM user allowed to call Nova 2 Lite on Bedrock. Store its keys with
`aws configure --profile vaani` (they go to `~/.aws/credentials`, never into
this project), set `AWS_PROFILE=vaani` in `.env`, then check access with
`python -m scripts.check_bedrock`.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env              # add SARVAM_API_KEY for voice; leave it empty for typing-only
cd web && npm ci && npm run build && cd ..
python -m server                  # http://localhost:7860
```

Without `SARVAM_API_KEY` the app runs in typing mode: same agent, same tools,
same panel. For frontend work, run `npm run dev` in `web/` (port 5173,
forwards `/api` to the Python server).

To host it for an interviewer, see [deploy/EC2.md](deploy/EC2.md): one EC2
instance, Docker, Caddy for HTTPS on a free `sslip.io` hostname.

## How it works

```
browser mic ─WebRTC─► Sarvam STT ─► turn detection (Silero VAD) ─► LangGraph agent ─► Sarvam TTS ─WebRTC─► speaker
                                                                     │
                                         gate ─► Nova ─► tools ─► gate ─► ... ─► reply
                                                           │
                                     identification core (code, not the LLM) + data store
```

**The LLM finds; code decides.** Nova picks out what the caller said
("teis April unnees sau sattaasi") and passes those exact words to a tool.
The tool normalises, matches and scores it, and tells the agent to accept,
read back ("Maine suna 23 April 1987, sahi hai?") or ask again. Nova never
decides that a DOB matched or a name is close enough.

```
heard                         normalised    matched                                  confidence
"teis April unnees sau sattaasi" 1987-04-23 exact                                    high
"Baadmer"                     baadmer       Barmer 0.60 (Bidar 2.75)                 high
"el en eleven"                LN00011       exact, zeros assumed                     medium → read back
"Bangalore"                   bangalore     Bengaluru 0.00, Mangalore 0.45           medium → read back
```

**Who may see what is decided in code.** Each call has a session holding
who the caller is proven to be. Before verification a customer can only
verify, find a branch, report fraud or ask for a callback. Account tools
appear only after name + DOB/mobile/loan ID **and** an OTP to the registered
mobile (shown on the simulated phone as an SMS). Staff log in with employee
ID + PIN, and their role decides their tools. Tools read identity from the
session, never from the model's arguments, so nothing a caller says to the
model can make it act for someone else. A final check stops internal notes
from ever being spoken to a customer.

## Making it sound human

- **Pick the voice by ear:** `python -m scripts.try_voices` renders the same
  Vaani lines in every female voice (`--male` for male) into
  `var/voices/index.html`. Put your pick in `SARVAM_TTS_VOICE`, and tune
  `SARVAM_TTS_PACE` and `SARVAM_TTS_TEMPERATURE`.
- **Gender follows the voice:** the prompt tells Vaani she is a woman (or a
  man) and how that changes Hindi and Marathi verbs. As a safety net, code
  corrects first-person forms like "sakta hoon" to "sakti hoon" before speaking.
- **Conversation, not a form:** Vaani answers what was said first ("haan, awaaz
  aa rahi hai"), finds out what the caller needs, and asks for verification
  only when the request needs their account, one detail at a time.
- **No dead air:** while it looks something up, Vaani says a short filler
  ("ek second, main dekh rahi hoon"), at most once per turn.
- **Read-aloud text:** dates come out as "5 November 2026", money as ₹19,499,
  and markdown and emoji are stripped before speech.

## What's where

| Folder | Contents |
| --- | --- |
| `identify/` | Transliteration (Devanagari, Tamil → phonetic Roman), phoneme-weighted matching, spoken numbers (en/hi/mr/ta), dates and relative dates, IDs, confidence |
| `agent/` | LangGraph graph, 25 tools with access rules, prompts, Bedrock model |
| `voice/` | Pipecat pipeline: Sarvam STT/TTS, VAD, agent bridge, reply-language switching, call limits |
| `server/` | FastAPI: calls, WebRTC signalling, typing mode, live events, rate limits, security headers |
| `core/` | Settings, data store, call sessions and OTPs, PII masking, audit log |
| `web/` | The phone simulator, scenario drawer and "under the hood" panel |
| `data/` | India Post reference data, synthetic NBFC data, 50 scenarios |
| `eval/` | Matcher comparison, scenario checks, live scenario runner |
| `deploy/` | EC2 guide, Caddyfile |

## Security and cost controls

All on by default. Settings are in `.env.example`.

- **Access:** an access code is needed to start calls. Production refuses to
  start without one (8+ characters) and without real host names.
- **Per-call tokens:** each call gets a random bearer token. The WebRTC
  connection, its ICE updates and the event stream are bound to the call
  that created them.
- **Verification:** OTPs are random, stored only as salted hashes, expire in
  5 minutes, and allow 3 tries. Three failed verifications lock the call.
  At most 3 OTPs are sent per call. Failure messages never say which detail
  was wrong.
- **Rate limits:** requests per IP, new calls per IP per hour, open calls per
  IP, access-code attempts, typed messages per call, WebRTC offers. There
  is also a daily call budget for everyone.
- **Cost caps:** concurrent voice calls (also keeps within Sarvam limits),
  call length, silence timeout, turns per call, agent steps per turn,
  records created per call. Bedrock calls retry with adaptive back-off and
  time out.
- **Hardening:** strict CSP and security headers, trusted hosts, request
  size limits, no stack traces in responses, no API docs in production.
  The container runs non-root on a read-only filesystem with all
  capabilities dropped.
- **Data:** logs and the audit trail mask phone numbers, dates of birth,
  OTPs and PINs. AWS credentials are never in the app's config: an IAM role
  on EC2, or your local AWS profile. All customer data is synthetic.

What a demo still trusts: the OTP is shown in the browser (there is no real
SMS), and data written during calls lives in memory until restart.

## Testing

```bash
python -m pytest                     # 188 tests, ~20 s, no API keys needed
python -m eval.matchers              # matcher comparison -> eval/results/matchers.md
python -m eval.scenario_entities     # every expected value recoverable from the caller's words?
python -m eval.run_scenarios         # all 50 scenarios against live Nova (needs AWS)
```

The tests cover:
- the identification core
- data consistency, and every customer's DOB and phone spoken in four
  languages and parsed back
- access rules (tools refused before verification, roles, lockouts, OTP
  limits, sound-alike impostors)
- the agent loop with a scripted model, including model failure and turn
  limits
- the server's limits and headers

## Results so far

Matcher comparison: names against all 300 customers, places against all
745 districts.

| Test set | Items | Levenshtein | Metaphone | Phoneme |
| --- | --- | --- | --- | --- |
| Hand-written names (STT spellings, surname first, native script) | 62 | 96.8% | 96.8% | 100% |
| Hand-written places (Baadmer, Lakhnau, Koyambattur, old names) | 50 | 92.0% | 74.0% | 100% |
| Customer names in Devanagari / Tamil script | 254 | 97.6% | 97.6% | 100% |
| Rule-made spelling variants, names | 246 | 99.6% | 96.3% | 100% |
| Rule-made spelling variants, places | 170 | 97.6% | 90.0% | 100% |

For 200 callers who are not customers, the phoneme matcher asked again for
194, read back 5, and wrongly gave high confidence to 1 ("Raman Patil" for
customer "Raman Patel").

**Read these numbers with care:**

- The rule-made variants use the confusions the phoneme matcher was designed
  around, so that set flatters it.
- Two misses on the hand-written set were fixed after the first run, so it
  is not fully held out.
- Different people can sound almost the same (Anil Patel and Anil Patil score
  0.35 apart), and a native-script spelling of a name can drift past 3.
  That is why the name is only a consistency check: the exact identifier
  plus the OTP is what verifies a caller.
- The live scenario run (`eval/run_scenarios.py`) has not been run yet,
  because it needs Bedrock access.

## Known gaps

- Not yet tested with live Bedrock and Sarvam keys, or with real recordings
  of callers. The voice pipeline is built and wired, but not heard end to end.
- The Marathi number words need checking by a native speaker.
- One server process: sessions, rate limits and call-created records live in
  memory. More than one instance would need Redis and a database behind the
  same interfaces.
- Callers on networks that block UDP need a TURN relay (`TURN_URL`) or
  typing mode.
