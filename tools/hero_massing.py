"""Model a big building in detail from full-density LiDAR and an aerial photo: a hero building's whole massing.

    .venv/bin/python hero_massing.py NAME WAY[,WAY...] [BRICK] [CELL]
    e.g. .venv/bin/python hero_massing.py calhoun-beach-club 1365387350 '#e3c2b2'

hero_house.py models a house: one roof of a few faces over one ring of walls. A big building steps: a tower over a
podium, wings at different heights, a courtyard deck with tennis courts, hip roofs of tile on top. This models that:

  points  every LiDAR return over the outline and 6 m round it (USGS 3DEP MN_CentralMissRiver_4_B22, 2022, all
          depths of the EPT copy), cached in osm-cache/heroes/NAME/
  heights a CELL (default 0.5 m) grid in the building's own axes, inside its OpenStreetMap outline(s) (ways fetched
          into osm-cache/bld_all.json if they aren't there): each cell the median of the single returns over it (the
          roof, not the trees), small holes filled from round them; cells under 2.2 m are open ground (courtyards)
  roofs   each cell's height the upper returns over it (the roof, not the facade below its edge); the roof's faces
          found as planes one at a time (RANSAC): flat decks, sloping ramps, each face of a hip roof; what fits none
          a flat step at its own height; drawn as big rectangles of one colour; rooftop plant as boxes
  walls   round the outline, from below the ground up to the roof inside, stepping with it, and between surfaces
          wherever one stands over the next by more than 0.8 m (a tower over its podium); brick with the game's
          windowed facade (a window a bay and a floor), plain brick where a wall is under a storey tall
  colour  every roof cell takes the aerial photo's colour over it (Hennepin County 2022), reduced to 32 colours, so
          tennis courts, a pool deck and rooftop plant read as they do from the air; flat roofs gravel, pitched tile

Writes heroes/NAME.json (see hero_house.py), seated on the game's ground (city/ground.bin) at its centre.
"""
import json, math, os, subprocess, sys

import laspy
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY
from footprints import m
from hero_kit import L, TILE, game_ground

NAME, WAYS = sys.argv[1], [int(w) for w in sys.argv[2].split(',')]
BRICK = sys.argv[3] if len(sys.argv) > 3 else '#e3c4b6'
CELL = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
CACHE = os.path.join(HERE, 'osm-cache', 'heroes', NAME)
OUT = os.path.join(HERE, 'heroes')
CITY = os.path.join(HERE, '..', '..', 'public', 'mpls-drive', 'city')
os.makedirs(CACHE, exist_ok=True)
EPT = 'https://s3-us-west-2.amazonaws.com/usgs-lidar-public/MN_CentralMissRiver_4_B22/'
AERIAL = 'https://gis.hennepin.us/arcgis/rest/services/Imagery/UTM_Aerial_2022/MapServer/export'
R = 6378137.0
MARGIN = 6.0                  # metres round the outline to fetch
OPEN = 2.2                    # cells lower than this are ground, not building
STEP = 0.8                    # a surface this much over its neighbour has a wall down to it
STONE = '#d8d0bf'


def curl(url, path=None):
    args = ['curl', '-sS', '--fail', '--retry', '4', url] + (['-o', path] if path else [])
    return subprocess.run(args, capture_output=True, check=True).stdout


# ------------------------------------------------------------ the outline(s)
bld_path = os.path.join(HERE, 'osm-cache', 'bld_all.json')
bld = json.load(open(bld_path)) if os.path.exists(bld_path) else {'elements': []}
have = {e['id'] for e in bld['elements']}
for w in WAYS:
    if w in have:
        continue
    d = json.loads(curl(f'https://api.openstreetmap.org/api/0.6/way/{w}/full.json'))
    nodes = {e['id']: e for e in d['elements'] if e['type'] == 'node'}
    way = [e for e in d['elements'] if e['type'] == 'way'][0]
    bld['elements'].append({'type': 'way', 'id': w, 'tags': way.get('tags', {}),
                            'geometry': [{'lat': nodes[n]['lat'], 'lon': nodes[n]['lon']} for n in way['nodes']]})
    json.dump(bld, open(bld_path, 'w'))
rings = []
for e in bld['elements']:
    if e['id'] in WAYS:
        ring = [m(p['lat'], p['lon']) for p in e['geometry']]
        rings.append(ring[:-1] if ring[0] == ring[-1] else ring)
allpts = [p for r in rings for p in r]
cx = sum(p[0] for p in allpts) / len(allpts)
cz = sum(p[1] for p in allpts) / len(allpts)
# The building's axes: its longest wall, folded into a quarter turn
edges = [(math.hypot(b[0] - a[0], b[1] - a[1]), math.atan2(b[1] - a[1], b[0] - a[0])) for r in rings for a, b in zip(r, r[1:] + r[:1])]
ANG = max(edges)[1] % (math.pi / 2)
CA, SA = math.cos(ANG), math.sin(ANG)
to_local = lambda x, z: ((x - cx) * CA + (z - cz) * SA, -(x - cx) * SA + (z - cz) * CA)
to_world = lambda u, v: (cx + u * CA - v * SA, cz + u * SA + v * CA)
loc = [[to_local(*p) for p in r] for r in rings]
U0 = min(p[0] for r in loc for p in r) - 1
U1 = max(p[0] for r in loc for p in r) + 1
V0 = min(p[1] for r in loc for p in r) - 1
V1 = max(p[1] for r in loc for p in r) + 1
NU, NV = int(math.ceil((U1 - U0) / CELL)), int(math.ceil((V1 - V0) / CELL))
print(NAME, 'outline', [len(r) for r in rings], 'grid', NU, 'x', NV, 'axis', round(math.degrees(ANG), 1), flush=True)

# ------------------------------------------------------------ the points
pts_path = os.path.join(CACHE, 'points.npy')
xs, zs = [p[0] for p in allpts], [p[1] for p in allpts]
bx0, bx1, bz0, bz1 = min(xs) - MARGIN, max(xs) + MARGIN, min(zs) - MARGIN, max(zs) + MARGIN
if os.path.exists(pts_path):
    P = np.load(pts_path)
else:
    def merc(lat, lon):
        return math.radians(lon) * R, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R
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
        path = os.path.join(CACHE, k + '.laz')
        if not os.path.exists(path):
            curl(EPT + f'ept-data/{k}.laz', path)
        las = laspy.read(path)
        lon = np.degrees(np.asarray(las.x) / R)
        lat = np.degrees(2 * np.arctan(np.exp(np.asarray(las.y) / R)) - np.pi / 2)
        x, z = (lon - LON0) * MX, -(lat - LAT0) * MY
        keep = (x > bx0) & (x < bx1) & (z > bz0) & (z < bz1)
        parts.append(np.stack([x[keep], z[keep], np.asarray(las.z)[keep], np.asarray(las.classification)[keep],
                               np.asarray(las.number_of_returns)[keep]], 1))
    P = np.concatenate(parts)
    np.save(pts_path, P)
print('points', len(P), flush=True)
gp = P[P[:, 3] == 2]
G0 = float(np.median(gp[np.hypot(gp[:, 0] - cx, gp[:, 1] - cz) < max(25, (bx1 - bx0) / 2), 2]))

# ------------------------------------------------------------ the height grid
mask_img = Image.new('L', (NU, NV), 0)
for r in loc:
    ImageDraw.Draw(mask_img).polygon([((u - U0) / CELL, (v - V0) / CELL) for u, v in r], fill=1)
inside = np.asarray(mask_img) > 0
Pu, Pv = to_local(P[:, 0], P[:, 1])
ci = np.floor((Pv - V0) / CELL).astype(int)
cj = np.floor((Pu - U0) / CELL).astype(int)
ok = (ci >= 0) & (ci < NV) & (cj >= 0) & (cj < NU) & (P[:, 3] != 2) & (P[:, 4] == 1)
ok &= inside[ci.clip(0, NV - 1), cj.clip(0, NU - 1)]
H = np.full((NV, NU), np.nan)
order = np.lexsort((P[ok, 2], cj[ok], ci[ok]))
keys = (ci[ok] * NU + cj[ok])[order]
hs = P[ok, 2][order] - G0
starts = np.r_[0, np.nonzero(np.diff(keys))[0] + 1, len(keys)]
for a, b in zip(starts[:-1], starts[1:]):
    H[keys[a] // NU, keys[a] % NU] = hs[a + int((b - a - 1) * 0.85)]     # the roof's returns, not the facade's below it


def neighbours(A, fn):
    p = np.pad(A, 1, constant_values=np.nan)
    return fn(np.stack([p[1 + a:NV + 1 + a, 1 + b:NU + 1 + b] for a in (-1, 0, 1) for b in (-1, 0, 1)]), 0)


with np.errstate(all='ignore'):
    for _ in range(6):                                   # fill holes inside from round them
        gap = inside & ~np.isfinite(H)
        if not gap.any():
            break
        H[gap] = neighbours(H, np.nanmedian)[gap]
    H = np.where(inside, neighbours(H, np.nanmedian), np.nan)   # and take the speckle out
solid = inside & np.isfinite(H) & (H >= OPEN)
H[~solid] = np.nan
# Close up thin low strips along the walls (returns off the facade just under a roof's edge, a cell or two wide):
# each cell the lowest of its neighbourhood's highest, three times over; wider low parts (a podium, a setback) stay
for _ in range(3):
    with np.errstate(all='ignore'):
        up = neighbours(np.where(solid, H, np.nan), np.nanmax)
        down = neighbours(np.where(solid, up, np.nan), np.nanmin)
    H = np.where(solid, np.maximum(H, down), np.nan)
print('building cells', int(solid.sum()), 'of', int(inside.sum()), 'inside; heights', np.nanpercentile(H, [5, 50, 95]).round(1), flush=True)

# ------------------------------------------------------------ surfaces
# Every roof face is a plane: found one at a time, the plane most of the remaining cells lie on (RANSAC, within
# 0.15 m, no steeper than 60°), keeping its largest connected patch. What's left joins a neighbouring plane it's near,
# else stands as a flat step at its own height (rounded to 0.5 m). A cell over its plane by more than 0.6 m in a
# small patch is rooftop plant (a box); everything is drawn at its plane's height.
gu = U0 + (np.arange(NU) + 0.5) * CELL
gv = V0 + (np.arange(NV) + 0.5) * CELL
GU, GV = np.meshgrid(gu, gv)
rng = np.random.default_rng(7)
label = np.full((NV, NU), -1)
planes = []


def biggest_patch(mask):
    seen = np.zeros_like(mask)
    best = []
    for i0, j0 in zip(*np.nonzero(mask)):
        if seen[i0, j0]:
            continue
        stack, comp = [(i0, j0)], []
        seen[i0, j0] = True
        while stack:
            i, j = stack.pop()
            comp.append((i, j))
            for a_, b_ in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a_ < NV and 0 <= b_ < NU and mask[a_, b_] and not seen[a_, b_]:
                    seen[a_, b_] = True
                    stack.append((a_, b_))
        if len(comp) > len(best):
            best = comp
    return best


MIN_FACE = int(4 / (CELL * CELL))                          # faces of 4 m2 and more


def patch_from(seed, mask):
    """The cells of mask connected to seed."""
    if not mask[seed]:
        return []
    seen = {seed}
    stack, comp = [seed], []
    while stack:
        i, j = stack.pop()
        comp.append((i, j))
        for a_, b_ in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a_ < NV and 0 <= b_ < NU and mask[a_, b_] and (a_, b_) not in seen:
                seen.add((a_, b_))
                stack.append((a_, b_))
    return comp


W2 = 2                                                      # a seed's plane: fitted over the 5 x 5 cells round it
for _ in range(400):
    left = solid & (label < 0)
    ii, jj = np.nonzero(left)
    if len(ii) < MIN_FACE:
        break
    cands = []
    for s_ in rng.choice(len(ii), min(len(ii), 120), replace=False):
        i, j = ii[s_], jj[s_]
        win = left[max(0, i - W2):i + W2 + 1, max(0, j - W2):j + W2 + 1]
        if win.sum() < 12:
            continue
        wu = GU[max(0, i - W2):i + W2 + 1, max(0, j - W2):j + W2 + 1][win]
        wv = GV[max(0, i - W2):i + W2 + 1, max(0, j - W2):j + W2 + 1][win]
        wh = H[max(0, i - W2):i + W2 + 1, max(0, j - W2):j + W2 + 1][win]
        A = np.stack([wu, wv, np.ones(len(wu))], 1)
        coef, *_ = np.linalg.lstsq(A, wh, rcond=None)
        if np.sqrt(np.mean((A @ coef - wh) ** 2)) > 0.12 or math.hypot(coef[0], coef[1]) > 2.0:
            continue                                        # not a face here (an edge, a wall) or steeper than 63°
        n_in = int((left & (np.abs(GU * coef[0] + GV * coef[1] + coef[2] - H) < 0.25)).sum())
        cands.append((n_in, (i, j), coef))
    if not cands:
        break
    cands.sort(key=lambda c: -c[0])
    best = None
    for n_in, seed, coef in cands[:4]:
        patch = patch_from(seed, left & (np.abs(GU * coef[0] + GV * coef[1] + coef[2] - H) < 0.25))
        if best is None or len(patch) > len(best[0]):
            best = (patch, coef)
    patch, coef = best
    if len(patch) < MIN_FACE:
        # nothing big left that's a face: try a few more times, then stop
        if all(len(patch_from(c[1], left & (np.abs(GU * c[2][0] + GV * c[2][1] + c[2][2] - H) < 0.25))) < MIN_FACE for c in cands[:12]):
            break
        continue
    pi_, pj_ = np.array([c[0] for c in patch]), np.array([c[1] for c in patch])
    A = np.stack([GU[pi_, pj_], GV[pi_, pj_], np.ones(len(pi_))], 1)
    coef, *_ = np.linalg.lstsq(A, H[pi_, pj_], rcond=None)    # refitted over the whole face
    label[pi_, pj_] = len(planes)
    planes.append(coef)
n_faces = len(planes)
raw = H.copy()
# Cells left over: onto a neighbouring plane they're near, a few rounds
for _ in range(6):
    left = solid & (label < 0)
    if not left.any():
        break
    for i, j in zip(*np.nonzero(left)):
        for a_, b_ in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a_ < NV and 0 <= b_ < NU and label[a_, b_] >= 0:
                c_ = planes[label[a_, b_]]
                if abs(GU[i, j] * c_[0] + GV[i, j] * c_[1] + c_[2] - H[i, j]) < 0.6:
                    label[i, j] = label[a_, b_]
                    break
# ...else flat steps at their own (rounded) height
step_h = np.round(H * 2) / 2
for i0, j0 in zip(*np.nonzero(solid & (label < 0))):
    if label[i0, j0] >= 0:
        continue
    k = len(planes)
    planes.append(np.array([0.0, 0.0, float(step_h[i0, j0])]))
    stack = [(i0, j0)]
    label[i0, j0] = k
    while stack:
        i, j = stack.pop()
        for a_, b_ in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a_ < NV and 0 <= b_ < NU and solid[a_, b_] and label[a_, b_] < 0 and step_h[a_, b_] == step_h[i0, j0]:
                label[a_, b_] = k
                stack.append((a_, b_))
for k, c_ in enumerate(planes):
    m_ = label == k
    H[m_] = GU[m_] * c_[0] + GV[m_] * c_[1] + c_[2]
# Rooftop plant: small patches standing well over their plane
over = solid & (raw - H > 0.6)
bumps = []
seen = np.zeros_like(over)
for i0, j0 in zip(*np.nonzero(over)):
    if seen[i0, j0]:
        continue
    stack, comp = [(i0, j0)], []
    seen[i0, j0] = True
    while stack:
        i, j = stack.pop()
        comp.append((i, j))
        for a_, b_ in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a_ < NV and 0 <= b_ < NU and over[a_, b_] and not seen[a_, b_]:
                seen[a_, b_] = True
                stack.append((a_, b_))
    ci_ = np.array([c[0] for c in comp]); cj_ = np.array([c[1] for c in comp])
    if 2 <= len(comp) <= 200:
        bumps.append((ci_.min(), cj_.min(), ci_.max() + 1, cj_.max() + 1, float(np.median(raw[ci_, cj_])), float(H[ci_, cj_].max())))
planes = {k: c_ for k, c_ in enumerate(planes)}
print('roof faces', n_faces, 'flat steps', len(planes) - n_faces, 'cells on faces', int((label >= 0).sum() if False else 0), 'rooftop boxes', len(bumps), flush=True)

# ------------------------------------------------------------ colours from the aerial photo
lon0, lon1 = LON0 + bx0 / MX, LON0 + bx1 / MX
lat0, lat1 = LAT0 - bz1 / MY, LAT0 - bz0 / MY
photo_path = os.path.join(CACHE, 'aerial.png')
if not os.path.exists(photo_path):
    W = 1200
    curl(f'{AERIAL}?bbox={lon0},{lat0},{lon1},{lat1}&bboxSR=4326&imageSR=4326&size={W},{round(W * (lat1 - lat0) / (lon1 - lon0))}'
         '&format=png&f=image', photo_path)
photo = Image.open(photo_path).convert('RGB')
pw, ph = photo.size
WX, WZ = to_world(GU, GV)
px = np.clip(((WX - bx0) / (bx1 - bx0) * pw).astype(int), 0, pw - 1)
pz = np.clip(((WZ - bz0) / (bz1 - bz0) * ph).astype(int), 0, ph - 1)
blur = max(1, round(CELL * pw / (bx1 - bx0) / 2))       # about half a cell of the photo
arr = np.asarray(photo.filter(__import__('PIL.ImageFilter', fromlist=['BoxBlur']).BoxBlur(blur))).astype(np.float64)
cell_rgb = np.clip(arr[pz, px] * 1.12 + 6, 0, 255).astype(np.uint8)
NCOL = 20
q = Image.fromarray(cell_rgb).quantize(NCOL, method=Image.Quantize.MEDIANCUT)
pal = q.getpalette()[:3 * NCOL]
cidx = np.asarray(q).copy()
# the speckle out (each cell the commonest colour round it), so a roof's colours come in patches it can be drawn in
for _ in range(2):
    pad = np.pad(cidx, 1, mode='edge')
    stack = np.stack([pad[1 + a:NV + 1 + a, 1 + b:NU + 1 + b] for a in (-1, 0, 1) for b in (-1, 0, 1)])
    counts = np.stack([(stack == k).sum(0) for k in range(NCOL)])
    cidx = counts.argmax(0)
cols = [BRICK, STONE] + ['#%02x%02x%02x' % tuple(pal[3 * k:3 * k + 3]) for k in range(NCOL)]
ROOFC = lambda k: 2 + int(k)

# ------------------------------------------------------------ the mesh
tris = []      # (corners [(x, y, z)], uvs, layer, colour index)
GH = game_ground(CITY)
g_c = GH(cx, cz)


def V3(u, v, h):
    x, z = to_world(u, v)
    return (x, h, z)


def quad(a, b, c, d, layer, col, uv):
    tris.append(([a, b, c], [uv[0], uv[1], uv[2]], layer, col))
    tris.append(([a, c, d], [uv[0], uv[2], uv[3]], layer, col))


def corner(i, j):
    """Height at grid corner (i, j), from the cells of the surface round it that are highest (so a wall's top is
    the roof's edge): the median of those cells."""
    vals = [H[a, b] for a in (i - 1, i) for b in (j - 1, j) if 0 <= a < NV and 0 <= b < NU and solid[a, b]]
    return float(np.median(vals)) if vals else None


# Roofs: planar surfaces in greedy rectangles of one colour, the rest cell by cell with shared corner heights
done = np.zeros((NV, NU), bool)
for i in range(NV):
    for j in range(NU):
        if not solid[i, j] or done[i, j]:
            continue
        k, c = label[i, j], cidx[i, j]
        if k in planes:
            j1 = j
            while j1 + 1 < NU and solid[i, j1 + 1] and not done[i, j1 + 1] and label[i, j1 + 1] == k and cidx[i, j1 + 1] == c:
                j1 += 1
            i1 = i
            while i1 + 1 < NV and all(solid[i1 + 1, b] and not done[i1 + 1, b] and label[i1 + 1, b] == k and cidx[i1 + 1, b] == c for b in range(j, j1 + 1)):
                i1 += 1
            done[i:i1 + 1, j:j1 + 1] = True
            a_, b_, c_ = planes[k]
            hgt = lambda u, v: a_ * u + b_ * v + c_
            us, ue, vs, ve = U0 + j * CELL, U0 + (j1 + 1) * CELL, V0 + i * CELL, V0 + (i1 + 1) * CELL
            sloped = math.hypot(a_, b_) > 0.15
            layer = L['shingles'] if sloped else L['gravel']
            tw, th = TILE[layer]
            pts = [V3(us, vs, hgt(us, vs)), V3(ue, vs, hgt(ue, vs)), V3(ue, ve, hgt(ue, ve)), V3(us, ve, hgt(us, ve))]
            uv = [(p[0] / tw, p[2] / th) for p in pts]
            quad(pts[0], pts[2], pts[1], pts[3], layer, ROOFC(c), [uv[0], uv[2], uv[1], uv[3]])
            # (wound so the face looks up)
            tris[-2] = ([pts[0], pts[2], pts[1]], [uv[0], uv[2], uv[1]], layer, ROOFC(c))
            tris[-1] = ([pts[0], pts[3], pts[2]], [uv[0], uv[3], uv[2]], layer, ROOFC(c))
        else:
            done[i, j] = True
            hs4 = [corner(i, j), corner(i, j + 1), corner(i + 1, j + 1), corner(i + 1, j)]
            us, ue, vs, ve = U0 + j * CELL, U0 + (j + 1) * CELL, V0 + i * CELL, V0 + (i + 1) * CELL
            pts = [V3(us, vs, hs4[0]), V3(ue, vs, hs4[1]), V3(ue, ve, hs4[2]), V3(us, ve, hs4[3])]
            tw, th = TILE[L['shingles']]
            uv = [(p[0] / tw, p[2] / th) for p in pts]
            tris.append(([pts[0], pts[2], pts[1]], [uv[0], uv[2], uv[1]], L['shingles'], ROOFC(c)))
            tris.append(([pts[0], pts[3], pts[2]], [uv[0], uv[3], uv[2]], L['shingles'], ROOFC(c)))
for i0, j0, i1, j1, hh, base_h in bumps:             # rooftop plant
    us, ue, vs, ve = U0 + j0 * CELL, U0 + j1 * CELL, V0 + i0 * CELL, V0 + i1 * CELL
    c4 = [(us, vs), (ue, vs), (ue, ve), (us, ve)]
    for (ua, va), (ub, vb) in zip(c4, c4[1:] + c4[:1]):
        Lm = math.hypot(ub - ua, vb - va)
        quad(V3(ua, va, base_h), V3(ub, vb, base_h), V3(ub, vb, hh), V3(ua, va, hh), L['metal'], ROOFC(cidx[i0, j0]),
             [(0, 0), (Lm, 0), (Lm, 1), (0, 1)])
    quad(*[V3(u, v, hh) for u, v in c4], L['metal'], ROOFC(cidx[i0, j0]), [(0, 0), (1, 0), (1, 1), (0, 1)])

# Walls: along every cell edge with open ground or a lower surface beyond it, runs merged where nothing changes
tw, th = TILE[L['brickRed']]
base = min(GH(*to_world(u, v)) for u, v in [(U0, V0), (U1, V0), (U1, V1), (U0, V1)]) - g_c - 0.6
walls = 0


def wall(ua, va, ub, vb, y0, y1, along0):
    """A wall from (ua, va) to (ub, vb), y0 to y1, its texture running on from along0 metres along its line."""
    global walls
    Lw = math.hypot(ub - ua, vb - va)
    layer = L['brickRed'] if y1 - y0 > 3.0 else L['brickRedPlain']
    pts = [V3(ua, va, y0), V3(ub, vb, y0), V3(ub, vb, y1), V3(ua, va, y1)]
    uv = [(along0 / tw, y0 / th), ((along0 + Lw) / tw, y0 / th), ((along0 + Lw) / tw, y1 / th), (along0 / tw, y1 / th)]
    quad(*pts, layer, 0, uv)
    # a stone coping where it meets the sky
    walls += 1


def edge_heights(i, j, di, dj):
    """The wall at the edge of cell (i, j) toward (i + di, j + dj): (bottom, top) or None."""
    top = H[i, j]
    a, b = i + di, j + dj
    if 0 <= a < NV and 0 <= b < NU and solid[a, b]:
        if top - H[a, b] < STEP:
            return None
        return (round(H[a, b], 1), round(top, 1))
    return (round(base, 1), round(top, 1))


for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
    if di:                       # edges along u (rows): walk along j
        for i in range(NV):
            run = None
            for j in range(NU + 1):
                e = edge_heights(i, j, di, dj) if j < NU and solid[i, j] else None
                if run and (e is None or abs(e[0] - run[2][0]) > 0.25 or abs(e[1] - run[2][1]) > 0.25):
                    v = V0 + (i + (1 if di > 0 else 0)) * CELL
                    j0, j1, hh = run[0], j, run[2]
                    ua, ub = U0 + j0 * CELL, U0 + j1 * CELL
                    if di < 0:
                        ua, ub = ub, ua
                    wall(ua, v, ub, v, hh[0], hh[1], (ua if di > 0 else -ua))
                    run = None
                if e is not None and run is None:
                    run = (j, None, e)
    else:                        # edges along v (columns): walk along i
        for j in range(NU):
            run = None
            for i in range(NV + 1):
                e = edge_heights(i, j, di, dj) if i < NV and solid[i, j] else None
                if run and (e is None or abs(e[0] - run[2][0]) > 0.25 or abs(e[1] - run[2][1]) > 0.25):
                    u = U0 + (j + (1 if dj > 0 else 0)) * CELL
                    i0, i1, hh = run[0], i, run[2]
                    va, vb = V0 + i0 * CELL, V0 + i1 * CELL
                    if dj > 0:
                        va, vb = vb, va
                    wall(u, va, u, vb, hh[0], hh[1], (va if dj < 0 else -va))
                    run = None
                if e is not None and run is None:
                    run = (i, None, e)
# Stone coping along the top of the outer walls
for i in range(NV):
    for j in range(NU):
        if not solid[i, j]:
            continue
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            a, b = i + di, j + dj
            if 0 <= a < NV and 0 <= b < NU and solid[a, b] and H[i, j] - H[a, b] < STEP:
                continue
            us, ue, vs, ve = U0 + j * CELL, U0 + (j + 1) * CELL, V0 + i * CELL, V0 + (i + 1) * CELL
            hh = H[i, j]
            edge = {(-1, 0): ((us, vs), (ue, vs)), (1, 0): ((us, ve), (ue, ve)), (0, -1): ((us, vs), (us, ve)), (0, 1): ((ue, vs), (ue, ve))}[(di, dj)]
            (ua, va), (ub, vb) = edge
            quad(V3(ua, va, hh + 0.12), V3(ub, vb, hh + 0.12), V3(ub, vb, hh - 0.18), V3(ua, va, hh - 0.18), L['concPlain'], 1,
                 [(0, 0), (1, 0), (1, 1), (0, 1)])

top = float(np.nanmax(H))
rec = dict(name=NAME, x=round(cx, 2), z=round(cz, 2), top=round(top, 2), rings=[[[round(a, 2), round(b, 2)] for a, b in r] for r in rings],
           col=cols, p=[], uv=[], f=[])
for corners_, uvs, layer, c in tris:
    for x, y, z in corners_:
        rec['p'] += [round(x * 100), round(y * 100), round(z * 100)]
    for u, v in uvs:
        rec['uv'] += [round(u * 100), round(v * 100)]
    rec['f'] += [layer, c]
json.dump(rec, open(os.path.join(OUT, NAME + '.json'), 'w'), separators=(',', ':'))
print('wrote', NAME, len(tris), 'triangles,', walls, 'wall runs, top', round(top, 1), 'm', flush=True)
# A picture of the roof's faces (coloured) and flat steps (grey), for checking
pic = np.zeros((NV, NU, 3), np.uint8)
prng = np.random.default_rng(1)
for k in range(len(planes)):
    pic[label == k] = prng.integers(60, 255, 3) if k < n_faces else (90, 90, 90)
Image.fromarray(pic).resize((NU * 3, NV * 3), Image.NEAREST).save(os.path.join(CACHE, 'faces.png'))
# A picture of the heights, for checking
img = np.nan_to_num((H - np.nanmin(H)) / (np.nanmax(H) - np.nanmin(H) + 1e-6) * 255).astype(np.uint8)
Image.fromarray(img).resize((NU * 2, NV * 2), Image.NEAREST).save(os.path.join(CACHE, 'heights.png'))
