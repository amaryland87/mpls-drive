"""Put hero buildings into the baked tiles without baking the whole city again.

    .venv/bin/python place_heroes.py ../../public/mpls-drive/city 2905-dean 2915-dean

bake_tiles.py puts every heroes/NAME.json into its tile, in place of the ordinary buildings, houses, garages and trees
inside its outline, but it needs the whole map's cache (fetch_osm.py, fetch_lidar.py). This does the same for the
named heroes in the tiles already baked: it takes out what stands inside their outlines, and adds each hero (or
replaces the one already there at the same spot).
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import TILE, X0, Z0

OUT, names = sys.argv[1], sys.argv[2:]


def inside(rings, x, z):
    for ring in rings:
        hit = False
        for (ax, az), (bx, bz) in zip(ring, ring[1:] + ring[:1]):
            if (az > z) != (bz > z) and x < ax + (z - az) * (bx - ax) / (bz - az):
                hit = not hit
        if hit:
            return True
    return False


for name in names:
    hero = json.load(open(os.path.join(HERE, 'heroes', name + '.json')))
    rings = hero['rings']
    path = os.path.join(OUT, 't', f'{int((hero["x"] - X0) // TILE)}_{int((hero["z"] - Z0) // TILE)}.json')
    data = json.load(open(path))
    # Buildings: [facade, tint, height, base, flags, ring count, n, x, z, ...]; stand inside if their first ring's
    # middle does
    keep, gone = [], 0
    for b in data['b']:
        n = b[6]
        xs, zs = b[7:7 + 2 * n:2], b[8:8 + 2 * n:2]
        if inside(rings, sum(xs) / n, sum(zs) / n):
            gone += 1
        else:
            keep.append(b)
    data['b'] = keep
    # Houses (12 numbers each, x*10 and z*10 first), garages (8) and trees (4)
    for key, size in (('h', 12), ('g', 8), ('t', 4)):
        flat, out = data[key], []
        for k in range(0, len(flat), size):
            if inside(rings, flat[k] / 10, flat[k + 1] / 10):
                gone += 1
            else:
                out += flat[k:k + size]
        data[key] = out
    rec = {k: v for k, v in hero.items() if k != 'name'}
    data['hx'] = [h for h in data.get('hx', []) if (h['x'], h['z']) != (rec['x'], rec['z']) and not inside(rings, h['x'], h['z'])] + [rec]
    json.dump(data, open(path, 'w'), separators=(',', ':'))
    print(name, '->', os.path.relpath(path, OUT), 'replaced', gone, 'things')
