# Vaani: multilingual voice agent for NBFC support

A browser-based voice agent for a lending company (NBFC) with two lines: a
customer helpline and an internal staff helpdesk. Callers speak Hindi,
Hinglish, Indian English, Marathi, Tamil and other Indian languages. The
focus is getting the facts right: names, dates, numbers, loan IDs and
places, heard through noisy speech-to-text.

**Status: step 1 of 7 done** — data, scenarios and the identification core,
all testable offline with no API keys. The agent (LangGraph + Amazon Nova on
Bedrock), voice (Sarvam STT/TTS via Pipecat) and the phone-simulator
frontend come next. The full design is in the project spec.

## Run it

```
pip install -r requirements.txt
python -m pytest                  # 139 tests, ~15 s
python -m eval.matchers           # matcher comparison -> eval/results/matchers.md
python -m eval.scenario_entities  # can every scenario's facts be recovered?
```

## The core idea

The LLM only *finds* an entity in what the caller said. Deterministic code
normalises it, matches it and scores it, and returns one of three actions:
**accept**, **read back** ("Maine suna 23 April 1987, sahi hai?") or **ask
again**. The LLM never decides that a DOB matched or a name is close enough.

```
heard ──► normalised ──► matched ──► confidence ──► accept / read back / ask again
"teis April unnees      1987-04-23   exact      high
 sau sattaasi"
"Baadmer"               baadmer      Barmer 0.60 high
"el en eleven"          LN00011      exact      medium  (zeros assumed)
"Bangalore"             bangalore    Bengaluru 0.00, Mangalore 0.45   medium
```

## What's in `identify/`

| Module | Does |
| --- | --- |
| `translit.py` | Devanagari and Tamil script → phonetic Roman, with Hindi schwa deletion (मोहन → mohan, बाड़मेर → baaṛmer) and Tamil voicing rules (முருகன் → murugan) |
| `phonetic.py` | Sound-weighted edit distance. Each sound has articulatory features; swapping similar sounds is cheap (Barmer/Baadmer 0.6), different ones expensive (Mohan/Rohan 1.7). Indian-specific confusions live in `data/reference/confusions.csv` |
| `numbers.py` | Spoken numbers in English, Hindi, Marathi and Tamil, Roman or native script. Digit strings ("nine eight double six"), values ("do lakh pachaas hazaar", "dhai lakh", "adich lakh") and years ("unnees sau sattaasi", "aayiratti tollaayiratti enbatti ezhu") |
| `dates.py` | DOBs in any spoken form; relative dates ("pichhle mahine ki paanch tareekh", "nethu", "3 din pehle"); financial years ("pichhle saal ka" → 2025-26). Hindi "kal" (yesterday *or* tomorrow) is reported as ambiguous unless the tense is known |
| `ids.py` | Phone, pincode, OTP, PIN, loan ID (LN + 5), employee ID (E + 4), ticket ID (TK + 6). Leading zeros are assumed but flagged; a near-miss loan ID is offered back, never accepted |
| `resolve.py` | Name and district matching with confidence levels; pincode cross-checks the district; city aliases (Trichy, Bangalore, Bombay) |

## Data

All records are synthetic; no real customer data exists anywhere in the
project. The parts that matter for matching are real:

- **Reference** (`data/reference/`): 19,486 India Post pincodes across 745
  districts (from India Post's directory via the `indiapins` package, built
  by `scripts/build_reference.py`); ~250 Indian names with Devanagari and
  Tamil spellings; city aliases.
- **Generated** (`data/generated/`, `scripts/generate_data.py`, seeded and
  reproducible): 300 customers, 341 loans across nine stages, 3,978 EMI rows,
  151 tickets, 20 staff, 202 branches. Pincode, district and state always
  agree.
- **Planted traps**: Rohan/Mohan/Sohan Verma; Ramesh/Mahesh/Suresh Gupta;
  Amit/Sumit Jain; two Priya Sharmas in different cities; two customers
  sharing a DOB; Kavita (Pune) and Kavitha (Chennai); customers in Barmer,
  Sikar and Sagar.
- **Scenarios** (`data/scenarios/`): 25 customer and 25 staff scenarios,
  each tied to a real record, with caller lines as STT returns them (Roman
  Hinglish, Devanagari, Tamil script, numbers as words) and expected values,
  tools and outcome.

Every customer's DOB and phone number is spoken in English, Hindi, Marathi
and Tamil and parsed back in the tests: 2,100 DOB and 1,200 phone round
trips, all passing.

## Results

Matcher comparison (`eval/results/matchers.md`), names against all 300
customers and places against all 745 districts:

| Test set | Items | Levenshtein | Metaphone | Phoneme |
| --- | --- | --- | --- | --- |
| Hand-written names (STT spellings, surname first, native script) | 62 | 96.8% | 96.8% | 100% |
| Hand-written places (Baadmer, Lakhnau, Koyambattur, old names) | 50 | 92.0% | 74.0% | 100% |
| Customer names in Devanagari / Tamil script | 254 | 97.6% | 97.6% | 100% |
| Rule-made spelling variants, names | 246 | 99.6% | 96.3% | 100% |
| Rule-made spelling variants, places | 170 | 97.6% | 90.0% | 100% |

On 200 callers who are **not** customers, the phoneme matcher asked again
for 194, read back 5, and wrongly gave high confidence to 1 ("Raman Patil"
matched customer "Raman Patel"). That one is why a name alone never
verifies anyone: the caller must also match DOB or phone, then an OTP.

**Read these numbers with care:**

- The rule-made variants use the same confusions the phoneme matcher was
  designed around, so that set flatters it. The hand-written and
  native-script sets are the fairer tests.
- After the first run I fixed two misses on the hand-written set (an
  "aw" spelling rule that broke Tawang, and the Hindi alias Lakhnau for
  Lucknow). Those sets are therefore not fully held out. The real test is
  the audio evaluation in a later step, with recordings of real people.
- The confidence thresholds are conservative on purpose: about a quarter of
  correct name matches still get a read-back or a re-ask. In lending,
  verifying the wrong person costs far more than one extra question.

## Known gaps

- The Marathi number table was written from standard references and still
  needs checking by a native speaker.
- Hindi "agle somvar" said on a Sunday is read as tomorrow; usage varies.
- District matching takes about 30 ms per call against 780 names, fine for
  a voice turn, but it is plain Python.

## Layout

```
identify/   the identification core (no network, no API keys)
data/       reference data, generated data, 50 scenarios
scripts/    builders for reference data, data and scenarios; speak.py renders values as callers say them
eval/       matcher comparison, scenario recoverability check
tests/      unit tests and data-consistency tests
```
