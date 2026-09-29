# Offline city coordinates

`us_places_2025.csv.gz` contains 32,350 public place names, state abbreviations and representative coordinates from the **US Census Bureau 2025 National Places Gazetteer** (50 states, DC and Puerto Rico). It contains no business listings, contacts or credentials. Gazetteer representative points are not street addresses or exact municipal boundaries.

Source: https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_place_national.zip

Documentation: https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2025.html

Rebuild after downloading the source ZIP:

```sh
python scripts/build_finder_locations.py /path/to/2025_Gaz_place_national.zip
```

The deterministic build retains only four columns and compresses them to approximately 0.5 MB. Django loads the index once per process; searches do not call an external geocoder. Matching is case/accent-insensitive and accepts full state names. Ambiguous same-state place names require a place type or nearby city; no coordinates are guessed. The Finder searches around the representative point and labels results without an explicit city as “Near …”.
