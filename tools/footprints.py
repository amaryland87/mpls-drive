"""OpenStreetMap geometry helpers and the building footprint list, shared by
fetch_lidar.py (which measures the buildings) and bake_tiles.py (which draws them).

Map data (c) OpenStreetMap contributors, ODbL.
"""
import glob, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY

CACHE = os.path.join(HERE, 'osm-cache')


def m(lat, lon):
    return (lon - LON0) * MX, -(lat - LAT0) * MY


def load_osm(pattern):
    seen, out = set(), []
    for path in sorted(glob.glob(os.path.join(CACHE, pattern + '.json'))):
        for e in json.load(open(path))['elements']:
            k = (e['type'], e['id'])
            if k not in seen:
                seen.add(k)
                out.append(e)
    return out


def rings(e):
    """[(role, [(x,z),...])] for a way or a multipolygon relation."""
    if e['type'] == 'way':
        return [('outer', [m(p['lat'], p['lon']) for p in e.get('geometry', [])])]
    # Multipolygon members are often fragments of one ring: stitch them end to end.
    res = []
    for role in ('outer', 'inner'):
        parts = [[(p['lat'], p['lon']) for p in mem['geometry']]
                 for mem in e.get('members', [])
                 if mem.get('type') == 'way' and mem.get('geometry') and (mem.get('role') or 'outer') == role]
        while parts:
            ring = parts.pop(0)
            grown = True
            while ring[0] != ring[-1] and grown:
                grown = False
                for i, p in enumerate(parts):
                    if p[0] == ring[-1]:
                        ring += p[1:]
                    elif p[-1] == ring[-1]:
                        ring += p[::-1][1:]
                    elif p[-1] == ring[0]:
                        ring = p + ring[1:]
                    elif p[0] == ring[0]:
                        ring = p[::-1] + ring[1:]
                    else:
                        continue
                    parts.pop(i)
                    grown = True
                    break
            res.append((role, [m(la, lo) for la, lo in ring]))
    return res


def area_of(r):
    a = 0
    for i in range(len(r)):
        x1, z1 = r[i]; x2, z2 = r[(i + 1) % len(r)]
        a += x1 * z2 - x2 * z1
    return abs(a) / 2


def centroid(r):
    return sum(p[0] for p in r) / len(r), sum(p[1] for p in r) / len(r)


def inside(x, z, r):
    hit = False
    for i in range(len(r)):
        (x1, z1), (x2, z2) = r[i - 1], r[i]
        if (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1):
            hit = not hit
    return hit


def bbox_of(pts, pad):
    xs = [p[0] for p in pts]; zs = [p[1] for p in pts]
    return min(xs) - pad, min(zs) - pad, max(xs) + pad, max(zs) + pad


def min_rect(r):
    """Smallest rotated rectangle around a footprint: (cx, cz, angle, long side, short side, area)."""
    best = None
    for i in range(len(r)):
        (x1, z1), (x2, z2) = r[i], r[(i + 1) % len(r)]
        L = math.hypot(x2 - x1, z2 - z1)
        if L < 0.5:
            continue
        ux, uz = (x2 - x1) / L, (z2 - z1) / L
        us = [x * ux + z * uz for x, z in r]
        vs = [-x * uz + z * ux for x, z in r]
        a = (max(us) - min(us)) * (max(vs) - min(vs))
        if best is None or a < best[0]:
            mu, mv = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
            best = (a, mu * ux - mv * uz, mu * uz + mv * ux, math.atan2(uz, ux), max(us) - min(us), max(vs) - min(vs))
    if best is None:
        return None
    a, cx, cz, ang, w, d = best
    if d > w:
        ang, w, d = ang + math.pi / 2, d, w
    return cx, cz, ang, w, d, a


def buildings():
    """Every building to draw, as dicts with a stable 'key' (OSM type, id and ring number)."""
    parts, outlines = [], []
    for e in load_osm('bld_*'):
        t = e.get('tags', {})
        if e['type'] == 'relation' and t.get('type') != 'multipolygon':
            continue                      # type=building relations just group outlines and parts we already have
        rs = [(role, r[:-1] if len(r) > 1 and r[0] == r[-1] else r) for role, r in rings(e)]
        rs = [(role, r) for role, r in rs if len(r) >= 3]
        outer = [r for role, r in rs if role == 'outer']
        for k, o in enumerate(outer):     # each outer ring is its own building; holes go with the ring they sit in
            holes = [r for role, r in rs if role == 'inner' and inside(*r[0], o)]
            a = area_of(o) - sum(area_of(h) for h in holes)
            if a < 8:
                continue
            cx, cz = centroid(o)
            rec = dict(key=f'{e["type"][0]}{e["id"]}.{k}', id=e['id'] * 4 + k, t=t, r=o, holes=holes, a=a, cx=cx, cz=cz)
            (parts if 'building:part' in t and 'building' not in t else outlines).append(rec)

    # An outline with 3D parts inside is drawn as those parts instead (the Simple 3D Buildings rule):
    # drawing both puts two walls in the same place, which flickers.
    PB = {}
    for p in parts:
        PB.setdefault((int(p['cx'] // 100), int(p['cz'] // 100)), []).append(p)
    out = []
    for o in outlines:
        x0, z0, x1, z1 = bbox_of(o['r'], 0)
        if not any(inside(p['cx'], p['cz'], o['r'])
                   for i in range(int(x0 // 100), int(x1 // 100) + 1)
                   for j in range(int(z0 // 100), int(z1 // 100) + 1)
                   for p in PB.get((i, j), ())):
            out.append(o)
    out += parts
    for b in out:
        b['rect'] = None if b['holes'] else min_rect(b['r'])
    return out


def load():
    """Footprints keyed for fetch_lidar.py: rect is (cx, cz, angle, long, short) when roughly rectangular."""
    res = {}
    for b in buildings():
        rect = b['rect']
        plain = rect is not None and b['a'] / max(rect[5], 1) > 0.8
        res[b['key']] = dict(r=b['r'], cx=b['cx'], cz=b['cz'], area=b['a'], rect=rect[:5] if plain else None)
    return res
