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

2905 has its garage on the north side (2901 Dean Parkway, OSM way 121034879): one storey of brick under a flat gravel
roof with two rows of skylights, falling 0.3 m to the north (LiDAR), entered through an overhead door in its west wall
from a ramp and a parking lot that a drive joins to the parkway. A concrete walk runs from the foot of each building's
front steps across the lawn to the parkway's sidewalk. Everything on the ground follows the game's own ground
(city/ground.bin, as mpls-geo.js groundH has it), so walks, steps and drives meet the streets and sidewalks the game
draws.
"""
import gzip, json, math, os, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from hero_kit import L, Mesh
from footprints import m

CACHE = os.path.join(os.path.dirname(HERE), 'osm-cache')
CITY = os.path.join(HERE, '..', '..', '..', 'public', 'mpls-drive', 'city')

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
WALK = '#eceae4'          # as the game's sidewalks (mpls-geo.js)
ASPHALT = '#8d9194'       # as the game's local streets
GARAGE = 121034879        # 2905's garage

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


def game_ground():
    """groundH(x, z) from the baked city: the ground the game draws everything on, in metres."""
    idx = json.load(open(os.path.join(CITY, 'index.json')))
    gr, (x0, _, z0, _) = idx['gr'], idx['bounds']
    raw = open(os.path.join(CITY, 'ground.bin'), 'rb').read()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    H = np.cumsum(np.frombuffer(raw, '<i2').reshape(gr['nz'], gr['nx']).astype(np.int64), axis=1).ravel() / 100.0
    nx, nz, step = gr['nx'], gr['nz'], gr['step']

    def gh(x, z):
        fx = min(max((x - x0) / step, 0), nx - 1.001)
        fz = min(max((z - z0) / step, 0), nz - 1.001)
        i, j = int(fx), int(fz)
        u, v, k = fx - i, fz - j, j * nx + i
        if u + v <= 1:
            return H[k] + (H[k + 1] - H[k]) * u + (H[k + nx] - H[k]) * v
        return H[k + nx + 1] + (H[k + nx] - H[k + nx + 1]) * (1 - u) + (H[k + 1] - H[k + nx + 1]) * (1 - v)
    return gh


GH = game_ground()


def streets(x, z):
    """The streets (not paths) in the tile at (x, z): (half width, sidewalk centre out from the centreline, points)."""
    i, j = int((x + 7000) // 1000), int((z + 4000) // 1000)
    out = []
    for r in json.load(open(os.path.join(CITY, 't', f'{i}_{j}.json')))['rd']:
        if r[0] in (7, 8, 12, 13, 14):                  # freeways (no sidewalks) and paths
            continue
        hw = r[1] / 20
        walk = hw + (1.65 if r[0] in (10, 11) else 3.15)   # mpls-geo.js streetGeo's sidewalk bands
        out.append((hw, walk, [(r[7 + 2 * k] / 10, r[8 + 2 * k] / 10) for k in range(r[6])]))
    return out


def nearest_line(x, z, out_of):
    """The nearest point to (x, z) on any street's line out_of(hw, walk) metres from its centreline, on (x, z)'s side."""
    best = None
    for hw, walk, pts in streets(x, z):
        d = out_of(hw, walk)
        for (ax, az), (bx, bz) in zip(pts, pts[1:]):
            L_ = math.hypot(bx - ax, bz - az)
            if L_ < 0.1:
                continue
            ux, uz = (bx - ax) / L_, (bz - az) / L_
            side = 1 if (x - ax) * -uz + (z - az) * ux > 0 else -1
            ox, oz = -uz * d * side, ux * d * side
            t = max(0, min(L_, (x - ax - ox) * ux + (z - az - oz) * uz))
            px, pz = ax + ox + ux * t, az + oz + uz * t
            dist = math.hypot(px - x, pz - z)
            if best is None or dist < best[0]:
                best = (dist, (px, pz))
    return best[1]


def strip(pts, width):
    """Corner pairs either side of a polyline, densified to 1 m, mitred at the bends."""
    dense = []
    for (ax, az), (bx, bz) in zip(pts, pts[1:]):
        n = max(1, math.ceil(math.hypot(bx - ax, bz - az)))
        dense += [(ax + (bx - ax) * k / n, az + (bz - az) * k / n) for k in range(n)]
    dense.append(pts[-1])
    out = []
    for k, (x, z) in enumerate(dense):
        a, b = dense[max(0, k - 1)], dense[min(len(dense) - 1, k + 1)]
        dx, dz = b[0] - a[0], b[1] - a[1]
        L_ = math.hypot(dx, dz) or 1
        out.append(((x - dz / L_ * width / 2, z + dx / L_ * width / 2), (x + dz / L_ * width / 2, z - dx / L_ * width / 2)))
    return out


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
    g_c = GH(cx, cz)

    def ground(x, z):
        return GH(x, z) - g_c

    M = Mesh()
    clear = []          # where trees and sheds go: under the walks and drives

    def drape(pts, width, layer, colour, lift):
        """A flat strip along the ground (a walk, a drive, a painted line), lift metres up off it."""
        sides = strip(pts, width)
        for (l0, r0), (l1, r1) in zip(sides, sides[1:]):
            M.poly([(p[0], ground(*p) + lift, p[1]) for p in (l0, l1, r1, r0)], layer, colour)
            clear.append([l0, l1, r1, r0])

    def drape_rect(x0, x1, z0, z1, layer, colour, lift, cell=2.0):
        nx_, nz_ = max(1, math.ceil((x1 - x0) / cell)), max(1, math.ceil((z1 - z0) / cell))
        xs = [x0 + (x1 - x0) * k / nx_ for k in range(nx_ + 1)]
        zs = [z0 + (z1 - z0) * k / nz_ for k in range(nz_ + 1)]
        for a, b in zip(xs, xs[1:]):
            for c, d in zip(zs, zs[1:]):
                M.poly([(x, ground(x, z) + lift, z) for x, z in ((a, c), (b, c), (b, d), (a, d))], layer, colour)
        clear.append([(x0, z0), (x1, z0), (x1, z1), (x0, z1)])

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
            # the front walk: straight out from the steps, then across the lawn to the parkway's sidewalk
            foot = P(w, s, 0, o1 - 0.1)[::2]
            out = P(w, s, 0, o1 + 4)[::2]
            end = nearest_line(*out, lambda hw, walk: walk)
            drape([foot, out, end], 1.5, L['sidewalk'], WALK, 0.1)
            walk_end = end

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

    rings = [ring]
    if name == '2905-dean':
        rings.append(garage(M, ground, brick, drape, drape_rect))
    rec = M.record(name, cx, cz, PENTHOUSE, rings)
    rec['clear'] = [[[round(a, 2), round(b, 2)] for a, b in r] for r in clear]
    json.dump(rec, open(os.path.join(HERE, name + '.json'), 'w'), separators=(',', ':'))
    print('wrote', name, len(M.tris), 'triangles; front walk meets the sidewalk at', [round(v, 1) for v in walk_end])


def garage(M, ground, brick, drape, drape_rect):
    """2905's garage, its ramp, lot and drive (see the top); returns its outline."""
    ring = osm_ring(GARAGE)
    TOP = 4.75                                   # the parapet's coping
    roof = lambda z: 4.22 + (z - 1673) * 0.018  # the roof, 4.22 m at the north wall to 4.5 m at the south (LiDAR)
    base = min(ground(x, z) for x, z in ring) - 0.5
    walls = []
    for a, b in zip(ring, ring[1:] + ring[:1]):
        Lw = math.hypot(b[0] - a[0], b[1] - a[1])
        if Lw < 0.3:
            continue
        ux, uz = (b[0] - a[0]) / Lw, (b[1] - a[1]) / Lw
        walls.append((a, b, Lw, ux, uz, uz, -ux))
        M.poly([(a[0], base, a[1]), (b[0], base, b[1]), (b[0], TOP - 0.15, b[1]), (a[0], TOP - 0.15, a[1])], L['brickRedPlain'], brick)

    def P(w, s, y, off=0.0):
        a, _, _, ux, uz, nx, nz = w
        return (a[0] + ux * s + nx * off, y, a[1] + uz * s + nz * off)

    def panel(w, s0, s1, y0, y1, off, layer, colour):
        M.poly([P(w, s0, y0, off), P(w, s1, y0, off), P(w, s1, y1, off), P(w, s0, y1, off)], layer, colour)

    for w in walls:
        panel(w, -0.1, w[2] + 0.1, TOP - 0.15, TOP, 0.08, L['concPlain'], STONE)
        panel(w, 0, w[2], base, min(ground(*P(w, 0, 0)[::2]), ground(*P(w, w[2], 0)[::2])) + 0.3, 0.03, L['concPlain'], CONCRETE)
    # The west wall: an overhead door onto the ramp, a steel door beside it
    west = max((w for w in walls if w[5] < -0.9), key=lambda w: w[2])
    a, b, Lw = west[0], west[1], west[2]
    sd = (1680.5 - a[1]) / (b[1] - a[1]) * Lw          # the door's middle, where the ramp meets the wall
    g = ground(*P(west, sd, 0, 1.0)[::2])
    panel(west, sd - 2.9, sd + 2.9, g, g + 2.75, 0.04, L['concPlain'], STONE)
    panel(west, sd - 2.7, sd + 2.7, g, g + 2.55, 0.06, L['garageDoor'], '#ecebe6')
    panel(west, sd - 3.0, sd + 3.0, g + 2.75, g + 3.0, 0.1, L['concPlain'], STONE)
    sm = sd + (4.6 if b[1] > a[1] else -4.6)
    gm = ground(*P(west, sm, 0, 1.0)[::2])
    panel(west, sm - 0.5, sm + 0.5, gm, gm + 2.15, 0.05, L['metal'], '#5f6468')
    # The roof: gravel behind the parapet, with two rows of four skylights
    inner = offset(ring, 0.25)
    for i0, i1, i2 in triangulate(inner):
        M.poly([(inner[i][0], roof(inner[i][1]), inner[i][1]) for i in (i0, i2, i1)], L['gravel'], '#8f8a80')
    for p, q in zip(inner, inner[1:] + inner[:1]):
        M.poly([(q[0], roof(q[1]), q[1]), (p[0], roof(p[1]), p[1]), (p[0], TOP, p[1]), (q[0], TOP, q[1])], L['brickRedPlain'], brick)
    for (p, q), (c, d) in zip(zip(ring, ring[1:] + ring[:1]), zip(inner, inner[1:] + inner[:1])):
        M.poly([(p[0], TOP, p[1]), (q[0], TOP, q[1]), (d[0], TOP, d[1]), (c[0], TOP, c[1])], L['concPlain'], STONE)
    x0 = min(p[0] for p in ring)
    z0, z1 = min(p[1] for p in ring), max(p[1] for p in ring)
    for fx in (5.7, 11.7, 18.0, 23.4):
        for fz in (0.34, 0.66):
            x, z = x0 + fx, z0 + (z1 - z0) * fz
            y = roof(z)
            M.box(x - 0.55, x + 0.55, y - 0.05, y + 0.35, z - 0.4, z + 0.4, L['concPlain'], '#cfd2d4', top=L['glass'], top_colour='#a9bccb')
    # The ramp down to the door, the lot west of it (stalls along its north side) and the drive out to the parkway
    wx = a[0] + (b[0] - a[0]) * sd / Lw
    drape_rect(-4476.0, wx, 1676.0, 1685.0, L['asphalt'], ASPHALT, 0.08)
    drape_rect(-4493.0, wx, 1665.5, 1676.0, L['asphalt'], ASPHALT, 0.08)
    for k in range(11):
        x = -4490.0 + 2.8 * k
        drape([(x, 1665.8), (x, 1671.0)], 0.12, L['paint'], '#f4f4f0', 0.1)
    start = (-4490.0, 1674.0)
    bend = (-4497.0, 1681.0)
    end = nearest_line(*bend, lambda hw, walk: hw - 0.6)
    drape([start, bend, end], 6.0, L['asphalt'], ASPHALT, 0.08)
    return ring


for name, args in BUILDINGS.items():
    model(name, *args)
