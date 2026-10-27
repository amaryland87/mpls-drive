"""A small kit for modelling hero buildings by hand, in the game's style.

Builds the same record hero_house.py writes (see there): triangles, each with a layer of the game's
facade texture array and a colour. Coordinates are world x and z (metres, as in area.py) and height y
in metres above the building's own ground, which the game sets on its ground at (x, z) of the record.

Texture coordinates are worked out for you: every flat piece is mapped in its own plane, in metres
divided by the size of one tile of its layer, so brick courses, siding and shingles run level and
keep their real scale wherever they are.
"""
import gzip, json, math, os

import numpy as np

# Facade texture layers, and the metres one tile of each covers (the game's LAYER and LAYER_M).
L = dict(brickRed=0, brickLite=1, concRibbon=2, glass=3, storefront=4, sidingWin=5, siding=6, garageDoor=7,
         sidingDoor=8, brickRedPlain=9, brickLitePlain=10, concPlain=11, shingles=12, gravel=13, fence=14, metal=15,
         asphalt=16, sidewalk=17, paint=18, grass=19)
TILE = [(2.4, 3.6), (2.4, 3.6), (3, 3.6), (1.5, 3.6), (4.8, 4.5), (2.4, 2.9), (2.4, 2.9), (3, 2.6), (2.4, 2.9), (2.4, 3.6),
        (2.4, 3.6), (3, 3.6), (2, 2), (4, 4), (2.4, 1.8), (1, 1), (4, 4), (1.5, 1.5), (1, 1), (2.8, 2.8)]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


class Mesh:
    def __init__(self):
        self.tris = []          # (corners, uvs, layer, colour index)
        self.cols, self._ci = [], {}

    def col(self, c):
        if c not in self._ci:
            self._ci[c] = len(self.cols)
            self.cols.append(c)
        return self._ci[c]

    # ------------------------------------------------------------- flat pieces
    def poly(self, pts, layer, colour, uv_turn=False):
        """A flat polygon (corners in order, (x, y, z)), fanned into triangles and mapped in its own plane."""
        if len(pts) < 3:
            return
        n = (0.0, 0.0, 0.0)
        for k in range(1, len(pts) - 1):
            c = _cross(_sub(pts[k], pts[0]), _sub(pts[k + 1], pts[0]))
            n = (n[0] + c[0], n[1] + c[1], n[2] + c[2])
        n = _norm(n)
        if abs(n[1]) > 0.98:                        # level: u east, v south
            eu, ev = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
        else:                                       # upright or sloping: u level along it, v up it
            eu = _norm(_cross((0.0, 1.0, 0.0), n))
            ev = _norm(_cross(n, eu))
        if uv_turn:
            eu, ev = ev, eu
        tw, th = TILE[layer]
        uv = [(_dot(p, eu) / tw, _dot(p, ev) / th) for p in pts]
        ci = self.col(colour)
        for k in range(1, len(pts) - 1):
            self.tris.append(((pts[0], pts[k], pts[k + 1]), (uv[0], uv[k], uv[k + 1]), layer, ci))

    def box(self, x0, x1, y0, y1, z0, z1, layer, colour, top=None, top_colour=None, bottom=False, uv_turn=False):
        """An upright box, sides in one layer, the top in another."""
        c = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
        for (ax, az), (bx, bz) in zip(c, c[1:] + c[:1]):
            self.poly([(ax, y0, az), (bx, y0, bz), (bx, y1, bz), (ax, y1, az)], layer, colour, uv_turn)
        self.poly([(x, y1, z) for x, z in c], top if top is not None else layer, top_colour or colour)
        if bottom:
            self.poly([(x, y0, z) for x, z in c], layer, colour)

    def prism(self, ring, y0, y1, layer, colour, top=None, top_colour=None):
        """An upright prism over a ring of (x, z) corners."""
        for (ax, az), (bx, bz) in zip(ring, ring[1:] + ring[:1]):
            self.poly([(ax, y0, az), (bx, y0, bz), (bx, y1, bz), (ax, y1, az)], layer, colour)
        self.poly([(x, y1, z) for x, z in ring], top if top is not None else layer, top_colour or colour)

    def cylinder(self, x, z, r, y0, y1, layer, colour, sides=8):
        pts = [(x + r * math.cos(a * 2 * math.pi / sides), z + r * math.sin(a * 2 * math.pi / sides)) for a in range(sides)]
        self.prism(pts, y0, y1, layer, colour)

    # ------------------------------------------------------------- roofs
    def gable_roof(self, axis, a0, a1, b0, b1, y_eave, y_ridge, layer, colour, ends=None, end_colour=None, over=0.35, fascia=None):
        """A gable roof whose ridge runs along axis ('x' or 'z') from a0 to a1, over the span b0..b1 across it.

        The eaves sit at y_eave over the wall lines b0 and b1 and run out `over` metres past every wall,
        dropping as the slope does. ends: a layer for the triangular gable walls under it (between a0 and a1)."""
        mid = (b0 + b1) / 2
        slope = (y_ridge - y_eave) / ((b1 - b0) / 2)
        ye = y_eave - over * slope
        P = (lambda a, b, y: (a, y, b)) if axis == 'x' else (lambda a, b, y: (b, y, a))
        A0, A1 = a0 - over, a1 + over
        for b_edge in (b0 - over, b1 + over):
            self.poly([P(A0, b_edge, ye), P(A1, b_edge, ye), P(A1, mid, y_ridge), P(A0, mid, y_ridge)], layer, colour, uv_turn=False)
            if fascia:
                self.poly([P(A0, b_edge, ye), P(A1, b_edge, ye), P(A1, b_edge, ye - 0.2), P(A0, b_edge, ye - 0.2)], L['concPlain'], fascia)
        if fascia:
            for a in (A0, A1):
                for b_edge in (b0 - over, b1 + over):
                    self.poly([P(a, b_edge, ye), P(a, mid, y_ridge), P(a, mid, y_ridge - 0.2), P(a, b_edge, ye - 0.2)], L['concPlain'], fascia)
        if ends is not None:
            for a in (a0, a1):
                self.poly([P(a, b0, y_eave), P(a, b1, y_eave), P(a, mid, y_ridge)], ends, end_colour)

    # ------------------------------------------------------------- on a wall
    def on_wall(self, axis, at, out):
        """Points on a wall face: the wall is the plane axis = at ('x' or 'z'), out is +1 or -1 (which way it faces).

        Returns P(along, y, off): a point `along` the wall (the other horizontal axis), `off` metres out from it."""
        if axis == 'z':
            return lambda s, y, off=0.0: (s, y, at + out * off)
        return lambda s, y, off=0.0: (at + out * off, y, s)

    def panel(self, P, s0, s1, y0, y1, off, layer, colour, depth=0.0):
        """A flat panel on a wall from s0 to s1 along it and y0 to y1 up it, off metres out (with sides if depth)."""
        self.poly([P(s0, y0, off), P(s1, y0, off), P(s1, y1, off), P(s0, y1, off)], layer, colour)
        if depth:
            for s in (s0, s1):
                self.poly([P(s, y0, off - depth), P(s, y0, off), P(s, y1, off), P(s, y1, off - depth)], layer, colour)
            for y in (y0, y1):
                self.poly([P(s0, y, off - depth), P(s1, y, off - depth), P(s1, y, off), P(s0, y, off)], layer, colour)

    def window(self, P, s, sill, w, h, frame='#f6f5f0', glass='#2c3e4d', shutters=None, awning=None, arch=False):
        """A window centred s along a wall: a white frame standing a little proud, panes, maybe shutters or an awning."""
        self.panel(P, s - w / 2 - 0.09, s + w / 2 + 0.09, sill - 0.12, sill + h + 0.09, 0.06, L['concPlain'], frame, depth=0.06)
        self.panel(P, s - w / 2, s + w / 2, sill, sill + h, 0.075, L['glass'], glass)
        # glazing bars: one down the middle, one across
        self.panel(P, s - 0.025, s + 0.025, sill, sill + h, 0.08, L['concPlain'], frame)
        self.panel(P, s - w / 2, s + w / 2, sill + h * 0.5 - 0.025, sill + h * 0.5 + 0.025, 0.08, L['concPlain'], frame)
        if arch:
            # a round top, as a few steps of frame over the window
            for k in range(1, 4):
                ww = w / 2 * math.cos(math.asin(k / 4))
                self.panel(P, s - ww, s + ww, sill + h + 0.09 + (k - 1) * w * 0.12, sill + h + 0.09 + k * w * 0.12, 0.06, L['concPlain'], frame)
        if shutters:
            sw = w * 0.48
            for side in (-1, 1):
                a = s + side * (w / 2 + 0.12)
                b = a + side * sw
                self.panel(P, min(a, b), max(a, b), sill - 0.05, sill + h + 0.05, 0.05, L['siding'], shutters, depth=0.04)
        if awning:
            top, out = sill + h + 0.35, 0.75
            y_low = sill + h - 0.15
            self.poly([P(s - w / 2 - 0.15, top, 0.02), P(s + w / 2 + 0.15, top, 0.02), P(s + w / 2 + 0.15, y_low, out), P(s - w / 2 - 0.15, y_low, out)],
                      L['paint'], awning)
            for x in (s - w / 2 - 0.15, s + w / 2 + 0.15):
                self.poly([P(x, top, 0.02), P(x, y_low, out), P(x, y_low - 0.18, out), P(x, y_low - 0.18, 0.02)], L['paint'], awning)
            self.poly([P(s - w / 2 - 0.15, y_low, out), P(s + w / 2 + 0.15, y_low, out), P(s + w / 2 + 0.15, y_low - 0.18, out), P(s - w / 2 - 0.15, y_low - 0.18, out)],
                      L['paint'], awning)

    # ------------------------------------------------------------- out
    def record(self, name, x, z, top, rings):
        rec = dict(name=name, x=round(x, 2), z=round(z, 2), top=round(top, 2), rings=[[[round(a, 2), round(b, 2)] for a, b in r] for r in rings],
                   col=self.cols, p=[], uv=[], f=[])
        for corners, uvs, layer, c in self.tris:
            for px, py, pz in corners:
                rec['p'] += [round(px * 100), round(py * 100), round(pz * 100)]
            for u, v in uvs:
                rec['uv'] += [round(u * 100), round(v * 100)]
            rec['f'] += [layer, c]
        return rec

    def write(self, path, *args):
        json.dump(self.record(*args), open(path, 'w'), separators=(',', ':'))
        print('wrote', path, len(self.tris), 'triangles')


def game_ground(city):
    """groundH(x, z) from the baked city (public/mpls-drive/city): the ground the game draws everything on, in metres
    (mpls-geo.js groundH)."""
    idx = json.load(open(os.path.join(city, 'index.json')))
    gr, (x0, _, z0, _) = idx['gr'], idx['bounds']
    raw = open(os.path.join(city, 'ground.bin'), 'rb').read()
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
