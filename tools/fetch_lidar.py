"""Measure every building's real height and roof shape, and find the real trees, from LiDAR.

    .venv/bin/pip install "laspy[lazrs]"        # once, on top of fetch_osm.py's packages
    .venv/bin/python fetch_lidar.py             # after fetch_osm.py

Source: USGS 3DEP point cloud MN_CentralMissRiver_4_B22 (2022), read from the public
Entwine (EPT) copy on AWS. Only the levels down to DEPTH are fetched, about 1.6 points
per square metre, about 1.5 GB cached in osm-cache/lidar/. The survey classifies ground,
water and bridges but not buildings or trees, so:
  roofs  are the last returns that land inside a building footprint (in leaf-off
         spring the pulse goes through bare branches to the roof);
  trees  are multi-return points standing well above the ground outside buildings;
         each local peak of that canopy is one tree.
Writes osm-cache/lidar_buildings.json ({footprint key: [height, roof, eave]}, keyed
like bake_tiles.py's buildings) and osm-cache/lidar_trees.json ([[x, z, height, radius]]).
"""
import concurrent.futures, io, json, math, os, subprocess, sys

import laspy
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY, TILE, X0, X1, Z0, Z1
import footprints

CACHE = os.path.join(HERE, 'osm-cache')
LAS = os.path.join(CACHE, 'lidar')
BASE = 'https://s3-us-west-2.amazonaws.com/usgs-lidar-public/MN_CentralMissRiver_4_B22/'
DEPTH = 9
R = 6378137.0
MARGIN = 60


def merc(lat, lon):
    return math.radians(lon) * R, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R


def get(path):
    return subprocess.run(['curl', '-sS', '--fail', '--retry', '4', BASE + path], capture_output=True, check=True).stdout


# ------------------------------------------------------------ which nodes
ept = json.loads(get('ept.json'))
B = ept['bounds']
SPAN = B[3] - B[0]
mx0, my0 = merc(LAT0 - (Z1 + MARGIN) / MY, LON0 + (X0 - MARGIN) / MX)
mx1, my1 = merc(LAT0 - (Z0 - MARGIN) / MY, LON0 + (X1 + MARGIN) / MX)


def node_box(key):
    d, x, y, z = map(int, key.split('-'))
    s = SPAN / 2 ** d
    return B[0] + x * s, B[1] + y * s, B[0] + (x + 1) * s, B[1] + (y + 1) * s


def wanted(key):
    a, b, c, d = node_box(key)
    return c > mx0 and a < mx1 and d > my0 and b < my1


os.makedirs(LAS, exist_ok=True)
listing = os.path.join(LAS, 'nodes.json')
if os.path.exists(listing):
    nodes = json.load(open(listing))
else:
    nodes, todo = [], ['0-0-0-0']
    while todo:
        h = json.loads(get(f'ept-hierarchy/{todo.pop()}.json'))
        for k, n in h.items():
            if not wanted(k) or int(k.split('-')[0]) > DEPTH:
                continue
            if n == -1:
                todo.append(k)
            elif n > 0:
                nodes.append(k)
    nodes = sorted(set(nodes))
    json.dump(nodes, open(listing, 'w'))
print('lidar nodes', len(nodes), flush=True)


def download(k):
    path = os.path.join(LAS, k + '.laz')
    if not os.path.exists(path):
        data = get(f'ept-data/{k}.laz')
        open(path + '.part', 'wb').write(data)
        os.rename(path + '.part', path)
    return k


with concurrent.futures.ThreadPoolExecutor(16) as pool:
    for n, _ in enumerate(pool.map(download, nodes)):
        if n % 500 == 0:
            print('downloaded', n, '/', len(nodes), flush=True)

# ------------------------------------------------- points, by game tile
NI, NJ = (X1 - X0) // TILE, (Z1 - Z0) // TILE
PAD = 40           # metres of points kept around each tile, for buildings and trees on its edge


def to_game(px, py):
    lon = np.degrees(px / R)
    lat = np.degrees(2 * np.arctan(np.exp(py / R)) - np.pi / 2)
    return (lon - LON0) * MX, -(lat - LAT0) * MY


# Which nodes touch which tile (node boxes are in Web Mercator; convert their corners).
node_tiles = {}
for k in nodes:
    a, b, c, d = node_box(k)
    xs, zs = zip(*[to_game(np.array(u), np.array(v)) for u, v in ((a, b), (c, d))])
    for i in range(max(0, int((min(xs) - PAD - X0) // TILE)), min(NI - 1, int((max(xs) + PAD - X0) // TILE)) + 1):
        for j in range(max(0, int((min(zs) - PAD - Z0) // TILE)), min(NJ - 1, int((max(zs) + PAD - Z0) // TILE)) + 1):
            node_tiles.setdefault((i, j), []).append(k)


def load_tile(i, j):
    tx0, tz0 = X0 + i * TILE - PAD, Z0 + j * TILE - PAD
    tx1, tz1 = tx0 + TILE + 2 * PAD, tz0 + TILE + 2 * PAD
    parts = []
    for k in node_tiles.get((i, j), ()):
        las = laspy.read(os.path.join(LAS, k + '.laz'))
        x, z = to_game(np.asarray(las.x), np.asarray(las.y))
        keep = (x >= tx0) & (x < tx1) & (z >= tz0) & (z < tz1)
        cls = np.asarray(las.classification)
        keep &= (cls == 1) | (cls == 2)
        if keep.any():
            rn, nr = np.asarray(las.return_number), np.asarray(las.number_of_returns)
            parts.append(np.stack([x[keep], z[keep], np.asarray(las.z)[keep], cls[keep],
                                   (rn == nr)[keep], (nr > 1)[keep]], axis=1))
    if not parts:
        return None, (tx0, tz0)
    return np.concatenate(parts), (tx0, tz0)


def fill(grid):
    """Fill empty (nan) cells from their neighbours, outward, so ground runs under buildings."""
    g = grid.copy()
    for _ in range(80):
        bad = np.isnan(g)
        if not bad.any():
            break
        p = np.pad(g, 1, constant_values=np.nan)
        stack = np.stack([p[1 + dy:p.shape[0] - 1 + dy, 1 + dx:p.shape[1] - 1 + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
        with np.errstate(all='ignore'):
            m = np.nanmean(stack, axis=0)
        g[bad] = m[bad]
    return np.nan_to_num(g, nan=np.nanmedian(grid) if np.isfinite(grid).any() else 250)


def fit_roof(u, v, h, w, d, house):
    """Best roof for a rectangle: flat, gabled (ridge along or across), or hipped. Returns (kind, eave, ridge).

    The points are noisy (walls, eaves, overhanging branches), so each model is fitted twice, the second
    time without the points the first fit missed by a lot. Houses lean towards a pitched roof."""
    inner = (np.abs(u) < w / 2 - 0.6) & (np.abs(v) < d / 2 - 0.6)
    if inner.sum() >= 12:
        u, v, h = u[inner], v[inner], h[inner]
    au, av = np.abs(u), np.abs(v)
    models = {'flat': None, 'gable': av, 'gablex': au, 'hip': np.maximum(av, au - (w - d) / 2)}
    prior = {'flat': 0.18 if house else 0.0, 'gable': 0.0, 'gablex': 0.04, 'hip': 0.0}
    best = None
    for kind, s in models.items():
        keep = np.ones(len(h), bool)
        for _ in range(2):
            if s is None:
                c, slope = float(np.median(h[keep])), 0.0
                pred = np.full(len(h), c)
            else:
                A = np.stack([np.ones(keep.sum()), -s[keep]], axis=1)
                (c, slope), *_ = np.linalg.lstsq(A, h[keep], rcond=None)
                pred = c - slope * s
            r = np.abs(h - pred)
            keep = r < max(0.6, 2.5 * float(np.median(r)))
            if keep.sum() < 6:
                break
        if s is not None and not 0.2 <= slope <= 1.6:   # too shallow, or too steep, to be a real roof
            continue
        score = float(np.mean(r[keep])) + 0.6 * (1 - keep.mean()) + prior[kind]
        if best is None or score < best[0]:
            best = (score, kind, (float(c), float(slope)))
    _, kind, (c, slope) = best
    half = {'flat': 0, 'gable': d / 2, 'gablex': w / 2, 'hip': d / 2}[kind]
    return kind, c - slope * half, c


ROOF_CODE = {'flat': 0, 'gable': 1, 'gablex': 2, 'hip': 3}
fps = footprints.load()
by_tile = {}
for key, f in fps.items():
    i, j = int((f['cx'] - X0) // TILE), int((f['cz'] - Z0) // TILE)
    if 0 <= i < NI and 0 <= j < NJ:
        by_tile.setdefault((i, j), []).append((key, f))

out_b, out_t = {}, []
G = 2   # metres per cell of the ground and canopy grids
for j in range(NJ):
    for i in range(NI):
        pts, (tx0, tz0) = load_tile(i, j)
        if pts is None:
            continue
        S = (TILE + 2 * PAD) // G
        ci = np.clip(((pts[:, 1] - tz0) / G).astype(int), 0, S - 1)
        cj = np.clip(((pts[:, 0] - tx0) / G).astype(int), 0, S - 1)
        # Ground: the lowest ground return in each cell, filled in under buildings.
        ground = np.full((S, S), np.nan)
        gm = pts[:, 3] == 2
        order = np.argsort(-pts[gm, 2])                # assign high first so the lowest wins
        ground[ci[gm][order], cj[gm][order]] = pts[gm, 2][order]
        ground = fill(ground)
        rel = pts[:, 2] - ground[ci, cj]

        # Label each 1 m cell with the building standing on it.
        L = Image.new('I', ((TILE + 2 * PAD), (TILE + 2 * PAD)), 0)
        ld = ImageDraw.Draw(L)
        tile_fps = by_tile.get((i, j), [])
        for n, (key, f) in enumerate(tile_fps):
            ld.polygon([(x - tx0, z - tz0) for x, z in f['r']], fill=n + 1)
        lab = np.asarray(L)
        li = np.clip((pts[:, 1] - tz0).astype(int), 0, lab.shape[0] - 1)
        lj = np.clip((pts[:, 0] - tx0).astype(int), 0, lab.shape[1] - 1)
        plab = lab[li, lj]

        # Roofs: last returns, not ground, inside a footprint.
        roof = (plab > 0) & (pts[:, 3] == 1) & (pts[:, 4] == 1) & (rel > 1.5)
        idx = np.nonzero(roof)[0]
        idx = idx[np.argsort(plab[idx], kind='stable')]
        groups = np.split(idx, np.nonzero(np.diff(plab[idx]))[0] + 1) if len(idx) else []
        for g in groups:
            if len(g) < 8:
                continue
            key, f = tile_fps[plab[g[0]] - 1]
            h = rel[g]
            top = float(np.percentile(h, 90))
            if f.get('rect') and f['area'] < 600:
                cx, cz, ang, w, d = f['rect']
                dx, dz = pts[g, 0] - cx, pts[g, 1] - cz
                u = dx * math.cos(ang) + dz * math.sin(ang)
                v = -dx * math.sin(ang) + dz * math.cos(ang)
                kind, eave, ridge = fit_roof(u, v, h, w, d, f['area'] < 320)
                ridge = min(ridge, top + 1)
                out_b[key] = [round(ridge, 1), ROOF_CODE[kind], round(max(2.2, min(eave, ridge)), 1)]
            else:
                out_b[key] = [round(top, 1), 0, round(top, 1)]

        # Trees: canopy points (multi-return, clear of buildings) standing over 3 m.
        dil = Image.fromarray((lab > 0).astype(np.uint8) * 255).resize((S, S), Image.BOX)
        near_bld = np.asarray(dil) > 0
        veg = (pts[:, 3] == 1) & (pts[:, 5] == 1) & (rel > 3) & (rel < 45) & ~near_bld[ci, cj]
        chm = np.zeros((S, S))
        np.maximum.at(chm, (ci[veg], cj[veg]), rel[veg])
        # A peak is the highest cell within 3 cells (6 m) and over 4 m tall.
        p = np.pad(chm, 3)
        neigh = np.max(np.stack([p[3 + dy:3 + dy + S, 3 + dx:3 + dx + S] for dy in range(-3, 4) for dx in range(-3, 4)]), axis=0)
        cover = np.zeros((S, S)); np.add.at(cover, (ci[veg], cj[veg]), 1)
        peaks = np.nonzero((chm >= neigh) & (chm > 4) & (cover >= 2))
        for a, b in zip(*peaks):
            x, z = tx0 + (b + 0.5) * G, tz0 + (a + 0.5) * G
            if X0 + i * TILE <= x < X0 + (i + 1) * TILE and Z0 + j * TILE <= z < Z0 + (j + 1) * TILE:
                ht = float(chm[a, b])
                out_t.append([round(x, 1), round(z, 1), round(ht, 1), round(min(9, 1.5 + ht * 0.28), 1)])
    print('row', j, 'buildings', len(out_b), 'trees', len(out_t), flush=True)

json.dump(out_b, open(os.path.join(CACHE, 'lidar_buildings.json'), 'w'), separators=(',', ':'))
json.dump(out_t, open(os.path.join(CACHE, 'lidar_trees.json'), 'w'), separators=(',', ':'))
print('done: buildings', len(out_b), 'trees', len(out_t))
