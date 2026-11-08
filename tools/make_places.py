"""Erzeugt app/data/places.tsv.gz (Orte ab 1.000 Einwohnern) und app/data/countries_de.json.

Nur beim Entwickeln nötig – die erzeugten Dateien liegen im Repo.
Quellen:
- all-the-cities (npm, MIT) mit Daten von GeoNames (CC BY 4.0): cities.pbf, Protobuf-Nachrichten hintereinander
- i18n-iso-countries (npm, MIT): langs/de.json (deutsche Ländernamen)

Aufruf:  python -I tools/make_places.py <pfad/cities.pbf> <pfad/de.json> app/data
"""
import gzip
import json
import os
import sys


def varint(b, i):
    shift = result = 0
    while True:
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        if c < 0x80:
            return result, i
        shift += 7


def zigzag(n):
    return (n >> 1) ^ -(n & 1)


def read_cities(data: bytes):
    """Wie index.js von all-the-cities: Nachrichten mit Längenpräfix, Koordinaten als Differenzen."""
    i = 0
    last_lat = last_lon = 0
    while i < len(data):
        length, i = varint(data, i)
        end = i + length
        city = {"name": "", "country": "", "population": 0, "lat": 0.0, "lon": 0.0}
        while i < end:
            key, i = varint(data, i)
            tag, wire = key >> 3, key & 7
            if wire == 0:
                val, i = varint(data, i)
                if tag == 1:
                    pass
                elif tag == 9:
                    city["population"] = val
                elif tag == 10:
                    last_lon += zigzag(val)
                    city["lon"] = last_lon / 1e5
                elif tag == 11:
                    last_lat += zigzag(val)
                    city["lat"] = last_lat / 1e5
            elif wire == 2:
                n, i = varint(data, i)
                raw = data[i:i + n]
                i += n
                if tag == 2:
                    city["name"] = raw.decode("utf-8", "replace")
                elif tag == 3:
                    city["country"] = raw.decode("ascii", "replace")
            else:
                raise ValueError(f"unerwarteter Typ {wire}")
        yield city


if __name__ == "__main__":
    pbf, de_json, out = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out, exist_ok=True)
    with open(pbf, "rb") as f:
        cities = list(read_cities(f.read()))
    rows = []
    for c in cities:
        name = c["name"].replace("\t", " ").replace("\n", " ").strip()
        if name and len(c["country"]) == 2:
            rows.append(f"{c['lat']:.4f}\t{c['lon']:.4f}\t{name}\t{c['country']}\t{c['population']}")
    with gzip.open(os.path.join(out, "places.tsv.gz"), "wt", encoding="utf-8", compresslevel=9) as g:
        g.write("# Orte ab 1.000 Einwohnern – Daten: GeoNames (CC BY 4.0) über all-the-cities (MIT)\n")
        g.write("\n".join(rows) + "\n")
    with open(de_json, encoding="utf-8") as f:
        de = json.load(f)["countries"]
    names = {k: (v[0] if isinstance(v, list) else v) for k, v in de.items()}
    with open(os.path.join(out, "countries_de.json"), "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, sort_keys=True, indent=0)
    print(f"{len(rows)} Orte, {len(names)} Länder → {out}")
