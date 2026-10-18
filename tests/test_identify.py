from datetime import date

import pytest

from identify import ids, resolve
from identify.dates import financial_year, parse_dob, parse_event
from identify.numbers import parse_digits, parse_value, parse_year
from identify.phonetic import name_distance
from identify.result import HIGH, LOW, MEDIUM
from identify.translit import to_roman

TODAY = date(2026, 10, 18)


# ---- script conversion -------------------------------------------------------

@pytest.mark.parametrize("native, roman", [
    ("मोहन", "mohan"),                 # final schwa dropped
    ("बाड़मेर", "baaṛmer"),             # flap, medial schwa dropped
    ("मिश्र", "mishra"),                # schwa kept after a conjunct
    ("नरेंद्र", "narendra"),
    ("सरस्वती", "sarasvatee"),
    ("முருகன்", "murugan"),            # Tamil stop voiced between vowels
    ("கார்த்திக்", "kaarttik"),         # geminate and final stops stay voiceless
    ("மீனாட்சி", "meenaakshi"),        # Tamil ட்ச is ksh
    ("சரவணன்", "saravaṇan"),           # initial ச is s
])
def test_to_roman(native, roman):
    assert to_roman(native) == roman


# ---- phonetic distance -------------------------------------------------------

def test_variants_are_close_and_different_names_are_far():
    close = [("Barmer", "Baadmer"), ("Barmer", "बाड़मेर"), ("Vikram", "Wikram"), ("Sultan Meena", "Meena Sultan"),
             ("Murugan", "முருகன்"), ("Jaipur", "जयपुर"), ("Meenakshi", "மீனாட்சி")]
    far = [("Mohan", "Rohan"), ("Amit Jain", "Sumit Jain"), ("Rohan Verma", "Rohan Sharma"), ("Rohan Verma", "Rohan")]
    assert max(name_distance(a, b) for a, b in close) < 0.8
    assert min(name_distance(a, b) for a, b in far) > 1.5


# ---- numbers -----------------------------------------------------------------

@pytest.mark.parametrize("spoken, digits", [
    ("nine eight double six five four three two one zero", "9866543210"),
    ("teen zero do zero zero ek", "302001"),
    ("नौ आठ सात छह", "9876"),
    ("onbadhu ettu ezhu aaru", "9876"),
    ("ninety eight seventy six", "9876"),
    ("double nine triple seven", "99777"),
    ("mera number nine eight seven hai", "987"),    # words around the number are ignored
])
def test_parse_digits(spoken, digits):
    assert parse_digits(spoken).value == digits


@pytest.mark.parametrize("spoken, value", [
    ("do lakh pachaas hazaar", 250000), ("2.5 lakh", 250000), ("dhai lakh", 250000), ("adich lakh", 250000),
    ("saadhe teen hazaar", 3500), ("25k", 25000), ("₹2,50,000", 250000), ("twenty five thousand", 25000),
    ("दो लाख पचास हज़ार", 250000), ("rendu laksham", 200000), ("barah hazaar paanch sau", 12500),
])
def test_parse_value(spoken, value):
    assert parse_value(spoken)[0] == value


def test_amount_in_a_sentence_takes_the_amount_and_reports_the_rest():
    value, reading = parse_value("paisa do baar kat gaya, pachchees hazaar rupaye")
    assert value == 25000
    assert any("also heard" in u for u in reading.unknown)


@pytest.mark.parametrize("spoken", [
    "1987", "unnees sau sattaasi", "nineteen eighty seven", "unnees sattaasi", "उन्नीस सौ सत्तासी",
    "aayiratti tollaayiratti enbatti ezhu", "ஆயிரத்தி தொள்ளாயிரத்தி எண்பத்தி ஏழு", "ekonis she sattyaayshi",
])
def test_parse_year(spoken):
    assert parse_year(spoken)[0] == 1987


def test_fuzzy_number_words_need_a_sure_neighbour():
    # "raha" sounds like Marathi "daha" (10) but is a verb here
    assert parse_digits("aage nahi badh raha").value is None


# ---- dates -------------------------------------------------------------------

@pytest.mark.parametrize("spoken", [
    "23 April 87", "23rd April 1987", "teis April unnees sau sattaasi", "teis chaar unnees sau sattaasi",
    "23/04/1987", "23-4-87", "1987-04-23", "twenty third april nineteen eighty seven",
    "तेईस अप्रैल उन्नीस सौ सत्तासी", "இருபத்தி மூணு ஏப்ரல் ஆயிரத்தி தொள்ளாயிரத்தி எண்பத்தி ஏழு",
])
def test_parse_dob(spoken):
    assert parse_dob(spoken, today=TODAY).iso == "1987-04-23"


def test_dob_split_ambiguity_is_resolved_by_validity():
    # "bees chhah" could be day 26, but then no month is left: it must be 20 June
    assert parse_dob("bees chhah unnees sau satattar", today=TODAY).iso == "1977-06-20"


def test_dob_problems_are_reported():
    assert parse_dob("April 87", today=TODAY).missing == ["day"]
    assert parse_dob("31 farvari 1990", today=TODAY).iso is None
    assert "age" in parse_dob("5 june 2010", today=TODAY).note


@pytest.mark.parametrize("spoken, tense, iso", [
    ("pichhle mahine ki paanch tareekh", "", "2026-09-05"),
    ("kal", "past", "2026-10-17"),
    ("teen din pehle", "", "2026-10-15"),
    ("next month 5th", "", "2026-11-05"),
    ("nethu", "", "2026-10-17"),
    ("pona maasam anju tedi", "", "2026-09-05"),
    ("25 tareekh", "past", "2026-09-25"),
])
def test_parse_event(spoken, tense, iso):
    assert parse_event(spoken, TODAY, tense=tense).iso == iso


def test_kal_without_tense_is_ambiguous():
    r = parse_event("kal", TODAY)
    assert r.iso is None and r.candidates == ["2026-10-17", "2026-10-19"]


def test_financial_year():
    assert financial_year("pichhle saal ka", TODAY) == "2025-26"
    assert financial_year("FY26", TODAY) == "2025-26"
    assert financial_year("is saal", TODAY) == "2026-27"


# ---- identifiers -------------------------------------------------------------

@pytest.mark.parametrize("fn, spoken, value, confidence", [
    (ids.loan_id, "el en zero zero one two three", "LN00123", HIGH),
    (ids.loan_id, "मेरा लोन आईडी एल एन शून्य शून्य एक दो तीन है", "LN00123", HIGH),
    (ids.loan_id, "LN 123", "LN00123", MEDIUM),            # zeros assumed: read it back
    (ids.loan_id, "el en eleven", "LN00011", MEDIUM),
    (ids.loan_id, "aath", None, LOW),                      # a bare number is not a loan ID
    (ids.ticket_id, "complaint number tee kay ek zero zero ek paanch ek", "TK100151", HIGH),
    (ids.employee_id, "employee id 1042", "E1042", HIGH),
    (ids.phone, "plus nine one 98665 43210", "9866543210", HIGH),
    (ids.phone, "98665 4321", None, LOW),
    (ids.otp, "four five six seven eight nine", "456789", HIGH),
])
def test_ids(fn, spoken, value, confidence):
    r = fn(spoken)
    assert (r.value, r.confidence) == (value, confidence)


def test_near_ids_are_offered_not_accepted():
    assert ids.near_ids("LN00127", {"LN00121", "LN00127", "LN00137"}, "LN") == ["LN00121", "LN00137"]


# ---- resolution --------------------------------------------------------------

@pytest.mark.parametrize("heard, district", [
    ("Baadmer", "Barmer|Rajasthan"), ("बाड़मेर", "Barmer|Rajasthan"), ("Jaipuur", "Jaipur|Rajasthan"),
    ("Chenai", "Chennai|Tamil Nadu"), ("Trichy", "Tiruchirappalli|Tamil Nadu"), ("Seekar", "Sikar|Rajasthan"),
    ("लखनऊ", "Lucknow|Uttar Pradesh"),
])
def test_district(heard, district):
    assert resolve.district(heard).value == district


def test_confusable_city_is_read_back_not_accepted():
    r = resolve.district("Bangalore")          # also close to Mangalore
    assert r.value == "Bengaluru Urban|Karnataka" and r.confidence == MEDIUM


def test_pincode_contradicting_the_city_is_flagged():
    r = resolve.district("Barmer", pincode="302031")      # a Jaipur pincode
    assert r.confidence == LOW and "Jaipur" in r.issues[0]


def test_sound_alike_customers():
    people = [("C1", "Rohan Verma"), ("C2", "Mohan Verma"), ("C3", "Sohan Verma")]
    r = resolve.name("Rohun Varma", people)
    assert r.value == "C1"
    assert resolve.name("Verma Rohan", people).value == "C1"


def test_same_name_twice_is_never_confident():
    r = resolve.name("Priya Sharma", [("C1", "Priya Sharma"), ("C2", "Priya Sharma")])
    assert r.confidence == LOW


def test_result_actions():
    assert resolve.dob("teis April unnees sau sattaasi", today=TODAY).action == "accept"
    assert ids.loan_id("LN 123").action == "read_back"
    assert ids.loan_id("aath").action == "ask_again"
