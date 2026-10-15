"""Bake the address and place search for Mpls Drive.

    .venv/bin/python bake_search.py ../../public/mpls-drive/city     # bake_tiles.py also runs this

Reads osm-cache/search.json and roads_all.json (from fetch_osm.py) and writes
search.json:
  st  [[street name, [house number, x, z, heading*100, ...] sorted by number, [x, z, heading*100]], ...]
      every address snapped onto the nearest drivable street, plus a spot
      halfway along the street for searches without a number
  pl  [[name, x, z, heading*100], ...]  named places and neighbourhoods
The game interpolates between known numbers for houses OpenStreetMap has no address for.

Map data (c) OpenStreetMap contributors, ODbL.
"""
import json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY, X0, X1, Z0, Z1

CACHE = os.path.join(HERE, 'osm-cache')
EDGE_IN = 150           # the game keeps the car this far inside the map
DRIVABLE = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'residential', 'unclassified', 'living_street',
            'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link'}
LOCAL = {'residential', 'unclassified', 'living_street', 'tertiary', 'secondary', 'primary'}
G = 100                 # metres per cell of the road lookup grid


def m(lat, lon):
    return (lon - LON0) * MX, -(lat - LAT0) * MY


def inside(x, z):
    return X0 + EDGE_IN <= x <= X1 - EDGE_IN and Z0 + EDGE_IN <= z <= Z1 - EDGE_IN


def bake(out):
    roads = [e for e in json.load(open(os.path.join(CACHE, 'roads_all.json')))['elements']
             if e['tags'].get('highway') in DRIVABLE]
    segs = {}          # grid cell -> [(ax, az, bx, bz, is local street, street name)]
    named = {}         # street name -> longest stretch of it on the map
    for e in roads:
        pts = [m(p['lat'], p['lon']) for p in e['geometry']]
        local = e['tags']['highway'] in LOCAL
        name = e['tags'].get('name')
        for (ax, az), (bx, bz) in zip(pts, pts[1:]):
            for i in range(int(min(ax, bx) // G), int(max(ax, bx) // G) + 1):
                for j in range(int(min(az, bz) // G), int(max(az, bz) // G) + 1):
                    segs.setdefault((i, j), []).append((ax, az, bx, bz, local, name))
        on_map = [p for p in pts if inside(*p)]
        if name and len(on_map) >= 2:
            L = sum(math.dist(a, b) for a, b in zip(on_map, on_map[1:]))
            if L > named.get(name, (0,))[0]:
                named[name] = (L, on_map)

    def snap(x, z, prefer_local=True, street=None):
        """Nearest point on a drivable street, with the street's heading. The address's own street
        wins if it's within reach (a corner house belongs on its own street, not the cross street),
        then house streets over freeways."""
        best = None
        for i in range(int(x // G) - 2, int(x // G) + 3):
            for j in range(int(z // G) - 2, int(z // G) + 3):
                for ax, az, bx, bz, local, name in segs.get((i, j), ()):
                    ex, ez = bx - ax, bz - az
                    L2 = ex * ex + ez * ez
                    if L2 < 1e-6:
                        continue
                    t = max(0, min(1, ((x - ax) * ex + (z - az) * ez) / L2))
                    px, pz = ax + ex * t, az + ez * t
                    d = math.hypot(px - x, pz - z) + (0 if local or not prefer_local else 60) + (0 if street is None or name == street else 120)
                    if best is None or d < best[0]:
                        best = (d, px, pz, math.atan2(ex, ez))
        if best is None:
            return None
        _, px, pz, h = best
        return round(px), round(pz), round(h * 100)

    src = json.load(open(os.path.join(CACHE, 'search.json')))
    streets = {}
    for street, num, lat, lon in src['addresses']:
        n = re.match(r'\d+', num.strip())
        x, z = m(lat, lon)
        if not n or not inside(x, z):
            continue
        s = snap(x, z, street=street.strip())
        if s:
            streets.setdefault(street.strip(), {})[int(n.group())] = s
    st = []
    for name in sorted(set(streets) | set(named)):
        nums = streets.get(name, {})
        flat = [v for k in sorted(nums) for v in (k,) + nums[k]]
        if name in named:
            pts = named[name][1]
            mid = pts[len(pts) // 2]
            spot = snap(*mid, prefer_local=False, street=name) or (round(mid[0]), round(mid[1]), 0)
        else:
            k = sorted(nums)[len(nums) // 2]
            spot = nums[k]
        st.append([name, flat, list(spot)])

    seen, pl = set(), []
    for name, lat, lon in src['places']:
        x, z = m(lat, lon)
        key = (name.lower(), round(x / 80), round(z / 80))
        if not inside(x, z) or key in seen:
            continue
        seen.add(key)
        s = snap(x, z)
        if s:
            pl.append([name] + list(s))
    pl.sort(key=lambda p: p[0].lower())
    json.dump({'st': st, 'pl': pl}, open(os.path.join(out, 'search.json'), 'w'), separators=(',', ':'))
    print('search: streets', len(st), 'addresses', sum(len(s[1]) // 4 for s in st), 'places', len(pl))


if __name__ == '__main__':
    bake(sys.argv[1])
