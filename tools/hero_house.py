"""Model one real building in detail from full-density LiDAR and an aerial photo: a "hero" building.

    .venv/bin/python hero_house.py NAME LAT LON [WALL_COLOUR] [DOOR_SIDE]
    e.g. .venv/bin/python hero_house.py 3800-beard 44.93380 -93.32440 '#e8e2d2' e

The game's ordinary houses are boxes with one of four roofs. A hero building is its real shape instead:

  points  every LiDAR return over the lot (USGS 3DEP MN_CentralMissRiver_4_B22, 2022, all depths of
          the EPT copy: about 70 points a square metre), cached in osm-cache/heroes/NAME/
  roof    the building's roof points (single returns standing over 2 m, inside its OpenStreetMap
          outline) are split into flat faces by repeatedly finding the plane most of them lie on.
          A 0.3 m grid in the building's own axes takes each cell's height from its face, so eaves
          run straight and faces stay flat; bumps well above their face (chimneys) keep their height.
  walls   run round the roof's outline, set in under the eaves, up to the roof above them, so gable
          ends come out as gables. Windows come from the game's facade textures.
  colour  each roof face's colour is the average of the Hennepin County 2022 aerial photo over it.

Writes heroes/NAME.json, which bake_tiles.py puts into the tile it stands in (hx) in place of the
ordinary buildings there:
  x, z      where it stands (the game seats it on the ground there)
  rings     the wall outlines [[[x, z], ...], ...], for collision and to clear away the ordinary buildings
  top       the highest point, metres above the ground
  p         triangles, corners as x*100, y*100 (above the ground), z*100
  uv        texture coordinates*100, two per corner
  f         per triangle: layer in the facade texture array, colour index into col
  col       colours
"""
import json, math, os, subprocess, sys

import laspy
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY
from footprints import m, load_osm

NAME, LAT, LON = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
WALL = sys.argv[4] if len(sys.argv) > 4 else '#ece6d6'
DOOR = sys.argv[5] if len(sys.argv) > 5 else None          # n, s, e or w: which side the front door is on
CACHE = os.path.join(HERE, 'osm-cache', 'heroes', NAME)
OUT = os.path.join(HERE, 'heroes')
os.makedirs(CACHE, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
EPT = 'https://s3-us-west-2.amazonaws.com/usgs-lidar-public/MN_CentralMissRiver_4_B22/'
AERIAL = 'https://gis.hennepin.us/arcgis/rest/services/Imagery/UTM_Aerial_2022/MapServer/export'
R = 6378137.0
HALF = 30                     # metres round the building to fetch
CELL = 0.3                    # roof grid
OVERHANG = 0.35               # walls set in this far under pitched eaves
# Facade texture layers (see the game's LAYER table).
SIDING_WIN, SIDING, SIDING_DOOR, SHINGLES, GRAVEL, CONC_PLAIN, BRICK_RED_PLAIN = 5, 6, 8, 12, 13, 11, 9


def curl(url, path=None):
    args = ['curl', '-sS', '--fail', '--retry', '4', url] + (['-o', path] if path else [])
    return subprocess.run(args, capture_output=True, check=True).stdout


# ------------------------------------------------------------ the building's outline
bx, bz = m(LAT, LON)
best = None
for e in load_osm('bld_all'):
    g = e.get('geometry') or ((e.get('members') or [{}])[0].get('geometry'))
    if not g or 'building' not in e.get('tags', {}):
        continue
    ring = [m(p['lat'], p['lon']) for p in g]
    cx, cz = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
    d = math.hypot(cx - bx, cz - bz)
    if d < 25 and (best is None or d < best[0]):
        best = (d, ring, cx, cz)
if not best:
    sys.exit('no building outline within 25 m of that spot')
_, osm_ring, cx, cz = best
# The building's axes: the direction of its longest wall, folded into a quarter turn.
edges = [(math.hypot(b[0] - a[0], b[1] - a[1]), math.atan2(b[1] - a[1], b[0] - a[0])) for a, b in zip(osm_ring, osm_ring[1:])]
ANG = max(edges)[1] % (math.pi / 2)
CA, SA = math.cos(ANG), math.sin(ANG)


def to_local(x, z):
    dx, dz = x - cx, z - cz
    return dx * CA + dz * SA, -dx * SA + dz * CA


def to_world(u, v):
    return cx + u * CA - v * SA, cz + u * SA + v * CA


print('outline', len(osm_ring), 'points, centre', round(cx, 1), round(cz, 1), 'axis', round(math.degrees(ANG), 1), 'deg', flush=True)

# ------------------------------------------------------------ every point over the lot
pts_path = os.path.join(CACHE, 'points.npy')
if os.path.exists(pts_path):
    P = np.load(pts_path)
else:
    def merc(lat, lon):
        return math.radians(lon) * R, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R
    ept = json.loads(curl(EPT + 'ept.json'))
    B = ept['bounds']
    SPAN = B[3] - B[0]
    mx0, my0 = merc(LAT0 - (cz + HALF) / MY, LON0 + (cx - HALF) / MX)
    mx1, my1 = merc(LAT0 - (cz - HALF) / MY, LON0 + (cx + HALF) / MX)

    def box(k):
        d, x, y, _ = map(int, k.split('-'))
        s = SPAN / 2 ** d
        return B[0] + x * s, B[1] + y * s, B[0] + (x + 1) * s, B[1] + (y + 1) * s

    nodes, todo = [], ['0-0-0-0']
    while todo:
        for k, n in json.loads(curl(EPT + f'ept-hierarchy/{todo.pop()}.json')).items():
            a, b, c, d = box(k)
            if not (c > mx0 and a < mx1 and d > my0 and b < my1):
                continue
            if n == -1:
                todo.append(k)
            elif n > 0:
                nodes.append(k)
    parts = []
    for k in sorted(set(nodes)):
        path = os.path.join(CACHE, k + '.laz')
        if not os.path.exists(path):
            curl(EPT + f'ept-data/{k}.laz', path)
        las = laspy.read(path)
        px, py = np.asarray(las.x), np.asarray(las.y)
        lon = np.degrees(px / R)
        lat = np.degrees(2 * np.arctan(np.exp(py / R)) - np.pi / 2)
        x, z = (lon - LON0) * MX, -(lat - LAT0) * MY
        keep = (np.abs(x - cx) < HALF) & (np.abs(z - cz) < HALF)
        parts.append(np.stack([x[keep], z[keep], np.asarray(las.z)[keep], np.asarray(las.classification)[keep],
                               np.asarray(las.number_of_returns)[keep]], 1))
    P = np.concatenate(parts)
    np.save(pts_path, P)
print('points', len(P), flush=True)

ground_pts = P[P[:, 3] == 2]
G0 = float(np.median(ground_pts[np.hypot(ground_pts[:, 0] - cx, ground_pts[:, 1] - cz) < 20, 2]))
U, V = to_local(P[:, 0], P[:, 1])
H = P[:, 2] - G0

# ------------------------------------------------------------ roof points and the roof grid
osm_local = [to_local(*p) for p in osm_ring]
uu = [p[0] for p in osm_local]
vv = [p[1] for p in osm_local]
U0, U1, V0, V1 = min(uu) - 2, max(uu) + 2, min(vv) - 2, max(vv) + 2
NU, NV = int(math.ceil((U1 - U0) / CELL)), int(math.ceil((V1 - V0) / CELL))
Img = Image.new('L', (NU, NV), 0)
from PIL import ImageDraw
ImageDraw.Draw(Img).polygon([((u - U0) / CELL, (v - V0) / CELL) for u, v in osm_local], fill=1)
inside = np.asarray(Img.filter(__import__('PIL.ImageFilter', fromlist=['MaxFilter']).MaxFilter(9))) > 0   # the outline, grown by ~1.2 m

ci = np.floor((V - V0) / CELL).astype(int)
cj = np.floor((U - U0) / CELL).astype(int)
ok = (ci >= 0) & (ci < NV) & (cj >= 0) & (cj < NU)
roof = ok & (P[:, 3] == 1) & (P[:, 4] == 1) & (H > 2.0)
roof &= inside[ci.clip(0, NV - 1), cj.clip(0, NU - 1)]
ru, rv, rh = U[roof], V[roof], H[roof]
rci, rcj = ci[roof], cj[roof]
print('roof points', len(rh), flush=True)

# Median height per cell.
cell_h = np.full((NV, NU), np.nan)
order = np.lexsort((rh, rcj, rci))
keys = rci[order] * NU + rcj[order]
starts = np.r_[0, np.nonzero(np.diff(keys))[0] + 1, len(keys)]
for a, b in zip(starts[:-1], starts[1:]):
    k = keys[a]
    cell_h[k // NU, k % NU] = rh[order][(a + b) // 2]

# ------------------------------------------------------------ flat faces
rng = np.random.default_rng(7)
planes = []
left = np.ones(len(rh), bool)
for _ in range(16):
    idx = np.nonzero(left)[0]
    if len(idx) < max(60, 0.015 * len(rh)):
        break
    best_p = None
    for _ in range(600):
        s = rng.choice(idx, 3, replace=False)
        p0 = np.array([ru[s[0]], rv[s[0]], rh[s[0]]])
        n = np.cross(np.array([ru[s[1]], rv[s[1]], rh[s[1]]]) - p0, np.array([ru[s[2]], rv[s[2]], rh[s[2]]]) - p0)
        if np.linalg.norm(n) < 1e-6:
            continue
        n /= np.linalg.norm(n)
        if abs(n[2]) < 0.35:                                    # a wall or a tree, not a roof
            continue
        d = np.abs((ru[idx] - p0[0]) * n[0] + (rv[idx] - p0[1]) * n[1] + (rh[idx] - p0[2]) * n[2])
        inl = idx[d < 0.08]
        if best_p is None or len(inl) > len(best_p[1]):
            best_p = (n, inl)
    if best_p is None:
        break
    # Refit by least squares, h = a*u + b*v + c, and keep the largest connected patch of it.
    inl = best_p[1]
    A = np.stack([ru[inl], rv[inl], np.ones(len(inl))], 1)
    coef, *_ = np.linalg.lstsq(A, rh[inl], rcond=None)
    d = np.abs(ru[idx] * coef[0] + rv[idx] * coef[1] + coef[2] - rh[idx])
    inl = idx[d < 0.1]
    mask = np.zeros((NV, NU), bool)
    mask[rci[inl], rcj[inl]] = True
    lab, n_lab = __import__('scipy.ndimage', fromlist=['label']).label(mask) if False else (None, 0)
    # (no scipy here: a flood fill keeps the biggest patch)
    seen = np.zeros_like(mask)
    biggest = []
    for i0, j0 in zip(*np.nonzero(mask)):
        if seen[i0, j0]:
            continue
        stack, comp = [(i0, j0)], []
        seen[i0, j0] = True
        while stack:
            i, j = stack.pop()
            comp.append((i, j))
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = i + di, j + dj
                if 0 <= a < NV and 0 <= b < NU and mask[a, b] and not seen[a, b]:
                    seen[a, b] = True
                    stack.append((a, b))
        if len(comp) > len(biggest):
            biggest = comp
    if len(biggest) < 12:                                        # under ~1 m2: noise
        left[inl] = False
        continue
    keep_cells = np.zeros_like(mask)
    for i, j in biggest:
        keep_cells[i, j] = True
    used = inl[keep_cells[rci[inl], rcj[inl]]]
    A = np.stack([ru[used], rv[used], np.ones(len(used))], 1)
    coef, *_ = np.linalg.lstsq(A, rh[used], rcond=None)
    planes.append(coef)
    left[used] = False
print('roof faces', len(planes), flush=True)

# Each cell takes the face that fits it best (and is near it); cells no face fits keep their own height.
gu = U0 + (np.arange(NU) + 0.5) * CELL
gv = V0 + (np.arange(NV) + 0.5) * CELL
GU, GV = np.meshgrid(gu, gv)
has = np.isfinite(cell_h)
# Fill small holes (a branch over the roof) from the neighbours, a few passes.
for _ in range(4):
    p = np.pad(cell_h, 1, constant_values=np.nan)
    st = np.stack([p[1 + a:NV + 1 + a, 1 + b:NU + 1 + b] for a in (-1, 0, 1) for b in (-1, 0, 1)])
    cnt = np.sum(np.isfinite(st), 0)
    with np.errstate(all='ignore'):
        mean = np.nanmean(st, 0)
    grow = ~np.isfinite(cell_h) & (cnt >= 5)
    cell_h[grow] = mean[grow]
has = np.isfinite(cell_h)
# Tidy the outline: drop specks, fill notches.
for _ in range(2):
    p = np.pad(has, 1)
    nb = sum(p[1 + a:NV + 1 + a, 1 + b:NU + 1 + b].astype(int) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b)
    has = (has & (nb >= 3)) | (~has & (nb >= 6) & inside)
# Notches just filled in take their height from round them.
for _ in range(10):
    gap = has & ~np.isfinite(cell_h)
    if not gap.any():
        break
    p = np.pad(cell_h, 1, constant_values=np.nan)
    st = np.stack([p[1 + a:NV + 1 + a, 1 + b:NU + 1 + b] for a in (-1, 0, 1) for b in (-1, 0, 1)])
    with np.errstate(all='ignore'):
        mean = np.nanmean(st, 0)
    cell_h[gap] = mean[gap]
has &= np.isfinite(cell_h)
# Keep only patches of roof bigger than ~2 m2 (a stray branch or wire over the yard is not the house).
seen = np.zeros_like(has)
for i0, j0 in zip(*np.nonzero(has)):
    if seen[i0, j0]:
        continue
    stack, comp = [(i0, j0)], []
    seen[i0, j0] = True
    while stack:
        i, j = stack.pop()
        comp.append((i, j))
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = i + di, j + dj
            if 0 <= a < NV and 0 <= b < NU and has[a, b] and not seen[a, b]:
                seen[a, b] = True
                stack.append((a, b))
    if len(comp) < 25:
        for i, j in comp:
            has[i, j] = False
plane_h = np.stack([GU * c[0] + GV * c[1] + c[2] for c in planes]) if planes else np.zeros((0, NV, NU))
label = np.full((NV, NU), -1)
if planes:
    err = np.abs(plane_h - np.where(np.isfinite(cell_h), cell_h, np.nanmedian(cell_h)))
    label = np.argmin(err, 0)
    label[np.min(err, 0) > 0.35] = -1                            # a bump: a chimney, a vent, a skylight
    # Bumps: every cell no face fits takes the face most of its neighbours have (the roof runs on under
    # it), and a compact block of them standing a little way up out of the roof inside its edge is a
    # chimney, kept as a box. Anything else (a branch over the roof, noise at the eaves) just goes.
    bump = has & (label < 0)
    for _ in range(12):
        todo = np.nonzero(label < 0)
        if not len(todo[0]):
            break
        new = label.copy()
        for i, j in zip(*todo):
            near = label[max(0, i - 2):i + 3, max(0, j - 2):j + 3]
            near = near[near >= 0]
            if len(near):
                new[i, j] = np.bincount(near).argmax()
        label = new
    label[label < 0] = 0
hp = np.pad(has, 2)
deep = np.ones_like(has)
for a in range(-2, 3):
    for b in range(-2, 3):
        deep &= hp[2 + a:NV + 2 + a, 2 + b:NU + 2 + b]
chimneys = []
seen = np.zeros_like(has)
for i0, j0 in zip(*np.nonzero(bump if planes else np.zeros_like(has))):
    if seen[i0, j0]:
        continue
    stack, comp = [(i0, j0)], []
    seen[i0, j0] = True
    while stack:
        i, j = stack.pop()
        comp.append((i, j))
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = i + di, j + dj
            if 0 <= a < NV and 0 <= b < NU and bump[a, b] and not seen[a, b]:
                seen[a, b] = True
                stack.append((a, b))
    ii, jj = np.array([c[0] for c in comp]), np.array([c[1] for c in comp])
    under = np.array([plane_h[label[i, j], i, j] for i, j in comp])
    rise = float(np.median(cell_h[ii, jj] - under))
    w, d = (jj.max() - jj.min() + 1) * CELL, (ii.max() - ii.min() + 1) * CELL
    if 4 <= len(comp) <= 40 and 0.4 < rise < 2.5 and max(w, d) < 2.6 and deep[ii, jj].all() and len(comp) > 0.5 * (w * d) / CELL ** 2:
        chimneys.append((ii.min(), jj.min(), ii.max() + 1, jj.max() + 1, float(np.median(cell_h[ii, jj])), float(under.min())))
height = np.where(label >= 0, np.take_along_axis(plane_h, label[None].clip(0), 0)[0] if planes else 0, cell_h)
height = np.where(has, height, np.nan)
# Nothing on the roof stands above what the survey actually saw of it (a face carried past its edge would).
faces_top = [float(plane_h[k][(label == k) & has].max()) for k in range(len(planes)) if ((label == k) & has).any()]
ROOF_TOP = (max(faces_top) if faces_top else float(np.percentile(rh, 95))) + 1.2   # room for a chimney
cell_h = np.minimum(cell_h, ROOF_TOP)
planes_cap = ROOF_TOP
print('roof cells', int(has.sum()), 'chimneys', len(chimneys), flush=True)

# ------------------------------------------------------------ colours from the aerial photo
lon0, lon1 = LON0 + (cx - HALF) / MX, LON0 + (cx + HALF) / MX
lat0, lat1 = LAT0 - (cz + HALF) / MY, LAT0 - (cz - HALF) / MY
photo_path = os.path.join(CACHE, 'aerial.png')
if not os.path.exists(photo_path):
    curl(f'{AERIAL}?bbox={lon0},{lat0},{lon1},{lat1}&bboxSR=4326&imageSR=4326&size=600,600&format=png&f=image', photo_path)
photo = np.asarray(Image.open(photo_path).convert('RGB')).astype(np.float64)


def photo_at(x, z):
    j = int((x - (cx - HALF)) / (2 * HALF) * photo.shape[1])
    i = int((z - (cz - HALF)) / (2 * HALF) * photo.shape[0])
    return photo[min(max(i, 0), photo.shape[0] - 1), min(max(j, 0), photo.shape[1] - 1)]


cols = [WALL, '#f4f3ef', '#5a5652']                     # walls, trim, chimney brick-ish grey
col_idx = {c: i for i, c in enumerate(cols)}


def colour(rgb):
    # The photo is a little dark and blue in the shade; lift it towards how the roof reads by day.
    r, g, b = (np.clip(np.asarray(rgb) * 1.18 + 6, 0, 255)).astype(int)
    c = '#%02x%02x%02x' % (r, g, b)
    if c not in col_idx:
        col_idx[c] = len(cols)
        cols.append(c)
    return col_idx[c]


# A roof is one material: all the pitched faces share the colour of all their photo pixels together
# (sunlit and shaded slopes averaged out), and the flat roofs theirs.
face_col, face_flat = {}, {}
samples = {True: [], False: []}
for k, c in enumerate(planes):
    cells = np.nonzero((label == k) & has)
    if not len(cells[0]):
        continue
    face_flat[k] = math.hypot(c[0], c[1]) < 0.12                 # near flat: membrane or gravel, not shingles
    samples[face_flat[k]] += [photo_at(*to_world(gu[j], gv[i])) for i, j in zip(*cells)]
kind_col = {fl: colour(np.median(np.array(s), 0)) for fl, s in samples.items() if s}
for k, fl in face_flat.items():
    face_col[k] = kind_col[fl]
bump_col = col_idx['#5a5652']

# ------------------------------------------------------------ the mesh
tris = []      # (corners [(x, y, z)], uvs, layer, colour)


def V(u, v, h):
    x, z = to_world(u, v)
    return (x, h, z)


def corner_h(i, j):
    """Roof height at grid corner (i, j): the median of what the cells round it say there."""
    vals = []
    u, v = U0 + j * CELL, V0 + i * CELL
    for a in (i - 1, i):
        for b in (j - 1, j):
            if 0 <= a < NV and 0 <= b < NU and has[a, b]:
                k = label[a, b]
                vals.append(planes[k][0] * u + planes[k][1] * v + planes[k][2] if k >= 0 else cell_h[a, b])
    return min(float(np.median(vals)), planes_cap) if vals else None


CH = [[corner_h(i, j) for j in range(NU + 1)] for i in range(NV + 1)]
for i in range(NV):
    for j in range(NU):
        if not has[i, j]:
            continue
        k = label[i, j]
        hs =[CH[i][j], CH[i][j + 1], CH[i + 1][j + 1], CH[i + 1][j]]
        q = [V(U0 + j * CELL, V0 + i * CELL, hs[0]), V(U0 + (j + 1) * CELL, V0 + i * CELL, hs[1]),
             V(U0 + (j + 1) * CELL, V0 + (i + 1) * CELL, hs[2]), V(U0 + j * CELL, V0 + (i + 1) * CELL, hs[3])]
        # Shingles run down the slope: u across it, v up it (both in metres, the layer tiles every 2 m).
        a, b = planes[k][0], planes[k][1]
        sl = math.hypot(a, b)
        du, dv = (-b / sl, a / sl) if sl > 1e-3 else (1, 0)
        uvs = []
        for p in q:
            lu, lv = to_local(p[0], p[2])
            uvs.append(((lu * du + lv * dv) / 2, (-(lu * dv - lv * du) * math.sqrt(1 + sl * sl)) / 2))
        layer = GRAVEL if face_flat.get(k) else SHINGLES
        tris.append(([q[0], q[2], q[1]], [uvs[0], uvs[2], uvs[1]], layer, face_col.get(k, 1)))
        tris.append(([q[0], q[3], q[2]], [uvs[0], uvs[3], uvs[2]], layer, face_col.get(k, 1)))

# Walls: round the outline, set in under the eaves, from just below the ground up to the roof.
inset = max(1, round(OVERHANG / CELL))
wall_cells = has.copy()
for _ in range(inset):
    p = np.pad(wall_cells, 1)
    wall_cells = wall_cells & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
# Flat parts have no overhang: there the walls stand right at the roof's edge.
flat_cell = np.zeros_like(has)
for k, fl in face_flat.items():
    if fl:
        flat_cell |= label == k
wall_cells |= has & flat_cell
# Boundary edges of wall_cells, as unit grid edges, chained into loops.
E = {}
for i in range(NV):
    for j in range(NU):
        if not wall_cells[i, j]:
            continue
        for (a0, b0), (a1, b1), (ni, nj) in (((i, j), (i, j + 1), (i - 1, j)), ((i, j + 1), (i + 1, j + 1), (i, j + 1)),
                                             ((i + 1, j + 1), (i + 1, j), (i + 1, j)), ((i + 1, j), (i, j), (i, j - 1))):
            if not (0 <= ni < NV and 0 <= nj < NU and wall_cells[ni, nj]):
                E.setdefault((a0, b0), []).append((a1, b1))
loops = []
while E:
    start = next(iter(E))
    loop, cur = [start], start
    while True:
        nxt = E[cur].pop()
        if not E[cur]:
            del E[cur]
        if nxt == start:
            break
        loop.append(nxt)
        cur = nxt
    loops.append(loop)


def straight_runs(loop):
    """Corners of a loop of grid points: where it turns."""
    n = len(loop)
    out = []
    for k in range(n):
        a, b, c = loop[k - 1], loop[k], loop[(k + 1) % n]
        if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
            out.append(b)
    return out


def simplify(pts, tol):
    """Douglas-Peucker on a closed loop of points: the stair steps of the grid smoothed into straight walls."""
    def dp(seq):
        a, b = seq[0], seq[-1]
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1e-9
        far, k = 0, 0
        for q in range(1, len(seq) - 1):
            d = abs((b[0] - a[0]) * (a[1] - seq[q][1]) - (a[0] - seq[q][0]) * (b[1] - a[1])) / L
            if d > far:
                far, k = d, q
        return dp(seq[:k + 1])[:-1] + dp(seq[k:]) if far > tol else [a, b]
    # Split the loop at its two points farthest apart, and simplify each half.
    i0 = 0
    i1 = max(range(len(pts)), key=lambda q: math.hypot(pts[q][0] - pts[0][0], pts[q][1] - pts[0][1]))
    out = dp(pts[i0:i1 + 1])[:-1] + dp(pts[i1:] + [pts[0]])[:-1]
    return out


def roof_at(u, v):
    """The underside of the roof over a point of the wall: the lowest the roof comes within a cell of it."""
    i, j = int(round((v - V0) / CELL)), int(round((u - U0) / CELL))
    vals = [CH[a][b] for a in range(i - 1, i + 2) for b in range(j - 1, j + 2)
            if 0 <= a <= NV and 0 <= b <= NU and CH[a][b] is not None]
    return min(vals) if vals else None


FLOOR, BAY, BASE = 2.9, 2.4, -0.4
ring_out = []
WCOL = col_idx[WALL]
walls = []
for loop in loops:
    corners = straight_runs(loop)
    if len(corners) < 4:
        continue
    pts = simplify([(U0 + j * CELL, V0 + i * CELL) for i, j in corners], 0.45)
    if len(pts) < 3:
        continue
    mu, mv = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    ring_out.append([[round(c, 2) for c in to_world(*p)] for p in pts])
    for a, b in zip(pts, pts[1:] + pts[:1]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 0.25:
            continue
        nu, nv = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
        if nu * ((a[0] + b[0]) / 2 - mu) + nv * ((a[1] + b[1]) / 2 - mv) < 0:
            nu, nv = -nu, -nv
        wx, wz = nu * CA - nv * SA, nu * SA + nv * CA          # outward, in the world
        side = 'e' if wx > 0.7 else 'w' if wx < -0.7 else 's' if wz > 0.7 else 'n' if wz < -0.7 else None
        walls.append((a, b, L, side))
# The front door: the middle of the longest wall on the door side.
door_wall = max((w for w in walls if w[3] == DOOR and w[2] > 3), key=lambda w: w[2], default=None)
for a, b, L, side in walls:
    n = max(2, math.ceil(L / 0.5))
    tops = [roof_at(a[0] + (b[0] - a[0]) * s / n, a[1] + (b[1] - a[1]) * s / n) for s in range(n + 1)]
    known = [t for t in tops if t is not None]
    if not known:
        continue
    tops = [t if t is not None else min(known) for t in tops]
    tops = [float(np.median(tops[max(0, s - 1):s + 2])) - 0.05 for s in range(n + 1)]
    eave = max(2.4, min(tops))
    W = lambda t, y: V(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, y)
    # Whole window bays across, a row a floor up to the eave (a short top row plain), the door in the middle bay.
    bays = max(1, round(L / BAY))
    ys = [BASE] + [FLOOR * k for k in range(1, 10) if FLOOR * k < eave - 0.6] + [eave]
    for q in range(bays):
        t0, t1 = q / bays, (q + 1) / bays
        for r in range(len(ys) - 1):
            y0, y1 = ys[r], ys[r + 1]
            layer = SIDING_WIN if y1 - y0 > 1.4 else SIDING
            if r == 0 and (a, b, L, side) == door_wall and q == bays // 2:
                layer = SIDING_DOOR
            v0, v1 = (y0 - BASE) / FLOOR if r == 0 else y0 / FLOOR, (y1 - BASE) / FLOOR if r == 0 else y1 / FLOOR
            if r == 0:
                v0, v1 = 0, 1
            p00, p10, p11, p01 = W(t0, y0), W(t1, y0), W(t1, y1), W(t0, y1)
            tris.append(([p00, p10, p11], [(q, v0), (q + 1, v0), (q + 1, v1)], layer, WCOL))
            tris.append(([p00, p11, p01], [(q, v0), (q + 1, v1), (q, v1)], layer, WCOL))
    # Above the eave, the wall follows the roof up: a gable end, in plain siding.
    for s in range(n):
        ta, tb = tops[s], tops[s + 1]
        if max(ta, tb) <= eave + 0.05:
            continue
        sa, sb = s / n, (s + 1) / n
        ua, ub = sa * L / BAY, sb * L / BAY
        e0, e1, g1, g0 = W(sa, eave), W(sb, eave), W(sb, max(tb, eave)), W(sa, max(ta, eave))
        tris.append(([e0, e1, g1], [(ua, eave / FLOOR), (ub, eave / FLOOR), (ub, g1[1] / FLOOR)], SIDING, WCOL))
        tris.append(([e0, g1, g0], [(ua, eave / FLOOR), (ub, g1[1] / FLOOR), (ua, g0[1] / FLOOR)], SIDING, WCOL))

# Chimneys: brick boxes from inside the roof up to the height the survey saw.
BRICK = colour((150, 92, 78))
for i0, j0, i1, j1, h, under in chimneys:
    c = [(U0 + j0 * CELL, V0 + i0 * CELL), (U0 + j1 * CELL, V0 + i0 * CELL), (U0 + j1 * CELL, V0 + i1 * CELL), (U0 + j0 * CELL, V0 + i1 * CELL)]
    lo = under - 0.3
    top_c = [V(u, v, h) for u, v in c]
    tris.append(([top_c[0], top_c[2], top_c[1]], [(0, 0), (1, 1), (1, 0)], CONC_PLAIN, col_idx['#5a5652']))
    tris.append(([top_c[0], top_c[3], top_c[2]], [(0, 0), (0, 1), (1, 1)], CONC_PLAIN, col_idx['#5a5652']))
    for (ua, va), (ub, vb) in zip(c, c[1:] + c[:1]):
        L = math.hypot(ub - ua, vb - va) / 2.4
        p0, p1, p2, p3 = V(ua, va, lo), V(ub, vb, lo), V(ub, vb, h), V(ua, va, h)
        tris.append(([p0, p1, p2], [(0, lo / 3.6), (L, lo / 3.6), (L, h / 3.6)], BRICK_RED_PLAIN, BRICK))
        tris.append(([p0, p2, p3], [(0, lo / 3.6), (L, h / 3.6), (0, h / 3.6)], BRICK_RED_PLAIN, BRICK))

# Fascia: a white band along the roof's own edge, so the eaves have some thickness.
TRIM = col_idx['#f4f3ef']
for i in range(NV):
    for j in range(NU):
        if not has[i, j] or label[i, j] < 0:
            continue
        for (a0, b0), (a1, b1), (ni, nj) in (((i, j), (i, j + 1), (i - 1, j)), ((i, j + 1), (i + 1, j + 1), (i, j + 1)),
                                             ((i + 1, j + 1), (i + 1, j), (i + 1, j)), ((i + 1, j), (i, j), (i, j - 1))):
            if 0 <= ni < NV and 0 <= nj < NU and has[ni, nj]:
                continue
            h0, h1 = CH[a0][b0], CH[a1][b1]
            p0, p1 = V(U0 + b0 * CELL, V0 + a0 * CELL, h0), V(U0 + b1 * CELL, V0 + a1 * CELL, h1)
            q0, q1 = (p0[0], h0 - 0.22, p0[2]), (p1[0], h1 - 0.22, p1[2])
            tris.append(([q0, q1, p1], [(0, 0)] * 3, CONC_PLAIN, TRIM))
            tris.append(([q0, p1, p0], [(0, 0)] * 3, CONC_PLAIN, TRIM))

top = min(float(np.nanmax(height)), ROOF_TOP)
rec = dict(name=NAME, x=round(cx, 2), z=round(cz, 2), top=round(top, 2), rings=ring_out,
           col=cols, p=[], uv=[], f=[])
for corners, uvs, layer, c in tris:
    for x, y, z in corners:
        rec['p'] += [round(x * 100), round(y * 100), round(z * 100)]
    for u, v in uvs:
        rec['uv'] += [round(u * 100), round(v * 100)]
    rec['f'] += [layer, c]
json.dump(rec, open(os.path.join(OUT, NAME + '.json'), 'w'), separators=(',', ':'))
print('wrote', NAME, len(tris), 'triangles, top', round(top, 1), 'm, roof colours', cols[3:], flush=True)

# A picture of the roof grid for checking: faces coloured, bumps dark.
pic = np.zeros((NV, NU, 3), np.uint8)
for k in range(len(planes)):
    pic[(label == k) & has] = np.asarray([int(cols[face_col.get(k, 1)][q:q + 2], 16) for q in (1, 3, 5)]) if k in face_col else 128
for i0, j0, i1, j1, *_ in chimneys:
    pic[i0:i1, j0:j1] = (200, 40, 40)
Image.fromarray(pic).resize((NU * 4, NV * 4), Image.NEAREST).save(os.path.join(CACHE, 'roof.png'))
