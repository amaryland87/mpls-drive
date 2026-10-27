"""2905 and 2915 Dean Parkway, modelled by hand: run it to (re)write heroes/2905-dean.json and heroes/2915-dean.json,
and the grounds of the Calhoun Beach Club next door (heroes/calhoun-beach-club-grounds.json; the Club itself and its
apartment towers are hero_massing.py's).

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

Without street photos, the rest is what such buildings have: house numbers on the entrance canopies; blinds, shades,
curtains and the odd air conditioner in the windows (seeded, so the same every time); and round the back a door with
a stoop and a light, a steel fire escape, downspouts from the roof, gas and electric meters, bins and a dumpster.
The lawn in front follows the aerial photo: dark asphalt paths from the entrances to the parkway's sidewalk (2905's
forking, with a branch curving away to the south-west), a concrete walk along the fronts, clipped round shrubs, squared
hedges and two benches. Cars stand parked in the lot's stalls and along the parkway's curb on the buildings' side (pk: drawn by the game's
mpls-parked.js with its own car models).
"""
import gzip, json, math, os, random, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from hero_kit import L, Mesh, game_ground
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
IRON = '#2a2c2f'          # the fire escapes
SHADES = ['#f1efe8', '#e8dfc9', '#d9cbb0', '#fbfaf6', '#cfc6b8']
CURTAINS = ['#8a3b32', '#3f5a6e', '#d8cfb8', '#6b7a52', '#efe9dc', '#5b4a6e']
FEET = {}                 # the foot of each building's front steps, (x, z), as the models are made
PATH = '#56595c'          # the dark asphalt paths across the lawn
GREENS = ['#3d5c33', '#46663a', '#37532f', '#4b6b3c']
# The lawn in front, from the 2022 aerial photo (traced on a 5 m grid): clipped round shrubs (x, z, radius), squared
# hedge blocks (x0, x1, z0, z1) and benches (x, z), long side east-west
SHRUBS = [(-4483.0, 1695.0, 1.4), (-4481.9, 1697.1, 1.2), (-4484.5, 1700.6, 1.3), (-4467.9, 1695.6, 1.1),
          (-4467.9, 1697.7, 1.0), (-4477.0, 1704.0, 0.9), (-4476.2, 1705.5, 0.8), (-4472.2, 1712.2, 0.6),
          (-4471.5, 1724.8, 1.1), (-4474.0, 1688.8, 1.2)]
HEDGES = [(-4475.0, -4471.8, 1698.2, 1702.0), (-4473.7, -4469.5, 1704.4, 1709.4), (-4469.3, -4466.0, 1723.1, 1728.0)]
BENCHES = [(-4474.0, 1690.8), (-4474.0, 1694.2)]
PARKED = []               # parked cars: [x, z, heading, body (0 sedan 1 SUV), paint]; they go in 2905's record

# House numbers: 3 x 5 blocks a digit
GLYPHS = {'0': '111101101101111', '1': '010110010010111', '2': '111001111100111', '3': '111001111001111',
          '4': '101101111001001', '5': '111100111001111', '6': '111100111101111', '7': '111001010010010',
          '8': '111101111101111', '9': '111101111001111'}

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


GH = game_ground(CITY)


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


def draw_number(panel, s, y, text, px, off, colour='#2f2a24'):
    """A house number in blocks of px on a wall (panel(s0, s1, y0, y1, off, layer, colour)), centred s along it,
    reading left to right from outside: s runs to the left of someone facing the wall."""
    width = (len(text) * 4 - 1) * px
    for i, ch in enumerate(text):
        for r_ in range(5):
            for c_ in range(3):
                if GLYPHS[ch][r_ * 3 + c_] == '1':
                    xr = -width / 2 + (i * 4 + c_) * px
                    yy = y + (4 - r_) * px
                    panel(s - xr - px, s - xr, yy, yy + px, off, L['concPlain'], colour)


def park(x, z, hx, hz, rng):
    """A car parked at (x, z) facing (hx, hz)."""
    PARKED.append([round(x, 2), round(z, 2), round(math.atan2(hx, hz), 3), int(rng.random() < 0.4), rng.randrange(10)])


def curb_cars(cx, cz, reach, rng, keep_clear):
    """Cars parked along the curb of the nearest street on (cx, cz)'s side, every 6.6 m within reach of it, with
    gaps, and none where keep_clear says (a drive or a walk)."""
    best = None
    for hw, walk, pts in streets(cx, cz):
        d = min(math.hypot(x - cx, z - cz) for x, z in pts)
        if best is None or d < best[0]:
            best = (d, hw, pts)
    _, hw, pts = best
    run = 0.0
    for (ax, az), (bx, bz) in zip(pts, pts[1:]):
        L_ = math.hypot(bx - ax, bz - az)
        if L_ < 0.1:
            continue
        ux, uz = (bx - ax) / L_, (bz - az) / L_
        rx, rz = -uz, ux                                # right of the way it runs (road-network.js: rx = -dz, rz = dx)
        side = 1 if (cx - ax) * rx + (cz - az) * rz > 0 else -1
        t = (6.6 - run) % 6.6
        while t < L_:
            off = (hw - 0.92) * side                    # its outer side just inside the curb
            x, z = ax + ux * t + rx * off, az + uz * t + rz * off
            if math.hypot(x - cx, z - cz) < reach and not keep_clear(x, z) and rng.random() < 0.7:
                park(x, z, ux * side, uz * side, rng)   # facing the way that side's lane runs
            t += 6.6
        run = (run + L_) % 6.6


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

    def wbox(w, s0, s1, y0, y1, o0, o1, layer, colour):
        """A box set square on a wall: s0..s1 along it, y0..y1 up, o0..o1 out from it."""
        c = [(s0, o0), (s1, o0), (s1, o1), (s0, o1)]
        for (sa, oa), (sb, ob) in zip(c, c[1:] + c[:1]):
            M.poly([P(w, sa, y0, oa), P(w, sb, y0, ob), P(w, sb, y1, ob), P(w, sa, y1, oa)], layer, colour)
        M.poly([P(w, sa, y1, oa) for sa, oa in c], layer, colour)

    rng = random.Random(name)

    def dress(w, s, sill, h, upper):
        """What's in a window: a blind or shade part way down, curtains, or nothing; now and then an air conditioner."""
        r = rng.random()
        if r < 0.5:
            drop = h * rng.choice((0.15, 0.3, 0.5, 0.7, 0.95))
            panel(w, s - 0.46, s + 0.46, sill + h - drop, sill + h, 0.078, L['concPlain'], rng.choice(SHADES))
        elif r < 0.72:
            c, gap = rng.choice(CURTAINS), rng.choice((0.0, 0.2, 0.35))
            panel(w, s - 0.46, s - gap, sill + 0.05, sill + h, 0.078, L['concPlain'], c)
            panel(w, s + gap, s + 0.46, sill + 0.05, sill + h, 0.078, L['concPlain'], c)
        if upper and rng.random() < 0.08:
            wbox(w, s - 0.32, s + 0.32, sill, sill + 0.42, 0.0, 0.5, L['metal'], '#cfd0cc')
            panel(w, s - 0.27, s + 0.27, sill + 0.06, sill + 0.36, 0.505, L['metal'], '#9ea2a3')

    def number(w, s, y, text, px, off):
        draw_number(lambda s0, s1, y0, y1, o, layer, c: panel(w, s0, s1, y0, y1, o, layer, c), s, y, text, px, off)

    def back(w, sd, sf):
        """The back: a door with a stoop and a light, meters, bins and a dumpster, a fire escape up the wall."""
        g = ground(*P(w, sd, 0, 1.0)[::2])
        wbox(w, sd - 0.9, sd + 0.9, base, g + 0.3, 0.0, 1.3, L['concPlain'], CONCRETE)       # the stoop
        panel(w, sd - 0.5, sd + 0.5, g + 0.3, g + 2.4, 0.05, L['concPlain'], '#5b4636')
        panel(w, sd - 0.62, sd + 0.62, g + 2.4, g + 2.55, 0.06, L['concPlain'], STONE)
        wbox(w, sd - 0.1, sd + 0.1, g + 2.65, g + 2.9, 0.0, 0.2, L['concPlain'], '#20242a')   # the light
        for k in range(6):                                                                  # gas and electric
            sm = sd + 1.4 + (k % 3) * 0.32
            wbox(w, sm - 0.12, sm + 0.12, g + 0.9 + (k // 3) * 0.45, g + 1.2 + (k // 3) * 0.45, 0.0, 0.14, L['metal'], '#b3b6b2')
        wbox(w, sd + 1.25, sd + 2.25, g + 0.75, g + 0.8, 0.0, 0.08, L['metal'], '#8a8d8a')
        drape([P(w, sd, 0, 0.5)[::2], P(w, sd, 0, 4.0)[::2]], 3.2, L['sidewalk'], WALK, 0.06)  # a slab out the back
        for k, c in enumerate(('#2b2d30', '#2b2d30', '#2d5aa0')):                           # bins
            sb = sd - 1.5 - k * 0.75
            gb = ground(*P(w, sb, 0, 1.6)[::2]) + 0.06
            wbox(w, sb - 0.3, sb + 0.3, gb, gb + 0.95, 1.25, 1.95, L['metal'], c)
            wbox(w, sb - 0.33, sb + 0.33, gb + 0.95, gb + 1.02, 1.2, 2.0, L['metal'], c)
        sx = sd + 3.4
        gx = ground(*P(w, sx, 0, 2.5)[::2]) + 0.06
        wbox(w, sx - 0.95, sx + 0.95, gx, gx + 1.15, 1.8, 3.1, L['metal'], '#2f5a3a')          # the dumpster
        wbox(w, sx - 1.0, sx + 1.0, gx + 1.15, gx + 1.25, 1.75, 3.15, L['metal'], '#26472f')
        # The fire escape: a railed landing at each upper floor, steep stairs between, a ladder down from the first
        for k in (1, 2, 3):
            y = FLOORS[k] + 0.3
            wbox(w, sf - 1.3, sf + 1.3, y - 0.06, y, 0.05, 1.15, L['metal'], IRON)
            for s_ in (sf - 1.3, sf + 1.3):
                wbox(w, s_ - 0.03, s_ + 0.03, y, y + 1.0, 0.05, 1.15, L['metal'], IRON)
            wbox(w, sf - 1.3, sf + 1.3, y + 0.96, y + 1.02, 1.09, 1.15, L['metal'], IRON)
            wbox(w, sf - 1.3, sf + 1.3, y + 0.46, y + 0.5, 1.11, 1.15, L['metal'], IRON)
            for j in range(9):
                s_ = sf - 1.3 + j * 2.6 / 8
                wbox(w, s_ - 0.015, s_ + 0.015, y, y + 1.0, 1.11, 1.14, L['metal'], IRON)
            if k > 1:                       # stairs from this landing down to the one below, against the railing
                y0 = FLOORS[k - 1] + 0.3
                for o0, o1 in ((0.55, 0.6), (1.0, 1.05)):
                    M.poly([P(w, sf - 1.15, y0, o0), P(w, sf + 1.15, y - 0.06, o0), P(w, sf + 1.15, y - 0.06, o1), P(w, sf - 1.15, y0, o1)], L['metal'], IRON)
                    M.poly([P(w, sf - 1.15, y0 + 0.2, o0), P(w, sf + 1.15, y + 0.14, o0), P(w, sf + 1.15, y - 0.06, o0), P(w, sf - 1.15, y0, o0)], L['metal'], IRON)
                for j in range(1, 12):
                    t = j / 12
                    s_ = sf - 1.15 + 2.3 * t
                    yy = y0 + (y - 0.06 - y0) * t
                    M.poly([P(w, s_ - 0.09, yy, 0.6), P(w, s_ + 0.09, yy, 0.6), P(w, s_ + 0.09, yy, 1.0), P(w, s_ - 0.09, yy, 1.0)], L['metal'], IRON)
        yl = FLOORS[1] + 0.3                 # the drop ladder, hung up out of reach
        for s_ in (sf + 0.75, sf + 1.15):
            wbox(w, s_ - 0.025, s_ + 0.025, yl - 2.6, yl, 0.95, 1.0, L['metal'], IRON)
        for j in range(8):
            yy = yl - 0.3 - j * 0.3
            wbox(w, sf + 0.75, sf + 1.15, yy - 0.02, yy, 0.96, 0.99, L['metal'], IRON)

    # The front: the westmost wall long enough for a doorway, with the ground falling to the parkway before it;
    # the back: the longest east wall
    front = min((w for w in walls if w[5] < -0.9 and w[2] > 2.2), key=lambda w: (w[0][0] + w[1][0]) / 2)
    rear = max((w for w in walls if w[5] > 0.9), key=lambda w: w[2])
    for w in walls:
        a, b, Lw, ux, uz, nx, nz = w
        # belt courses: over the garden storey, under the top storey's sills, and the cornice under the coping
        for y0, y1, out in ((FLOORS[1] - 0.25, FLOORS[1] + 0.05, 0.06), (11.0, 11.3, 0.1), (PARAPET - 0.25, PARAPET, 0.14)):
            panel(w, -out if y1 == PARAPET else 0, Lw + (out if y1 == PARAPET else 0), y0, y1, out, L['concPlain'], STONE, depth=out)
        # a pale base course along the ground
        g0 = min(ground(*P(w, 0, 0)[::2]), ground(*P(w, Lw, 0)[::2]))
        panel(w, 0, Lw, base, g0 + 0.35, 0.03, L['concPlain'], CONCRETE)
        # downspouts at the ends of the long walls but the front, from a scupper under the coping
        if w is not front and Lw > 8:
            for sp in (0.45, Lw - 0.45):
                gs = ground(*P(w, sp, 0, 0.3)[::2])
                wbox(w, sp - 0.06, sp + 0.06, gs, PARAPET - 0.55, 0.02, 0.14, L['metal'], '#8a8f93')
                wbox(w, sp - 0.16, sp + 0.16, PARAPET - 0.75, PARAPET - 0.5, 0.0, 0.2, L['metal'], '#8a8f93')
                wbox(w, sp - 0.1, sp + 0.1, gs, gs + 0.08, 0.14, 0.55, L['concPlain'], CONCRETE)   # splash block
        # windows, a whole number of bays across, clear of the corners
        n = int((Lw - 1.2) // BAY)
        if n < 1:
            continue
        door_bay = n // 2 if w is front else -1
        fire_bay = max(0, n // 2 - 2) if w is rear else -1
        if w is rear:
            back(w, Lw / 2 + (n // 2 - (n - 1) / 2) * BAY, Lw / 2 + (fire_bay - (n - 1) / 2) * BAY)
            back_door = n // 2
        else:
            back_door = -1
        for q in range(n):
            s = Lw / 2 + (q - (n - 1) / 2) * BAY
            for k, f in enumerate(FLOORS):
                sill = f + (1.25 if k == 0 else 0.9)
                if k == 0 and (q in (door_bay, back_door) or sill < ground(*P(w, s, 0, 0.5)[::2]) + 0.25):
                    continue
                h = 1.0 if k == 0 else 1.55
                if w is rear and q == fire_bay and k >= 1:
                    # the fire escape's landing: a steel door onto it in place of the window
                    panel(w, s - 0.48, s + 0.48, f + 0.35, f + 2.45, 0.05, L['metal'], '#55595e')
                    continue
                M.window(lambda s_, y, off=0.0: P(w, s_, y, off), s, sill, 0.95, h, frame=FRAME, glass=GLASS)
                panel(w, s - 0.62, s + 0.62, sill - 0.2, sill - 0.08, 0.1, L['concPlain'], STONE, depth=0.1)   # the sill
                dress(w, s, sill, h, k >= 1)
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
            # a flat canopy over it, the house number on its front
            panel(w, s - 1.15, s + 1.15, sill + 2.95, sill + 3.3, 1.3, L['concPlain'], STONE, depth=1.3)
            number(w, s, sill + 3.02, name.split('-')[0], 0.044, 1.31)
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
            # the paths from the steps across the lawn come with the landscaping (landscape(), below)
            FEET[name] = P(w, s, 0, o1 - 0.1)[::2]
            out = P(w, s, 0, o1 + 4)[::2]
            end = nearest_line(out[0] - 8, out[1], lambda hw, walk: walk)
            curb_cars(*out, 30, rng, lambda x, z: math.hypot(x - end[0], z - end[1]) < 3.5 or math.hypot(x + 4506, z - 1689) < 9)

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
    if len(FEET) == len(BUILDINGS):
        landscape(M, ground, drape, clear)
    rec = M.record(name, cx, cz, PENTHOUSE, rings)
    rec['clear'] = [[[round(a, 2), round(b, 2)] for a, b in r] for r in clear]
    print(name, len(M.tris), 'triangles')
    return rec


def bezier(a, c, b, n=10):
    """A quadratic curve from a to b pulled toward c, as n + 1 points."""
    return [((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t * t * b[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t * t * b[1])
            for t in (k / n for k in range(n + 1))]


def landscape(M, ground, drape, clear):
    """The lawn between the fronts and the parkway, as the aerial photo has it (see SHRUBS above): a concrete walk
    along the fronts from the parking area to 2915, dark paths from the entrances to the parkway's sidewalk (2905's
    straight out with a branch curving off to the south-west, 2915's short and straight), shrubs, hedges, benches."""
    f1, f2 = FEET['2905-dean'], FEET['2915-dean']
    print('steps at', [round(v, 1) for v in f1], [round(v, 1) for v in f2])
    sidewalk = lambda x, z: nearest_line(x, z, lambda hw, walk: walk)
    paths = []                              # (points, half width), to keep the planting off them

    def path(pts, width, layer, colour, lift):
        drape(pts, width, layer, colour, lift)
        paths.append((pts, width / 2))
    # 2905: straight west, and the branch
    path([f1, (f1[0] - 12, f1[1]), sidewalk(f1[0] - 24, f1[1] - 1)], 1.8, L['asphalt'], PATH, 0.1)
    fork = (f1[0] - 7.5, f1[1] + 0.5)
    path(bezier(fork, (f1[0] - 12.5, f1[1] + 1.5), sidewalk(f1[0] - 15, f1[1] + 12), 12), 1.6, L['asphalt'], PATH, 0.1)
    # 2915: west to the sidewalk
    path([f2, (f2[0] - 4, f2[1]), sidewalk(f2[0] - 9, f2[1])], 1.8, L['asphalt'], PATH, 0.1)
    # the concrete walk along the fronts, past the foot of each flight of steps
    x1, x2 = f1[0] - 0.85, f2[0] - 0.85
    path([(x1, 1685.5), (x1, f1[1]), (x1, 1718.5)] + bezier((x1, 1718.5), (x1, 1721.5), (x2, 1723.5), 6)[1:] + [(x2, f2[1] + 3.5)],
         1.6, L['sidewalk'], WALK, 0.11)

    def clear_of_paths(x, z, r):
        """(x, z) moved, if it must be, so that a round thing of radius r there keeps 0.3 m off every path."""
        for _ in range(3):
            for pts, hw in paths:
                for (ax, az), (bx, bz) in zip(pts, pts[1:]):
                    dx, dz = bx - ax, bz - az
                    t = max(0, min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz or 1)))
                    px, pz = ax + dx * t, az + dz * t
                    d, need = math.hypot(x - px, z - pz), r + hw + 0.3
                    if d < need:
                        ux, uz = ((x - px) / d, (z - pz) / d) if d > 1e-6 else (-dz, dx)
                        x, z = px + ux * need, pz + uz * need
        return x, z
    # Shrubs: low faceted domes, a little squashed
    rng = random.Random('dean-lawn')
    for x, z, r in SHRUBS:
        x, z = clear_of_paths(x, z, r)
        g, h, col = ground(x, z), r * rng.uniform(1.0, 1.3), rng.choice(GREENS)
        ring_pts = []
        for k, (rr, yy) in enumerate([(0.75, 0.0), (1.0, 0.35), (0.92, 0.7), (0.62, 0.95), (0.0, 1.0)]):
            ring_pts.append([(x + math.cos(t) * r * rr, g + yy * h, z + math.sin(t) * r * rr) for t in (j * math.pi / 5 for j in range(10))])
        for lo, hi in zip(ring_pts, ring_pts[1:]):
            for j in range(10):
                q = [lo[j], lo[(j + 1) % 10], hi[(j + 1) % 10], hi[j]]
                if q[2] == q[3]:
                    M.poly(q[:3], L['grass'], col)
                else:
                    M.poly(q, L['grass'], col)
        clear.append([(x - r, z - r), (x + r, z - r), (x + r, z + r), (x - r, z + r)])
    # Hedges: clipped blocks with chamfered tops, kept off the walk
    for x0, x1_, z0, z1 in HEDGES:
        x1_ = min(x1_, min(x1, x2) - 1.2)
        # a block too near a path moves off it whole
        mx, mz = clear_of_paths((x0 + x1_) / 2, (z0 + z1) / 2, math.hypot(x1_ - x0, z1 - z0) / 2 * 0.8)
        dx_, dz_ = mx - (x0 + x1_) / 2, mz - (z0 + z1) / 2
        x0, x1_, z0, z1 = x0 + dx_, x1_ + dx_, z0 + dz_, z1 + dz_
        g = min(ground(x0, z0), ground(x1_, z0), ground(x1_, z1), ground(x0, z1))
        h, col, i = rng.uniform(1.2, 1.5), rng.choice(GREENS), 0.2
        lo = [(x0, z0), (x1_, z0), (x1_, z1), (x0, z1)]
        hi = [(x0 + i, z0 + i), (x1_ - i, z0 + i), (x1_ - i, z1 - i), (x0 + i, z1 - i)]
        for a, b, c, d in zip(lo, lo[1:] + lo[:1], hi[1:] + hi[:1], hi):
            M.poly([(a[0], g - 0.1, a[1]), (b[0], g - 0.1, b[1]), (b[0], g + h - 0.25, b[1]), (a[0], g + h - 0.25, a[1])], L['grass'], col)
            M.poly([(a[0], g + h - 0.25, a[1]), (b[0], g + h - 0.25, b[1]), (c[0], g + h, c[1]), (d[0], g + h, d[1])], L['grass'], col)
        M.poly([(p[0], g + h, p[1]) for p in hi], L['grass'], col)
        clear.append(lo)
    # Benches: a slatted seat and back on iron ends
    for x, z in BENCHES:
        x, z = clear_of_paths(x, z, 0.9)
        g = ground(x, z)
        M.box(x - 0.8, x + 0.8, g + 0.42, g + 0.47, z - 0.22, z + 0.22, L['concPlain'], '#7a5a3a')
        M.box(x - 0.8, x + 0.8, g + 0.6, g + 0.85, z + 0.2, z + 0.25, L['concPlain'], '#7a5a3a')
        for e in (-0.7, 0.7):
            M.box(x + e - 0.03, x + e + 0.03, g, g + 0.85, z - 0.22, z + 0.25, L['metal'], IRON)


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
    draw_number(lambda s0, s1, y0, y1, o, layer, c: panel(west, s0, s1, y0, y1, o, layer, c), sd, g + 2.79, '2901', 0.036, 0.11)
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
    rng = random.Random('2901-dean')
    for k in range(10):                     # nose in to the stalls, facing north
        if rng.random() < 0.65:
            park(-4490.0 + 2.8 * k + 1.4, 1668.7, 0.0, -1.0, rng)
    start = (-4490.0, 1674.0)
    bend = (-4497.0, 1681.0)
    end = nearest_line(*bend, lambda hw, walk: hw - 0.6)
    drape([start, bend, end], 6.0, L['asphalt'], ASPHALT, 0.08)
    return ring


def beach_club_grounds():
    """The Calhoun Beach Club's grounds next door (its building is hero_massing.py's): the walk along the fronts
    going on south from 2915 to the paved terrace at the Club's west door, a walk curving to it from the parkway's
    sidewalk, and the hedged flower bed between its south plaza and Lake Street's sidewalk, as the aerial has them."""
    cx, cz = -4458.0, 1790.0
    g_c = GH(cx, cz)
    ground = lambda x, z: GH(x, z) - g_c
    M = Mesh()
    clear = []

    def drape(pts, width, layer, colour, lift):
        sides = strip(pts, width)
        for (l0, r0), (l1, r1) in zip(sides, sides[1:]):
            M.poly([(q[0], ground(*q) + lift, q[1]) for q in (l0, l1, r1, r0)], layer, colour)
            clear.append([l0, l1, r1, r0])

    f2 = FEET['2915-dean']
    x2 = f2[0] - 0.85
    xw = -4463.6                             # a metre off the Club's west wall
    drape([(x2, f2[1] + 3.4), (x2, 1745.0)] + bezier((x2, 1745.0), (x2, 1749.5), (xw, 1752.0), 6)[1:] + [(xw, 1778.0)],
          1.6, L['sidewalk'], WALK, 0.11)
    # the terrace at the west door, in a paler paving, on a grid of 2 m
    x0, x1, z0, z1 = -4466.5, -4462.2, 1777.5, 1789.0
    for a in range(int((x1 - x0) // 2) + 1):
        for b in range(int((z1 - z0) // 2) + 1):
            xa, xb = x0 + a * 2, min(x1, x0 + a * 2 + 2)
            za, zb = z0 + b * 2, min(z1, z0 + b * 2 + 2)
            if xb - xa < 0.05 or zb - za < 0.05:
                continue
            M.poly([(x, ground(x, z) + 0.13, z) for x, z in ((xa, za), (xb, za), (xb, zb), (xa, zb))], L['sidewalk'], '#d9d3c7')
    clear.append([(x0, z0), (x1, z0), (x1, z1), (x0, z1)])
    # the walk curving in to it from the parkway's sidewalk
    start = nearest_line(-4472.0, 1778.0, lambda hw, walk: walk)
    drape(bezier(start, (-4468.5, 1777.5), (-4466.2, 1783.5), 10), 1.8, L['sidewalk'], WALK, 0.11)
    # the flower bed: a low clipped hedge round it, flowers inside
    bx0, bx1, bz0, bz1 = -4450.0, -4435.0, 1819.0, 1825.0
    gb = min(ground(bx0, bz0), ground(bx1, bz0), ground(bx1, bz1), ground(bx0, bz1))
    rng = random.Random('cbc-bed')
    for (ax, az), (bx, bz) in (((bx0, bz0), (bx1, bz0)), ((bx1, bz0), (bx1, bz1)), ((bx1, bz1), (bx0, bz1)), ((bx0, bz1), (bx0, bz0))):
        xa, xb, za, zb = min(ax, bx) - 0.3, max(ax, bx) + 0.3, min(az, bz) - 0.3, max(az, bz) + 0.3
        M.box(xa, xb, gb - 0.1, gb + 0.55, za, zb, L['grass'], GREENS[1])
    for k in range(int((bx1 - bx0 - 0.6) / 0.8)):
        for j in range(int((bz1 - bz0 - 0.6) / 0.8)):
            x, z = bx0 + 0.7 + k * 0.8, bz0 + 0.7 + j * 0.8
            M.box(x - 0.3, x + 0.3, gb - 0.05, gb + rng.uniform(0.25, 0.4), z - 0.3, z + 0.3, L['grass'],
                  rng.choice(['#b04a6a', '#d77a3a', '#e3c34a', '#9a5fb0', '#46663a', '#46663a']))
    clear.append([(bx0, bz0), (bx1, bz0), (bx1, bz1), (bx0, bz1)])
    rec = M.record('calhoun-beach-club-grounds', cx, cz, 1.0, [])
    rec['clear'] = [[[round(a, 2), round(b, 2)] for a, b in r] for r in clear]
    print('calhoun-beach-club-grounds', len(M.tris), 'triangles')
    return rec


records = {name: model(name, *args) for name, args in BUILDINGS.items()}
records['calhoun-beach-club-grounds'] = beach_club_grounds()
records['2905-dean']['pk'] = PARKED              # all the cars go with one building, so each is drawn once
for name, rec in records.items():
    json.dump(rec, open(os.path.join(HERE, name + '.json'), 'w'), separators=(',', ':'))
print(len(PARKED), 'parked cars')
