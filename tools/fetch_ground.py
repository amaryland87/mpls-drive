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
"""
import concurrent.futures, json, os, sys

import laspy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY, X0, X1, Z0, Z1

CACHE = os.path.join(HERE, 'osm-cache')
LAS = os.path.join(CACHE, 'lidar')
R = 6378137.0
FINE = 5                      # metres per cell while gathering
STEP = 10                     # metres between the nodes shipped to the game
NX, NZ = (X1 - X0) // FINE + 1, (Z1 - Z0) // FINE + 1


def node_sums(k):
    las = laspy.read(os.path.join(LAS, k + '.laz'))
    cls = np.asarray(las.classification)
    keep = (cls == 2) | (cls == 9) | (cls == 17)
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
    with concurrent.futures.ProcessPoolExecutor() as pool:
        for n, res in enumerate(pool.map(node_sums, nodes, chunksize=8)):
            if res:
                (u, s, c), (wu, wsum, wc), (du, dlo) = res
                np.minimum.at(deck, du, dlo)
                np.add.at(gs, u, s); np.add.at(gn, u, c)
                np.add.at(ws, wu, wsum); np.add.at(wn, wu, wc)
            if n % 500 == 0:
                print('read', n, '/', len(nodes), flush=True)

    with np.errstate(all='ignore'):
        g = np.where(gn > 0, gs / gn, np.where(wn > 0, ws / wn, np.nan)).reshape(NZ, NX)
    print('cells with ground', float(np.mean(gn > 0)), 'water only', float(np.mean((gn == 0) & (wn > 0))), flush=True)


    g = blur(fill(g), 1)
    k = STEP // FINE
    out = g[::k, ::k].astype(np.float32)
    print('ground', out.shape, 'from', float(out.min()), 'to', float(out.max()), 'median', float(np.median(out)))
    deck = np.where(np.isfinite(deck), deck, np.nan).reshape(NZ, NX).astype(np.float32)
    print('deck cells', int(np.isfinite(deck).sum()), flush=True)
    np.savez_compressed(os.path.join(CACHE, 'ground.npz'), h=out, step=STEP, x0=X0, z0=Z0, deck=deck, fine=FINE)


if __name__ == '__main__':
    main()
