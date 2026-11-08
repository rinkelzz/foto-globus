"""Ortsnamen offline: Koordinaten → „Palma, Spanien“.

Grundlage sind alle Orte ab 1.000 Einwohnern aus GeoNames (app/data/places.tsv.gz, ca. 135.000 Orte, CC BY 4.0)
und deutsche Ländernamen (app/data/countries_de.json). Nichts verlässt die NAS.

Die Ortsliste wird nur beim Scan geladen (einige MB im Speicher) und danach wieder freigegeben.
"""
import gzip
import json
import math
import threading
from array import array
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DATA = Path(__file__).parent / "data"
MAX_KM = 50.0          # weiter weg → kein Ortsname mehr
COUNTRY_KM = 150.0     # bis hierhin wenigstens das Land (z. B. Gletscher, Nationalpark)
POP_WEIGHT = 3.0       # Stadtteile verlieren gegen die Großstadt: Wertung = km − 3 × log10(Einwohner)
CELL = 1.0             # Rastergröße in Grad für die Suche

# Kürzere, gebräuchliche Namen statt der amtlichen Langform
SHORT = {
    "US": "USA", "GB": "Großbritannien", "RU": "Russland", "KR": "Südkorea", "KP": "Nordkorea",
    "IR": "Iran", "SY": "Syrien", "LA": "Laos", "VN": "Vietnam", "BO": "Bolivien", "VE": "Venezuela",
    "TZ": "Tansania", "MD": "Moldau", "CZ": "Tschechien", "MK": "Nordmazedonien", "TW": "Taiwan",
    "AE": "Vereinigte Arabische Emirate", "CD": "Kongo (Dem. Rep.)", "CG": "Kongo", "VA": "Vatikanstadt",
}

# Deutsche Namen für bekannte Orte (GeoNames liefert hier die englische Form). Schlüssel: (Name, Land)
GERMAN = {
    ("Munich", "DE"): "München", ("Cologne", "DE"): "Köln", ("Nuremberg", "DE"): "Nürnberg",
    ("Hanover", "DE"): "Hannover", ("Brunswick", "DE"): "Braunschweig", ("Frankfurt am Main", "DE"): "Frankfurt am Main",
    ("Vienna", "AT"): "Wien", ("Zurich", "CH"): "Zürich", ("Geneva", "CH"): "Genf", ("Lucerne", "CH"): "Luzern",
    ("Basel", "CH"): "Basel", ("Bern", "CH"): "Bern",
    ("Rome", "IT"): "Rom", ("Milan", "IT"): "Mailand", ("Naples", "IT"): "Neapel", ("Venice", "IT"): "Venedig",
    ("Florence", "IT"): "Florenz", ("Turin", "IT"): "Turin", ("Genoa", "IT"): "Genua", ("Padua", "IT"): "Padua",
    ("Syracuse", "IT"): "Syrakus", ("Bolzano", "IT"): "Bozen", ("Merano", "IT"): "Meran", ("Mantova", "IT"): "Mantua",
    ("Lisbon", "PT"): "Lissabon", ("Seville", "ES"): "Sevilla", ("Saragossa", "ES"): "Saragossa",
    ("Prague", "CZ"): "Prag", ("Pilsen", "CZ"): "Pilsen", ("Brno", "CZ"): "Brünn", ("Karlovy Vary", "CZ"): "Karlsbad",
    ("Warsaw", "PL"): "Warschau", ("Krakow", "PL"): "Krakau", ("Kraków", "PL"): "Krakau", ("Gdańsk", "PL"): "Danzig",
    ("Wrocław", "PL"): "Breslau", ("Szczecin", "PL"): "Stettin", ("Poznań", "PL"): "Posen",
    ("Copenhagen", "DK"): "Kopenhagen", ("Brussels", "BE"): "Brüssel", ("Antwerpen", "BE"): "Antwerpen",
    ("Bruges", "BE"): "Brügge", ("Ghent", "BE"): "Gent", ("Liège", "BE"): "Lüttich",
    ("The Hague", "NL"): "Den Haag", ("Luxembourg", "LU"): "Luxemburg",
    ("Moscow", "RU"): "Moskau", ("Saint Petersburg", "RU"): "Sankt Petersburg", ("Kyiv", "UA"): "Kiew",
    ("Athens", "GR"): "Athen", ("Thessaloniki", "GR"): "Thessaloniki", ("Corfu", "GR"): "Korfu",
    ("Bucharest", "RO"): "Bukarest", ("Belgrade", "RS"): "Belgrad", ("Sofia", "BG"): "Sofia",
    ("Budapest", "HU"): "Budapest", ("Bratislava", "SK"): "Pressburg", ("Ljubljana", "SI"): "Laibach",
    ("Istanbul", "TR"): "Istanbul", ("Nicosia", "CY"): "Nikosia", ("Valletta", "MT"): "Valletta",
    ("Reykjavík", "IS"): "Reykjavík", ("Gothenburg", "SE"): "Göteborg", ("Helsinki", "FI"): "Helsinki",
    ("Tallinn", "EE"): "Tallinn", ("Riga", "LV"): "Riga", ("Vilnius", "LT"): "Wilna",
    ("London", "GB"): "London", ("Edinburgh", "GB"): "Edinburgh", ("Dublin", "IE"): "Dublin",
    ("Tokyo", "JP"): "Tokio", ("Kyoto", "JP"): "Kyoto", ("Beijing", "CN"): "Peking", ("Shanghai", "CN"): "Shanghai",
    ("Seoul", "KR"): "Seoul", ("Bangkok", "TH"): "Bangkok", ("Singapore", "SG"): "Singapur",
    ("New Delhi", "IN"): "Neu-Delhi", ("Cairo", "EG"): "Kairo", ("Jerusalem", "IL"): "Jerusalem",
    ("Cape Town", "ZA"): "Kapstadt", ("Mexico City", "MX"): "Mexiko-Stadt", ("New York City", "US"): "New York",
    ("Havana", "CU"): "Havanna", ("Rio de Janeiro", "BR"): "Rio de Janeiro", ("Montreal", "CA"): "Montreal",
    ("Quebec", "CA"): "Québec", ("Tunis", "TN"): "Tunis", ("Algiers", "DZ"): "Algier", ("Marrakesh", "MA"): "Marrakesch",
    ("Tbilisi", "GE"): "Tiflis", ("Yerevan", "AM"): "Jerewan", ("Damascus", "SY"): "Damaskus", ("Tehran", "IR"): "Teheran",
}

_lock = threading.Lock()
_index = None  # (lats, lons, names, ccs, grid)
_countries: Optional[Dict[str, str]] = None


def country_name(cc: Optional[str]) -> Optional[str]:
    global _countries
    if not cc:
        return None
    if _countries is None:
        try:
            _countries = json.loads((DATA / "countries_de.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _countries = {}
    return SHORT.get(cc) or _countries.get(cc) or cc


def all_countries() -> Dict[str, str]:
    country_name("DE")
    return {cc: SHORT.get(cc, n) for cc, n in (_countries or {}).items()}


def _load():
    lats, lons, pops = array("d"), array("d"), array("d")
    names: List[str] = []
    ccs: List[str] = []
    grid: Dict[Tuple[int, int], List[int]] = {}
    with gzip.open(DATA / "places.tsv.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            try:
                la, lo = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            i = len(names)
            lats.append(la)
            lons.append(lo)
            pops.append(math.log10(max(1, int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1000)))
            names.append(parts[2])
            ccs.append(parts[3])
            grid.setdefault((int(math.floor(la / CELL)), int(math.floor(lo / CELL))), []).append(i)
    return lats, lons, pops, names, ccs, grid


def load() -> None:
    global _index
    with _lock:
        if _index is None:
            _index = _load()


def unload() -> None:
    global _index
    with _lock:
        _index = None


def _km(la1, lo1, la2, lo2) -> float:
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def _candidates(lat: float, lon: float, radius: float):
    lats, lons, pops, names, ccs, grid = _index
    ci, cj = int(math.floor(lat / CELL)), int(math.floor(lon / CELL))
    rows = int(radius / 111.0 / CELL) + 1
    # in Ost-West-Richtung sind die Rasterfelder zu den Polen hin schmaler
    cols = 1 + int(radius / (111.0 * max(0.05, math.cos(math.radians(min(abs(lat), 89))))) / CELL)
    for di in range(-rows, rows + 1):
        for dj in range(-cols, cols + 1):
            j = (cj + dj + 180) % 360 - 180  # über die Datumsgrenze
            for i in grid.get((ci + di, j), ()):
                d = _km(lat, lon, lats[i], lons[i])
                if d <= radius:
                    yield i, d


def nearest(lat: float, lon: float) -> Optional[Tuple[Optional[str], str, float]]:
    """(Ort, Ländercode, Entfernung in km) – Ort ist None, wenn nur das Land bekannt ist; None, wenn gar nichts.

    Gewählt wird nicht stur der nächste Punkt: Größere Orte gewinnen gegen Stadtteile in ihrer Nähe
    („New York City“ statt „Hell's Kitchen“), Dörfer behalten ihren Namen gegen die Kreisstadt nebenan."""
    if _index is None:
        load()
    lats, lons, pops, names, ccs, grid = _index
    best, best_score, best_d = None, None, None
    for i, d in _candidates(lat, lon, MAX_KM):
        score = d - POP_WEIGHT * pops[i]
        if best_score is None or score < best_score:
            best, best_score, best_d = i, score, d
    if best is not None:
        name, cc = names[best], ccs[best]
        return GERMAN.get((name, cc), name), cc, round(best_d, 1)
    near = min(_candidates(lat, lon, COUNTRY_KM), key=lambda x: x[1], default=None)
    if near:
        return None, ccs[near[0]], round(near[1], 1)
    return None


def label(place: Optional[str], cc: Optional[str]) -> Optional[str]:
    if place and cc:
        return f"{place}, {country_name(cc)}"
    return country_name(cc) if cc else place
