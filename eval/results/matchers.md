# Matcher evaluation

982 test items. Names are matched against 300 customers; places against 745 districts plus aliases.

| Source | Kind | Items | Levenshtein top-1 | Metaphone top-1 | Phoneme top-1 | Phoneme top-3 |
| --- | --- | --- | --- | --- | --- | --- |
| handwritten | name | 62 | 96.8% | 96.8% | 100.0% | 100.0% |
| handwritten | place | 50 | 92.0% | 74.0% | 100.0% | 100.0% |
| native | name | 254 | 97.6% | 97.6% | 100.0% | 100.0% |
| rules | name | 246 | 99.6% | 96.3% | 100.0% | 100.0% |
| rules | place | 170 | 97.6% | 90.0% | 100.0% | 100.0% |

Levenshtein and Metaphone compare letters of the romanised text; for native-script input they get the same romanisation the phoneme matcher gets.

## Phoneme matcher: how often each confidence level is right

| Kind | Confidence | Items | Top-1 correct | What the agent does |
| --- | --- | --- | --- | --- |
| name | high | 425 | 100.0% | accepts |
| name | medium | 108 | 100.0% | reads it back |
| name | low | 29 | 100.0% | asks again |
| place | high | 195 | 100.0% | accepts |
| place | medium | 17 | 100.0% | reads it back |
| place | low | 8 | 100.0% | asks again |

## Callers who are not customers

200 random full names built from the same name lists, none of them a customer. The right outcome is anything but a confident match.

| Phoneme confidence | Items | Meaning |
| --- | --- | --- |
| high | 1 | wrongly accepted as a customer |
| medium | 5 | read back; the caller must confirm, and DOB/phone still has to match |
| low | 194 | asked again |

## Phoneme matcher misses

| Source | Kind | Heard | Expected | Top 3 | Confidence |
| --- | --- | --- | --- | --- | --- |
| absent | name | Raman Patil | (not a customer) | Raman Patel, Yamuna Patil, Manoj Patel | high |
