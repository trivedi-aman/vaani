"""
Build data/reference/{pincodes,districts}.csv from the India Post
all-India pincode directory.

Source: India Post's pincode directory as published on data.gov.in, in the
compressed JSON-lines copy bundled with the MIT-licensed `indiapins` package
(data dated 21 Feb 2026). Download it once with

    pip download --no-deps indiapins

unzip the wheel, and pass the path to `indiapins/pins.json.bz2`:

    python scripts/build_reference.py /path/to/pins.json.bz2

The output is committed to the repo, so nobody needs to run this again
unless they want to refresh the data.
"""
import bz2
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "reference"


def tidy(name: str) -> str:
    """India Post uses upper case; turn it into readable title case."""
    out = []
    for w in name.strip().split():
        if "." in w:
            out.append(w.upper())            # Y.S.R.
        elif w.lower() in {"and", "of"}:
            out.append(w.lower())            # Jammu and Kashmir
        else:
            out.append(w.capitalize())
    return " ".join(out)


def main(src: str) -> None:
    offices = defaultdict(Counter)   # pincode -> Counter[(district, state)]
    names = defaultdict(list)        # pincode -> office names
    with bz2.open(src, "rt", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            pin, district, state = row.get("Pincode"), row.get("District"), row.get("State")
            if not (pin and district and state):
                continue
            key = (tidy(district), tidy(state))
            offices[str(pin)][key] += 1
            names[str(pin)].append(row["Name"].replace(" B.O", "").replace(" S.O", "").replace(" H.O", ""))

    OUT.mkdir(parents=True, exist_ok=True)
    district_pins = defaultdict(list)
    with open(OUT / "pincodes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pincode", "district", "state", "sample_office"])
        for pin in sorted(offices):
            (district, state), _ = offices[pin].most_common(1)[0]
            w.writerow([pin, district, state, names[pin][0]])
            district_pins[(district, state)].append(pin)

    with open(OUT / "districts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["district", "state", "pincode_count"])
        for (district, state), pins in sorted(district_pins.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            w.writerow([district, state, len(pins)])

    print(f"{len(offices)} pincodes, {len(district_pins)} districts -> {OUT}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
