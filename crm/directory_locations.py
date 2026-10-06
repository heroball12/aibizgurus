"""Normalize explicit US city/state searches without a separate geocoding service."""

import re
import csv
import gzip
import math
from collections import Counter
import unicodedata
from functools import lru_cache
from pathlib import Path

US_STATES = dict(line.split("|", 1) for line in """AL|Alabama
AK|Alaska
AZ|Arizona
AR|Arkansas
CA|California
CO|Colorado
CT|Connecticut
DE|Delaware
DC|District of Columbia
FL|Florida
GA|Georgia
HI|Hawaii
ID|Idaho
IL|Illinois
IN|Indiana
IA|Iowa
KS|Kansas
KY|Kentucky
LA|Louisiana
ME|Maine
MD|Maryland
MA|Massachusetts
MI|Michigan
MN|Minnesota
MS|Mississippi
MO|Missouri
MT|Montana
NE|Nebraska
NV|Nevada
NH|New Hampshire
NJ|New Jersey
NM|New Mexico
NY|New York
NC|North Carolina
ND|North Dakota
OH|Ohio
OK|Oklahoma
OR|Oregon
PA|Pennsylvania
RI|Rhode Island
SC|South Carolina
SD|South Dakota
TN|Tennessee
TX|Texas
UT|Utah
VT|Vermont
VA|Virginia
WA|Washington
WV|West Virginia
WI|Wisconsin
WY|Wyoming
PR|Puerto Rico""".splitlines())


def city_and_state(value):
    value = re.sub(r"\s+", " ", (value or "").strip())
    value = re.sub(r",\s*(?:USA|United States|US)$", "", value, flags=re.I)
    aliases = {
        **{name.lower(): code for code, name in US_STATES.items()},
        **{code.lower(): code for code in US_STATES},
    }
    for suffix in sorted(aliases, key=len, reverse=True):
        match = re.fullmatch(r"(.+?)[,\s]+" + re.escape(suffix), value, re.I)
        if match:
            city = match[1].strip(" ,")
            if city and not city.isdigit():
                return city, aliases[suffix]
    raise ValueError(
        "Enter a US city and state, such as San Diego, CA. A city keeps the search focused; nationwide and ZIP-only searches are not supported."
    )


def place_key(value):
    value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    )
    value = re.sub(r"\bst[. ]", "saint ", value)
    value = re.sub(r"\bft[. ]", "fort ", value)
    value = re.sub(r"\bmt[. ]", "mount ", value)
    return re.sub(r"[^a-z0-9]", "", value)


def short_place_name(value):
    return re.sub(
        r" (?:city|town|village|borough|municipality|CDP|zona urbana|comunidad|unified government|metropolitan government)(?: \(balance\))?$",
        "",
        value,
    )


@lru_cache(maxsize=1)
def place_records():
    with gzip.open(
        Path(__file__).parent / "data/us_places_2025.csv.gz", "rt", encoding="utf-8"
    ) as source:
        rows = list(csv.DictReader(source))
    short_counts = Counter((place_key(short_place_name(row["name"])), row["state"]) for row in rows)
    full_counts = Counter((place_key(row["name"]), row["state"]) for row in rows)
    used = set()
    records = []
    for row in rows:
        short, state = short_place_name(row["name"]), row["state"]
        lat, lon = float(row["latitude"]), float(row["longitude"])
        label = short if short_counts[(place_key(short), state)] == 1 else row["name"]
        if full_counts[(place_key(label), state)] > 1:
            # Some states contain multiple CDPs with exactly the same name.
            # Distinguish them by a nearby incorporated place from the same
            # gazetteer instead of guessing which coordinate the user meant.
            anchors = [other for other in rows if other["state"] == state
                       and re.search(r" (?:city|town|village)$", other["name"])
                       and short_counts[(place_key(short_place_name(other["name"])), state)] == 1]
            anchors.sort(key=lambda other: (float(other["latitude"]) - lat) ** 2
                         + ((float(other["longitude"]) - lon) * math.cos(math.radians(lat))) ** 2)
            for anchor in anchors:
                label = f"{short} (near {short_place_name(anchor['name'])})"
                if (place_key(label), state) not in used:
                    break
            else:
                label = f"{short} ({lat:.6f}, {lon:.6f})"
        used.add((place_key(label), state))
        records.append((row["name"], label, state, lat, lon))
    return tuple(records)


@lru_cache(maxsize=1)
def city_index():
    index = {}
    for full_name, label, state, latitude, longitude in place_records():
        short = short_place_name(full_name)
        names = {short, full_name, label}
        if "/" in short:
            names.add(short.split("/", 1)[0])
        if full_name == "Urban Honolulu CDP":
            names.add("Honolulu")
        if full_name == "New York city":
            names.update(["New York City", "NYC"])
        if full_name == "Washington city":
            names.add("Washington DC")
        place = (label, state, latitude, longitude)
        for key in {place_key(name) for name in names}:
            index.setdefault((key, state), []).append(place)
    return index


@lru_cache(maxsize=1)
def canonical_city_index():
    return {(label.casefold(), state): (label, state, lat, lon)
            for _, label, state, lat, lon in place_records()}


def resolve_city(location):
    """Resolve locally so directory queries never scan national boundaries."""
    city, state = city_and_state(location)
    # Exact dropdown names take precedence over compact spelling aliases:
    # "Masontown" and the full place name "Mason town" are different places.
    exact = canonical_city_index().get((city.casefold(), state))
    if exact:
        return exact
    matches = city_index().get((place_key(city), state), [])
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError(
            f"More than one {city} is listed in {state}. Choose the specific place from the city dropdown."
        )
    raise ValueError(
        f"Could not find {city}, {state} in the US city index. Check the spelling or choose a nearby city."
    )


@lru_cache(maxsize=54)
def city_choices(state):
    """Use the same local index for dropdowns and directory coordinates.

    Ambiguous names keep their Census place type so every submitted option
    resolves to exactly one reference point, even within the same state.
    """
    if state not in US_STATES:
        return ()
    return tuple(sorted(
        ((label, label) for _, label, code, _, _ in place_records() if code == state),
        key=lambda item: item[1].casefold(),
    ))
