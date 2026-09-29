"""Rebuild the offline city index from the official 2025 Census places ZIP.

Usage: python scripts/build_finder_locations.py /path/to/2025_Gaz_place_national.zip
Source: https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_place_national.zip
Only public place names, state abbreviations and coordinates are retained.
"""

import csv
import gzip
import io
from pathlib import Path
import sys
import zipfile


def main():
    with zipfile.ZipFile(sys.argv[1]) as archive:
        source = archive.read("2025_Gaz_place_national.txt").decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(source), delimiter="|"))
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["state", "name", "latitude", "longitude"])
    for row in sorted(rows, key=lambda row: (row["USPS"], row["NAME"], row["GEOID"])):
        lat, lon = float(row["INTPTLAT"]), float(row["INTPTLONG"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid Census coordinate")
        writer.writerow([row["USPS"], row["NAME"], lat, lon])
    target = Path(__file__).resolve().parents[1] / "crm/data/us_places_2025.csv.gz"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(gzip.compress(output.getvalue().encode(), mtime=0))
    print(
        f"Stored {len(rows)} public places in {target.name} ({target.stat().st_size:,} bytes)."
    )


if __name__ == "__main__":
    main()
