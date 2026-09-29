"""Normalize explicit US city/state searches without a separate geocoding service."""

import re
import csv
import gzip
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
    return re.sub(r"[^a-z0-9]", "", value)


def short_place_name(value):
    return re.sub(
        r" (?:city|town|village|borough|municipality|CDP|zona urbana|comunidad|unified government|metropolitan government)(?: \(balance\))?$",
        "",
        value,
    )


@lru_cache(maxsize=1)
def city_index():
    index = {}
    with gzip.open(
        Path(__file__).parent / "data/us_places_2025.csv.gz", "rt", encoding="utf-8"
    ) as source:
        for row in csv.DictReader(source):
            full_name = row["name"]
            city = short_place_name(full_name)
            names = {city, full_name}
            if "/" in city:
                names.add(city.split("/", 1)[0])
            if full_name == "Urban Honolulu CDP":
                names.add("Honolulu")
            if full_name == "New York city":
                names.update(["New York City", "NYC"])
            if full_name == "Washington city":
                names.add("Washington DC")
            place = (
                city,
                row["state"],
                float(row["latitude"]),
                float(row["longitude"]),
            )
            for key in {place_key(name) for name in names}:
                index.setdefault((key, row["state"]), []).append(place)
    return index


def resolve_city(location):
    """Resolve locally so directory queries never scan national boundaries."""
    city, state = city_and_state(location)
    matches = city_index().get((place_key(city), state), [])
    if len(matches) == 1:
        if len(city_index().get((place_key(matches[0][0]), state), [])) > 1:
            return (city, *matches[0][1:])
        return matches[0]
    if matches:
        raise ValueError(
            f"More than one {city} is listed in {state}. Include the place type (city, town or village), or choose a nearby city."
        )
    raise ValueError(
        f"Could not find {city}, {state} in the US city index. Check the spelling or choose a nearby city."
    )
