"""Model a tall building's whole form from full-density LiDAR: setbacks, tapers and pyramid tops, as a hero building.

    .venv/bin/python hero_tower.py NAME                 # one of the TOWERS below
    .venv/bin/python hero_tower.py foshay preview       # and draw it (osm-cache/heroes/NAME/preview.png)

hero_massing.py steps a building up in flat terraces from a roof grid, which suits a building of wings and decks. A
tower is mostly walls: a shaft that tapers (the Foshay's obelisk), setbacks every few dozen storeys (Wells Fargo
Center's), notched corners (the IDS Tower's "zogs"). This models it from the side, in slices:

  points   every LiDAR return (the survey classed most of those off the tops of the towers as high noise: they count) over the footprint and 8 m round it (USGS 3DEP MN_CentralMissRiver_4_B22, 2022, all
           depths of the EPT copy: 80-130 points a square metre downtown), cached in osm-cache/heroes/scout/
  heights  a 0.5 m grid in the building's own axes, inside its OpenStreetMap outline: each cell the height of its top
           surface (the second highest return over it, so one stray return doesn't count). On a tapering wall that is
           where the wall passes over the cell, so the grid holds the taper too
  slices   every metre up, the cells at least that high, cleaned up (gaps closed, specks and spires under MIN_AREA
           dropped) and traced round into outlines, simplified to SIMPLIFY metres (masts and spires are left out)
  walls    consecutive slices whose outlines keep their corners and move evenly are one band of wall, from the lowest
           outline to the highest: straight up, or sloping in where the building tapers. Where the outline changes, a
           band ends with a roof, and the next starts on it (a setback). A part that closes in to nothing ends in a
           pyramid up to its highest point
  prism    (if it has one) the walls of a tower from PRISM[0] to PRISM[1] as one outline traced finely half way up,
           straight up
  shaft    (if the tower has one) the walls from SHAFT[0] to SHAFT[1] fitted as one evenly tapering shaft of four
           sides, between the rectangles round its outline there, and a pyramid up to where its cap ends
  dress    each band's facade from the building's facade list by height, each roof the aerial photo's colour over it
           (fetch_city.py; up to PHOTO_MAX), and the extras (the Foshay's name in lights)

Writes heroes/NAME.json (see hero_house.py), seated on the game's ground (city/ground.bin) at the outline's middle.
"""
import json, math, os, subprocess, sys

import laspy
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY, X0, Z0
from footprints import load_osm, min_rect, rings
from hero_kit import L, Mesh, TILE, game_ground

EPT = 'https://s3-us-west-2.amazonaws.com/usgs-lidar-public/MN_CentralMissRiver_4_B22/'
R = 6378137.0
CELL = 0.5
MARGIN = 8.0
MIN_AREA = 30.0                # m²: smaller pieces of a slice (spires, masts, rooftop plant) are left out
SIMPLIFY = 1.1                 # metres: outlines are simplified this far (a tower can say otherwise: simplify)
PRISM_SIMPLIFY = 0.4           # metres: a straight tower's one outline (prism) is traced this finely
TAPER_TOL = 0.8                # metres: a band's middle slices lie this close to the line from its first to its last
CITY = os.path.join(HERE, '..', '..', 'public', 'mpls-drive', 'city')

# name: OpenStreetMap ways of its outline, its facades [(up to height m, layer, colour)], roof colour, extras
TOWERS = {
    # Foshay Tower (1929): an obelisk of Indiana limestone on a two-storey base, its name in lights under the cap
    'foshay': dict(ways=[28525360], facade=[(12, 'brickLitePlain', '#d9ccb0'), (999, 'brickLite', '#e2d6bb')],
                   roof='#c9bfae', letters=('FOSHAY', 0.75), shaft=(22, 123)),
    # Wells Fargo Center (1988, Cesar Pelli): Kasota stone, stepping back to a lit crown
    'wells-fargo': dict(ways=[41763762], facade=[(30, 'brickLitePlain', '#d7c08f'), (999, 'brickLite', '#dcc897')],
                        roof='#d9c99e'),
    # IDS Center (1972, Philip Johnson): the blue glass tower with its zigzag corners, the Crystal Court's stepped
    # glass roof, the Marquette Hotel and the low wings round the block
    'ids': dict(ways=[1385236413], facade=[(14, 'glass', '#a9c4dc'), (999, 'glass', '#8fb3d6')], roof='#9aa5ae',
                prism=(40, 228)),
}

NAME = sys.argv[1]
T = TOWERS[NAME]
SIMPLIFY = T.get('simplify', SIMPLIFY)
CACHE = os.path.join(HERE, 'osm-cache', 'heroes', NAME)
LAZ = os.path.join(HERE, 'osm-cache', 'heroes', 'scout')
os.makedirs(CACHE, exist_ok=True)
os.makedirs(LAZ, exist_ok=True)


def curl(url, path=None):
    args = ['curl', '-sS', '--fail', '--retry', '6', '--retry-all-errors', url] + (['-o', path] if path else [])
    return subprocess.run(args, capture_output=True, check=True).stdout


# ------------------------------------------------------------ the outline
outline = []
for e in load_osm('bld_all'):
    if e['type'] == 'way' and e['id'] in T['ways']:
        outline.append(rings(e)[0][1])
assert outline, 'outline not found in osm-cache/bld_all.json'
allpts = [p for r in outline for p in r]
rect = min_rect(max(outline, key=len))
cx, cz, ang = rect[0], rect[1], rect[2]
ca, sa = math.cos(ang), math.sin(ang)


def to_local(x, z):
    dx, dz = x - cx, z - cz
    return dx * ca + dz * sa, -dx * sa + dz * ca


def to_world(u, v):
    return cx + u * ca - v * sa, cz + u * sa + v * ca


loc = [[to_local(x, z) for x, z in r] for r in outline]
U0 = min(u for r in loc for u, _ in r) - MARGIN
U1 = max(u for r in loc for u, _ in r) + MARGIN
V0 = min(v for r in loc for _, v in r) - MARGIN
V1 = max(v for r in loc for _, v in r) + MARGIN
NU, NV = int((U1 - U0) / CELL) + 1, int((V1 - V0) / CELL) + 1

# ------------------------------------------------------------ the points
pts_path = os.path.join(CACHE, 'points.npy')
if os.path.exists(pts_path):
    P = np.load(pts_path)
else:
    def merc(lat, lon):
        return math.radians(lon) * R, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R
    xs, zs = [p[0] for p in allpts], [p[1] for p in allpts]
    bx0, bx1, bz0, bz1 = min(xs) - MARGIN, max(xs) + MARGIN, min(zs) - MARGIN, max(zs) + MARGIN
    ept = json.loads(curl(EPT + 'ept.json'))
    B = ept['bounds']
    SPAN = B[3] - B[0]
    mx0, my0 = merc(LAT0 - bz1 / MY, LON0 + bx0 / MX)
    mx1, my1 = merc(LAT0 - bz0 / MY, LON0 + bx1 / MX)

    def box(k):
        d, x, y, _ = map(int, k.split('-'))
        s = SPAN / 2 ** d
        return B[0] + x * s, B[1] + y * s, B[0] + (x + 1) * s, B[1] + (y + 1) * s
    found, todo = [], ['0-0-0-0']
    while todo:
        for k, n in json.loads(curl(EPT + f'ept-hierarchy/{todo.pop()}.json')).items():
            a, b, c, d = box(k)
            if not (c > mx0 and a < mx1 and d > my0 and b < my1):
                continue
            if n == -1:
                todo.append(k)
            elif n > 0:
                found.append(k)
    parts = []
    for k in sorted(set(found)):
        path = os.path.join(LAZ, k + '.laz')
        if not os.path.exists(path):
            curl(EPT + f'ept-data/{k}.laz', path)
        las = laspy.read(path)
        lon = np.degrees(np.asarray(las.x) / R)
        lat = np.degrees(2 * np.arctan(np.exp(np.asarray(las.y) / R)) - np.pi / 2)
        x, z = (lon - LON0) * MX, -(lat - LAT0) * MY
        keep = (x > bx0) & (x < bx1) & (z > bz0) & (z < bz1)
        parts.append(np.stack([x[keep], z[keep], np.asarray(las.z)[keep], np.asarray(las.classification)[keep]], 1))
    P = np.concatenate(parts)
    np.save(pts_path, P)
print(NAME, 'points', len(P), flush=True)
G0 = float(np.median(P[P[:, 3] == 2, 2]))

# ------------------------------------------------------------ the height grid
mask_img = Image.new('L', (NU, NV), 0)
for r in loc:
    ImageDraw.Draw(mask_img).polygon([((u - U0) / CELL, (v - V0) / CELL) for u, v in r], fill=1)
inside = ndimage.binary_dilation(np.asarray(mask_img) > 0, iterations=3)       # 1.5 m past the outline: eaves, cornices
Pu, Pv = to_local(P[:, 0], P[:, 1])
ci = np.floor((Pv - V0) / CELL).astype(int)
cj = np.floor((Pu - U0) / CELL).astype(int)
# (the survey classed most returns off the tops of the towers as high noise, 18: they count, up to 300 m)
ok = (ci >= 0) & (ci < NV) & (cj >= 0) & (cj < NU) & (P[:, 3] != 2) & (P[:, 3] != 7) & (P[:, 2] - G0 < 300)
ok &= inside[ci.clip(0, NV - 1), cj.clip(0, NU - 1)]
H = np.zeros((NV, NU))
order = np.lexsort((P[ok, 2], cj[ok], ci[ok]))
keys = (ci[ok] * NU + cj[ok])[order]
hs = P[ok, 2][order] - G0
starts = np.r_[0, np.nonzero(np.diff(keys))[0] + 1, len(keys)]
for a, b in zip(starts[:-1], starts[1:]):
    H[keys[a] // NU, keys[a] % NU] = hs[max(a, b - 2)]                 # the second highest: one stray return doesn't count
# a cell the survey missed between two that it saw takes the lower of its neighbours' heights
H = np.maximum(H, np.minimum(ndimage.maximum_filter(H, 3), ndimage.median_filter(H, 3)) * (H < 1))
TOP = float(np.percentile(H[H > 3], 99.95))
print('ground', round(G0, 2), 'top', round(TOP, 1), flush=True)


# ------------------------------------------------------------ slices into outlines
def trace(mask):
    """The outer boundary of a mask (one component, holes ignored) as a closed list of cell corners (i, j), anticlockwise
    in (u, v)."""
    m = np.pad(mask, 1)
    edges = {}
    ii, jj = np.nonzero(m)
    for i, j in zip(ii, jj):
        if not m[i - 1, j]:
            edges[(i, j)] = (i, j + 1)            # top edge, left to right
        if not m[i + 1, j]:
            edges[(i + 1, j + 1)] = (i + 1, j)
        if not m[i, j - 1]:
            edges[(i + 1, j)] = (i, j)
        if not m[i, j + 1]:
            edges[(i, j + 1)] = (i + 1, j + 1)
    # the longest loop is the outside
    best, seen = [], set()
    for start in list(edges):
        if start in seen:
            continue
        loop, p = [], start
        while p not in seen and p in edges:
            seen.add(p)
            loop.append(p)
            p = edges[p]
        if len(loop) > len(best):
            best = loop
    return [((j - 1) * CELL + U0, (i - 1) * CELL + V0) for i, j in best]


def simplify(ring, tol):
    """Douglas-Peucker on a closed ring, starting from its two furthest-apart corners."""
    n = len(ring)
    if n < 4:
        return ring
    a = 0
    b = max(range(n), key=lambda k: (ring[k][0] - ring[0][0]) ** 2 + (ring[k][1] - ring[0][1]) ** 2)

    def dp(pts):
        if len(pts) < 3:
            return pts
        (ax, ay), (bx, by) = pts[0], pts[-1]
        L_ = math.hypot(bx - ax, by - ay) or 1e-9
        d = [abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / L_ for x, y in pts[1:-1]]
        k = int(np.argmax(d)) + 1
        if d[k - 1] <= tol:
            return [pts[0], pts[-1]]
        return dp(pts[:k + 1])[:-1] + dp(pts[k:])
    first = dp(ring[a:b + 1])
    second = dp(ring[b:] + ring[:1])
    out = first[:-1] + second[:-1]
    # drop corners that turned out collinear
    clean = []
    for k, p in enumerate(out):
        q, r = out[k - 1], out[(k + 1) % len(out)]
        if abs((p[0] - q[0]) * (r[1] - q[1]) - (p[1] - q[1]) * (r[0] - q[0])) > 0.05:
            clean.append(p)
    return clean


def area(ring):
    return abs(sum(ring[k - 1][0] * ring[k][1] - ring[k][0] * ring[k - 1][1] for k in range(len(ring)))) / 2


LEVELS = np.arange(3.0, TOP + 1.0, 1.0)
slices = []          # per level: [(mask, ring)]
for h in LEVELS:
    m = ndimage.binary_closing(H >= h, iterations=2)
    m = ndimage.binary_fill_holes(m)
    m = ndimage.binary_opening(m, iterations=2)          # slivers of returns off a facade, a metre wide, go
    lab, n = ndimage.label(m)
    comps = []
    for k in range(1, n + 1):
        c = lab == k
        if c.sum() * CELL * CELL < MIN_AREA:
            continue
        ring = simplify(trace(c), SIMPLIFY)
        if len(ring) >= 3:
            comps.append((c, ring))
    slices.append(comps)
    if os.environ.get('SLICES') and h % 3 == 0:
        print(f'{h:5.0f}', ' | '.join(f'{c.sum() * CELL * CELL:6.0f} m² {min_rect(r)[3]:5.1f} x {min_rect(r)[4]:5.1f} at '
                                      f'{np.mean([p[0] for p in r]):6.1f} {np.mean([p[1] for p in r]):6.1f} ({len(r)} corners)'
                                      for c, r in comps))


# ------------------------------------------------------------ bands of wall
def aligned(a, b):
    """b's corners in the order of a's (same count; each to the nearest after the best rotation), or None."""
    if len(a) != len(b):
        return None
    best = None
    for s in range(len(b)):
        r = b[s:] + b[:s]
        d = max(math.hypot(p[0] - q[0], p[1] - q[1]) for p, q in zip(a, r))
        if best is None or d < best[0]:
            best = (d, r)
    return best[1] if best[0] < 6 else None


bands = []           # (ring at y0, y0, ring at y1, y1)
open_bands = []      # [mask, y0, ring0, history [(y, ring)]]


def close(band, apex=None):
    mask, y0, ring0, hist = band
    y1, ring1 = hist[-1]
    bands.append((ring0, y0 - 1.0 if y0 == LEVELS[0] else y0 - 1.0, ring1, y1))
    if apex is not None:
        bands.append((ring1, y1, None, apex))


for li, h in enumerate(LEVELS):
    nxt = []
    used = set()
    for mask, ring in slices[li]:
        # the open band this part carries on (the one it overlaps most), if its outline still fits it
        best = None
        for bi, band in enumerate(open_bands):
            if bi in used:
                continue
            ov = (band[0] & mask).sum()
            if ov > 0.5 * mask.sum() and (best is None or ov > best[0]):
                best = (ov, bi)
        if best is not None:
            bi = best[1]
            band = open_bands[bi]
            r = aligned(band[2], ring)
            fits = r is not None
            if fits:
                # every slice in between lies on the line from the band's first outline to this one
                for y, mid in band[3][1:]:
                    t = (y - band[1]) / (h - band[1])
                    m2 = aligned(band[2], mid)
                    if m2 is None or any(math.hypot(p[0] + (q[0] - p[0]) * t - s[0], p[1] + (q[1] - p[1]) * t - s[1]) > TAPER_TOL
                                         for p, q, s in zip(band[2], r, m2)):
                        fits = False
                        break
            used.add(bi)
            if fits:
                band[0] = mask
                band[3].append((h, r))
                nxt.append(band)
                continue
            close(band)
        nxt.append([mask, h, ring, [(h, ring)]])
    for bi, band in enumerate(open_bands):
        if bi not in used:
            # this part ends here: a pyramid if it was closing in to a point, else a flat roof
            y1, ring1 = band[3][-1]
            sel = band[0] & (H > y1)
            apex = None
            # (up to where most of what stands over it ends: a mast on top isn't the roof)
            if area(ring1) < 120 and sel.sum() > 8 and np.percentile(H[sel], 80) > y1 + 2:
                apex = float(np.percentile(H[sel], 80))
            close(band, apex)
    open_bands = nxt
for band in open_bands:
    close(band)


def rect_of(ring, a):
    """The rectangle turned by angle a (in the building's axes) round a ring: its four corners, anticlockwise."""
    c, s = math.cos(a), math.sin(a)
    us = [p[0] * c + p[1] * s for p in ring]
    vs = [-p[0] * s + p[1] * c for p in ring]
    return [(u * c - v * s, u * s + v * c) for u, v in ((min(us), min(vs)), (max(us), min(vs)), (max(us), max(vs)), (min(us), max(vs)))]


def main_ring(y):
    comps = slices[int(round(y - LEVELS[0]))]
    return max(comps, key=lambda cr: cr[0].sum())[1]


def inside_ring(u, v, ring):
    hit = False
    for k in range(len(ring)):
        (x1, y1_), (x2, y2) = ring[k - 1], ring[k]
        if (y1_ > v) != (y2 > v) and u < x1 + (v - y1_) * (x2 - x1) / (y2 - y1_):
            hit = not hit
    return hit


if T.get('shaft'):
    # A shaft that tapers evenly from y0 to y1 and ends in a pyramid: one rectangle round the survey's outline a little
    # over its foot, one a little under its head, sloping walls between them and a pyramid up to where its cap ends.
    # The survey's outlines between them are kept out (their wobbles are the scan's, not the stone's)
    y0, y1 = T['shaft']
    a = min_rect(main_ring(y0 + 3))[2]
    lo, hi = rect_of(main_ring(y0 + 3), a), rect_of(main_ring(y1 - 1), a)
    mu, mv = sum(p[0] for p in lo) / 4, sum(p[1] for p in lo) / 4
    # the head straight over the foot: a shaft that tapers stands plumb, whatever the scan's outline at its head
    hu, hv = sum(p[0] for p in hi) / 4, sum(p[1] for p in hi) / 4
    hi = [(p[0] - hu + mu, p[1] - hv + mv) for p in hi]
    reach = [(mu + (p[0] - mu) * 1.15, mv + (p[1] - mv) * 1.15) for p in lo]
    kept = []
    for r0, b0, r1, b1 in bands:
        cu, cv = sum(p[0] for p in r0) / len(r0), sum(p[1] for p in r0) / len(r0)
        if not inside_ring(cu, cv, reach) or b1 <= y0:
            kept.append((r0, b0, r1, b1))
        elif b0 < y0 and r1 is not None:
            t = (y0 - b0) / (b1 - b0)
            kept.append((r0, b0, [(p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t) for p, q in zip(r0, r1)], y0))
    sel = np.zeros_like(H, bool)
    jj, ii = np.meshgrid(np.arange(NU), np.arange(NV))
    uu, vv = U0 + (jj + 0.5) * CELL, V0 + (ii + 0.5) * CELL
    for k in range(4):                                      # the cells inside the head's rectangle
        (x1, z1), (x2, z2) = hi[k - 1], hi[k]
        sel_k = (x2 - x1) * (vv - z1) - (z2 - z1) * (uu - x1) >= 0
        sel = sel_k if k == 0 else sel & sel_k
    if not sel.any() or (H[sel] > y1).sum() < 8:
        sel = ~sel
    apex = float(np.percentile(H[sel & (H > y1)], 90))
    bands = kept + [(lo, y0, hi, y1), (hi, y1, None, apex)]
    print('shaft', [round(math.hypot(lo[1][0] - lo[0][0], lo[1][1] - lo[0][1]), 1), round(math.hypot(lo[2][0] - lo[1][0], lo[2][1] - lo[1][1]), 1)],
          'to', [round(math.hypot(hi[1][0] - hi[0][0], hi[1][1] - hi[0][1]), 1), round(math.hypot(hi[2][0] - hi[1][0], hi[2][1] - hi[1][1]), 1)],
          'cap', round(y1, 1), 'to', round(apex, 1))
if T.get('prism'):
    # A tower that runs straight up from y0 to y1: its outline from one slice half way up, traced finer (PRISM_SIMPLIFY,
    # so notched corners keep their notches), as one band of upright wall. The survey's bands of that part between are
    # left out (the same outline, wobbling with the scan); those of bigger parts it rises out of, and the crown over
    # it, stay
    y0, y1 = T['prism']
    li = int(round((y0 + y1) / 2 - LEVELS[0]))
    mask = max(slices[li], key=lambda cr: cr[0].sum())[0]
    ring = simplify(trace(mask), PRISM_SIMPLIFY)
    A = area(ring)
    kept = []
    for r0, b0, r1, b1 in bands:
        cu, cv = sum(p[0] for p in r0) / len(r0), sum(p[1] for p in r0) / len(r0)
        mine = inside_ring(cu, cv, ring) and abs(area(r0) - A) < 0.25 * A
        if mine and y0 - 0.5 <= b0 < y1 - 0.5:
            continue
        kept.append((r0, b0, r1, b1))
    bands = kept + [(ring, y0, ring, y1)]
    print('prism', len(ring), 'corners', round(A), 'm² from', y0, 'to', y1)
print('bands', len(bands), flush=True)


# ------------------------------------------------------------ the mesh
def ear_clip(ring):
    """Triangles of a simple polygon [(u, v)] (any winding), as index triples."""
    idx = list(range(len(ring)))
    if sum(ring[k - 1][0] * ring[k][1] - ring[k][0] * ring[k - 1][1] for k in range(len(ring))) < 0:
        idx.reverse()
    out = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            (ax, ay), (bx, by), (cx_, cy) = ring[a], ring[b], ring[c]
            if (bx - ax) * (cy - ay) - (by - ay) * (cx_ - ax) <= 1e-9:
                continue
            ear = True
            for o in idx:
                if o in (a, b, c):
                    continue
                px, py = ring[o]
                d1 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
                d2 = (cx_ - bx) * (py - by) - (cy - by) * (px - bx)
                d3 = (ax - cx_) * (py - cy) - (ay - cy) * (px - cx_)
                if d1 >= 0 and d2 >= 0 and d3 >= 0:
                    ear = False
                    break
            if ear:
                out.append((a, b, c))
                idx.pop(k)
                break
        else:
            break
    if len(idx) == 3:
        out.append(tuple(idx))
    return out


def facade(y):
    for top, layer, col in T['facade']:
        if y <= top:
            return L[layer], col
    return L[T['facade'][-1][1]], T['facade'][-1][2]


gh = game_ground(CITY)
GX, GZ = to_world(0, 0)
mesh = Mesh()


def W(u, y, v):
    x, z = to_world(u, v)
    return (x, y, z)


ROOF = L['concPlain']
PHOTO_MAX = 60      # metres: roofs up to this high take their colour from the aerial photo; a taller one leans out of
                    # place in it (the photo isn't a true orthophoto), so it keeps the tower's roof colour
AER = {}


def roof_colour(ring, y):
    """The median colour of the aerial photo (fetch_city.py) over a roof ring pulled in 1 m, or the tower's roof colour."""
    if y > PHOTO_MAX:
        return T['roof']
    world = [to_world(*p) for p in ring]
    mx, mz = sum(p[0] for p in world) / len(world), sum(p[1] for p in world) / len(world)
    key = (int((mx - X0) // 1000), int((mz - Z0) // 1000))
    if key not in AER:
        path = os.path.join(HERE, 'osm-cache', 'city', 'aerial', f'{key[0]}_{key[1]}.jpg')
        AER[key] = (np.asarray(Image.open(path).convert('RGB')), json.load(open(path[:-4] + '.json'))) if os.path.exists(path) else None
    if AER[key] is None:
        return T['roof']
    img, (w, s_, e, n) = AER[key]
    rad = max(1e-3, sum(math.hypot(p[0] - mx, p[1] - mz) for p in world) / len(world))
    k = max(0.3, 1 - 1.0 / rad)
    pix = [((LON0 + (mx + (x - mx) * k) / MX - w) / (e - w) * img.shape[1], (n - (LAT0 - (mz + (z - mz) * k) / MY)) / (n - s_) * img.shape[0])
           for x, z in world]
    m = Image.new('L', (img.shape[1], img.shape[0]), 0)
    ImageDraw.Draw(m).polygon(pix, fill=1)
    sel = img[np.asarray(m, bool)]
    if len(sel) < 6:
        return T['roof']
    c = np.clip(np.median(sel, axis=0) * 1.15, 0, 255)
    return '#%02x%02x%02x' % tuple(int(v) for v in c)


for ring0, y0, ring1, y1 in bands:
    lay, col = facade((y0 + y1) / 2)
    y0 = max(0.0, y0) if y0 <= LEVELS[0] else y0
    base = -1.5 if y0 <= LEVELS[0] else y0     # the lowest walls run on down into the ground, for the slope
    if ring1 is None:
        # a pyramid from the outline up to its middle
        mu = sum(p[0] for p in ring0) / len(ring0)
        mv = sum(p[1] for p in ring0) / len(ring0)
        for k in range(len(ring0)):
            a, b = ring0[k - 1], ring0[k]
            mesh.poly([W(a[0], y0, a[1]), W(b[0], y0, b[1]), W(mu, y1, mv)], lay, col)
        continue
    n = len(ring0)
    rc = roof_colour(ring1, y1)
    for k in range(n):
        a0, b0, a1, b1 = ring0[k - 1], ring0[k], ring1[k - 1], ring1[k]
        mesh.poly([W(a0[0], base, a0[1]), W(b0[0], base, b0[1]), W(b1[0], y1, b1[1]), W(a1[0], y1, a1[1])], lay, col)
    for a, b, c in ear_clip(ring1):
        mesh.poly([W(ring1[a][0], y1, ring1[a][1]), W(ring1[b][0], y1, ring1[b][1]), W(ring1[c][0], y1, ring1[c][1])], ROOF, rc)
print('triangles', len(mesh.tris), flush=True)

# The Foshay's name in lights on each face, just under its cap: blocky capitals, a lit tube each stroke
FONT = {
    'F': ['111', '100', '110', '100', '100'], 'O': ['111', '101', '101', '101', '111'], 'S': ['111', '100', '111', '001', '111'],
    'H': ['101', '101', '111', '101', '101'], 'A': ['111', '101', '111', '101', '101'], 'Y': ['101', '101', '111', '010', '010'],
}
if T.get('letters'):
    word, px = T['letters']
    # the shaft's last outline before the cap, and its height
    cap = [b for b in bands if b[2] is None]
    shaft = max((b for b in bands if b[2] is not None), key=lambda b: b[3])
    ring, ytop = (cap[0][0], cap[0][1]) if cap else (shaft[2], shaft[3])
    y_mid = ytop - 6.0
    n = len(ring)
    for k in range(n):
        a, b = ring[k - 1], ring[k]
        L_ = math.hypot(b[0] - a[0], b[1] - a[1])
        if L_ < len(word) * 4 * px:
            continue
        ux, uv = (b[0] - a[0]) / L_, (b[1] - a[1]) / L_
        nx, nv = uv, -ux                                   # outward, for an anticlockwise ring
        if sum(p[0] * nx + p[1] * nv for p in ring) / n > a[0] * nx + a[1] * nv:
            nx, nv = -nx, -nv
        width = len(word) * 4 * px - px
        s0 = (L_ - width) / 2
        for ci_, ch in enumerate(word):
            for row, bits in enumerate(FONT[ch]):
                for col_, bit in enumerate(bits):
                    if bit != '1':
                        continue
                    s = s0 + (ci_ * 4 + col_) * px
                    y = y_mid + (2 - row) * px
                    o = 0.35
                    q = lambda ss, yy: W(a[0] + ux * ss + nx * o, yy, a[1] + uv * ss + nv * o)
                    mesh.poly([q(s, y - px / 2), q(s + px, y - px / 2), q(s + px, y + px / 2), q(s, y + px / 2)], L['paint'], '#fff6dc')

rings_out = [[to_world(*p) for p in simplify(r, 0.5)] for r in loc]
gy = gh(GX, GZ)
top = max(b[3] for b in bands)
mesh.write(os.path.join(HERE, 'heroes', NAME + '.json'), NAME, GX, GZ, top, rings_out)
# heights in the record are above the ground at its middle; the survey's ground there is G0, the game's gy (eased)
print('game ground', round(gy, 2), 'survey ground', round(G0, 2))

# ------------------------------------------------------------ a preview, from the south-west and the north-east
if len(sys.argv) > 2 and sys.argv[2] == 'preview':
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure(figsize=(12, 9))
    for k, (el, az) in enumerate(((12, -135), (12, 45), (12, -45), (70, -100))):
        ax = fig.add_subplot(2, 2, k + 1, projection='3d')
        polys, cols = [], []
        light = np.array([0.4, 0.8, 0.3])
        light /= np.linalg.norm(light)
        for corners, _, layer, c in mesh.tris:
            p = np.array([(x - GX, z - GZ, y) for x, y, z in corners])
            nrm = np.cross(p[1] - p[0], p[2] - p[0])
            ln = np.linalg.norm(nrm)
            shade = 0.45 + 0.55 * abs(nrm @ np.array([light[0], light[2], light[1]])) / ln if ln > 1e-9 else 1
            rgb = np.array([int(mesh.cols[c][i:i + 2], 16) for i in (1, 3, 5)]) / 255
            polys.append(p)
            cols.append(np.clip(rgb * shade, 0, 1))
        ax.add_collection3d(Poly3DCollection(polys, facecolors=cols, edgecolors='none'))
        r = max(U1 - U0, V1 - V0) / 2
        ax.set_xlim(-r, r); ax.set_ylim(-r, r); ax.set_zlim(0, top * 1.02)
        ax.set_box_aspect((1, 1, top / (2 * r)))
        ax.view_init(el, az)
        ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(os.path.join(CACHE, 'preview.png'), dpi=80)
    print('preview', os.path.join(CACHE, 'preview.png'))
