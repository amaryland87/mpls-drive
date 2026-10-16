"""The Irene Hixon Whitney Bridge (Siah Armajani, 1988), modelled by hand: run it to (re)write
heroes/whitney-bridge.json.

    ../.venv/bin/python model_whitney_bridge.py

The footbridge from the Sculpture Garden over Lyndale, I-94 and Hennepin to Loring Park. The game
draws its deck (bake_tiles.py's bridges, from OpenStreetMap, at the height the 2022 LiDAR saw it);
this is everything standing on it, placed from the full-density 2022 LiDAR cached in
osm-cache/heroes/sculpture-garden/ (heights below are metres above E0, as the game's are):

  the deck at -6.9 (8 m over the freeway), between two through trusses 3 m tall, braced overhead;
  the west half, over Lyndale, pale "Jeffersonian" yellow, with a cable hung between two tall gates
      (at the west end and the centre pier, both up to +0.8) that sags down through the truss;
  the east half, over I-94 and Hennepin, baby blue, with an arch rising from the centre gate over it,
      highest (-1.2) about 15 m east of the gate, coming down onto the top chord at the east end;
  piers at the west end, west of I-94 and at the east end (the centre pier stands in the game's
      I-94 lanes, so it's left out).

Which colour and which curve is on which half: the 2022 aerial shows the west half's overhead
bracing pale yellow; the Smithsonian's inventory has the yellow half as the suspension half; and
the LiDAR has the arch over the east half and the sagging cable over the west.
"""
import math, os, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from area import X0, Z0
from hero_kit import L, Mesh

# ---------------------------------------------------------------- the game's ground (as bake_tiles.py ships it)
_g = np.load(os.path.join(os.path.dirname(HERE), 'osm-cache', 'ground.npz'))
GSTEP, GH_ABS = int(_g['step']), _g['h'].astype(np.float64)
E0 = float(np.median(np.concatenate([GH_ABS[0], GH_ABS[-1], GH_ABS[:, 0], GH_ABS[:, -1]])))
GNZ, GNX = GH_ABS.shape


def ground(x, z):
    """The game's ground height at (x, z) (the bridge is far from the map's eased edge)."""
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
YELLOW = '#efdd93'          # "Jeffersonian Yellow"
BLUE = '#9ec5e6'            # "elegant baby blue"
PIER = '#c9c2b2'


class Hero(Mesh):
    def __init__(self, name, cx, cz):
        super().__init__()
        self.name, self.cx, self.cz = name, cx, cz
        self.g0 = ground(cx, cz)
        self.top = 0.0

    def poly(self, pts, layer, colour, uv_turn=False):
        self.top = max(self.top, max(p[1] for p in pts))
        super().poly(pts, layer, colour, uv_turn)

    def beam(self, a, b, w, h, colour, layer=L['paint'], caps=False):
        """A square-sectioned bar from point a to point b, w across and h deep (open-ended unless caps)."""
        _, s, u = frame(sub(b, a))
        off = [add(mul(s, w * i / 2), mul(u, h * j / 2)) for i, j in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        A = [add(a, o) for o in off]
        B = [add(b, o) for o in off]
        for k in range(4):
            self.poly([A[k], A[(k + 1) % 4], B[(k + 1) % 4], B[k]], layer, colour)
        if caps:
            self.poly(A, layer, colour)
            self.poly(B, layer, colour)

    def write_hero(self):
        self.write(os.path.join(HERE, f'{self.name}.json'), self.name, self.cx, self.cz, self.top, [])


# ---------------------------------------------------------------- the line of the deck
# The deck the game draws runs along OpenStreetMap's line, from the west landing to where it turns
# north for the ramp down to Loring Park; the trusses stand on its edges (the game's railings are
# just inside them).
A_ = (-2302.0, -438.6)
B_ = (-2211.0, -438.2)
XW, XC, XE = -2313.0, -2252.5, -2206.0       # west gate, centre gate (on the centre pier), east end
HW = 2.45                                   # half the width between the trusses
H = Hero('whitney-bridge', (XW + XE) / 2, A_[1] + (B_[1] - A_[1]) * ((XW + XE) / 2 - A_[0]) / (B_[0] - A_[0]))
Y = lambda v: v - H.g0                      # heights above E0 into the hero's own
YD = Y(-6.9 + 0.06)                         # the deck's top
YT = Y(-3.9)                                # the top chords
YG = Y(0.8)                                 # the gates' tops
_ux, _uz = B_[0] - A_[0], B_[1] - A_[1]
_n = math.hypot(_ux, _uz)
UX, UZ = _ux / _n, _uz / _n                 # along the bridge, east
NX, NZ = -UZ, UX                            # across it


def P(x, side, y):
    """The point on the deck's line at world x, `side` metres across it, at hero height y."""
    t = (x - A_[0]) / UX
    return (A_[0] + UX * t + NX * side, y, A_[1] + UZ * t + NZ * side)


def colour_at(x):
    return YELLOW if x < XC else BLUE


def panels(x0, x1, size):
    n = max(1, round((x1 - x0) / size))
    return [x0 + (x1 - x0) * k / n for k in range(n + 1)]


# ---------------------------------------------------------------- the trusses
# Each half its own run of panels about 3 m long: verticals at the panel points, a diagonal across
# each panel leaning down towards the half's middle (a Pratt truss), chords top and bottom; overhead,
# a cross beam at each panel point and an X of bracing across each panel.
for x0, x1, c in ((XW, XC, YELLOW), (XC, XE, BLUE)):
    xs = panels(x0, x1, 3.0)
    mid = (x0 + x1) / 2
    for s in (-HW, HW):
        H.beam(P(x0, s, YD + 0.12), P(x1, s, YD + 0.12), 0.3, 0.3, c)
        H.beam(P(x0, s, YT), P(x1, s, YT), 0.32, 0.3, c)
        for k, x in enumerate(xs):
            H.beam(P(x, s, YD), P(x, s, YT), 0.2, 0.2, c)
            if k:
                xa, xb = xs[k - 1], x
                if (xa + xb) / 2 < mid:
                    H.beam(P(xa, s, YT), P(xb, s, YD + 0.12), 0.14, 0.14, c)
                else:
                    H.beam(P(xa, s, YD + 0.12), P(xb, s, YT), 0.14, 0.14, c)
    for k, x in enumerate(xs):
        H.beam(P(x, -HW, YT), P(x, HW, YT), 0.18, 0.22, c)
        if k:
            H.beam(P(xs[k - 1], -HW, YT + 0.05), P(x, HW, YT + 0.05), 0.08, 0.08, c)
            H.beam(P(xs[k - 1], HW, YT + 0.05), P(x, -HW, YT + 0.05), 0.08, 0.08, c)

# ---------------------------------------------------------------- the gates
# Tall square frames over the deck: at the west end, and at the centre pier where the colours meet
# (its west posts yellow, its east posts blue, as the halves they belong to).
for gx, depth in ((XW, 2.5), (XC, 3.0)):
    for side in (-HW, HW):
        for x in (gx - depth / 2, gx + depth / 2):
            H.beam(P(x, side, YD), P(x, side, YG), 0.34, 0.34, colour_at(x), caps=True)
        for y in (YT + 1.6, YG - 0.15):
            H.beam(P(gx - depth / 2, side, y), P(gx + depth / 2, side, y), 0.26, 0.26, colour_at(gx - 0.01))
    for x in (gx - depth / 2, gx + depth / 2):
        for y in (YT + 1.6, YG - 0.15):
            H.beam(P(x, -HW, y), P(x, HW, y), 0.26, 0.26, colour_at(x))
    H.beam(P(gx, -HW, YG - 0.15), P(gx, HW, YG - 0.15), 0.2, 0.2, colour_at(gx - 0.01))

# ---------------------------------------------------------------- the west half's hanging cable
# Hung in each truss's plane from the west gate's top to the centre gate's, sagging to just over a
# metre above the deck halfway between; tied to the top chord at the panel points where it's above it.
C0, C1 = XW + 1.25, XC - 1.5
CTOP, CLOW = YG - 0.4, Y(-5.8)


def cable_y(x):
    half = (C1 - C0) / 2
    return CLOW + (CTOP - CLOW) * (abs(x - (C0 + C1) / 2) / half) ** 2.4


xs = list(np.linspace(C0, C1, 25))
for s in (-HW, HW):
    for xa, xb in zip(xs, xs[1:]):
        H.beam(P(xa, s, cable_y(xa)), P(xb, s, cable_y(xb)), 0.18, 0.18, YELLOW)
    for x in panels(XW, XC, 3.0):
        if C0 + 0.5 < x < C1 - 0.5:
            H.beam(P(x, s, cable_y(x)), P(x, s, YT), 0.1, 0.1, YELLOW)

# ---------------------------------------------------------------- the east half's arch
# From the centre gate, over the top chord, highest about 15 m east of the gate, down onto the
# chord near the east end; in each truss's plane, with a post down to the chord at each panel point.
AX, AY, AK = -2236.0, Y(-1.2), 0.00496
A0 = XC + 1.5
A1 = AX + math.sqrt((AY - YT) / AK)


def arch_y(x):
    return AY - AK * (x - AX) ** 2


xs = list(np.linspace(A0, A1, 18))
for s in (-HW, HW):
    for xa, xb in zip(xs, xs[1:]):
        H.beam(P(xa, s, arch_y(xa)), P(xb, s, arch_y(xb)), 0.26, 0.34, BLUE)
    for x in panels(XC, XE, 3.0):
        if A0 + 0.5 < x < A1 - 0.5:
            H.beam(P(x, s, arch_y(x)), P(x, s, YT), 0.12, 0.12, BLUE)

# ---------------------------------------------------------------- piers
# A column under each truss and a cap beam across under the deck, down to the ground.
for px in (XW + 1.0, -2273.0, XE + 2.0):
    under = YD - 0.8
    for s in (-HW + 0.3, HW - 0.3):
        q = P(px, s, 0)
        g = Y(ground(q[0], q[2]))
        H.beam((q[0], g - 0.5, q[2]), (q[0], under, q[2]), 0.8, 0.8, PIER, L['concPlain'])
    H.beam(P(px, -HW - 0.2, under), P(px, HW + 0.2, under), 0.9, 0.7, PIER, L['concPlain'], caps=True)

H.write_hero()
