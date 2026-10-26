"""2905 and 2915 Dean Parkway, modelled by hand: run it to (re)write heroes/2905-dean.json and heroes/2915-dean.json.

    ../.venv/bin/python model_dean_apartments.py

Two four-storey brick apartment blocks side by side on Dean Parkway, between Lake of the Isles and Bde Maka Ska,
fronting west onto the parkway's lawn. Outlines are OpenStreetMap's (ways 121034871 and 121034883, in
osm-cache/bld_all.json); heights are measured from the full-density 2022 LiDAR over each lot (hero_house.py fetches
it into osm-cache/heroes/NAME/): flat roofs 11.65 m up behind brick parapets to 12.4 m, a brick stair and elevator
penthouse at the east end of each roof to about 15.3 m, and the ground falling away to the west, so the garden
storey stands clear of the lawn on the front. The look follows the 2022 aerial photo: red-brown brick with a pale
coping round the parapet, a white membrane roof on 2905 and a dark one on 2915, and the entrances in the bays on the
west front. Windows are a regular grid of white-framed sash windows, four rows, with limestone sills and belt courses.
"""
import json, math, os, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from hero_kit import L, Mesh
from footprints import m

CACHE = os.path.join(os.path.dirname(HERE), 'osm-cache')

ROOF = 11.65              # the roof membrane, above the ground at the building's centre
PARAPET = 12.4            # top of the parapet coping
PENTHOUSE = 15.3          # top of the rooftop penthouse
FLOORS = [-0.6, 2.4, 5.4, 8.4]   # the four storeys' floors: the garden storey half below the east side's ground
BAY = 2.7                 # window spacing along the walls
STONE = '#d8d0bf'         # limestone sills, belt courses and coping
FRAME = '#efece4'
GLASS = '#2a3846'
DOOR = '#4b3527'
CONCRETE = '#b9b4aa'

BUILDINGS = {
    # name: OSM way, brick tint (multiplied over the red brick layer), roof colour, the penthouse (x0, x1, z0, z1)
    '2905-dean': (121034871, '#e9cbbb', '#e4e2dc', (-4436.2, -4429.6, 1702.6, 1707.0)),
    '2915-dean': (121034883, '#dcbcaa', '#55575b', (-4433.4, -4427.4, 1729.4, 1733.8)),
}


def osm_ring(way):
    for e in json.load(open(os.path.join(CACHE, 'bld_all.json')))['elements']:
        if e['id'] == way:
            ring = [m(p['lat'], p['lon']) for p in e['geometry']]
            if ring[0] == ring[-1]:
                ring = ring[:-1]
            # wind it clockwise seen from above (x east, z south): outward normals are then (dz, -dx)
            area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))
            return ring if area > 0 else ring[::-1]
    sys.exit(f'way {way} not in osm-cache/bld_all.json')


def triangulate(ring):
    """Ear clipping: triangles over a simple polygon (no holes) as index triples."""
    idx = list(range(len(ring)))
    sign = 1 if sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])) > 0 else -1
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    out, guard = [], 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = ring[i0], ring[i1], ring[i2]
            if cross(a, b, c) * sign <= 1e-9:
                continue
            if any(cross(a, b, ring[j]) * sign > 0 and cross(b, c, ring[j]) * sign > 0 and cross(c, a, ring[j]) * sign > 0
                   for j in idx if j not in (i0, i1, i2)):
                continue
            out.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        out.append(tuple(idx))
    return out


def offset(ring, d):
    """The ring moved d metres inward (mitred at the corners)."""
    n = len(ring)
    out = []
    for k in range(n):
        p, c, q = ring[k - 1], ring[k], ring[(k + 1) % n]
        def inward(a, b):
            dx, dz = b[0] - a[0], b[1] - a[1]
            L_ = math.hypot(dx, dz) or 1
            return (-dz / L_, dx / L_)
        n0, n1 = inward(p, c), inward(c, q)
        mx, mz = n0[0] + n1[0], n0[1] + n1[1]
        cos = n0[0] * n1[0] + n0[1] * n1[1]
        k_ = d / max(0.3, 1 + cos)
        out.append((c[0] + mx * k_, c[1] + mz * k_))
    return out


def model(name, way, brick, roof_col, pent):
    ring = osm_ring(way)
    cx = sum(p[0] for p in ring) / len(ring)
    cz = sum(p[1] for p in ring) / len(ring)
    pts = np.load(os.path.join(CACHE, 'heroes', name, 'points.npy'))
    gp = pts[pts[:, 3] == 2]
    G0 = float(np.median(gp[np.hypot(gp[:, 0] - cx, gp[:, 1] - cz) < 20, 2]))

    def ground(x, z, r=2.5):
        near = gp[np.hypot(gp[:, 0] - x, gp[:, 1] - z) < r]
        return float(np.median(near[:, 2])) - G0 if len(near) else 0.0

    M = Mesh()
    base = min(ground(x, z) for x, z in ring) - 0.5
    walls = []
    for a, b in zip(ring, ring[1:] + ring[:1]):
        dx, dz = b[0] - a[0], b[1] - a[1]
        Lw = math.hypot(dx, dz)
        if Lw < 0.2:
            continue
        ux, uz = dx / Lw, dz / Lw
        nx, nz = uz, -ux                                     # outward
        walls.append((a, b, Lw, ux, uz, nx, nz))
        # the brick, from below the lowest ground up to the coping
        M.poly([(a[0], base, a[1]), (b[0], base, b[1]), (b[0], PARAPET - 0.25, b[1]), (a[0], PARAPET - 0.25, a[1])], L['brickRedPlain'], brick)

    def P(w, s, y, off=0.0):
        a, _, _, ux, uz, nx, nz = w
        return (a[0] + ux * s + nx * off, y, a[1] + uz * s + nz * off)

    def panel(w, s0, s1, y0, y1, off, layer, colour, depth=0.0):
        M.poly([P(w, s0, y0, off), P(w, s1, y0, off), P(w, s1, y1, off), P(w, s0, y1, off)], layer, colour)
        if depth:
            for s in (s0, s1):
                M.poly([P(w, s, y0, off - depth), P(w, s, y0, off), P(w, s, y1, off), P(w, s, y1, off - depth)], layer, colour)
            for y in (y0, y1):
                M.poly([P(w, s0, y, off - depth), P(w, s1, y, off - depth), P(w, s1, y, off), P(w, s0, y, off)], layer, colour)

    # The front: the westmost wall long enough for a doorway, with the ground falling to the parkway before it
    front = min((w for w in walls if w[5] < -0.9 and w[2] > 2.2), key=lambda w: (w[0][0] + w[1][0]) / 2)
    for w in walls:
        a, b, Lw, ux, uz, nx, nz = w
        # belt courses: over the garden storey, under the top storey's sills, and the cornice under the coping
        for y0, y1, out in ((FLOORS[1] - 0.25, FLOORS[1] + 0.05, 0.06), (11.0, 11.3, 0.1), (PARAPET - 0.25, PARAPET, 0.14)):
            panel(w, -out if y1 == PARAPET else 0, Lw + (out if y1 == PARAPET else 0), y0, y1, out, L['concPlain'], STONE, depth=out)
        # a pale base course along the ground
        g0 = min(ground(*P(w, 0, 0)[::2]), ground(*P(w, Lw, 0)[::2]))
        panel(w, 0, Lw, base, g0 + 0.35, 0.03, L['concPlain'], CONCRETE)
        # windows, a whole number of bays across, clear of the corners
        n = int((Lw - 1.2) // BAY)
        if n < 1:
            continue
        door_bay = n // 2 if w is front else -1
        for q in range(n):
            s = Lw / 2 + (q - (n - 1) / 2) * BAY
            for k, f in enumerate(FLOORS):
                sill = f + (1.25 if k == 0 else 0.9)
                if k == 0 and (q == door_bay or sill < ground(*P(w, s, 0, 0.5)[::2]) + 0.25):
                    continue
                h = 1.0 if k == 0 else 1.55
                M.window(lambda s_, y, off=0.0: P(w, s_, y, off), s, sill, 0.95, h, frame=FRAME, glass=GLASS)
                panel(w, s - 0.62, s + 0.62, sill - 0.2, sill - 0.08, 0.1, L['concPlain'], STONE, depth=0.1)   # the sill
        if door_bay >= 0:
            s = Lw / 2 + (door_bay - (n - 1) / 2) * BAY
            g = ground(*P(w, s, 0, 3.0)[::2])
            sill = g + 0.15 + 0.17 * 4
            # the doorway: a limestone surround, a glazed wood door and a transom, a lamp either side
            panel(w, s - 1.0, s + 1.0, sill - 0.05, sill + 3.0, 0.08, L['concPlain'], STONE, depth=0.08)
            panel(w, s - 0.6, s + 0.6, sill, sill + 2.25, 0.1, L['concPlain'], DOOR)
            panel(w, s - 0.35, s + 0.35, sill + 0.9, sill + 2.0, 0.11, L['glass'], GLASS)
            panel(w, s - 0.6, s + 0.6, sill + 2.35, sill + 2.85, 0.1, L['glass'], GLASS)
            for side in (-1, 1):
                panel(w, s + side * 1.25 - 0.1, s + side * 1.25 + 0.1, sill + 1.9, sill + 2.3, 0.2, L['concPlain'], '#20242a', depth=0.1)
            # a flat canopy over it
            panel(w, s - 1.15, s + 1.15, sill + 3.0, sill + 3.15, 1.3, L['concPlain'], STONE, depth=1.3)
            # steps down to the walk: a landing at the door, then steps of 17 cm
            M.poly([P(w, s - 1.3, sill, 0), P(w, s + 1.3, sill, 0), P(w, s + 1.3, sill, 1.4), P(w, s - 1.3, sill, 1.4)], L['concPlain'], CONCRETE)
            for k in range(4):
                y = sill - 0.17 * (k + 1)
                o0, o1 = 1.4 + 0.32 * k, 1.4 + 0.32 * (k + 1)
                M.poly([P(w, s - 1.3, y + 0.17, o0), P(w, s + 1.3, y + 0.17, o0), P(w, s + 1.3, y, o0), P(w, s - 1.3, y, o0)], L['concPlain'], CONCRETE)
                M.poly([P(w, s - 1.3, y, o0), P(w, s + 1.3, y, o0), P(w, s + 1.3, y, o1), P(w, s - 1.3, y, o1)], L['concPlain'], CONCRETE)
            for side in (-1, 1):
                ss = s + side * 1.3
                M.poly([P(w, ss, base, 0), P(w, ss, base, o1), P(w, ss, sill - 0.68, o1), P(w, ss, sill, 1.4), P(w, ss, sill, 0)], L['concPlain'], CONCRETE)

    # The roof behind the parapet, and the parapet's inside face
    inner = offset(ring, 0.3)
    for i0, i1, i2 in triangulate(inner):
        M.poly([(inner[i][0], ROOF, inner[i][1]) for i in (i0, i2, i1)], L['gravel'], roof_col)
    for a, b in zip(inner, inner[1:] + inner[:1]):
        M.poly([(b[0], ROOF, b[1]), (a[0], ROOF, a[1]), (a[0], PARAPET, a[1]), (b[0], PARAPET, b[1])], L['brickRedPlain'], brick)
    # the coping's top, from the outer face to the inner
    for (a, b), (c, d) in zip(zip(ring, ring[1:] + ring[:1]), zip(inner, inner[1:] + inner[:1])):
        M.poly([(a[0], PARAPET, a[1]), (b[0], PARAPET, b[1]), (d[0], PARAPET, d[1]), (c[0], PARAPET, c[1])], L['concPlain'], STONE)

    # The penthouse: stair and elevator, brick with a stone cap and a steel door to the roof
    x0, x1, z0, z1 = pent
    M.box(x0, x1, ROOF, PENTHOUSE - 0.2, z0, z1, L['brickRedPlain'], brick, top=L['gravel'], top_colour='#8a8780')
    M.box(x0 - 0.08, x1 + 0.08, PENTHOUSE - 0.2, PENTHOUSE, z0 - 0.08, z1 + 0.08, L['concPlain'], STONE)
    pw = M.on_wall('x', x0, -1)
    M.panel(pw, (z0 + z1) / 2 - 0.5, (z0 + z1) / 2 + 0.5, ROOF, ROOF + 2.1, 0.03, L['metal'], '#6d7276')
    # vents and a hatch on the roof
    for k, (vx, vz) in enumerate(((cx - 8, cz - 3), (cx - 2, cz + 3), (cx + 4, cz - 3))):
        M.box(vx - 0.3, vx + 0.3, ROOF, ROOF + 0.7, vz - 0.3, vz + 0.3, L['metal'], '#9a9ea2')

    rec = M.record(name, cx, cz, PENTHOUSE, [ring])
    json.dump(rec, open(os.path.join(HERE, name + '.json'), 'w'), separators=(',', ':'))
    print('wrote', name, len(M.tris), 'triangles; ground at the front', round(ground(*P(front, front[2] / 2, 0, 3)[::2]), 2))


for name, args in BUILDINGS.items():
    model(name, *args)
