"""Erzeugt app/static/vendor/world.geojson aus world-atlas (TopoJSON, Natural Earth).

Nur beim Entwickeln nötig: Die erzeugte Datei liegt im Repo. Sie dient als Grundkarte,
wenn die Online-Kacheln nicht erreichbar sind (Kugel mit Ländern statt Straßenkarte).

Aufruf:  python tools/make_world.py pfad/zu/countries-50m.json app/static/vendor/world.geojson
"""
import json
import sys


def decode(topo: dict, name: str) -> dict:
    scale = topo.get("transform", {}).get("scale", [1, 1])
    translate = topo.get("transform", {}).get("translate", [0, 0])
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append([round(x * scale[0] + translate[0], 3), round(y * scale[1] + translate[1], 3)])
        arcs.append(pts)

    def ring(indexes):
        out = []
        for i in indexes:
            pts = arcs[i] if i >= 0 else list(reversed(arcs[~i]))
            out.extend(pts if not out else pts[1:])
        return out

    feats = []
    for g in topo["objects"][name]["geometries"]:
        if g["type"] == "Polygon":
            polys = [[ring(r) for r in g["arcs"]]]
        elif g["type"] == "MultiPolygon":
            polys = [[ring(r) for r in p] for p in g["arcs"]]
        else:
            continue
        out = []
        for poly in polys:
            if not any(_jumps(r) for r in poly):
                out.append(poly)
                continue
            # Ringe über die Datumsgrenze (Russland, Fidschi) bzw. um den Südpol (Antarktis): einzeln flach machen
            for r in poly:
                out.extend([[piece] for piece in fix_ring(r)])
        feats.append({"type": "Feature", "properties": {"name": (g.get("properties") or {}).get("name", "")},
                      "geometry": {"type": "MultiPolygon", "coordinates": out}})
    return {"type": "FeatureCollection", "features": feats}


def _jumps(r) -> int:
    return sum(1 for a, b in zip(r, r[1:]) if abs(a[0] - b[0]) > 180)


def _unwrap(r):
    out = [list(r[0])]
    for p in r[1:]:
        x = p[0]
        while x - out[-1][0] > 180:
            x -= 360
        while x - out[-1][0] < -180:
            x += 360
        out.append([x, p[1]])
    return out


def _clip(r, lo, hi):
    """Sutherland-Hodgman an zwei senkrechten Linien x=lo und x=hi."""
    def cut(pts, inside, xedge):
        res = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if inside(cur):
                if not inside(prev):
                    res.append(_cross(prev, cur, xedge))
                res.append(cur)
            elif inside(prev):
                res.append(_cross(prev, cur, xedge))
        return res
    pts = r[:-1] if r[0] == r[-1] else r
    pts = cut(pts, lambda p: p[0] >= lo, lo)
    if pts:
        pts = cut(pts, lambda p: p[0] <= hi, hi)
    return pts + [pts[0]] if len(pts) >= 3 else []


def _cross(a, b, x):
    t = (x - a[0]) / (b[0] - a[0])
    return [x, round(a[1] + t * (b[1] - a[1]), 3)]


def fix_ring(r):
    u = _unwrap(r)
    if abs(u[-1][0] - u[0][0]) > 180:  # umschließt einen Pol → über den Pol schließen
        pole = -90 if sum(p[1] for p in u) < 0 else 90
        u = u + [[u[-1][0], pole], [u[0][0], pole], u[0]]
    pieces = []
    for k in (-1, 0, 1):
        part = _clip(u, -180 + 360 * k, 180 + 360 * k)
        if part:
            pieces.append([[round(x - 360 * k, 3), y] for x, y in part])
    return pieces


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        topo = json.load(f)
    data = decode(topo, "countries")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"{len(data['features'])} Länder → {dst}")
