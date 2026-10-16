"""3800 Beard Ave S, modelled by hand: run it to (re)write heroes/3800-beard.json.

    ../.venv/bin/python model_3800_beard.py

A brick-and-white centre-hall Colonial on the corner of W 38th St (its front) and Beard Ave S.
Sizes and heights are measured from the full-density 2022 LiDAR over the lot (hero_house.py
fetches it into osm-cache/heroes/3800-beard/); the look follows street photos of the house:
red brick below and white above, green shutters at every window, an arched portico over a
green front door, three gabled dormers on the front roof, a brick chimney up the Beard Ave
gable end with green awnings over the windows either side of it, a white glassed sunroom with a
railed roof deck at the back, a one-storey white addition on the west, the garage by the alley,
and steps up from the sidewalk between brick pillars, lamps and stone planter walls.
"""
import math, os, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from hero_kit import L, Mesh

# Ground: heights below are above the ground at the house (G0), as the survey measured it.
pts = np.load(os.path.join(os.path.dirname(HERE), 'osm-cache', 'heroes', '3800-beard', 'points.npy'))
gp = pts[pts[:, 3] == 2]
CX, CZ = -5148.0, 3560.0
G0 = float(np.median(gp[np.hypot(gp[:, 0] - CX, gp[:, 1] - CZ) < 20, 2]))


def ground(x, z, r=1.5):
    near = gp[np.hypot(gp[:, 0] - x, gp[:, 1] - z) < r]
    return float(np.median(near[:, 2])) - G0 if len(near) else 0.0


# Colours
BRICK = '#e2c4ba'          # tints the red brick layer a little browner
WHITE = '#f3f1ea'
TRIM = '#f8f7f2'
GREEN = '#1f4a39'
ROOF = '#55565a'
FOUND = '#b7b1a6'
STONE = '#bdb5a5'
BLACK = '#1d1f22'
GRAVEL = '#d7d2c8'

# The house's walls (world x east, z south): the main block, its two rear wings, and the parts round it.
W, E, N = -5151.35, -5139.15, 3551.75     # main block: west and east walls, front wall on 38th
S_E, S_W = 3563.45, 3567.35               # the back walls of the east and west rear wings
MID = -5145.5                             # where the two rear wings meet
RIDGE_Z = 3556.3
STRING = 3.45                             # top of the brick storey
TOP = 6.95                                # walls up to the eaves

m = Mesh()


def wall(x0, z0, x1, z1, top=TOP, upper=True):
    """A wall from (x0, z0) to (x1, z1): concrete foundation, brick storey, white trim band, white upper storey."""
    def q(y0, y1, layer, colour, off=0.0):
        nx, nz = (z1 - z0), -(x1 - x0)
        n = (nx * nx + nz * nz) ** 0.5 or 1
        ox, oz = nx / n * off, nz / n * off
        m.poly([(x0 + ox, y0, z0 + oz), (x1 + ox, y0, z1 + oz), (x1 + ox, y1, z1 + oz), (x0 + ox, y1, z0 + oz)], layer, colour)
    q(-0.6, 0.35, L['concPlain'], FOUND)
    q(0.35, min(STRING, top), L['brickRedPlain'], BRICK)
    if upper and top > STRING:
        q(STRING, top, L['siding'], WHITE)


# ---------------------------------------------------------------- walls
for a, b in [((W, N), (E, N)), ((E, N), (E, S_E)), ((E, S_E), (MID, S_E)), ((MID, S_E), (MID, S_W)),
             ((MID, S_W), (W, S_W)), ((W, S_W), (W, N))]:
    wall(a[0], a[1], b[0], b[1], top=7.1 if a[1] >= RIDGE_Z and b[1] >= RIDGE_Z and a[0] != E else TOP)
# A white band between the brick and the siding, all the way round.
ring = [(W, N), (E, N), (E, S_E), (MID, S_E), (MID, S_W), (W, S_W)]
for (ax, az), (bx, bz) in zip(ring, ring[1:] + ring[:1]):
    dx, dz = bx - ax, bz - az
    n = (dx * dx + dz * dz) ** 0.5
    ox, oz = dz / n * 0.05, -dx / n * 0.05
    m.poly([(ax - ox, STRING - 0.08, az - oz), (bx - ox, STRING - 0.08, bz - oz), (bx - ox, STRING + 0.12, bz - oz), (ax - ox, STRING + 0.12, az - oz)],
           L['concPlain'], TRIM)

# ---------------------------------------------------------------- roofs
# Main roof: gables east and west, ridge along the house; two rear wings with their own gables to the south.
m.gable_roof('x', W, E, N, 2 * RIDGE_Z - N, TOP, 10.5, L['shingles'], ROOF, ends=L['siding'], end_colour=WHITE, fascia=TRIM)
m.gable_roof('z', RIDGE_Z, S_W, W, MID, 7.1, 9.5, L['shingles'], ROOF, ends=L['siding'], end_colour=WHITE, fascia=TRIM)
m.gable_roof('z', RIDGE_Z, S_E, MID, E, 7.0, 9.6, L['shingles'], ROOF, ends=L['siding'], end_colour=WHITE, fascia=TRIM)

# Three gabled dormers on the front slope, each with a little arched window between shutters.
slope = (10.5 - TOP) / (RIDGE_Z - N)
for s in (-5141.85, -5145.25, -5148.85):
    zf, zb = 3552.55, 3555.4
    m.box(s - 0.8, s + 0.8, TOP + (zf - N) * slope - 0.3, 8.75, zf, zb, L['siding'], WHITE)
    m.gable_roof('z', zf, zb, s - 0.8, s + 0.8, 8.75, 9.45, L['shingles'], ROOF, ends=L['siding'], end_colour=WHITE, over=0.15, fascia=TRIM)
    P = m.on_wall('z', zf, -1)
    m.window(P, s, 7.85, 0.6, 0.75, shutters=GREEN, arch=True)

# The chimney up the middle of the Beard Ave gable: broad to the eaves, then a shaft past the ridge.
m.box(E, E + 0.75, -0.6, 6.2, 3555.35, 3557.25, L['brickRedPlain'], BRICK)
m.poly([(E + 0.75, 6.2, 3555.35), (E + 0.75, 6.2, 3557.25), (E + 0.55, 6.9, 3556.85), (E + 0.55, 6.9, 3555.75)], L['brickRedPlain'], BRICK)
m.box(E, E + 0.55, 6.2, 11.3, 3555.75, 3556.85, L['brickRedPlain'], BRICK)
m.box(E - 0.06, E + 0.61, 11.3, 11.45, 3555.69, 3556.91, L['concPlain'], '#8d8a84')

# ---------------------------------------------------------------- the front, on 38th
P = m.on_wall('z', N, -1)
DOOR = -5145.25
for s in (-5140.6, -5142.3, -5147.95, -5149.75):
    m.window(P, s, 0.95, 1.0, 1.65, shutters=GREEN)
    m.window(P, s, 4.15, 1.0, 1.5, shutters=GREEN)
for s in (-5144.7, -5145.8):
    m.window(P, s, 4.25, 0.5, 1.3, shutters=None)
# The door: green, with sidelights and a fanlight, in a white surround.
m.panel(P, DOOR - 0.95, DOOR + 0.95, 0.45, 3.05, 0.04, L['concPlain'], TRIM)
m.panel(P, DOOR - 0.5, DOOR + 0.5, 0.45, 2.6, 0.07, L['paint'], GREEN)
m.panel(P, DOOR - 0.38, DOOR + 0.38, 1.5, 2.45, 0.08, L['glass'], '#2c3e4d')
for side in (-1, 1):
    m.panel(P, DOOR + side * 0.58, DOOR + side * 0.85, 0.9, 2.6, 0.07, L['glass'], '#2c3e4d')
for k in range(4):
    ww = 0.8 * math.cos(math.asin(min(0.99, (k + 0.5) / 4)))
    m.panel(P, DOOR - ww, DOOR + ww, 2.65 + k * 0.09, 2.65 + (k + 1) * 0.09, 0.07, L['glass'], '#2c3e4d')
# The portico: a brick stoop, two white columns, and an arched pediment.
m.box(DOOR - 1.6, DOOR + 1.6, -0.6, 0.45, N - 1.7, N, L['brickRedPlain'], BRICK, top=L['concPlain'], top_colour='#cfcac0')
for side in (-1, 1):
    m.cylinder(DOOR + side * 1.05, N - 1.35, 0.13, 0.45, 2.95, L['concPlain'], TRIM)
    m.cylinder(DOOR + side * 1.05, N - 0.12, 0.1, 0.45, 2.95, L['concPlain'], TRIM)
m.box(DOOR - 1.25, DOOR + 1.25, 2.95, 3.25, N - 1.55, N, L['concPlain'], TRIM)
m.gable_roof('z', N - 1.55, N, DOOR - 1.25, DOOR + 1.25, 3.25, 4.0, L['shingles'], ROOF, ends=L['concPlain'], end_colour=TRIM, over=0.12, fascia=TRIM)

# Steps from the sidewalk up to the stoop, between brick cheek walls; pillars, lamps and planter walls.
SIDEWALK_Z = 3542.6
ys = ground(DOOR, SIDEWALK_Z - 0.6)
walk_y = max(ys + 0.6, ground(DOOR, 3547.5))
steps = max(3, round((walk_y - ys) / 0.17))
z = SIDEWALK_Z
for k in range(steps):                                   # the lower flight, up from the sidewalk
    y = ys + (k + 1) * (walk_y - ys) / steps
    m.box(DOOR - 0.9, DOOR + 0.9, y - 1.5, y, z, z + 0.32, L['concPlain'], '#cbc6bd')
    z += 0.32
m.box(DOOR - 0.9, DOOR + 0.9, walk_y - 1.5, walk_y, z, N - 2.6, L['sidewalk'], '#d5d0c6')      # the walk
up = max(2, round((0.45 - walk_y) / 0.17))
zz = N - 2.6
for k in range(up):                                      # and a few more up onto the stoop
    y = walk_y + (k + 1) * (0.45 - walk_y) / up
    m.box(DOOR - 0.9, DOOR + 0.9, y - 1.5, y, zz, zz + 0.9 / up, L['concPlain'], '#cbc6bd')
    zz += 0.9 / up
for side in (-1, 1):
    x0 = DOOR + side * 0.9
    x1 = x0 + side * 0.25
    for k in range(steps):                               # a low brick cheek wall stepping up beside the stairs
        y = ys + (k + 1) * (walk_y - ys) / steps
        m.box(min(x0, x1), max(x0, x1), y - 1.5, y + 0.22, SIDEWALK_Z + k * 0.32, SIDEWALK_Z + (k + 1) * 0.32, L['brickRedPlain'], BRICK,
              top=L['concPlain'], top_colour='#d8d3c9')
    # brick pillars at the bottom, a stone cap and a stone lion on each (the house number and "Beard" on them)
    px = DOOR + side * 1.55
    m.box(px - 0.35, px + 0.35, ys - 1, ys + 0.85, SIDEWALK_Z + 0.1, SIDEWALK_Z + 0.8, L['brickRedPlain'], BRICK)
    m.box(px - 0.42, px + 0.42, ys + 0.85, ys + 0.97, SIDEWALK_Z + 0.03, SIDEWALK_Z + 0.87, L['concPlain'], '#d8d3c9')
    m.box(px - 0.15, px + 0.15, ys + 0.97, ys + 1.5, SIDEWALK_Z + 0.25, SIDEWALK_Z + 0.65, L['concPlain'], '#b4b0a8')
    m.box(px - 0.12, px + 0.12, ys + 1.5, ys + 1.72, SIDEWALK_Z + 0.33, SIDEWALK_Z + 0.57, L['concPlain'], '#b4b0a8')
    # a black lamp post behind it
    lx, lz = DOOR + side * 1.65, SIDEWALK_Z + 1.4
    lg = ground(lx, lz)
    m.cylinder(lx, lz, 0.05, lg - 0.3, lg + 2.2, L['metal'], BLACK, sides=6)
    m.box(lx - 0.11, lx + 0.11, lg + 2.2, lg + 2.48, lz - 0.11, lz + 0.11, L['paint'], '#f3e2a6')
    m.box(lx - 0.15, lx + 0.15, lg + 2.48, lg + 2.56, lz - 0.15, lz + 0.15, L['metal'], BLACK)
    m.box(lx - 0.13, lx + 0.13, lg + 2.14, lg + 2.2, lz - 0.13, lz + 0.13, L['metal'], BLACK)
    # a curving stone planter wall across the front lawn
    prev = None
    for k in range(9):
        t = k / 8
        x = DOOR + side * (2.1 + t * 6.2)
        z = 3545.4 + 1.6 * t * t
        if prev:
            g = max(ground(*prev), ground(x, z))
            xa, xb = sorted((prev[0], x))
            m.box(xa - 0.05, xb + 0.05, g - 1.2, g + 0.45, min(prev[1], z) - 0.2, max(prev[1], z) + 0.2, L['brickLitePlain'], STONE,
                  top=L['concPlain'], top_colour='#cfc8ba')
        prev = (x, z)

# ---------------------------------------------------------------- the Beard Ave side
P = m.on_wall('x', E, 1)
for s in (3553.7, 3558.95):
    m.window(P, s, 0.95, 1.0, 1.6, awning=GREEN)
    m.window(P, s, 4.15, 1.0, 1.5, shutters=GREEN)
for s in (3554.85, 3557.75):
    m.window(P, s, 7.75, 0.5, 0.85, arch=True)
m.window(P, 3561.9, 4.15, 0.9, 1.4, shutters=GREEN)

# ---------------------------------------------------------------- the back and the west side
P = m.on_wall('z', S_W, 1)
for s in (-5149.85, -5147.0):
    m.window(P, s, 0.95, 1.0, 1.6, shutters=GREEN)
    m.window(P, s, 4.15, 1.0, 1.4, shutters=GREEN)
m.window(P, -5148.4, 7.55, 0.6, 0.8, arch=True)
P = m.on_wall('z', S_E, 1)
m.panel(P, -5144.1, -5143.1, 4.6, 6.75, 0.07, L['glass'], '#2c3e4d')            # the door out onto the sunroom roof
m.panel(P, -5144.25, -5142.95, 4.6, 6.9, 0.05, L['concPlain'], TRIM)
m.window(P, -5141.0, 4.6, 1.0, 1.4, shutters=GREEN)
m.window(P, -5142.3, 7.6, 0.6, 0.8, arch=True)
P = m.on_wall('x', MID, 1)
m.window(P, 3565.4, 4.15, 0.9, 1.4, shutters=GREEN)
m.window(P, 3565.4, 0.95, 0.9, 1.5, shutters=GREEN)
P = m.on_wall('x', W, -1)
for s in (3553.6, 3558.6, 3562.2, 3565.6):
    m.window(P, s, 4.15, 1.0, 1.45, shutters=GREEN)
for s in (3561.9, 3565.6):
    m.window(P, s, 0.95, 1.0, 1.6, shutters=GREEN)
for s in (3554.9, 3557.7):
    m.window(P, s, 7.75, 0.5, 0.85, arch=True)

# ---------------------------------------------------------------- the one-storey white addition on the west
AW, AN, AS = -5156.7, 3555.0, 3559.3
for a, b in [((AW, AN), (W, AN)), ((AW, AS), (W, AS)), ((AW, AN), (AW, AS))]:
    m.poly([(a[0], -0.6, a[1]), (b[0], -0.6, b[1]), (b[0], 0.35, b[1]), (a[0], 0.35, a[1])], L['concPlain'], FOUND)
    m.poly([(a[0], 0.35, a[1]), (b[0], 0.35, b[1]), (b[0], 3.85, b[1]), (a[0], 3.85, a[1])], L['siding'], WHITE)
m.box(AW - 0.15, W, 3.85, 4.1, AN - 0.15, AS + 0.15, L['concPlain'], TRIM, top=L['gravel'], top_colour=GRAVEL)
P = m.on_wall('z', AN, -1)
for s in (-5155.2, -5153.0):
    m.window(P, s, 1.0, 1.1, 1.7)
P = m.on_wall('x', AW, -1)
for s in (3556.2, 3558.1):
    m.window(P, s, 1.0, 1.1, 1.7)

# ---------------------------------------------------------------- the sunroom, with a railed deck on its roof
SW_, SE_, SN, SS = -5144.2, -5138.0, S_E, 3570.5
corners = [(SW_, SN), (SE_, SN), (SE_, SS), (SW_, SS)]
for (ax, az), (bx, bz) in zip(corners[1:], corners[2:] + corners[:1]):
    m.poly([(ax, -0.6, az), (bx, -0.6, bz), (bx, 0.95, bz), (ax, 0.95, az)], L['siding'], WHITE)
    m.poly([(ax, 0.95, az), (bx, 0.95, bz), (bx, 3.55, bz), (ax, 3.55, az)], L['glass'], '#33475a')
    m.poly([(ax, 3.55, az), (bx, 3.55, bz), (bx, 4.35, bz), (ax, 4.35, az)], L['concPlain'], TRIM)
    # white posts between the panes
    length = ((bx - ax) ** 2 + (bz - az) ** 2) ** 0.5
    n = max(1, round(length / 1.0))
    for k in range(n + 1):
        t = k / n
        px, pz = ax + (bx - ax) * t, az + (bz - az) * t
        m.box(px - 0.07, px + 0.07, 0.95, 3.55, pz - 0.07, pz + 0.07, L['concPlain'], TRIM)
# (the side against the house is the house wall)
m.poly([(SW_ - 0.15, 4.45, SN), (SE_ + 0.15, 4.45, SN), (SE_ + 0.15, 4.45, SS + 0.15), (SW_ - 0.15, 4.45, SS + 0.15)], L['gravel'], GRAVEL)
for (ax, az), (bx, bz) in [((SW_, SN), (SW_, SS)), ((SW_, SS), (SE_, SS)), ((SE_, SS), (SE_, SN))]:
    m.poly([(ax, 4.35, az), (bx, 4.35, bz), (bx, 4.45, bz), (ax, 4.45, az)], L['concPlain'], TRIM)
    length = ((bx - ax) ** 2 + (bz - az) ** 2) ** 0.5
    n = max(1, round(length / 0.9))
    for k in range(n + 1):
        t = k / n
        px, pz = ax + (bx - ax) * t, az + (bz - az) * t
        m.box(px - 0.035, px + 0.035, 4.45, 5.45, pz - 0.035, pz + 0.035, L['metal'], BLACK)
    m.box(min(ax, bx) - 0.04, max(ax, bx) + 0.04, 5.4, 5.48, min(az, bz) - 0.04, max(az, bz) + 0.04, L['metal'], BLACK)

# ---------------------------------------------------------------- the garage, by the alley
GW, GE, GN, GS = -5156.7, -5152.2, 3567.0, 3573.5
m.box(GW, GE, -0.3, 0.2, GN, GS, L['concPlain'], FOUND)
m.box(GW, GE, 0.2, 3.0, GN, GS, L['siding'], WHITE)
m.box(GW - 0.15, GE + 0.15, 3.0, 3.25, GN - 0.15, GS + 0.15, L['concPlain'], TRIM, top=L['gravel'], top_colour=GRAVEL)
P = m.on_wall('x', GW, -1)
m.panel(P, 3568.9, 3571.6, 0.0, 2.3, 0.04, L['garageDoor'], TRIM)
P = m.on_wall('z', GN, -1)
m.window(P, -5154.45, 1.0, 0.9, 1.0)

rings = [[(W, N), (E, N), (E, S_E), (MID, S_E), (MID, S_W), (W, S_W)],
         [(AW, AN), (W, AN), (W, AS), (AW, AS)],
         [(SW_, SN), (SE_, SN), (SE_, SS), (SW_, SS)],
         [(GW, GN), (GE, GN), (GE, GS), (GW, GS)]]
m.write(os.path.join(HERE, '3800-beard.json'), '3800-beard', CX, CZ, 11.45, rings)
print('ground: sidewalk', round(ys, 2), 'walk', round(walk_y, 2))
