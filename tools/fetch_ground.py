"""The real lie of the land: a bare-earth height grid for the whole map, from LiDAR.

    .venv/bin/python fetch_ground.py            # after fetch_lidar.py has filled osm-cache/lidar/

Reads the point cloud fetch_lidar.py cached (USGS 3DEP MN_CentralMissRiver_4_B22, 2022) and keeps
the points classed ground (2) and water (9). Each 5 m cell takes the mean of its ground points,
or of its water points where there is no ground (lakes, the river). Cells with neither (under
buildings, on water the pulses skipped off) are filled in from around them. The grid is smoothed,
then sampled every STEP metres and written to osm-cache/ground.npz as metres above sea level,
nodes at X0 + i * STEP, Z0 + j * STEP. bake_tiles.py ships it to the game.

Points classed bridge deck (17) are kept too: the lowest in each 5 m cell (the deck, not its railings
or arches), as deck (nan where there is none), for bake_tiles.py to set the bridges' heights from.
Some bridges the survey left unclassified (1), like the Irene Hixon Whitney footbridge over I-94, so
along every OpenStreetMap bridge the unclassified points are kept as well, and each 5 m cell there
takes the lowest height well over the ground that its points crowd thickly round (a deck is one flat
sheet of returns; its railings, trusses and the cars under it are thin), as deck1, for where there
is no deck. Trees crowd too, so bake_tiles.py is careful with these.
"""
import concurrent.futures, json, math, os, sys

import laspy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY, X0, X1, Z0, Z1
from footprints import load_osm, m

CACHE = os.path.join(HERE, 'osm-cache')
LAS = os.path.join(CACHE, 'lidar')
R = 6378137.0
FINE = 5                      # metres per cell while gathering
STEP = 10                     # metres between the nodes shipped to the game
NX, NZ = (X1 - X0) // FINE + 1, (Z1 - Z0) // FINE + 1
ON_BRIDGE = None              # the 5 m cells along OpenStreetMap's bridges, set in each worker


def bridge_cells():
    """Flat indices of the 5 m cells along the roads and paths OpenStreetMap marks as bridges."""
    lines = []
    for pattern in ('roads_*', 'paths'):
        for e in load_osm(pattern):
            t = e.get('tags', {})
            if t.get('bridge') in (None, 'no') or str(t.get('layer', '0')).startswith('-') or not e.get('geometry'):
                continue
            lines.append([m(p['lat'], p['lon']) for p in e['geometry']])
    on = np.zeros(NX * NZ, bool)
    for pts in lines:
        for a, b in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 2))
            for q in range(n + 1):
                x, z = a[0] + (b[0] - a[0]) * q / n, a[1] + (b[1] - a[1]) * q / n
                i, j = round((x - X0) / FINE), round((z - Z0) / FINE)
                if 0 <= i < NX and 0 <= j < NZ:
                    on[j * NX + i] = True
    return on


def set_bridge_cells(on):
    global ON_BRIDGE
    ON_BRIDGE = on


def crowd(h, g):
    """The lowest height, 3 m or more over the ground g, that a cell's points crowd thickly round (within
    0.6 m), or nan if none does: the deck, under its railings, trusses and lamps, over the traffic below."""
    h = np.sort(h[h > g + 3])
    if len(h) < 4:
        return np.nan
    n = np.searchsorted(h, h + 0.6, side='right') - np.arange(len(h))
    k = np.flatnonzero(n >= max(4, 0.2 * len(h)))
    return float(np.median(h[k[0]:k[0] + n[k[0]]])) if len(k) else np.nan


def node_sums(k):
    las = laspy.read(os.path.join(LAS, k + '.laz'))
    cls = np.asarray(las.classification)
    keep = (cls == 1) | (cls == 2) | (cls == 9) | (cls == 17)
    if not keep.any():
        return None
    px, py, h, cls = np.asarray(las.x)[keep], np.asarray(las.y)[keep], np.asarray(las.z)[keep], cls[keep]
    lon = np.degrees(px / R)
    lat = np.degrees(2 * np.arctan(np.exp(py / R)) - np.pi / 2)
    x, z = (lon - LON0) * MX, -(lat - LAT0) * MY
    i, j = np.round((x - X0) / FINE).astype(int), np.round((z - Z0) / FINE).astype(int)
    ok = (i >= 0) & (i < NX) & (j >= 0) & (j < NZ)
    if not ok.any():
        return None
    idx, h, cls = (j * NX + i)[ok], h[ok], cls[ok]
    out = []
    for sel in (cls == 2, cls == 9):
        u, inv = np.unique(idx[sel], return_inverse=True)
        out.append((u, np.bincount(inv, h[sel]), np.bincount(inv)))
    sel = cls == 17
    u, inv = np.unique(idx[sel], return_inverse=True)
    lo = np.full(len(u), np.inf)
    np.minimum.at(lo, inv, h[sel])
    out.append((u, lo))
    sel = (cls == 1) & ON_BRIDGE[idx]
    out.append((idx[sel], h[sel].astype(np.float32)))
    return out


def fill(a):
    """Fill the gaps from coarser and coarser averages of what's around them."""
    a = a.copy()
    levels = [a]
    while min(levels[-1].shape) > 2:
        p = levels[-1]
        h, w = (p.shape[0] + 1) // 2 * 2, (p.shape[1] + 1) // 2 * 2
        q = np.full((h, w), np.nan)
        q[:p.shape[0], :p.shape[1]] = p
        blocks = q.reshape(h // 2, 2, w // 2, 2)
        with np.errstate(all='ignore'):
            levels.append(np.nanmean(blocks, axis=(1, 3)))
    for k in range(len(levels) - 2, -1, -1):
        fine, coarse = levels[k], levels[k + 1]
        up = np.repeat(np.repeat(coarse, 2, 0), 2, 1)[:fine.shape[0], :fine.shape[1]]
        bad = np.isnan(fine)
        fine[bad] = up[bad]
    return levels[0]


def blur(a, r):
    """Box blur, three passes (close to a Gaussian), edges held."""
    for _ in range(3):
        for ax in (0, 1):
            p = np.pad(a, [(r, r) if k == ax else (0, 0) for k in (0, 1)], mode='edge')
            c = np.cumsum(p, axis=ax)
            c = np.concatenate([np.zeros_like(np.take(c, [0], axis=ax)), c], axis=ax)
            n = a.shape[ax]
            a = (np.take(c, np.arange(2 * r + 1, n + 2 * r + 1), axis=ax) - np.take(c, np.arange(0, n), axis=ax)) / (2 * r + 1)
    return a


def main():
    nodes = json.load(open(os.path.join(LAS, 'nodes.json')))
    gs, gn = np.zeros(NX * NZ), np.zeros(NX * NZ)
    ws, wn = np.zeros(NX * NZ), np.zeros(NX * NZ)
    deck = np.full(NX * NZ, np.inf)
    b_idx, b_h = [], []
    with concurrent.futures.ProcessPoolExecutor(initializer=set_bridge_cells, initargs=(bridge_cells(),)) as pool:
        for n, res in enumerate(pool.map(node_sums, nodes, chunksize=8)):
            if res:
                (u, s, c), (wu, wsum, wc), (du, dlo), (bi, bh) = res
                b_idx.append(bi); b_h.append(bh)
                np.minimum.at(deck, du, dlo)
                np.add.at(gs, u, s); np.add.at(gn, u, c)
                np.add.at(ws, wu, wsum); np.add.at(wn, wu, wc)
            if n % 500 == 0:
                print('read', n, '/', len(nodes), flush=True)

    with np.errstate(all='ignore'):
        g = np.where(gn > 0, gs / gn, np.where(wn > 0, ws / wn, np.nan)).reshape(NZ, NX)
    print('cells with ground', float(np.mean(gn > 0)), 'water only', float(np.mean((gn == 0) & (wn > 0))), flush=True)


    g = blur(fill(g), 1)
    gf = g.ravel()
    k = STEP // FINE
    out = g[::k, ::k].astype(np.float32)
    print('ground', out.shape, 'from', float(out.min()), 'to', float(out.max()), 'median', float(np.median(out)))
    deck = np.where(np.isfinite(deck), deck, np.nan).reshape(NZ, NX).astype(np.float32)
    print('deck cells', int(np.isfinite(deck).sum()), flush=True)
    b_idx, b_h = np.concatenate(b_idx), np.concatenate(b_h)
    o = np.argsort(b_idx, kind='stable')
    b_idx, b_h = b_idx[o], b_h[o]
    deck1 = np.full(NX * NZ, np.nan, np.float32)
    cells, starts = np.unique(b_idx, return_index=True)
    for c, a, b in zip(cells, starts, list(starts[1:]) + [len(b_idx)]):
        deck1[c] = crowd(b_h[a:b], gf[c])
    deck1 = deck1.reshape(NZ, NX)
    print('unclassified deck cells', int(np.isfinite(deck1).sum()), flush=True)
    np.savez_compressed(os.path.join(CACHE, 'ground.npz'), h=out, step=STEP, x0=X0, z0=Z0, deck=deck, deck1=deck1,
                        fine=FINE)


if __name__ == '__main__':
    main()
