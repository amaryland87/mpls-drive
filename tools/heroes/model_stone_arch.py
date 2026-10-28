"""The Stone Arch Bridge (1883), modelled from the survey: run it to (re)write heroes/stone-arch.json.

    ../.venv/bin/python model_stone_arch.py

James J. Hill's railway viaduct of limestone and granite across the Mississippi below St. Anthony Falls, a footbridge
since 1994. The game draws its deck (bake_tiles.py's bridges, at the height the 2022 LiDAR saw it, 4.6 m wide for a
cycleway); this is the stone under it. From the full-density 2022 LiDAR along its OpenStreetMap line (way 23115958),
cached in osm-cache/heroes/stone-arch/:

  the deck     the survey's bridge-deck returns (class 17): 8.8 m across, level at the top
  the faces    an airborne scan sees under no arch, but it sees the bridge's two faces at a slant: along each metre of
               the bridge, the lowest return on its faces (3.6 to 5.2 m out from its line, over the water) is the
               edge of the stone there: the water where a pier stands, the arch's curve between
  the arches   piers are where that edge reaches the water for 3 m or more (two closer than 6 m are one; a lone one
               squeezed between two close neighbours is a rock); gaps too long for one arch get piers evenly through
               them (on the dam's apron the survey can't see them), and the last arch reaches to the east bank. Each
               is a round arch from springings 3 m over the water (or just over the apron), up to the deck less 1.4 m
  the truss    the longest stretch whose underside the survey saw 6.5 to 9.5 m over the water (the apron is lower) is the steel truss span
               over the lock (1963, in place of two arches): dark steel from its underside to the deck, a pier at each
               end; the lock's walls and the bents under it count as part of it. Elsewhere (the west bank) the edge as measured
  dressed      limestone faces from the edge up to the deck, a parapet and railing each side, and the wider deck

The bridge stands on the game's ground at its middle; heights are the survey's less the game's E0 (city/index.json gr),
as the game's are. Its piers (only) are solid. bake_tiles.py leaves out its own piers along this bridge (HERO_BRIDGES).
"""
import json, math, os, subprocess, sys

import laspy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from area import LAT0, LON0, MX, MY
from footprints import load_osm, m
from hero_kit import L, Mesh, game_ground

WAY = 23115958
CACHE = os.path.join(os.path.dirname(HERE), 'osm-cache', 'heroes', 'stone-arch')
LAZ = os.path.join(os.path.dirname(HERE), 'osm-cache', 'heroes', 'scout')
CITY = os.path.join(os.path.dirname(HERE), '..', 'city')
EPT = 'https://s3-us-west-2.amazonaws.com/usgs-lidar-public/MN_CentralMissRiver_4_B22/'
R = 6378137.0
HALF = 4.4                       # metres either side of the line: the stone's faces
FACE = (3.6, 5.2)                # the band of returns off a face
SPRING = 3.0                     # arches spring this far over the water
STONE, STONE_DARK, RAIL, DECK = '#cdbf9f', '#b8aa8c', '#34383b', '#b9b4aa'
os.makedirs(CACHE, exist_ok=True)


def curl(url, path=None):
    args = ['curl', '-sS', '--fail', '--retry', '6', '--retry-all-errors', url] + (['-o', path] if path else [])
    return subprocess.run(args, capture_output=True, check=True).stdout


line = [m(p['lat'], p['lon']) for p in next(e for e in load_osm('paths') if e['id'] == WAY)['geometry']]

# ------------------------------------------------------------ the points near the line
near_path = os.path.join(CACHE, 'near.npz')
if not os.path.exists(near_path):
    xs, zs = [p[0] for p in line], [p[1] for p in line]
    bx0, bx1, bz0, bz1 = min(xs) - 12, max(xs) + 12, min(zs) - 12, max(zs) + 12

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
            if c > mx0 and a < mx1 and d > my0 and b < my1:
                (todo if n == -1 else found if n > 0 else []).append(k)
    X, Z, H, C = [], [], [], []
    for k in sorted(set(found)):
        path = os.path.join(LAZ, k + '.laz')
        if not os.path.exists(path):
            curl(EPT + f'ept-data/{k}.laz', path)
        las = laspy.read(path)
        lon = np.degrees(np.asarray(las.x) / R)
        lat = np.degrees(2 * np.arctan(np.exp(np.asarray(las.y) / R)) - np.pi / 2)
        x, z = (lon - LON0) * MX, -(lat - LAT0) * MY
        keep = (x > bx0) & (x < bx1) & (z > bz0) & (z < bz1)
        X.append(x[keep]); Z.append(z[keep]); H.append(np.asarray(las.z)[keep]); C.append(np.asarray(las.classification)[keep])
    X, Z, H, C = map(np.concatenate, (X, Z, H, C))
    best = np.full(len(X), 1e9); along = np.zeros(len(X)); s0 = 0.0
    for (ax, az), (bx, bz) in zip(line, line[1:]):
        Ls = math.hypot(bx - ax, bz - az)
        ux, uz = (bx - ax) / Ls, (bz - az) / Ls
        t = (X - ax) * ux + (Z - az) * uz
        d = -(X - ax) * uz + (Z - az) * ux
        ok = (t >= -0.5) & (t <= Ls + 0.5) & (np.abs(d) < np.abs(best))
        best[ok] = d[ok]
        along[ok] = s0 + t[ok]
        s0 += Ls
    keep = np.abs(best) < 9
    np.savez(near_path, H=H[keep], C=C[keep], d=best[keep], s=along[keep])
D = np.load(near_path)
H, C, d, s = D['H'], D['C'], D['d'], D['s']

# ------------------------------------------------------------ the profile
cum = [0.0]
for a, b in zip(line, line[1:]):
    cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
LEN = cum[-1]
N = int(LEN) + 1
water = float(np.median(H[C == 9]))
deck = float(np.median(H[(C == 17) & (np.abs(d) < 2.5)]))
face = (np.abs(d) > FACE[0]) & (np.abs(d) < FACE[1]) & (H > water + 1.5) & (H < deck - 0.5) & (C != 9)
edge = np.full(N, np.nan)
for k in range(N):
    sel = face & (s >= k) & (s < k + 1)
    if sel.sum() >= 3:
        edge[k] = np.percentile(H[sel], 5) - water
# piers: runs of 3 m or more where the edge comes down to the water
low = np.nan_to_num(edge, nan=99) <= 2.5
piers, k = [], 0
while k < N:
    if low[k]:
        j = k
        while j < N and low[j]:
            j += 1
        if j - k >= 3:
            piers.append((k, j))
        k = j
    else:
        k += 1
# Tidy the piers: two closer than 6 m are one; one squeezed between two others under 16 m away is a rock
merged = []
for a, b in piers:
    if merged and a - merged[-1][1] < 6:
        merged[-1] = (merged[-1][0], b)
    else:
        merged.append((a, b))
piers = [p for k, p in enumerate(merged)
         if not (0 < k < len(merged) - 1 and p[0] - merged[k - 1][1] < 16 and merged[k + 1][0] - p[1] < 16)]
# The steel truss span (1963) over the lock: the longest stretch whose underside the survey saw 6.5 to 9.5 m over the
# water, with a pier at either end
def kind(v):
    return 'T' if 6.5 <= v <= 9.5 else 'S' if v <= 3 else 'O'      # truss underside, a support down to the water, other


truss_run, k = None, 0
while k < N:
    if np.isnan(edge[k]) or kind(edge[k]) != 'T':
        k += 1
        continue
    j, last = k, k
    while j < N:
        if not np.isnan(edge[j]) and kind(edge[j]) == 'T':
            last = j
            j += 1
            continue
        # a support (the lock's walls, a bent) up to 7 m long, or a gap in the scan up to 3 m, and the truss carries on
        q = j
        while q < N and (np.isnan(edge[q]) or kind(edge[q]) == 'S') and q - j <= 7:
            q += 1
        if q < N and q - j <= 7 and not np.isnan(edge[q]) and kind(edge[q]) == 'T' and \
                not (np.all(np.isnan(edge[j:q])) and q - j > 3):
            j = q
            continue
        break
    if last + 1 - k >= 30 and (truss_run is None or last + 1 - k > truss_run[1] - truss_run[0]):
        truss_run = (k, last + 1)
    k = last + 1
if truss_run:
    t0, t1 = truss_run
    piers = [p for p in piers if p[1] <= t0 - 2 or p[0] >= t1 + 2]       # (the supports under it are steel bents)
    piers += [(t0 - 5, t0), (t1, t1 + 5)]
    piers.sort()
    truss_y = float(np.nanmedian([v for v in edge[t0:t1] if not np.isnan(v) and kind(v) == 'T']))
# Gaps longer than an arch get piers spaced evenly through them (the survey can't see piers on the dam's apron)
full = [piers[0]]
for (a0, a1), (b0, b1) in zip(piers, piers[1:]):
    gap = b0 - a1
    if gap > 34 and not (truss_run and a1 >= truss_run[0] - 6 and b0 <= truss_run[1] + 6):
        n = round((b1 - a0) / 27)
        for q in range(1, n):
            c = a0 + (b1 - a0) * q / n
            full.append((int(c - 2.5), int(c + 2.5)))
    full.append((b0, b1))
piers = full
# The last arch, from the last pier out to the east bank (where the faces stand on ground 10 m or more over the water)
bank = next((k for k in range(piers[-1][1] + 8, N) if not np.isnan(edge[k]) and edge[k] >= 9), None)
under = np.interp(np.arange(N), np.nonzero(~np.isnan(edge))[0], edge[~np.isnan(edge)])
spans = list(zip([p[1] for p in piers], [p[0] for p in piers[1:]]))
if bank and bank - piers[-1][1] > 12:
    spans.append((piers[-1][1], bank))
arches = 0
for a1, b0 in spans:
    gap = b0 - a1
    if truss_run and a1 >= truss_run[0] - 6 and b0 <= truss_run[1] + 6:
        under[a1:b0] = truss_y                  # the truss's underside
        continue
    if gap < 8 or gap > 40:
        continue
    # springing over the water, or over the dam's apron where the survey saw one under the arch
    apron = np.nanpercentile(edge[a1:b0], 20) if np.any(~np.isnan(edge[a1:b0])) else 0
    spring = min(7.0, max(SPRING, apron + 0.5 if apron < 8 else SPRING))
    r = gap / 2
    rise = min(r, deck - water - spring - 1.4)
    for k in range(a1, b0):
        t = (k + 0.5 - a1 - r) / r
        under[k] = spring + rise * math.sqrt(max(0.0, 1 - t * t))
    arches += 1
for a, b in piers:
    under[a:b] = -1.5                       # piers stand down into the river
under = np.minimum(under, deck - water - 1.2)
print('water', round(water, 2), 'deck', round(deck, 2), 'piers', len(piers), 'arches', arches, 'truss', truss_run, 'length', round(LEN))


# ------------------------------------------------------------ the mesh
def at(sk):
    """(x, z), unit along and unit across (to the left) at sk metres along the line."""
    i = max(1, min(len(cum) - 1, next((k for k, c in enumerate(cum) if c >= sk), len(cum) - 1)))
    (ax, az), (bx, bz) = line[i - 1], line[i]
    Ls = (cum[i] - cum[i - 1]) or 1
    t = (sk - cum[i - 1]) / Ls
    ux, uz = (bx - ax) / Ls, (bz - az) / Ls
    return ax + (bx - ax) * t, az + (bz - az) * t, ux, uz


idx = json.load(open(os.path.join(CITY, 'index.json')))
E0 = idx['gr']['e0']
gh = game_ground(CITY)
MX_, MZ_ = at(LEN / 2)[:2]
G = gh(MX_, MZ_)
Y = lambda h: h - E0 - G                    # survey height to the record's (above the game's ground at the middle)
yw, yd = Y(water), Y(deck) - 0.08           # the stone stops just under the game's own deck
mesh = Mesh()
st = list(np.arange(0, LEN, 1.0)) + [LEN]
pts = []
for sk in st:
    x, z, ux, uz = at(sk)
    k = min(N - 1, int(sk))
    pts.append((x, z, -uz, ux, yw + under[k]))
for sk0, (x0, z0, nx0, nz0, y0), (x1, z1, nx1, nz1, y1) in zip(st, pts, pts[1:]):
    for side in (-1, 1):
        a = (x0 + nx0 * HALF * side, z0 + nz0 * HALF * side)
        b = (x1 + nx1 * HALF * side, z1 + nz1 * HALF * side)
        # the face, from the edge up to the deck, and the parapet over it
        steel = truss_run and truss_run[0] <= sk0 < truss_run[1]
        mesh.poly([(a[0], y0, a[1]), (b[0], y1, b[1]), (b[0], yd, b[1]), (a[0], yd, a[1])],
                  L['fence'] if steel else L['brickLitePlain'], '#4b5257' if steel else STONE)
        mesh.poly([(a[0], yd, a[1]), (b[0], yd, b[1]), (b[0], yd + 0.45, b[1]), (a[0], yd + 0.45, a[1])], L['concPlain'], STONE_DARK)
        ar = (x0 + nx0 * (HALF - 0.1) * side, z0 + nz0 * (HALF - 0.1) * side)
        br = (x1 + nx1 * (HALF - 0.1) * side, z1 + nz1 * (HALF - 0.1) * side)
        mesh.poly([(ar[0], yd + 0.45, ar[1]), (br[0], yd + 0.45, br[1]), (br[0], yd + 1.15, br[1]), (ar[0], yd + 1.15, ar[1])], L['fence'], RAIL)
    # the arch's underside and the deck over the whole width
    l0, r0 = (x0 - nx0 * HALF, z0 - nz0 * HALF), (x0 + nx0 * HALF, z0 + nz0 * HALF)
    l1, r1 = (x1 - nx1 * HALF, z1 - nz1 * HALF), (x1 + nx1 * HALF, z1 + nz1 * HALF)
    mesh.poly([(l0[0], y0, l0[1]), (r0[0], y0, r0[1]), (r1[0], y1, r1[1]), (l1[0], y1, l1[1])], L['brickLitePlain'], STONE_DARK)
    mesh.poly([(l0[0], yd + 0.02, l0[1]), (l1[0], yd + 0.02, l1[1]), (r1[0], yd + 0.02, r1[1]), (r0[0], yd + 0.02, r0[1])], L['sidewalk'], DECK)
# the piers' ends: pointed cutwaters on both faces, up to just over the springing
rings = []
for a, b in piers:
    xa, za, ux, uz = at(a)
    xb, zb, _, _ = at(b)
    nx, nz = -uz, ux
    c = [(xa - nx * HALF, za - nz * HALF), (xb - nx * HALF, zb - nz * HALF), (xb + nx * HALF, zb + nz * HALF), (xa + nx * HALF, za + nz * HALF)]
    rings.append(c)
    for side in (-1, 1):
        mx, mz = (xa + xb) / 2, (za + zb) / 2
        tip = (mx + nx * (HALF + 2.5) * side, mz + nz * (HALF + 2.5) * side)
        e0 = (xa + nx * HALF * side, za + nz * HALF * side)
        e1 = (xb + nx * HALF * side, zb + nz * HALF * side)
        for p, q in ((e0, tip), (tip, e1)):
            mesh.poly([(p[0], yw - 1.5, p[1]), (q[0], yw - 1.5, q[1]), (q[0], yw + SPRING + 1, q[1]), (p[0], yw + SPRING + 1, p[1])], L['brickLitePlain'], STONE)
        mesh.poly([(e0[0], yw + SPRING + 1, e0[1]), (tip[0], yw + SPRING + 1, tip[1]), (e1[0], yw + SPRING + 1, e1[1])], L['concPlain'], STONE_DARK)
mesh.write(os.path.join(HERE, 'stone-arch.json'), 'stone-arch', MX_, MZ_, yd + 1.2, rings)
