"""The Minneapolis Sculpture Garden, modelled by hand: run it to (re)write heroes/sg-*.json.

    ../.venv/bin/python model_sculpture_garden.py

Placed from the Hennepin County 2022 aerial photo and the full-density 2022 LiDAR over the garden
(fetched into osm-cache/heroes/sculpture-garden/), sized from the survey where it sees the piece,
and laid out after the Walker's 2019 garden map (the numbers below are its numbers):

  19  Spoonbridge and Cherry (Oldenburg and van Bruggen) in its pond, the spoon resting on the lawn
      between the pond's two lobes, the cherry and its stem up at the far end of the bowl
  37  the Cowles Conservatory: a tall glass pavilion with a pyramid roof between two long glass houses
      the four hedge rooms east of it, walled in clipped arborvitae, with
  22    Empire (Eva Rothschild), a slender red, black and green arch, in the northeast room
  30,31,32  Serra's Five Plates, Two Poles, Tony Smith's Amaryllis, Kelly's Double Curve, northwest
  40    Dan Graham's mirror-and-steel hedge labyrinth on its square of paving, southwest
  34,35 two Henry Moore bronzes, southeast
      the north meadow's three round lawns:
   4    Arikidea (Mark di Suvero): steel I-beams leaning together, a wooden swing hung under them
   6    Hahn/Cock (Katharina Fritsch): the ultramarine rooster on its grey plinth
  12    Black Vessel for a Saint (Theaster Gates): a round temple of black brick
  13    X with Columns (Sol LeWitt): a white block X with taller columns at its ends
  39    Jim Hodges' mirror-skinned boulders by the conservatory, and Okciyapi (Angela Two Stars),
      the round stone fountain west of the pond

Each group is its own hero building, standing on the ground at its own centre; heights in it are
relative to that, with the game's own ground (the same 10 m grid bake_tiles.py ships) under every
piece, so things stand on the slope the way they do in the game.
"""
import math, os, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from area import X0, X1, Z0, Z1
from hero_kit import L, Mesh

# ---------------------------------------------------------------- the game's ground (as bake_tiles.py ships it)
_g = np.load(os.path.join(os.path.dirname(HERE), 'osm-cache', 'ground.npz'))
GSTEP, GH_ABS = int(_g['step']), _g['h'].astype(np.float64)
E0 = float(np.median(np.concatenate([GH_ABS[0], GH_ABS[-1], GH_ABS[:, 0], GH_ABS[:, -1]])))
GNZ, GNX = GH_ABS.shape


def ground(x, z):
    """The game's ground height at (x, z) (the garden is far from the map's eased edge)."""
    fx = min(max((x - X0) / GSTEP, 0), GNX - 1.001)
    fz = min(max((z - Z0) / GSTEP, 0), GNZ - 1.001)
    i, j = int(fx), int(fz)
    u, v = fx - i, fz - j
    G = lambda a, b: round((GH_ABS[b, a] - E0) * 100) / 100
    a, b, c, d = G(i, j), G(i + 1, j), G(i, j + 1), G(i + 1, j + 1)
    return a + (b - a) * u + (c - a) * v if u + v <= 1 else d + (c - d) * (1 - u) + (b - d) * (1 - v)


# ---------------------------------------------------------------- vectors
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a):
    n = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def frame(d):
    d = norm(d)
    up = (0.0, 1.0, 0.0) if abs(d[1]) < 0.95 else (1.0, 0.0, 0.0)
    s = norm(cross(d, up))
    return d, s, cross(s, d)


# ---------------------------------------------------------------- colours
GREY_STONE = '#bdb6aa'
WATER = '#3f6577'
SPOON = '#e4e7ea'
CHERRY = '#b3112c'
STEM = '#7d0d22'
HEDGE = '#557a4c'
HEDGE_TOP = '#628a56'
PAVING = '#cfc9bd'
GLASS = '#c9dde4'
WHITE = '#f2f1ec'
BLUE = '#1c3fc4'
CORTEN = '#7a4a30'
BLACK = '#26272a'
BRONZE = '#5b4a35'


class Site(Mesh):
    """A group of pieces: a Mesh whose heights are above the game's ground at its centre."""

    def __init__(self, name, cx, cz):
        super().__init__()
        self.name, self.cx, self.cz = name, cx, cz
        self.g0 = ground(cx, cz)
        self.rings = []
        self.top = 0.0

    def g(self, x, z):
        """The ground at (x, z), above this site's own."""
        return ground(x, z) - self.g0

    def poly(self, pts, layer, colour, uv_turn=False):
        self.top = max(self.top, max(p[1] for p in pts))
        super().poly(pts, layer, colour, uv_turn)

    # ---- shapes beyond the kit's
    def beam(self, a, b, w, h, layer, colour, roll=0.0):
        """A square-sectioned bar from point a to point b, w across and h deep."""
        d, s, u = frame(sub(b, a))
        if roll:
            c, n = math.cos(roll), math.sin(roll)
            s, u = add(mul(s, c), mul(u, n)), add(mul(u, c), mul(s, -n))
        off = [add(mul(s, w * i / 2), mul(u, h * j / 2)) for i, j in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        A = [add(a, o) for o in off]
        B = [add(b, o) for o in off]
        for k in range(4):
            self.poly([A[k], A[(k + 1) % 4], B[(k + 1) % 4], B[k]], layer, colour)
        self.poly(A, layer, colour)
        self.poly(B, layer, colour)

    def tube(self, path, r, layer, colour, sides=8, caps=True):
        """A round tube along a list of points."""
        rings = []
        for k, p in enumerate(path):
            d = sub(path[min(k + 1, len(path) - 1)], path[max(k - 1, 0)])
            _, s, u = frame(d)
            rr = r(k / (len(path) - 1)) if callable(r) else r
            rings.append([add(p, add(mul(s, rr * math.cos(t * 2 * math.pi / sides)), mul(u, rr * math.sin(t * 2 * math.pi / sides)))) for t in range(sides)])
        for a, b in zip(rings, rings[1:]):
            for t in range(sides):
                self.poly([a[t], a[(t + 1) % sides], b[(t + 1) % sides], b[t]], layer, colour)
        if caps:
            self.poly(rings[0], layer, colour)
            self.poly(rings[-1], layer, colour)

    def ellipsoid(self, c, rx, ry, rz, layer, colour, n=10, m=7, axes=None):
        """An ellipsoid round c, radii along its axes (default x, y, z)."""
        ax, ay, az = axes or ((1, 0, 0), (0, 1, 0), (0, 0, 1))
        def P(i, j):
            th, ph = 2 * math.pi * i / n, math.pi * j / m - math.pi / 2
            return add(c, add(add(mul(ax, rx * math.cos(ph) * math.cos(th)), mul(ay, ry * math.sin(ph))), mul(az, rz * math.cos(ph) * math.sin(th))))
        for j in range(m):
            for i in range(n):
                q = [P(i, j), P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)]
                if j == 0:
                    q = [q[0], q[2], q[3]]
                elif j == m - 1:
                    q = q[:3]
                self.poly(q, layer, colour)

    def hedge(self, x0, z0, x1, z1, h=2.3, w=1.2):
        """A clipped arborvitae hedge along a straight line, standing on the slope, with a collision ring."""
        dx, dz = x1 - x0, z1 - z0
        n = math.hypot(dx, dz)
        ox, oz = -dz / n * w / 2, dx / n * w / 2
        steps = max(1, int(n / 6))
        for k in range(steps):
            t0, t1 = k / steps, (k + 1) / steps
            ax, az = x0 + dx * t0, z0 + dz * t0
            bx, bz = x0 + dx * t1, z0 + dz * t1
            ga, gb = self.g(ax, az), self.g(bx, bz)
            c = [(ax - ox, az - oz, ga), (bx - ox, bz - oz, gb), (bx + ox, bz + oz, gb), (ax + ox, az + oz, ga)]
            for (px, pz, pg), (qx, qz, qg) in zip(c, c[1:] + c[:1]):
                self.poly([(px, pg - 0.3, pz), (qx, qg - 0.3, qz), (qx, qg + h, qz), (px, pg + h, pz)], L['grass'], HEDGE)
            # a rounded-off top: a narrower crown over the face
            self.poly([(px, pg + h, pz) for px, pz, pg in c], L['grass'], HEDGE_TOP)
        self.rings.append([(x0 - ox, z0 - oz), (x1 - ox, z1 - oz), (x1 + ox, z1 + oz), (x0 + ox, z0 + oz)])

    def write_hero(self):
        rec_rings = [[(x, z) for x, z in r] for r in self.rings]
        self.write(os.path.join(HERE, f'{self.name}.json'), self.name, self.cx, self.cz, self.top, rec_rings)

    # The kit works in world x and z with heights above the site's ground; turn site-relative x/z into world.
    def to(self, x, y, z):
        return (x, y, z)


sites = []


def site(name, cx, cz):
    s = Site(name, cx, cz)
    sites.append(s)
    return s


# ================================================================ 19  Spoonbridge and Cherry, in its pond
S = site('sg-spoonbridge', -2372.0, -476.0)
# The pond's edge, as OpenStreetMap has it (the game draws its water from the same outline): a west
# lobe and an east lobe, with the lawn running in between them from the north where the spoon's
# handle comes down.
POND = [(-2399.5, -476.2), (-2398.9, -473.6), (-2396.9, -471.5), (-2394.3, -469.8), (-2389.9, -468.2), (-2384.6, -466.9),
        (-2380.1, -465.3), (-2375.9, -462.7), (-2373.0, -460.6), (-2370.4, -458.8), (-2367.3, -457.4), (-2364.5, -457.3),
        (-2361.7, -458.7), (-2359.5, -461.2), (-2358.0, -464.6), (-2357.9, -468.2), (-2357.1, -471.5), (-2356.2, -474.6),
        (-2354.8, -477.4), (-2353.2, -480.4), (-2352.5, -482.8), (-2352.7, -484.6), (-2353.3, -486.3), (-2354.3, -487.9),
        (-2355.3, -489.4), (-2357.1, -491.1), (-2359.2, -492.5), (-2361.3, -493.0), (-2363.1, -493.0), (-2365.0, -492.8),
        (-2367.1, -492.2), (-2369.3, -490.9), (-2371.4, -489.2), (-2372.9, -486.5), (-2373.3, -483.3), (-2373.2, -477.7),
        (-2374.0, -475.2), (-2374.7, -474.4), (-2375.8, -474.0), (-2377.3, -473.8), (-2378.8, -473.9), (-2380.6, -474.7),
        (-2385.4, -478.5), (-2389.2, -481.0), (-2392.0, -481.9), (-2393.8, -482.3), (-2395.5, -481.9), (-2397.1, -481.3),
        (-2398.3, -480.1), (-2399.3, -478.5)]
# Which way is out from each edge (the ring runs clockwise as seen from above, x east and z south).
_area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(POND, POND[1:] + POND[:1]))
OUT = 1 if _area > 0 else -1


def edge_out(a, b, d):
    ex, ez = b[0] - a[0], b[1] - a[1]
    n = math.hypot(ex, ez)
    nx, nz = -ez / n * OUT, ex / n * OUT
    return (a[0] + nx * d, a[1] + nz * d), (b[0] + nx * d, b[1] + nz * d)


# A granite curb round the water, 0.7 m wide, on the ground, a hand's width proud of it.
for a, b in zip(POND, POND[1:] + POND[:1]):
    oa, ob = edge_out(a, b, 0.7)
    ya, yb = S.g(*a) + 0.15, S.g(*b) + 0.15
    S.poly([(a[0], ya - 0.6, a[1]), (b[0], yb - 0.6, b[1]), (b[0], yb, b[1]), (a[0], ya, a[1])], L['concPlain'], GREY_STONE)
    S.poly([(a[0], ya, a[1]), (b[0], yb, b[1]), (ob[0], yb, ob[1]), (oa[0], ya, oa[1])], L['concPlain'], GREY_STONE)
    S.poly([(oa[0], ya, oa[1]), (ob[0], yb, ob[1]), (ob[0], yb - 0.6, ob[1]), (oa[0], ya - 0.6, oa[1])], L['concPlain'], GREY_STONE)
WL = min(S.g(*p) for p in POND)

# The spoon: 15.8 m long. Its handle rests on the lawn between the lobes and rises over the water
# to the bowl, which holds the cherry at its far end, about 9 m up at the top of the stem.
TIP = (-2378.3, -477.6)
BOWL = (-2365.4, -466.9)
dx, dz = BOWL[0] - TIP[0], BOWL[1] - TIP[1]
hl = math.hypot(dx, dz)
ux, uz = dx / hl, dz / hl                     # along the spoon
px, pz = -uz, ux                              # across it
y_tip = S.g(*TIP) + 0.25
BOWL_Y = WL + 4.6
# The handle: a flat bar, wider towards the bowl, rising in a long curve.
N = 16
for k in range(N):
    t0, t1 = k / N, (k + 1) / N
    def hp(t, side, up=0.0):
        s = t * (hl - 2.6)
        y = y_tip + (BOWL_Y - 0.4 - y_tip) * (t ** 1.6) + up
        w = 0.32 + 0.38 * t
        return (TIP[0] + ux * s + px * w * side, y, TIP[1] + uz * s + pz * w * side)
    for up in (0.0, 0.18):
        S.poly([hp(t0, -1, up), hp(t1, -1, up), hp(t1, 1, up), hp(t0, 1, up)], L['metal'], SPOON)
    for side in (-1, 1):
        S.poly([hp(t0, side), hp(t1, side), hp(t1, side, 0.18), hp(t0, side, 0.18)], L['metal'], SPOON)
# The bowl: a shallow oval dish, tilted up a little towards its tip, 6 m long and 4 m across.
BL, BW, BD = 3.1, 2.1, 1.25
bc = (BOWL[0] - ux * 0.3, BOWL_Y, BOWL[1] - uz * 0.3)
def bowl_pt(i, j, rim_out=0.0):
    th = 2 * math.pi * i / 16
    r = j / 4
    a, c = math.cos(th) * BL * r, math.sin(th) * BW * r
    y = bc[1] - BD * (1 - r * r) + 0.35 * (a / BL) + rim_out
    return (bc[0] + ux * a + px * c, y, bc[2] + uz * a + pz * c)
for j in range(4):
    for i in range(16):
        S.poly([bowl_pt(i, j), bowl_pt(i + 1, j), bowl_pt(i + 1, j + 1), bowl_pt(i, j + 1)], L['metal'], SPOON)
for i in range(16):        # the rim's thickness, and the underside: the same dish 0.3 m lower
    S.poly([bowl_pt(i, 4), bowl_pt(i + 1, 4), bowl_pt(i + 1, 4, -0.3), bowl_pt(i, 4, -0.3)], L['metal'], SPOON)
    for j in range(4):
        S.poly([bowl_pt(i, j, -0.3), bowl_pt(i + 1, j, -0.3), bowl_pt(i + 1, j + 1, -0.3), bowl_pt(i, j + 1, -0.3)], L['metal'], SPOON)
# The cherry, 2.8 m across, sitting in the bowl's back half; and its stem, curling up and over.
CH = (-2368.0, BOWL_Y + 1.15, -467.3)
S.ellipsoid(CH, 1.45, 1.4, 1.45, L['paint'], CHERRY, n=14, m=9)
stem = []
for k in range(9):
    t = k / 8
    stem.append(add(CH, (0.5 * t + 0.6 * t * t, 1.25 + 1.7 * t - 0.4 * t * t * t, -0.5 * t * t)))
S.tube(stem, lambda t: 0.16 - 0.06 * t, L['paint'], STEM, sides=6)
S.write_hero()


# ================================================================ 37  the Cowles Conservatory
S = site('sg-conservatory', -2423.0, -391.5)
RIB = WHITE


def glasshouse(x0, x1, z0, z1, wall, ridge):
    """A long glass house: low glass walls under a glass gable, ridge along z, white ribs every 2.5 m."""
    gb = min(S.g(x0, z0), S.g(x1, z0), S.g(x0, z1), S.g(x1, z1))
    xm = (x0 + x1) / 2
    S.box(x0, x1, gb - 0.6, gb + 0.6, z0, z1, L['concPlain'], '#b9b2a6')
    for (ax, az), (bx, bz) in (((x0, z0), (x0, z1)), ((x1, z0), (x1, z1)), ((x0, z0), (x1, z0)), ((x0, z1), (x1, z1))):
        S.poly([(ax, gb + 0.6, az), (bx, gb + 0.6, bz), (bx, gb + wall, bz), (ax, gb + wall, az)], L['glass'], GLASS)
    for x in (x0, x1):
        S.poly([(x, gb + wall, z0), (x, gb + wall, z1), (xm, gb + ridge, z1), (xm, gb + ridge, z0)], L['glass'], GLASS)
    for z in (z0, z1):
        S.poly([(x0, gb + wall, z), (x1, gb + wall, z), (xm, gb + ridge, z)], L['glass'], GLASS)
    n = max(2, round((z1 - z0) / 2.5))
    for k in range(n + 1):
        z = z0 + (z1 - z0) * k / n
        S.beam((x0, gb + 0.6, z), (x0, gb + wall, z), 0.12, 0.12, L['concPlain'], RIB)
        S.beam((x1, gb + 0.6, z), (x1, gb + wall, z), 0.12, 0.12, L['concPlain'], RIB)
        S.beam((x0, gb + wall, z), (xm, gb + ridge, z), 0.12, 0.12, L['concPlain'], RIB)
        S.beam((x1, gb + wall, z), (xm, gb + ridge, z), 0.12, 0.12, L['concPlain'], RIB)
    S.beam((xm, gb + ridge, z0), (xm, gb + ridge, z1), 0.18, 0.18, L['concPlain'], RIB)
    for x in (x0, x1):
        S.beam((x, gb + wall, z0), (x, gb + wall, z1), 0.14, 0.14, L['concPlain'], RIB)
    S.rings.append([(x0, z0), (x1, z0), (x1, z1), (x0, z1)])


# The two long houses north and south, 7.5 m wide and 25 m long.
glasshouse(-2421.0, -2413.5, -430.2, -405.0, 2.3, 5.4)
glasshouse(-2421.0, -2413.5, -378.3, -353.2, 2.3, 5.4)
# The central pavilion: a glass lean-to all round (2.5 m walls rising to 5 m), a glass box inside it
# up to 11 m, and a glass pyramid on that to 17 m.
OX0, OX1, OZ0, OZ1 = -2435.0, -2416.0, -401.0, -382.0
IX0, IX1, IZ0, IZ1 = -2432.0, -2419.0, -398.0, -385.0
gb = min(S.g(OX0, OZ0), S.g(OX1, OZ0), S.g(OX0, OZ1), S.g(OX1, OZ1))
S.box(OX0, OX1, gb - 0.6, gb + 0.6, OZ0, OZ1, L['concPlain'], '#b9b2a6')
outer = [(OX0, OZ0), (OX1, OZ0), (OX1, OZ1), (OX0, OZ1)]
inner = [(IX0, IZ0), (IX1, IZ0), (IX1, IZ1), (IX0, IZ1)]
for k in range(4):
    (ax, az), (bx, bz) = outer[k], outer[(k + 1) % 4]
    (cx_, cz_), (dx_, dz_) = inner[k], inner[(k + 1) % 4]
    S.poly([(ax, gb + 0.6, az), (bx, gb + 0.6, bz), (bx, gb + 2.6, bz), (ax, gb + 2.6, az)], L['glass'], GLASS)
    S.poly([(ax, gb + 2.6, az), (bx, gb + 2.6, bz), (dx_, gb + 5.0, dz_), (cx_, gb + 5.0, cz_)], L['glass'], GLASS)
    S.poly([(cx_, gb + 5.0, cz_), (dx_, gb + 5.0, dz_), (dx_, gb + 11.2, dz_), (cx_, gb + 11.2, cz_)], L['glass'], GLASS)
    S.poly([(cx_, gb + 11.2, cz_), (dx_, gb + 11.2, dz_), ((IX0 + IX1) / 2, gb + 17.2, (IZ0 + IZ1) / 2)], L['glass'], GLASS)
    # white ribs: the corners, the eaves, and mullions up the walls
    S.beam((ax, gb + 0.6, az), (ax, gb + 2.6, az), 0.2, 0.2, L['concPlain'], RIB)
    S.beam((ax, gb + 2.6, az), (bx, gb + 2.6, bz), 0.16, 0.16, L['concPlain'], RIB)
    S.beam((ax, gb + 2.6, az), (cx_, gb + 5.0, cz_), 0.16, 0.16, L['concPlain'], RIB)
    S.beam((cx_, gb + 5.0, cz_), (cx_, gb + 11.2, cz_), 0.24, 0.24, L['concPlain'], RIB)
    S.beam((cx_, gb + 5.0, cz_), (dx_, gb + 5.0, dz_), 0.16, 0.16, L['concPlain'], RIB)
    S.beam((cx_, gb + 11.2, cz_), (dx_, gb + 11.2, dz_), 0.2, 0.2, L['concPlain'], RIB)
    S.beam((cx_, gb + 11.2, cz_), ((IX0 + IX1) / 2, gb + 17.2, (IZ0 + IZ1) / 2), 0.2, 0.2, L['concPlain'], RIB)
    for t in (0.25, 0.5, 0.75):
        mx, mz = ax + (bx - ax) * t, az + (bz - az) * t
        nx, nz = cx_ + (dx_ - cx_) * t, cz_ + (dz_ - cz_) * t
        S.beam((mx, gb + 0.6, mz), (mx, gb + 2.6, mz), 0.1, 0.1, L['concPlain'], RIB)
        S.beam((mx, gb + 2.6, mz), (nx, gb + 5.0, nz), 0.1, 0.1, L['concPlain'], RIB)
        S.beam((nx, gb + 5.0, nz), (nx, gb + 11.2, nz), 0.1, 0.1, L['concPlain'], RIB)
        S.beam((nx, gb + 11.2, nz), ((IX0 + IX1) / 2, gb + 17.2, (IZ0 + IZ1) / 2), 0.1, 0.1, L['concPlain'], RIB)
    for y in (6.9, 9.0):
        S.beam((cx_, gb + y, cz_), (dx_, gb + y, dz_), 0.08, 0.08, L['concPlain'], RIB)
S.rings.append(outer)

# 39  Jim Hodges' boulders, skinned in polished steel, in the lawn west of the south glass house.
for bx_, bz_, r, h in ((-2441.5, -368.5, 1.0, 1.1), (-2439.3, -366.3, 1.25, 1.5), (-2437.0, -368.0, 0.9, 0.9), (-2439.0, -370.2, 1.05, 1.2)):
    S.ellipsoid((bx_, S.g(bx_, bz_) + h * 0.35, bz_), r, h * 0.7, r * 0.85, L['metal'], '#dfe4ea', n=7, m=4)
S.write_hero()


# ================================================================ the four hedge rooms
# Each room is a square of lawn walled in clipped arborvitae, with a gap in the middle of each side
# for the walks; the cross walk between them is lined with linden trees (the game's own).
ROOMS = dict(nw=(-2411.0, -2375.0, -436.4, -400.0), ne=(-2358.0, -2323.0, -436.4, -400.0),
             sw=(-2411.0, -2375.0, -386.0, -349.0), se=(-2358.0, -2323.0, -386.0, -349.0))
GAP = 3.0


def room(S, x0, x1, z0, z1):
    xm, zm = (x0 + x1) / 2, (z0 + z1) / 2
    for a, b in (((x0, z0), (x1, z0)), ((x1, z0), (x1, z1)), ((x1, z1), (x0, z1)), ((x0, z1), (x0, z0))):
        mx, mz = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        dx, dz = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dz)
        gx, gz = dx / n * GAP / 2, dz / n * GAP / 2
        S.hedge(a[0], a[1], mx - gx, mz - gz)
        S.hedge(mx + gx, mz + gz, b[0], b[1])


# ---- northwest: Serra's plates and poles, Tony Smith's Amaryllis, Kelly's Double Curve
x0, x1, z0, z1 = ROOMS['nw']
S = site('sg-room-nw', (x0 + x1) / 2, (z0 + z1) / 2)
room(S, x0, x1, z0, z1)
# 30  Five Plates, Two Poles: five steel plates leaning in on each other round two poles
px_, pz_ = -2401.2, -419.4
S.rings.append([(px_ + 1.6 * math.cos(a), pz_ + 1.6 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)])
gp = S.g(px_, pz_)
for k in range(5):
    a = k * 2 * math.pi / 5 + 0.3
    bx_, bz_ = px_ + math.cos(a) * 1.4, pz_ + math.sin(a) * 1.4
    tx, tz = px_ + math.cos(a) * 0.35, pz_ + math.sin(a) * 0.35
    ex, ez = -math.sin(a) * 0.75, math.cos(a) * 0.75
    S.poly([(bx_ - ex, gp, bz_ - ez), (bx_ + ex, gp, bz_ + ez), (tx + ex, gp + 2.3, tz + ez), (tx - ex, gp + 2.3, tz - ez)], L['paint'], '#3b3631')
for ox in (-0.25, 0.25):
    S.cylinder(px_ + ox, pz_, 0.09, gp, gp + 2.6, L['paint'], '#3b3631', sides=6)
# 31  Amaryllis: black steel, a stack of slanted facets, 3.5 m high
ax_, az_ = -2385.0, -426.0
ga = S.g(ax_, az_)
S.rings.append([(ax_ - 1.8, az_ - 1.0), (ax_ + 0.4, az_ - 1.0), (ax_ + 2.2, az_ + 0.4), (ax_ + 2.2, az_ + 2.4), (ax_ - 1.8, az_ + 1.0)])
S.poly([(ax_ - 1.8, ga, az_ - 1.0), (ax_ + 0.4, ga, az_ - 1.0), (ax_ + 0.4, ga + 2.0, az_ - 1.0), (ax_ - 1.8, ga + 3.4, az_ - 1.0)], L['paint'], BLACK)
S.poly([(ax_ - 1.8, ga, az_ + 1.0), (ax_ + 0.4, ga, az_ + 1.0), (ax_ + 0.4, ga + 2.0, az_ + 1.0), (ax_ - 1.8, ga + 3.4, az_ + 1.0)], L['paint'], BLACK)
S.poly([(ax_ + 0.4, ga, az_ - 1.0), (ax_ + 0.4, ga, az_ + 1.0), (ax_ + 0.4, ga + 2.0, az_ + 1.0), (ax_ + 0.4, ga + 2.0, az_ - 1.0)], L['paint'], BLACK)
S.poly([(ax_ - 1.8, ga + 3.4, az_ - 1.0), (ax_ - 1.8, ga + 3.4, az_ + 1.0), (ax_ + 0.4, ga + 2.0, az_ + 1.0), (ax_ + 0.4, ga + 2.0, az_ - 1.0)], L['paint'], BLACK)
S.poly([(ax_ - 1.8, ga, az_ - 1.0), (ax_ - 1.8, ga, az_ + 1.0), (ax_ - 1.8, ga + 3.4, az_ + 1.0), (ax_ - 1.8, ga + 3.4, az_ - 1.0)], L['paint'], BLACK)
S.poly([(ax_ + 0.4, ga + 2.0, az_ - 1.0), (ax_ + 0.4, ga + 2.0, az_ + 1.0), (ax_ + 2.2, ga + 0.6, az_ + 2.4), (ax_ + 2.2, ga + 0.6, az_ + 0.4)], L['paint'], BLACK)
S.poly([(ax_ + 0.4, ga, az_ - 1.0), (ax_ + 0.4, ga, az_ + 1.0), (ax_ + 2.2, ga, az_ + 2.4), (ax_ + 2.2, ga, az_ + 0.4)], L['paint'], BLACK)
S.poly([(ax_ + 0.4, ga, az_ + 1.0), (ax_ + 2.2, ga, az_ + 2.4), (ax_ + 2.2, ga + 0.6, az_ + 2.4), (ax_ + 0.4, ga + 2.0, az_ + 1.0)], L['paint'], BLACK)
S.poly([(ax_ + 0.4, ga, az_ - 1.0), (ax_ + 2.2, ga, az_ + 0.4), (ax_ + 2.2, ga + 0.6, az_ + 0.4), (ax_ + 0.4, ga + 2.0, az_ - 1.0)], L['paint'], BLACK)
S.poly([(ax_ + 2.2, ga, az_ + 0.4), (ax_ + 2.2, ga, az_ + 2.4), (ax_ + 2.2, ga + 0.6, az_ + 2.4), (ax_ + 2.2, ga + 0.6, az_ + 0.4)], L['paint'], BLACK)
# 32  Double Curve: a tall bronze blade, 6 m up, its two edges curving
kx, kz = -2393.0, -410.5
gk = S.g(kx, kz)
prev = None
for k in range(9):
    t = k / 8
    w = 0.55 * math.sin(math.pi * (0.15 + 0.7 * t))
    y = gk + 6.0 * t
    p = ((kx - w, y, kz), (kx + w, y, kz))
    if prev:
        S.poly([prev[0], prev[1], p[1], p[0]], L['paint'], BRONZE)
    prev = p
S.write_hero()

# ---- northeast: Eva Rothschild's Empire, an arch meeting the ground at ten points
x0, x1, z0, z1 = ROOMS['ne']
S = site('sg-room-ne', (x0 + x1) / 2, (z0 + z1) / 2)
room(S, x0, x1, z0, z1)
# An archway of beaded tube: arcs thrown from side to side across a 4.5 m wide way, touching down
# ten times, five each side, tallest in the middle, striped red, black and green along its length.
ex0, ez0, ex1, ez1 = -2344.8, -424.3, -2333.3, -411.8
cols = ['#b5242a', BLACK, '#2f7a46']
lx, lz = ex1 - ex0, ez1 - ez0
ln = math.hypot(lx, lz)
ax_, az_ = lx / ln, lz / ln                       # along the way
cx_, cz_ = -az_, ax_                              # across it
feet = []
for k in range(10):
    t = k / 9
    side = 1 if k % 2 else -1
    feet.append((ex0 + lx * t + cx_ * 2.25 * side, ez0 + lz * t + cz_ * 2.25 * side, t))
S.rings.append([(ex0 - cx_ * 2.6, ez0 - cz_ * 2.6), (ex1 - cx_ * 2.6, ez1 - cz_ * 2.6), (ex1 + cx_ * 2.6, ez1 + cz_ * 2.6), (ex0 + cx_ * 2.6, ez0 + cz_ * 2.6)])
seg = 0
for (x0_, z0_, t0), (x1_, z1_, t1) in zip(feet, feet[1:]):
    H = 2.6 + 3.2 * math.sin(math.pi * (t0 + t1) / 2)
    path = []
    for j in range(13):
        u = j / 12
        x, z = x0_ + (x1_ - x0_) * u, z0_ + (z1_ - z0_) * u
        path.append((x, S.g(x, z) - 0.05 + H * math.sin(math.pi * u) ** 0.8, z))
    for j in range(0, 12, 3):
        S.tube(path[j:j + 4], 0.13, L['paint'], cols[seg % 3], sides=6, caps=False)
        seg += 1
S.write_hero()

# ---- southwest: Dan Graham's labyrinth of perforated steel and two-way mirror on a paved square
x0, x1, z0, z1 = ROOMS['sw']
S = site('sg-room-sw', (x0 + x1) / 2, (z0 + z1) / 2)
room(S, x0, x1, z0, z1)
qx0, qx1, qz0, qz1 = -2399.0, -2387.0, -373.0, -361.0
gq = max(S.g(qx0, qz0), S.g(qx1, qz0), S.g(qx0, qz1), S.g(qx1, qz1))
S.box(qx0, qx1, gq - 0.8, gq + 0.05, qz0, qz1, L['concPlain'], PAVING)
# The zigzag: three mirror walls and two of punched steel, 2.3 m high, with clipped hedge between.
zig = [(-2396.5, -370.5), (-2393.0, -370.5), (-2393.0, -366.5), (-2390.0, -366.5), (-2390.0, -363.5)]
for k, (a, b) in enumerate(zip(zig, zig[1:])):
    S.poly([(a[0], gq, a[1]), (b[0], gq, b[1]), (b[0], gq + 2.3, b[1]), (a[0], gq + 2.3, a[1])], L['glass'] if k % 2 == 0 else L['paint'],
           '#a7b8c4' if k % 2 == 0 else '#4a4c4f')
    S.beam((a[0], gq + 2.3, a[1]), (b[0], gq + 2.3, b[1]), 0.08, 0.08, L['paint'], '#2b2c2e')
S.rings.append([(-2397.0, -371.0), (-2389.6, -371.0), (-2389.6, -363.2), (-2397.0, -363.2)])
S.box(-2397.0, -2396.0, gq, gq + 1.6, -369.5, -364.0, L['grass'], HEDGE)
S.box(-2393.0, -2391.8, gq, gq + 1.6, -365.0, -362.0, L['grass'], HEDGE)
S.write_hero()

# ---- southeast: two Henry Moore bronzes, a standing figure and a reclining mother and child
x0, x1, z0, z1 = ROOMS['se']
S = site('sg-room-se', (x0 + x1) / 2, (z0 + z1) / 2)
room(S, x0, x1, z0, z1)
mx_, mz_ = -2349.0, -374.0
gm = S.g(mx_, mz_)
S.box(mx_ - 0.6, mx_ + 0.6, gm - 0.3, gm + 0.4, mz_ - 0.6, mz_ + 0.6, L['concPlain'], '#9d978c')
S.ellipsoid((mx_, gm + 2.2, mz_), 0.45, 1.9, 0.25, L['paint'], BRONZE, n=8, m=6)
S.ellipsoid((mx_ + 0.1, gm + 4.0, mz_), 0.25, 0.6, 0.15, L['paint'], BRONZE, n=6, m=4)
S.rings.append([(mx_ - 0.6, mz_ - 0.6), (mx_ + 0.6, mz_ - 0.6), (mx_ + 0.6, mz_ + 0.6), (mx_ - 0.6, mz_ + 0.6)])
rx_, rz_ = -2344.5, -372.5
S.rings.append([(rx_ - 1.6, rz_ - 0.8), (rx_ + 1.6, rz_ - 0.8), (rx_ + 1.6, rz_ + 0.8), (rx_ - 1.6, rz_ + 0.8)])
gr = S.g(rx_, rz_)
S.box(rx_ - 1.6, rx_ + 1.6, gr - 0.3, gr + 0.35, rz_ - 0.8, rz_ + 0.8, L['concPlain'], '#9d978c')
S.ellipsoid((rx_ - 0.6, gr + 1.0, rz_), 1.3, 0.7, 0.6, L['paint'], BRONZE, n=8, m=5)
S.ellipsoid((rx_ + 0.9, gr + 1.4, rz_), 0.45, 1.0, 0.5, L['paint'], BRONZE, n=8, m=5)
S.ellipsoid((rx_ + 1.1, gr + 2.5, rz_), 0.3, 0.35, 0.3, L['paint'], BRONZE, n=6, m=4)
S.write_hero()


# ================================================================ the north meadow
# ---- 6  Hahn/Cock: the ultramarine rooster, 4.7 m tall, on a 3 m grey plinth, looking north
S = site('sg-hahn-cock', -2340.6, -538.5)
gp = S.g(-2340.6, -538.5)
PX0, PX1, PZ0, PZ1 = -2342.0, -2339.2, -541.4, -535.6
S.box(PX0, PX1, gp - 0.5, gp + 3.0, PZ0, PZ1, L['concPlain'], '#9c9a97', top=L['concPlain'], top_colour='#a9a7a3')
S.rings.append([(PX0, PZ0), (PX1, PZ0), (PX1, PZ1), (PX0, PZ1)])
Y = gp + 3.0
cx_, cz_ = -2340.6, -538.4
# legs and feet
for side in (-0.35, 0.35):
    S.tube([(cx_ + side, Y, cz_ - 0.2), (cx_ + side, Y + 0.7, cz_), (cx_ + side * 0.8, Y + 1.25, cz_ + 0.1)], 0.12, L['paint'], BLUE, sides=6)
    for toe in (-0.5, 0.0, 0.5):
        S.beam((cx_ + side, Y + 0.05, cz_ - 0.2), (cx_ + side + toe * 0.5, Y + 0.05, cz_ - 0.75), 0.1, 0.1, L['paint'], BLUE)
    S.beam((cx_ + side, Y + 0.05, cz_ - 0.2), (cx_ + side, Y + 0.05, cz_ + 0.35), 0.1, 0.1, L['paint'], BLUE)
# body, breast, neck, head
S.ellipsoid((cx_, Y + 2.0, cz_ + 0.15), 0.85, 0.85, 1.35, L['paint'], BLUE, n=12, m=8)
S.ellipsoid((cx_, Y + 2.25, cz_ - 0.8), 0.75, 0.8, 0.6, L['paint'], BLUE, n=10, m=7)
S.tube([(cx_, Y + 2.5, cz_ - 0.95), (cx_, Y + 3.2, cz_ - 1.25), (cx_, Y + 3.8, cz_ - 1.35)], lambda t: 0.48 - 0.15 * t, L['paint'], BLUE, sides=8)
S.ellipsoid((cx_, Y + 4.05, cz_ - 1.45), 0.3, 0.32, 0.42, L['paint'], BLUE, n=8, m=6)
# beak, comb and wattles
S.tube([(cx_, Y + 4.05, cz_ - 1.85), (cx_, Y + 3.98, cz_ - 2.12)], lambda t: 0.1 - 0.08 * t, L['paint'], BLUE, sides=5)
for k, (dz_, h) in enumerate(((-1.7, 0.45), (-1.5, 0.6), (-1.3, 0.5), (-1.12, 0.35))):
    S.ellipsoid((cx_, Y + 4.3 + h / 2, cz_ + dz_), 0.06, h / 2, 0.11, L['paint'], BLUE, n=6, m=4)
S.ellipsoid((cx_, Y + 3.6, cz_ - 1.75), 0.08, 0.25, 0.12, L['paint'], BLUE, n=6, m=4)
# the tail: sickle feathers arching up and back over it, in a fan
for k in range(7):
    fan = (k - 3) * 0.12
    path = []
    for j in range(8):
        t = j / 7
        path.append((cx_ + fan * (0.3 + t), Y + 2.4 + 2.3 * math.sin(t * 2.4), cz_ + 1.0 + 1.6 * t - 0.4 * t * t * t))
    S.tube(path, lambda t: 0.16 - 0.1 * t, L['paint'], BLUE, sides=5)
# the wing
for side in (-1, 1):
    S.ellipsoid((cx_ + side * 0.72, Y + 2.15, cz_ + 0.25), 0.15, 0.55, 1.05, L['paint'], '#183aa8', n=8, m=5)
S.write_hero()

# ---- 4  Arikidea: steel I-beams leaning together from a round lawn, a wooden swing under them
S = site('sg-arikidea', -2347.0, -580.0)
apex = (-2347.0, S.g(-2347.0, -580.0) + 7.6, -580.5)
feet = [(-2348.5, -588.0), (-2357.0, -576.0), (-2338.5, -578.5), (-2349.0, -574.0)]
S.rings.append([(apex[0] - 1.5, apex[2] - 1.5), (apex[0] + 1.5, apex[2] - 1.5), (apex[0] + 1.5, apex[2] + 1.5), (apex[0] - 1.5, apex[2] + 1.5)])
for fx_, fz_ in feet:
    S.rings.append([(fx_ - 0.4, fz_ - 0.4), (fx_ + 0.4, fz_ - 0.4), (fx_ + 0.4, fz_ + 0.4), (fx_ - 0.4, fz_ + 0.4)])
    S.beam((fx_, S.g(fx_, fz_) - 0.3, fz_), apex, 0.45, 0.32, L['paint'], CORTEN)
# a cross beam lashed over the top, and the swing's chains and seat hung under it
S.beam(add(apex, (-3.2, -0.9, 0.4)), add(apex, (2.6, 0.3, -0.2)), 0.4, 0.3, L['paint'], CORTEN)
sx, sz = -2346.0, -579.6
for ox in (-0.9, 0.9):
    S.beam((sx + ox, apex[1] - 0.3, sz), (sx + ox, S.g(sx, sz) + 0.85, sz), 0.04, 0.04, L['paint'], '#2d2b29')
S.box(sx - 1.1, sx + 1.1, S.g(sx, sz) + 0.75, S.g(sx, sz) + 0.85, sz - 0.6, sz + 0.6, L['paint'], '#9b7a52')
S.write_hero()

# ---- 12  Black Vessel for a Saint: a round temple of black brick, Saint Laurence inside
S = site('sg-black-vessel', -2389.0, -555.5)
vx, vz = -2389.0, -555.5
gv = min(S.g(vx + 2.8 * math.cos(a), vz + 2.8 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 9))
R_OUT, SIDES = 2.8, 20
door = math.radians(160)                        # the doorway faces the path, to the west
ring = []
for k in range(SIDES):
    a0, a1 = 2 * math.pi * k / SIDES, 2 * math.pi * (k + 1) / SIDES
    pa = (vx + R_OUT * math.cos(a0), vz + R_OUT * math.sin(a0))
    pb = (vx + R_OUT * math.cos(a1), vz + R_OUT * math.sin(a1))
    ring.append(pa)
    mid = (a0 + a1) / 2
    in_door = abs(math.atan2(math.sin(mid - door), math.cos(mid - door))) < 0.25
    y0 = gv + (2.4 if in_door else -0.4)
    S.poly([(pa[0], y0, pa[1]), (pb[0], y0, pb[1]), (pb[0], gv + 6.6, pb[1]), (pa[0], gv + 6.6, pa[1])], L['brickRedPlain'], '#3a3836')
    qa = (vx + (R_OUT - 0.4) * math.cos(a0), vz + (R_OUT - 0.4) * math.sin(a0))
    qb = (vx + (R_OUT - 0.4) * math.cos(a1), vz + (R_OUT - 0.4) * math.sin(a1))
    S.poly([(qa[0], y0, qa[1]), (qb[0], y0, qb[1]), (qb[0], gv + 6.6, qb[1]), (qa[0], gv + 6.6, qa[1])], L['brickRedPlain'], '#4a4744')
    S.poly([(pa[0], gv + 6.6, pa[1]), (pb[0], gv + 6.6, pb[1]), (qb[0], gv + 6.6, qb[1]), (qa[0], gv + 6.6, qa[1])], L['concPlain'], '#2a2a2a')
    if in_door:
        S.poly([(pa[0], gv + 2.4, pa[1]), (pb[0], gv + 2.4, pb[1]), (qb[0], gv + 2.4, qb[1]), (qa[0], gv + 2.4, qa[1])], L['concPlain'], '#2a2a2a')
S.poly([(vx + (R_OUT - 0.4) * math.cos(a), gv + 0.05, vz + (R_OUT - 0.4) * math.sin(a)) for a in np.linspace(0, 2 * math.pi, SIDES, endpoint=False)],
       L['concPlain'], '#8f8a82')
# Saint Laurence on a low plinth facing the door
S.box(vx - 0.4, vx + 0.4, gv, gv + 0.9, vz - 0.4, vz + 0.4, L['concPlain'], '#8f8a82')
S.ellipsoid((vx, gv + 1.85, vz), 0.32, 0.95, 0.28, L['concPlain'], '#d9d4c8', n=8, m=5)
S.ellipsoid((vx, gv + 2.95, vz), 0.17, 0.2, 0.17, L['concPlain'], '#d9d4c8', n=6, m=4)
S.rings.append([p for k, p in enumerate(ring) if abs(math.atan2(math.sin(2 * math.pi * (k + 0.5) / SIDES - door), math.cos(2 * math.pi * (k + 0.5) / SIDES - door))) >= 0.25])
S.write_hero()

# ---- 13  X with Columns: two arms of white block crossing, a taller column at each end
S = site('sg-x-columns', -2385.5, -526.8)
arms = [((-2389.5, -529.3), (-2381.5, -524.2)), ((-2381.3, -529.3), (-2389.3, -524.2))]
for (ax_, az_), (bx_, bz_) in arms:
    ln_ = math.hypot(bx_ - ax_, bz_ - az_)
    qx, qz = -(bz_ - az_) / ln_ * 0.6, (bx_ - ax_) / ln_ * 0.6
    S.rings.append([(ax_ - qx, az_ - qz), (bx_ - qx, bz_ - qz), (bx_ + qx, bz_ + qz), (ax_ + qx, az_ + qz)])
    n = 6
    for k in range(n):
        t0, t1 = k / n, (k + 1) / n
        p0 = (ax_ + (bx_ - ax_) * t0, az_ + (bz_ - az_) * t0)
        p1 = (ax_ + (bx_ - ax_) * t1, az_ + (bz_ - az_) * t1)
        y = min(S.g(*p0), S.g(*p1))
        S.beam((p0[0], y - 0.3, p0[1]), (p0[0], y + 3.2, p0[1]), 0.9, 0.9, L['concPlain'], WHITE)
        S.beam((p0[0], y + 2.75, p0[1]), (p1[0], y + 2.75, p1[1]), 0.9, 0.9, L['concPlain'], WHITE)
    for ex, ez in ((ax_, az_), (bx_, bz_)):
        y = S.g(ex, ez)
        S.box(ex - 0.6, ex + 0.6, y - 0.3, y + 4.4, ez - 0.6, ez + 0.6, L['concPlain'], WHITE)
S.write_hero()

# ---- Okciyapi (Help Each Other): rings of stone stepping down to a round pool, west of the pond
S = site('sg-okciyapi', -2426.0, -456.0)
ox_, oz_ = -2426.0, -456.0
go = S.g(ox_, oz_)
for r, y in ((6.6, 0.45), (5.4, 0.3), (4.2, 0.15)):
    pts = [(ox_ + r * math.cos(a), oz_ + r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 28, endpoint=False)]
    S.prism(pts, go - 0.4, go + y, L['concPlain'], '#e3ddd0')
S.rings.append([(ox_ + 6.6 * math.cos(a), oz_ + 6.6 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 12, endpoint=False)])
pts = [(ox_ + 3.0 * math.cos(a), oz_ + 3.0 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 24, endpoint=False)]
S.poly([(x, go + 0.08, z) for x, z in pts], L['paint'], WATER)
S.cylinder(ox_, oz_, 0.35, go, go + 1.1, L['concPlain'], '#d7d0c0', sides=10)
S.write_hero()

