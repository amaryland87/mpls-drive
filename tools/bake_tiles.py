"""Bake OpenStreetMap Minneapolis into Mpls Drive's tiled city.

    python3 -m venv .venv && .venv/bin/pip install osmium numpy pillow "laspy[lazrs]"   # once
    .venv/bin/python fetch_osm.py                # downloads and cuts the map data into osm-cache/
    .venv/bin/python fetch_lidar.py              # optional: real heights, roof shapes and trees
    .venv/bin/python fetch_ground.py             # optional: the lie of the land (needs fetch_lidar.py's cache)
    .venv/bin/python fetch_city.py               # optional: walls, roofs, lights, hydrants, pavement, bike lanes
    .venv/bin/python bake_transit.py             # optional: the bus stops (and the trains' schedule)
    .venv/bin/python bake_tiles.py ../../public/mpls-drive/city
    .venv/bin/python make_textures.py ../../public/mpls-drive/tex

The map (see area.py) is cut into 1 km tiles. For each tile i_j this writes
  t/i_j.jpg    the ground, 1024 px (about 1 m a pixel), with soft occlusion
               around buildings and shade under trees baked in
  t/i_j-s.jpg  the same at 512 px, for phones
  t/i_j.json   the 3D things on it:
    b  buildings   [facade layer, tint, height*10, base height*10, flags, rings, n, x, z, ...]
                   flags: 1 storefront ground floor, 2 parapet and rooftop plant; above them (flags >> 2)
                   1 + the flat roof's colour in index.json roofs, if the aerial photo showed it
    h  houses      [x*10, z*10, angle*100, length*10, depth*10, eave*10, ridge*10, roof, front side,
                    wall tint, roof tint, flags]   roof: 0 flat 1 gable 2 gable across 3 hip;
                   front side: which wall faces the street (0 +x, 1 -x, 2 +z, 3 -z);
                   flags: 1 chimney, 2 front porch; flags >> 2 the walls (0 clapboard 1 stucco 2 brick
                   3 cedar shakes, as the city assessor has them); roof tint indexes houseRoof, the
                   aerial photo's colours
    g  garages     [x*10, z*10, angle*100, length*10, depth*10, height*10, colours, door side]
                   colours: the wall tint, plus 256 * (1 + the roof's in houseRoof) if the photo showed it
    t  trees       [x*10, z*10, height*10, crown radius*10]
    f  fences      [kind (0 fence 1 wall 2 hedge 3 low rail fence), n, x, z, ...]
    s  street signs [x*10, z*10, angle*100, name, angle*100, name], names indexing sn
    rd street pieces [class, width*10, lanes, oneway, start clearance*10, end clearance*10, n, x*10, z*10, ...]
                   class indexes the road order below (one past the end: a footpath or trail);
                   markings and sidewalks stop the clearance
                   short of an intersection at that end; after the points, the surface (0 asphalt
                   1 concrete 2 brick 3 gravel) and bike lane (0 none 1 lane 2 buffered 3 protected
                   4 shared with buses 5 bike boulevard), from the city's pavement and bikeway maps
    jn intersections [x*10, z*10, radius*10]
    cw crosswalks  [x*10, z*10, angle of the street*100, street width*10]
    lp street lights [x*10, z*10, angle to the street*100, fixture (0 cobra head 1 lantern 2 acorn
                   3 teardrop 4 shoebox 5 globe 6 accent)], the city's own
    sg signalled corners [x*10, z*10]: junctions with an OpenStreetMap traffic signal
    fu street furniture [kind, x*10, z*10, angle to the street*100]: 0 hydrant 1 bench 2 litter bin
                   3 bus stop sign 4 bus shelter 5 Nice Ride dock 6 mailbox 7 utility pole 8 bike rack
                   9 light rail platform canopy (its angle along the track)
    hx hero buildings, modelled in detail by hero_house.py (see there); they replace the ordinary
                   buildings, houses, garages and trees inside their outline (and the houses, garages
                   and trees under their walks and drives: clear)
and for the whole map
  index.json   bounds, palettes, bridges and the main-street routes traffic drives;
               bridges are deck pieces [ax, az, bx, bz, width, height at a*10, height at b*10, pier at a]
  ground.bin   the ground's height every 10 m (see index.json gr): gzipped little-endian int16
               centimetres above gr.e0, each row stored as differences from the node before
  overview.jpg the whole map small, for the big map screen
  search.json  street addresses and named places (see bake_search.py)

Every building is a real OpenStreetMap footprint. Heights and roof shapes come from
the 2022 USGS LiDAR survey where fetch_lidar.py measured them, then OpenStreetMap
height tags, then the building type. 3D building:part shapes replace their outlines.

Houses' walls, roofs and years come from the City of Minneapolis assessor where its parcel
data has them (fetch_city.py), and every roof's colour from Hennepin County's 2022 aerial photo.

Map data (c) OpenStreetMap contributors, ODbL. LiDAR: USGS 3DEP, public domain. City data:
City of Minneapolis and Hennepin County open data; Metro Transit GTFS.
"""
import glob, gzip, json, math, os, random, sys
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY, TILE, X0, X1, Z0, Z1
from footprints import bbox_of, buildings as load_buildings, load_osm as load, m, rings

OUT = sys.argv[1]
CACHE = os.path.join(HERE, 'osm-cache')
NI, NJ = (X1 - X0) // TILE, (Z1 - Z0) // TILE
TS = 2048                     # tile drawing resolution, downsampled when saved
PPM = TS / TILE
random.seed(7)


def in_map(x, z):
    return X0 <= x < X1 and Z0 <= z < Z1


def jload(name, default):
    path = os.path.join(CACHE, name)
    return json.load(open(path)) if os.path.exists(path) else default


# ----------------------------------------------------------------- ground
# Heights are shipped relative to the median height round the map's edge, and eased back to it over
# the outer EDGE_EASE metres, so the land meets the flat wide map beyond.
EDGE_EASE = 260
_gp = os.path.join(CACHE, 'ground.npz')
if os.path.exists(_gp):
    _g = np.load(_gp)
    GSTEP = int(_g['step'])
    GH_ABS = _g['h'].astype(np.float64)
    DECK, DFINE = (_g['deck'], int(_g['fine'])) if 'deck' in _g else (None, 5)
    DECK1 = _g['deck1'] if 'deck1' in _g else None
else:
    GSTEP = 10
    GH_ABS = np.zeros(((Z1 - Z0) // GSTEP + 1, (X1 - X0) // GSTEP + 1))
    DECK, DFINE, DECK1 = None, 5, None
GNZ, GNX = GH_ABS.shape
E0 = float(np.median(np.concatenate([GH_ABS[0], GH_ABS[-1], GH_ABS[:, 0], GH_ABS[:, -1]])))
_ex = np.minimum(np.arange(GNX) * GSTEP, (X1 - X0) - np.arange(GNX) * GSTEP)
_ez = np.minimum(np.arange(GNZ) * GSTEP, (Z1 - Z0) - np.arange(GNZ) * GSTEP)
_e = np.clip(np.minimum.outer(_ez, _ex) / EDGE_EASE, 0, 1)
GROUND = np.round((GH_ABS - E0) * (_e * _e * (3 - 2 * _e)) * 100) / 100     # what the game gets, to the centimetre


def ease(x, z):
    e = min(1, max(0, min(x - X0, X1 - x, z - Z0, Z1 - z) / EDGE_EASE))
    return e * e * (3 - 2 * e)


def deck_at(x, z, deck=None):
    """The surveyed bridge deck's height at (x, z), like ground()'s, or nan where the survey saw none.
    deck=DECK1 reads the decks the survey left unclassified instead (see fetch_ground.py)."""
    deck = DECK if deck is None else deck
    if deck is None:
        return float('nan')
    i, j = int(round((x - X0) / DFINE)), int(round((z - Z0) / DFINE))
    v = deck[max(0, j - 1):j + 2, max(0, i - 1):i + 2]
    v = v[np.isfinite(v)]
    return float((np.median(v) - E0) * ease(x, z)) if len(v) else float('nan')


def ground(x, z):
    """Height of the ground at (x, z), interpolated exactly as the game's ground mesh is."""
    fx = min(max((x - X0) / GSTEP, 0), GNX - 1.001)
    fz = min(max((z - Z0) / GSTEP, 0), GNZ - 1.001)
    i, j = int(fx), int(fz)
    u, v = fx - i, fz - j
    a, b, c, d = GROUND[j, i], GROUND[j, i + 1], GROUND[j + 1, i], GROUND[j + 1, i + 1]
    return a + (b - a) * u + (c - a) * v if u + v <= 1 else d + (c - d) * (1 - u) + (b - d) * (1 - v)


# ----------------------------------------------------------------- palette
C = dict(
    land='#a9d17c', park='#8fcb5c', golf='#a3db6e', wood='#6fb24f', cemetery='#9fcd78',
    water='#5aa9e0', shore='#86c3ea', plaza='#dcd6c8', curb='#ece8dc', road='#8e969e', major='#a3aab1',
    highway='#b3b9bf', line='#f3e7a8', rail='#a99b8c', roof='#9a8f86', bldg='#b8afa4', walk='#d9d5cb',
    parking='#9a9da0',
)
# Land-use classes, drawn into a 2 m grid over the whole map to place trees and find bridges.
CLS = dict(land=0, park=1, golf=1, cemetery=1, wood=2, water=3, shore=4, plaza=5, curb=5, walk=5,
           road=6, major=6, highway=6, line=6, rail=6, roof=7, bldg=7, parking=6)

# Every drawing call is recorded once, in paint order, then replayed into the
# 2 m class grid and into each tile it touches.
ops = []   # (kind, 'poly'|'line'|'dot', pts, width_m, bbox)


def poly(pts, kind):
    if len(pts) >= 3:
        ops.append((kind, 'poly', pts, 0, bbox_of(pts, 1)))


def line(pts, w_m, kind):
    if len(pts) >= 2:
        ops.append((kind, 'line', pts, w_m, bbox_of(pts, w_m)))


shade_dots = []    # (x, z, radius): tree canopies, baked as soft shade on the ground

# ---------------------------------------------------------------- greens
for e in load('green'):
    t = e.get('tags', {})
    if e['type'] == 'relation' and t.get('type') != 'multipolygon':
        continue
    kind = t.get('leisure') or t.get('landuse') or t.get('natural')
    k = {'golf_course': 'golf', 'cemetery': 'cemetery', 'forest': 'wood', 'wood': 'wood'}.get(kind, 'park')
    for role, r in rings(e):
        if role == 'outer':
            poly(r, k)

# ----------------------------------------------------------------- water
WATER = load('water')
for e in WATER:
    if e.get('tags', {}).get('waterway') == 'river':
        line(rings(e)[0][1], 40, 'water')
for e in WATER:
    if e.get('tags', {}).get('waterway') == 'river':
        continue
    rs = rings(e)
    for role, r in rs:
        if role == 'outer':
            line(r + r[:1], 6, 'shore')
            poly(r, 'water')
    for role, r in rs:
        if role == 'inner':
            poly(r, 'park')
N_WATER_OPS = len(ops)          # the class grid is snapshotted here, before roads cover the river

for e in load('paved'):         # surface parking lots
    for role, r in rings(e):
        if role == 'outer':
            poly(r, 'parking')

# ----------------------------------------------------------------- roads
WIDTH = dict(motorway=26, trunk=22, primary=16, secondary=14, tertiary=12, residential=9, unclassified=9,
             living_street=7, pedestrian=6, motorway_link=10, trunk_link=10, primary_link=9, secondary_link=9, tertiary_link=8)
order = ['pedestrian', 'living_street', 'residential', 'unclassified', 'tertiary_link', 'secondary_link',
         'primary_link', 'trunk_link', 'motorway_link', 'tertiary', 'secondary', 'primary', 'trunk', 'motorway']
roads = []
for e in load('roads_*'):
    hw = e.get('tags', {}).get('highway')
    if hw in WIDTH and e.get('geometry'):
        roads.append((order.index(hw), hw, [m(p['lat'], p['lon']) for p in e['geometry']], e.get('tags', {}),
                      [(p['lat'], p['lon']) for p in e['geometry']]))
roads.sort(key=lambda r: r[0])


def is_bridge(t):
    return t.get('bridge') not in (None, 'no') and not str(t.get('layer', '0')).startswith('-')


# Footpaths, bike paths and trails (the ones round the lakes, through the parks, along the river), and alleys.
# Sidewalks and crossings along streets are left out (the streets bring their own).
paths = []
for e in load('paths'):
    t = e.get('tags', {})
    if (t.get('footway') in ('sidewalk', 'crossing', 'access_aisle', 'traffic_island') or t.get('area') == 'yes'
            or t.get('indoor') == 'yes' or t.get('tunnel') in ('yes', 'building_passage')
            or str(t.get('layer', '0')).startswith('-') or not e.get('geometry')):
        continue
    w = 4.2 if t.get('service') == 'alley' else 3.2 if t.get('highway') == 'cycleway' or t.get('bicycle') == 'designated' else 2.4
    paths.append(([m(p['lat'], p['lon']) for p in e['geometry']], w, dict(t, _id=e['id'])))

# Where the pavement is (streets and paths on the ground, not bridges or tunnels), in 20 m cells,
# so nothing solid (a fence, a pier) ends up standing across a way through.
PG = 20
pavement = {}
for pts, half in ([(pts, WIDTH[hw] / 2) for _, hw, pts, t, _ in roads if not is_bridge(t) and t.get('tunnel') in (None, 'no')]
                  + [(pts, w / 2) for pts, w, t in paths if not is_bridge(t)]):
    for a, b in zip(pts, pts[1:]):
        for i in range(int(min(a[0], b[0]) // PG) - 1, int(max(a[0], b[0]) // PG) + 2):
            for j in range(int(min(a[1], b[1]) // PG) - 1, int(max(a[1], b[1]) // PG) + 2):
                pavement.setdefault((i, j), []).append((a, b, half))


def on_pavement(x, z, pad=0.0):
    for a, b, r in pavement.get((int(x // PG), int(z // PG)), ()):
        ex, ez = b[0] - a[0], b[1] - a[1]
        L2 = ex * ex + ez * ez or 1e-9
        t = max(0, min(1, ((x - a[0]) * ex + (z - a[1]) * ez) / L2))
        if math.hypot(x - a[0] - ex * t, z - a[1] - ez * t) < r + pad:
            return True
    return False

# Street segments a house can face, bucketed in 50 m cells.
FACING = ('residential', 'unclassified', 'living_street', 'tertiary', 'secondary', 'primary')
SG = 50
street_segs = {}
for _, hw, pts, t, _ in roads:
    if hw not in FACING:
        continue
    for (ax, az), (bx, bz) in zip(pts, pts[1:]):
        for i in range(int(min(ax, bx) // SG), int(max(ax, bx) // SG) + 1):
            for j in range(int(min(az, bz) // SG), int(max(az, bz) // SG) + 1):
                street_segs.setdefault((i, j), []).append((ax, az, bx, bz, WIDTH[hw]))


def nearest_street(x, z, reach=60):
    best = None
    for i in range(int((x - reach) // SG), int((x + reach) // SG) + 1):
        for j in range(int((z - reach) // SG), int((z + reach) // SG) + 1):
            for ax, az, bx, bz, w in street_segs.get((i, j), ()):
                ex, ez = bx - ax, bz - az
                L2 = ex * ex + ez * ez
                if L2 < 1e-6:
                    continue
                t = max(0, min(1, ((x - ax) * ex + (z - az) * ez) / L2))
                px, pz = ax + ex * t, az + ez * t
                d = math.hypot(px - x, pz - z)
                if d < reach and (best is None or d < best[0]):
                    best = (d, px, pz, w)
    return best


def side_towards(cx, cz, ang, tx, tz):
    """Which side of a box turned by ang faces the point: 0 +x, 1 -x, 2 +z, 3 -z (box-local axes)."""
    dx, dz = tx - cx, tz - cz
    u = dx * math.cos(ang) + dz * math.sin(ang)
    v = -dx * math.sin(ang) + dz * math.cos(ang)
    return (0 if u > 0 else 1) if abs(u) > abs(v) else (2 if v > 0 else 3)


def side_point(cx, cz, ang, w, d, side):
    """Middle of that side, in world coordinates."""
    lu, lv = [(w / 2, 0), (-w / 2, 0), (0, d / 2), (0, -d / 2)][side]
    return cx + lu * math.cos(ang) - lv * math.sin(ang), cz + lu * math.sin(ang) + lv * math.cos(ang)


# ------------------------------------------------------------ city data
# What the City of Minneapolis, Hennepin County and Metro Transit publish (fetch_city.py, bake_transit.py): each
# parcel's walls and roof from the assessor, the street lights, hydrants, Nice Ride docks, pavement and bike lanes,
# the bus stops, and the aerial photo the roofs take their colours from. Where any of it is missing the city is
# baked as before.
CITY = os.path.join(CACHE, 'city')


def cload(name, default):
    path = os.path.join(CITY, name)
    return json.load(open(path)) if os.path.exists(path) else default


class Grid:
    """Things with a bounding box, bucketed in cells of `size` metres, to find those near a point."""
    def __init__(self, size):
        self.size, self.cells = size, {}

    def add(self, item, x0, z0, x1, z1):
        s = self.size
        for i in range(int(x0 // s), int(x1 // s) + 1):
            for j in range(int(z0 // s), int(z1 // s) + 1):
                self.cells.setdefault((i, j), []).append(item)

    def near(self, x, z, r=0):
        s, seen = self.size, set()
        for i in range(int((x - r) // s), int((x + r) // s) + 1):
            for j in range(int((z - r) // s), int((z + r) // s) + 1):
                for it in self.cells.get((i, j), ()):
                    if id(it) not in seen:
                        seen.add(id(it))
                        yield it


def seg_dist(x, z, ax, az, bx, bz):
    """Distance from (x, z) to the segment a-b, and the nearest point on it."""
    ex, ez = bx - ax, bz - az
    L2 = ex * ex + ez * ez or 1e-9
    t = max(0, min(1, ((x - ax) * ex + (z - az) * ez) / L2))
    px, pz = ax + ex * t, az + ez * t
    return math.hypot(x - px, z - pz), px, pz


PARCELS = Grid(60)
n_parcels = 0
for p in cload('parcels.json', []):
    rs = [[m(la, lo) for la, lo in r] for r in p['rings']]
    if not rs or not rs[0]:
        continue
    p['xz'] = rs
    xs, zs = [q[0] for q in rs[0]], [q[1] for q in rs[0]]
    PARCELS.add(p, min(xs), min(zs), max(xs), max(zs))
    n_parcels += 1


def inside_ring(x, z, r):
    hit = False
    for i in range(len(r)):
        (x1, z1), (x2, z2) = r[i - 1], r[i]
        if (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1):
            hit = not hit
    return hit


def parcel_at(x, z):
    for p in PARCELS.near(x, z):
        if inside_ring(x, z, p['xz'][0]):
            return p
    return None


# Walls the assessor names, as the game's house walls: 0 clapboard (wood, vinyl and steel siding), 1 stucco, 2 brick,
# 3 cedar shakes. Each has its own colours: painted siding, stucco's creams and greys, brick's reds and browns (over
# the red brick texture), stained cedar.
WALL_KIND = {'STUCCO': 1, 'CONCRETE': 1, 'BRICK': 2, 'STONE': 2, 'WOOD SHAKE': 3}
STUCCO_WALL = ['#efe9dc', '#e6dcc6', '#d9d3c5', '#ece4d0', '#d4c8b0', '#c9c3b5', '#e8dfcf', '#bfb6a3', '#d8c9a3', '#b8bcb2']
BRICK_WALL = ['#ffffff', '#f3e9e3', '#e9ddd6', '#dccbc2', '#d9c2b5', '#c7a99a', '#f0dfd3', '#b89a8c']
SHAKE_WALL = ['#b98f68', '#9c7552', '#8d8579', '#a8a399', '#7d6a55', '#c4a27c', '#6f665c', '#b3aa98']
# The assessor's roofs, as the game's: 1 gable (turned whichever way the LiDAR found it), 3 hip, 0 flat
ROOF_KIND = {'GABLE': 1, 'GAMBREL': 1, 'SHED': 1, 'HIP': 3, 'MANSARD': 3, 'FLAT': 0}

# The aerial photo: each tile's picture (fetch_city.py) and the degrees it covers, read when a roof needs it
AERIAL = {}


def aerial(i, j):
    if (i, j) not in AERIAL:
        if len(AERIAL) > 6:
            AERIAL.pop(next(iter(AERIAL)))
        path = os.path.join(CITY, 'aerial', f'{i}_{j}.jpg')
        AERIAL[(i, j)] = (np.asarray(Image.open(path).convert('RGB')), json.load(open(path[:-4] + '.json'))) \
            if os.path.exists(path) else None
    return AERIAL[(i, j)]


def roof_photo(ring, inset=0.8):
    """The roof's colour in the aerial photo inside a footprint ring (pulled in by inset metres from its edge, past
    the eaves and the trees hanging over them): the median of what isn't leaves or deep shadow, or None."""
    cx = sum(p[0] for p in ring) / len(ring)
    cz = sum(p[1] for p in ring) / len(ring)
    A = aerial(int((cx - X0) // TILE), int((cz - Z0) // TILE))
    if A is None:
        return None
    img, (w, s, e, n) = A
    H, Wd = img.shape[:2]

    def px(x, z):
        lat, lon = LAT0 - z / MY, LON0 + x / MX
        return (lon - w) / (e - w) * Wd, (n - lat) / (n - s) * H
    rad = max(1e-3, sum(math.hypot(p[0] - cx, p[1] - cz) for p in ring) / len(ring))
    k = max(0.3, 1 - inset / rad)
    pts = [px(cx + (p[0] - cx) * k, cz + (p[1] - cz) * k) for p in ring]
    x0, y0 = int(max(0, min(p[0] for p in pts))), int(max(0, min(p[1] for p in pts)))
    x1, y1 = int(min(Wd - 1, max(p[0] for p in pts))) + 1, int(min(H - 1, max(p[1] for p in pts))) + 1
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    mask = Image.new('L', (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(mask).polygon([(p[0] - x0, p[1] - y0) for p in pts], fill=1)
    sel = img[y0:y1, x0:x1][np.asarray(mask, bool)].astype(np.float32)
    if len(sel) < 4:
        return None
    r, g, b = sel[:, 0], sel[:, 1], sel[:, 2]
    keep = ~((g > r + 6) & (g > b + 4)) & (r + g + b > 90)
    if keep.sum() >= max(4, len(sel) * 0.2):
        sel = sel[keep]
    return np.median(sel, axis=0)


LIGHTS = cload('lights.json', [])
HYDRANTS = cload('hydrants.json', [])
NICERIDE = cload('niceride.json', [])
STOPS = cload('stops.json', [])
print('city data: parcels', n_parcels, 'lights', len(LIGHTS), 'hydrants', len(HYDRANTS), 'stops', len(STOPS), flush=True)

# ------------------------------------------------------------- buildings
LIDAR_B = jload('lidar_buildings.json', {})
LIDAR_T = jload('lidar_trees.json', None)
print('lidar: buildings', len(LIDAR_B), 'trees', len(LIDAR_T or []), flush=True)

# Facade layers in the texture array (see make_textures.py).
BRICK_RED, BRICK_LITE, CONC_RIBBON, GLASS, STOREFRONT, SIDING_WIN, SIDING, GARAGE_DOOR, SIDING_DOOR, \
    BRICK_RED_PLAIN, BRICK_LITE_PLAIN, CONC_PLAIN = range(12)
TINT_RED = ['#ffffff', '#f3e9e3', '#e9ddd6', '#f8f0e8', '#dccbc2']        # over red brick: small variations
TINT_LITE = ['#efe3c8', '#e3cfa6', '#d8c39a', '#e9e2d6', '#cfc6b8', '#e7d2b5', '#d9cdb8', '#c9b38f']
TINT_CONC = ['#e6e3dc', '#d6d3cc', '#cfc9bd', '#e2ddd0', '#c8c6c0']
HOUSE_WALL = ['#f3f1ea', '#efe3c4', '#e9dfb0', '#c9d3d8', '#b9c4b0', '#7d8f7a', '#5f6f80', '#9e5a4a', '#cdb89a', '#a9aaa6',
              '#f1ece0', '#d8c7a4', '#8f9faa', '#e8d6c0']
HOUSE_ROOF = ['#4a4a4c', '#5b5650', '#6b4f42', '#3f4448', '#6e6a63', '#53463d', '#7a5c4a', '#2f3336']
BOX_WALL = HOUSE_WALL
OVERRIDE = {   # name -> (height m if OpenStreetMap has none, wall colour)
    'IDS Center': (22, '#bfc8d2'),            # the block-wide base; the tower is its own 3D part
    'IDS Tower': (241, '#7fa6d6'),
    'Wells Fargo Center': (236, '#d9c48f'),
    'Foshay Tower': (137, '#e4d7b6'),
    'Capella Tower': (237, '#cfd5dc'),
    '33 South Sixth': (204, '#7a8698'),
    'US Bank Stadium': (83, '#8e9fb4'),
    'Target Center': (41, '#c99a85'),
    'Guthrie Theater': (35, '#6f8fb3'),
}
HOUSE_WALLS = HOUSE_WALL + STUCCO_WALL + BRICK_WALL + SHAKE_WALL       # the game's houseWall palette
WALL_BASE = [0, len(HOUSE_WALL), len(HOUSE_WALL) + len(STUCCO_WALL), len(HOUSE_WALL) + len(STUCCO_WALL) + len(BRICK_WALL)]
HOUSE_TAGS = ('house', 'detached', 'residential', 'semidetached_house', 'bungalow', 'cabin', 'hosue')
BOX_TAGS = ('garage', 'garages', 'shed', 'carport', 'hut')
SHOP_TAGS = ('retail', 'commercial', 'supermarket', 'kiosk', 'mixed_use')


def num(v):
    try:
        return float(str(v).split(';')[0].split()[0].replace('m', '').replace(',', '.'))
    except Exception:
        return None


def height_of(t, area):
    for k in ('height', 'building:height'):
        h = num(t.get(k))
        if h and 2 <= h < 400:
            return h
    lv = num(t.get('building:levels'))
    if lv and 0 < lv < 80:
        return lv * 3.5 + (1 if 'building:part' not in t else 0)
    b = t.get('building') or t.get('building:part') or 'yes'
    if b in BOX_TAGS or b == 'roof':
        return 3.2
    if b in HOUSE_TAGS and area < 400:
        return 8
    if b in ('apartments', 'dormitory', 'hotel'):
        return 18
    if b in ('commercial', 'retail', 'office'):
        return 12
    if b in ('industrial', 'warehouse'):
        return 10
    if b == 'yes' and area < 60:
        return 3.2      # untagged sheds and garages
    if b == 'yes' and area < 260:
        return 8        # untagged houses
    return 9 if area < 600 else 14


def min_height_of(t):
    for k in ('min_height', 'building:min_height'):
        h = num(t.get(k))
        if h is not None and 0 <= h < 400:
            return h
    lv = num(t.get('building:min_level'))
    return lv * 3.5 if lv and lv > 0 else 0


def facade_of(t, tag, h, area, eid):
    """(facade layer, tint colour, storefront?) from the building's type, material and size."""
    mat = t.get('building:material', '')
    c = t.get('building:colour') or t.get('colour')
    pick = lambda pal: pal[eid % len(pal)]
    shop = tag in SHOP_TAGS or ('shop' in t and h < 20)
    if 'glass' in mat:
        fac = GLASS
    elif 'concrete' in mat:
        fac = CONC_RIBBON
    elif 'brick' in mat:
        fac = BRICK_RED if eid % 2 else BRICK_LITE
    elif 'wood' in mat or 'vinyl' in mat:
        fac = SIDING_WIN
    elif h >= 40:
        fac = (GLASS, GLASS, CONC_RIBBON, BRICK_LITE)[eid % 4] if h >= 70 else (CONC_RIBBON, GLASS, BRICK_LITE)[eid % 3]
    elif tag == 'office':
        fac = (CONC_RIBBON, BRICK_LITE, GLASS if h > 25 else BRICK_RED)[eid % 3]
    elif tag in ('industrial', 'warehouse', 'manufacture', 'storage_tank'):
        fac = (BRICK_RED_PLAIN, BRICK_LITE_PLAIN, CONC_PLAIN)[eid % 3]
    elif tag in ('parking',):
        fac = CONC_PLAIN
    elif tag in ('church', 'cathedral', 'chapel'):
        fac = (BRICK_LITE_PLAIN, BRICK_RED_PLAIN)[eid % 2]
    elif tag in BOX_TAGS or tag == 'roof':
        fac = SIDING
    elif tag in HOUSE_TAGS or (tag == 'yes' and area < 260 and h <= 12):
        fac = SIDING_WIN
    else:
        fac = BRICK_RED if eid % 5 < 3 else BRICK_LITE
    if c:
        try:
            r, g, b = ImageColor.getrgb(c.strip())[:3]
            if fac in (BRICK_RED, BRICK_RED_PLAIN):
                fac += 1                          # light brick takes a colour better
            return fac, '#%02x%02x%02x' % (r, g, b), shop
        except Exception:
            pass
    pal = {BRICK_RED: TINT_RED, BRICK_RED_PLAIN: TINT_RED, STOREFRONT: TINT_RED, GLASS: ['#ffffff', '#e8eef4', '#dfe8ee'],
           CONC_RIBBON: TINT_CONC, CONC_PLAIN: TINT_CONC, SIDING_WIN: HOUSE_WALL, SIDING: HOUSE_WALL}.get(fac, TINT_LITE)
    return fac, pick(pal), shop


houses, boxes, solids = [], [], []
measured = 0
for b in load_buildings():
    t, r, a = b['t'], b['r'], b['a']
    if not in_map(b['cx'], b['cz']):
        continue
    h = height_of(t, a)
    h0 = min_height_of(t)
    name = t.get('name', '')
    col = None
    explicit = 'height' in t or 'building:part' in t or h0 > 0
    if name in OVERRIDE:
        col = OVERRIDE[name][1]
        if 'height' not in t:
            h = OVERRIDE[name][0]
            explicit = True
    L = LIDAR_B.get(b['key'])
    tag = t.get('building', t.get('building:part', 'yes'))
    rect = None if b['holes'] or h0 or 'building:part' in t else b['rect']
    fill = a / max(rect[5], 1) if rect is not None else 0   # how much of its bounding rectangle the footprint fills
    plain = fill > 0.8 and h <= 12
    if plain and a < 70 and (tag in BOX_TAGS or (tag == 'yes' and h <= 4)):
        gh = max(2.4, min(5, L[0])) if L else 2.8
        boxes.append([rect[0], rect[1], rect[2], rect[3], rect[4], gh, b['id'] % len(BOX_WALL), b['key']])
        poly(r, 'roof')
        continue
    # Houses with a bump-out or an L still get a house's roof over their bounding rectangle.
    if fill > 0.65 and h <= 12 and 50 <= a < 300 and (tag in HOUSE_TAGS or tag == 'yes') and (not L or L[0] < 18):
        w, d = rect[3], rect[4]
        # What the assessor says of the house on this parcel: its walls, its roof, its year and its storeys
        P = parcel_at(b['cx'], b['cz'])
        said = ROOF_KIND.get(P['roof']) if P else None
        if L and L[0] >= 3:
            ridge, roof, eave = L
            measured += 1
            if roof == 0 and a < 200 and said != 0:
                # Nearly every small Minneapolis house is pitched: a "flat" reading is usually branches over the roof.
                roof = said if said is not None else 3 if b['id'] % 3 == 0 else 1
                eave = max(2.6, ridge - 0.33 * d)
            elif roof == 0:
                eave = ridge
            elif said == 3:
                roof = 3                  # the survey's points are too few to tell a hip from a gable; the assessor can
            elif said == 1 and roof == 3:
                roof = 1
            eave = max(2.6, min(eave, ridge))
            ridge = min(ridge, eave + 0.65 * (d if roof != 2 else w))
        else:
            lv = num(t.get('building:levels')) or (P and P['stories'])
            eave = lv * 2.9 + 0.5 if lv and lv <= 3 else 5.0
            roof = said if said is not None else 3 if b['id'] % 3 == 0 else 1
            ridge = eave + (d * 0.35 if roof else 0)
        kind = WALL_KIND.get(P['wall'], 0) if P else 0
        pal = (HOUSE_WALL, STUCCO_WALL, BRICK_WALL, SHAKE_WALL)[kind]
        wc = WALL_BASE[kind] + b['id'] % len(pal)
        houses.append([rect[0], rect[1], rect[2], w, d, eave, ridge, roof, -1,
                       wc, (b['id'] // 7) % len(HOUSE_ROOF), kind << 2, r, P['year'] if P else 0])
        poly(r, 'roof')
        continue
    if not explicit and L and 2.5 <= L[0] < 300:
        h = L[0]
        measured += 1
    if tag == 'bridge':                   # skyways: a few metres up, so streets run underneath
        h0 = max(h0, 5)
        h = h0 + 4
    elif tag == 'roof':                   # canopies over gas pumps and platforms: drive-under slabs
        h0, h = 3.6, 4.4
    fac, tint, shop = facade_of(t, tag, h, a, b['id'])
    if col is not None:
        tint = col
    if tag == 'bridge':
        fac = GLASS
    flags = (1 if shop and h0 == 0 and h >= 5 and fac not in (GLASS, SIDING_WIN, SIDING) else 0) \
        | (2 if h0 == 0 and a > 150 and fac != SIDING_WIN and tag not in ('roof', 'bridge') else 0)
    if h0 == 0:
        line(r + r[:1], 5, 'plaza')   # pavement around bigger buildings: plazas, parking aprons
        poly(r, 'bldg')
    solids.append(dict(r=r, holes=b['holes'], h=h, h0=h0, fac=fac, tint=tint, flags=flags, cx=b['cx'], cz=b['cz']))
print('measured by lidar', measured, flush=True)

# Houses face their street: a front door, maybe a porch, and a walk out to the sidewalk.
house_grid = {}
for hs in houses:
    cx, cz, ang, w, d = hs[:5]
    st = nearest_street(cx, cz)
    if st:
        _, px, pz, sw = st
        side = side_towards(cx, cz, ang, px, pz)
        hs[8] = side
        fx, fz = side_point(cx, cz, ang, w, d, side)
        L = math.hypot(px - fx, pz - fz)
        if L > sw / 2 + 1:
            k = (L - sw / 2) / L
            line([(fx, fz), (fx + (px - fx) * k, fz + (pz - fz) * k)], 1.3, 'walk')
        # Front porches on the old houses (nearly every one built before the 1930s has one), a few on the newer
        year = hs[13]
        if random.random() < (0.85 if 0 < year < 1930 else 0.35 if 0 < year < 1960 else 0.15 if year else 0.55) and w * d > 70:
            hs[11] |= 2
    year = hs[13]
    if hs[7] != 0 and random.random() < (0.75 if 0 < year < 1950 else 0.25 if year else 0.5):
        hs[11] |= 1
    house_grid.setdefault((int(cx // 40), int(cz // 40)), []).append((cx, cz))

# Garages open away from their house, onto the alley behind.
for g in boxes:
    cx, cz, ang = g[:3]
    best = None
    for i in range(int(cx // 40) - 1, int(cx // 40) + 2):
        for j in range(int(cz // 40) - 1, int(cz // 40) + 2):
            for hx, hz in house_grid.get((i, j), ()):
                dd = math.hypot(hx - cx, hz - cz)
                if dd < 35 and (best is None or dd < best[0]):
                    best = (dd, hx, hz)
    if best:
        g.append(side_towards(cx, cz, ang, 2 * cx - best[1], 2 * cz - best[2]))
    else:
        st = nearest_street(cx, cz)
        g.append(side_towards(cx, cz, ang, st[1], st[2]) if st else 0)

# Fences, walls and hedges. Ones up on bridges are left out (they'd stand on the ground below, across
# whatever the bridge crosses), and the rest are cut wherever they'd run across a street or path.
fences = []
fence_cuts = 0
for e in load('barriers'):
    t = e['tags']
    # Retaining walls hold up a step in the ground, which the survey's ground already has.
    if t['barrier'] == 'retaining_wall' or is_bridge(t) or str(t.get('layer', '0')) not in ('0', '-1', '-2'):
        continue
    kind = {'fence': 0, 'wall': 1, 'hedge': 2}[t['barrier']]
    try:
        ht = float(str(t.get('height', '')).split()[0].rstrip('m')) if "'" not in str(t.get('height', '')) else 0
    except (ValueError, IndexError):
        ht = 0
    if kind == 0 and (t.get('fence_type') in ('post_and_rail', 'split_rail', 'rail', 'bollard', 'guard_rail') or 0 < ht < 1.3):
        kind = 3                                  # a low rail fence, as along the lake paths
    pts = [m(p['lat'], p['lon']) for p in e['geometry']]
    run = []
    for a, b in zip(pts, pts[1:] + [None]):
        n = 1 if b is None else max(1, math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / 1.5))
        for q in range(n):
            p = a if b is None else (a[0] + (b[0] - a[0]) * q / n, a[1] + (b[1] - a[1]) * q / n)
            if on_pavement(*p, 0.4):
                if len(run) >= 2:
                    fences.append((kind, run))
                fence_cuts += bool(run)
                run = []
            elif not run or p != run[-1]:
                run.append(p)
    if len(run) >= 2:
        fences.append((kind, run))
print('fences cut where they cross streets and paths', fence_cuts, flush=True)

for pts, w, t in paths:                          # trails and alleys, under the streets they cross
    line(pts, w, 'road' if t.get('service') == 'alley' else 'walk')
for _, hw, pts, t, _ in roads:                    # a curb along the edge (the sidewalks are 3D, beyond a grass boulevard)
    if hw not in ('motorway', 'trunk', 'motorway_link', 'trunk_link'):
        line(pts, WIDTH[hw] + 1.2, 'curb')
for _, hw, pts, t, _ in roads:
    line(pts, WIDTH[hw], 'highway' if hw in ('motorway', 'trunk') else 'major' if hw in ('primary', 'secondary') else 'road')
for _, hw, pts, t, _ in roads:                    # a pale centre line on the big roads
    if hw in ('motorway', 'trunk', 'primary'):
        line(pts, 0.9, 'line')
for e in load('rail'):                            # railways and the light rail's tracks, not where they run underground
    if e.get('tags', {}).get('tunnel') in (None, 'no'):
        line(rings(e)[0][1], 5, 'rail')
print('ops', len(ops), 'buildings', len(solids), 'houses', len(houses), 'garages', len(boxes), 'fences', len(fences), flush=True)

# ----------------------------------------------- the 2 m class grid
GW, GH = (X1 - X0) // 2, (Z1 - Z0) // 2


def gpx(x, z):
    return ((x - X0) / 2, (z - Z0) / 2)


def replay(draw, to_px, ppm, which, fill_of):
    for kind, shape, pts, w, _ in which:
        f = fill_of(kind)
        if shape == 'poly':
            draw.polygon([to_px(*p) for p in pts], fill=f)
        elif shape == 'line':
            draw.line([to_px(*p) for p in pts], fill=f, width=max(1, int(round(w * ppm))), joint='curve')


cls_img = Image.new('L', (GW, GH), CLS['land'])
cd = ImageDraw.Draw(cls_img)
replay(cd, gpx, 0.5, ops[:N_WATER_OPS], CLS.get)
wet = np.isin(np.asarray(cls_img), (CLS['water'], CLS['shore']))
replay(cd, gpx, 0.5, ops[N_WATER_OPS:], CLS.get)
grid = np.asarray(cls_img)


def cell(x, z):
    return int((z - Z0) / 2), int((x - X0) / 2)


# ----------------------------------------------------------------- trees
trees = []
if LIDAR_T is not None:
    # Real trees from the LiDAR canopy, skipping any that landed on a road or in the water.
    for x, z, ht, rad in LIDAR_T:
        if not in_map(x, z):
            continue
        i, j = cell(x, z)
        if grid[i, j] in (CLS['road'], CLS['water']):
            continue
        trees.append((x, z, max(4.5, min(ht, 32)), max(1.6, min(rad, 8))))
    # The survey finds each crown's peak, which can hang out over the street. Move such a trunk
    # back to the edge of the pavement (onto the boulevard), or drop it if that's no good either.
    TG = 20
    keep_off = {}
    for _, hw, pts, t, _ in roads:
        if not is_bridge(t):
            for a, b in zip(pts, pts[1:]):
                for i in range(int(min(a[0], b[0]) // TG) - 1, int(max(a[0], b[0]) // TG) + 2):
                    for j in range(int(min(a[1], b[1]) // TG) - 1, int(max(a[1], b[1]) // TG) + 2):
                        keep_off.setdefault((i, j), []).append((a, b, WIDTH[hw] / 2 + 0.9))
    for pts, w, t in paths:
        for a, b in zip(pts, pts[1:]):
            for i in range(int(min(a[0], b[0]) // TG) - 1, int(max(a[0], b[0]) // TG) + 2):
                for j in range(int(min(a[1], b[1]) // TG) - 1, int(max(a[1], b[1]) // TG) + 2):
                    keep_off.setdefault((i, j), []).append((a, b, w / 2 + 0.6))

    def intrusion(x, z):
        worst = None
        for a, b, r in keep_off.get((int(x // TG), int(z // TG)), ()):
            ex, ez = b[0] - a[0], b[1] - a[1]
            L2 = ex * ex + ez * ez or 1e-9
            t = max(0, min(1, ((x - a[0]) * ex + (z - a[1]) * ez) / L2))
            qx, qz = x - a[0] - ex * t, z - a[1] - ez * t
            d = math.hypot(qx, qz)
            if d < r and (worst is None or r - d > worst[0]):
                worst = (r - d, qx / d if d > 1e-6 else -ez / math.sqrt(L2), qz / d if d > 1e-6 else ex / math.sqrt(L2))
        return worst

    moved = dropped = 0
    kept = []
    for x, z, ht, rad in trees:
        hit = intrusion(x, z)
        if hit:
            x, z = x + hit[1] * (hit[0] + 0.1), z + hit[2] * (hit[0] + 0.1)
            moved += 1
            if intrusion(x, z):
                dropped += 1
                continue
        kept.append((x, z, ht, rad))
    trees = kept
    print('trees moved off pavement', moved, 'dropped', dropped, flush=True)
else:
    # No LiDAR: scatter boulevard and park trees.
    lot, park = grid == CLS['land'], (grid == CLS['park']) | (grid == CLS['wood'])
    for _, hw, pts, t, _ in roads:
        if hw not in ('residential', 'living_street', 'unclassified'):
            continue
        off = WIDTH[hw] / 2 + 3.5
        for (x1, z1), (x2, z2) in zip(pts, pts[1:]):
            seg = math.hypot(x2 - x1, z2 - z1)
            s = random.uniform(0, 8)
            while seg > 1 and s < seg:
                for side in (-1, 1):
                    tx, tz = x1 + (x2 - x1) * s / seg - (z2 - z1) / seg * side * off, z1 + (z2 - z1) * s / seg + (x2 - x1) / seg * side * off
                    i, j = cell(tx, tz)
                    if in_map(tx, tz) and 0 <= i < GH and 0 <= j < GW and lot[i, j] and random.random() < 0.6:
                        ht = random.uniform(8, 16)
                        trees.append((tx, tz, ht, 1.5 + ht * 0.28))
                s += random.uniform(14, 18)
    pi, pj = np.nonzero(park)
    for idx in np.random.default_rng(3).permutation(len(pi))[: len(pi) // 60]:
        ht = random.uniform(8, 20)
        trees.append((pj[idx] * 2 + X0 + 1, pi[idx] * 2 + Z0 + 1, ht, 1.5 + ht * 0.28))
for x, z, ht, rad in trees:
    shade_dots.append((x, z, rad * 0.9))
print('trees', len(trees), flush=True)

# ---------------------------------------------------------- street signs
# A sign post on one corner of every intersection of two named streets, with a blade for each.
junctions = {}
for _, hw, pts, t, ll in roads:
    name = t.get('name')
    if not name or hw in ('motorway', 'trunk', 'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link'):
        continue
    for k, key in enumerate(ll):
        nb = [pts[k + s] for s in (-1, 1) if 0 <= k + s < len(pts)]
        junctions.setdefault(key, []).append((name, pts[k], nb, WIDTH[hw]))
signs, sign_seen = [], {}
for key, ends in junctions.items():
    names = []
    for e in ends:
        if e[0] not in [n[0] for n in names]:
            names.append(e)
    if len(names) < 2:
        continue
    (na, p, nba, wa), (nb_, _, nbb, wb) = names[0], names[1]
    if na.startswith(nb_) or nb_.startswith(na):
        continue                                   # one street renamed partway ("... Boulevard" / "... Boulevard West")
    if not nba or not nbb:
        continue
    pair = tuple(sorted((na, nb_)))
    if any(math.hypot(p[0] - q[0], p[1] - q[1]) < 60 for q in sign_seen.get(pair, ())):
        continue                                   # divided roads meet twice: one sign is enough
    sign_seen.setdefault(pair, []).append(p)

    def unit(q):
        dx, dz = q[0] - p[0], q[1] - p[1]
        L = math.hypot(dx, dz) or 1
        return dx / L, dz / L
    ua, ub = unit(nba[-1]), unit(nbb[-1])
    bx, bz = ua[0] + ub[0], ua[1] + ub[1]
    L = math.hypot(bx, bz)
    if L < 0.3:
        continue
    off = (max(wa, wb) / 2 + 2.2) * 1.3
    sx, sz = p[0] + bx / L * off, p[1] + bz / L * off
    if in_map(sx, sz):
        signs.append((sx, sz, math.atan2(ua[1], ua[0]), na, math.atan2(ub[1], ub[0]), nb_))
print('signs', len(signs), flush=True)

# ------------------------------------------------------- 3D street pieces
# Every street is split at its intersections. Each piece carries how far its
# sidewalks and markings stop short of the intersection at either end (so they
# don't run across the cross street), and stretches over water are left out:
# the bridges have their own decks. Busy intersections get crosswalks.
STREET = set(WIDTH) - {'pedestrian'}
node_roads = {}
for ri, (_, hw, pts, t, ll) in enumerate(roads):
    if hw in STREET:
        for key in ll:
            node_roads.setdefault(key, set()).add(ri)
junctions = {k: v for k, v in node_roads.items() if len(v) >= 2}
MAJOR = ('primary', 'secondary', 'tertiary')
FREEWAY = ('motorway', 'trunk', 'motorway_link', 'trunk_link')


def clearance(key, ri):
    return max(WIDTH[roads[o][1]] for o in junctions[key] if o != ri) / 2 + 1.6


street_pieces, crosswalks = [], []
for ri, (_, hw, pts, t, ll) in enumerate(roads):
    if hw not in STREET or t.get('tunnel') in ('yes', 'building_passage') or str(t.get('layer', '0')).startswith('-') \
            or is_bridge(t):
        continue
    lanes = int(num(t.get('lanes')) or 0)
    oneway = 1 if t.get('oneway') == 'yes' or hw in ('motorway', 'motorway_link') else 0
    cuts = [0] + [k for k in range(1, len(pts) - 1) if ll[k] in junctions] + [len(pts) - 1]
    for a, b in zip(cuts, cuts[1:]):
        seg = pts[a:b + 1]
        # Split again wherever the street crosses water.
        runs, run = [], [seg[0]]
        for p, q in zip(seg, seg[1:]):
            i, j = cell((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            if 0 <= i < GH and 0 <= j < GW and wet[i, j]:
                if len(run) >= 2:
                    runs.append((run, run[0] is seg[0], False))
                run = [q]
            else:
                run.append(q)
        if len(run) >= 2:
            runs.append((run, run[0] is seg[0], True))
        for run, at_a, at_b in runs:
            t0 = clearance(ll[a], ri) if at_a and ll[a] in junctions else 0
            t1 = clearance(ll[b], ri) if at_b and ll[b] in junctions else 0
            street_pieces.append((order.index(hw), WIDTH[hw], lanes, oneway, t0, t1, run))
            # Crosswalks across this street where it meets a busy one.
            if hw in FREEWAY:
                continue
            for end, key, tt in ((0, ll[a], t0), (1, ll[b], t1)):
                if not tt or not any(roads[o][1] in MAJOR for o in junctions[key]):
                    continue
                p0, p1 = (run[0], run[1]) if end == 0 else (run[-1], run[-2])
                L = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) or 1
                if L < tt:
                    continue
                ux, uz = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
                d = tt - 1.8
                crosswalks.append((p0[0] + ux * d, p0[1] + uz * d, math.atan2(uz, ux), WIDTH[hw]))
junction_pads = []
for key, rs in junctions.items():
    if all(roads[o][1] in FREEWAY for o in rs):
        continue
    x, z = m(*key)
    i, j = cell(x, z)
    if 0 <= i < GH and 0 <= j < GW and not wet[i, j]:
        junction_pads.append((x, z, max(WIDTH[roads[o][1]] for o in rs) / 2))
print('street pieces', len(street_pieces), 'junctions', len(junction_pads), 'crosswalks', len(crosswalks), flush=True)


def nearest_pave(x, z, reach=40):
    """The nearest street or path centreline on the ground: (distance, x, z, half width) or None."""
    best = None
    for i in range(int((x - reach) // PG), int((x + reach) // PG) + 1):
        for j in range(int((z - reach) // PG), int((z + reach) // PG) + 1):
            for a, b, half in pavement.get((i, j), ()):
                d, px, pz = seg_dist(x, z, a[0], a[1], b[0], b[1])
                if d < reach and (best is None or d < best[0]):
                    best = (d, px, pz, half)
    return best


def off_the_street(x, z, gap):
    """(x, z) moved out of the street to gap metres past its edge if it stands in it, and the angle from there to the
    street's middle (or None with no street near)."""
    st = nearest_pave(x, z)
    if not st:
        return x, z, None
    d, px, pz, half = st
    if d > 1e-3:
        ux, uz = (x - px) / d, (z - pz) / d
        if d < half + gap:
            x, z = px + ux * (half + gap), pz + uz * (half + gap)
        return x, z, math.atan2(-uz, -ux)
    return x, z, None


# Pavement and bike lanes (fetch_city.py): each street piece takes the surface and bike lane of the city's block
# lines lying along it. Appended to its record: surface (0 asphalt, 1 concrete, 2 brick, 3 gravel) and bike lane
# (0 none, 1 a lane, 2 buffered, 3 protected by posts, 4 shared with buses, 5 a bike boulevard's markings).
SURFACE = {'PCC': 1, 'BR': 2, 'PVB': 2, 'GR': 3}
BIKE = {'Bike Lane': 1, 'Advisory Bike Lane': 1, 'Buffered Bike Lane': 2, 'On-Street Protected Bike Lane': 3,
        'Shared Bike/Bus Lane': 4, 'Bike Boulevard': 5, 'Shared Use Pavement Marking': 5}


def line_grid(items, code_of):
    G = Grid(40)
    for it in items:
        code = code_of(it)
        if not code:
            continue
        for ln in it['lines']:
            pts = [m(la, lo) for la, lo in ln]
            for a, b in zip(pts, pts[1:]):
                G.add((a[0], a[1], b[0], b[1], code), min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
    return G


def vote(G, run, reach=10):
    """The code of the city lines lying along a street piece (most of its length), or 0."""
    cum = [0]
    for a, b in zip(run, run[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    votes = {}
    for f in (0.2, 0.5, 0.8):
        s = cum[-1] * f
        k = max(1, next((i for i, c in enumerate(cum) if c >= s), len(run) - 1))
        a, b = run[k - 1], run[k]
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
        ux, uz = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        t = (s - cum[k - 1]) / L
        x, z = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        best = None
        for ax, az, bx, bz, code in G.near(x, z, reach):
            sl = math.hypot(bx - ax, bz - az) or 1
            if abs((bx - ax) / sl * ux + (bz - az) / sl * uz) < 0.8:
                continue
            d = seg_dist(x, z, ax, az, bx, bz)[0]
            if d < reach and (best is None or d < best[0]):
                best = (d, code)
        if best:
            votes[best[1]] = votes.get(best[1], 0) + 1
    code, n = max(votes.items(), key=lambda kv: kv[1]) if votes else (0, 0)
    return code if n >= 2 else 0


PAVE_G = line_grid(cload('pavement.json', []), lambda it: SURFACE.get(it['surface'], 9))
BIKE_G = line_grid(cload('bikeways.json', []), lambda it: BIKE.get(it['type'], 0))
surfaced = {}
for k, (cls, w, lanes, oneway, t0, t1, run) in enumerate(street_pieces):
    sf = vote(PAVE_G, run)
    bk = vote(BIKE_G, run, 12) if order[cls] not in FREEWAY else 0
    street_pieces[k] = (cls, w, lanes, oneway, t0, t1, run, 0 if sf == 9 else sf, bk)
    surfaced[sf] = surfaced.get(sf, 0) + 1
print('street surfaces (9: asphalt, matched)', surfaced, flush=True)

# The street lights (fetch_city.py): every city-owned light where it stands, its fixture as the game draws it
# (0 cobra head, 1 lantern, 2 acorn, 3 teardrop, 4 shoebox, 5 globe, 6 accent), turned to face the street.
LAMP_STYLE = (('cobra', 0), ('lantern', 1), ('acorn', 2), ('tear', 3), ('shoebox', 4), ('globe', 5), ('accent', 6))
lamps, lamp_seen = [], Grid(4)
for la, lo, kind in LIGHTS:
    x, z = m(la, lo)
    if not in_map(x, z) or any(math.hypot(x - q[0], z - q[1]) < 1.0 for q in lamp_seen.near(x, z, 1)):
        continue                                  # two heads on one pole
    lamp_seen.add((x, z), x, z, x, z)
    style = next((n for k, n in LAMP_STYLE if k in kind.lower()), 0)
    x, z, ang = off_the_street(x, z, 0.5)
    lamps.append((x, z, ang if ang is not None else 0, style))
print('lamps', len(lamps), flush=True)

# Signalled corners: every junction with an OpenStreetMap traffic signal within SIGNAL_R of it
SIGNAL_R = 18
POINTS = load('points')
sig_g = Grid(30)
for p in POINTS:
    if p['kind'] == 'signal':
        x, z = m(p['lat'], p['lon'])
        sig_g.add((x, z), x, z, x, z)
signals = [(x, z) for x, z, _ in junction_pads
           if any(math.hypot(x - q[0], z - q[1]) < SIGNAL_R for q in sig_g.near(x, z, SIGNAL_R))]
print('signalled junctions', len(signals), flush=True)

# Street furniture: [kind, x, z, angle to the street]. 0 hydrant, 1 bench, 2 litter bin, 3 bus stop sign, 4 bus
# shelter, 5 Nice Ride dock, 6 mailbox, 7 utility pole, 8 bike rack, 9 light rail platform canopy. The city's hydrants
# and docks, Metro Transit's stops, and the rest from OpenStreetMap.
furniture = []
OSM_FURN = {'bench': 1, 'bin': 2, 'mailbox': 6, 'pole': 7, 'bikerack': 8}
for la, lo in HYDRANTS:
    furniture.append([0, *m(la, lo), 0.7])
for la, lo, _ in NICERIDE:
    furniture.append([5, *m(la, lo), 1.2])
shelters = Grid(30)
for p in POINTS:
    x, z = m(p['lat'], p['lon'])
    t = p.get('tags', {})
    if p['kind'] in OSM_FURN:
        furniture.append([OSM_FURN[p['kind']], x, z, 0.6])
    elif (p['kind'] == 'shelter' and t.get('shelter_type') == 'public_transport') or (p['kind'] == 'stop' and t.get('shelter') == 'yes'):
        shelters.add([x, z, False], x, z, x, z)
for la, lo, kind, name in STOPS:
    x, z = m(la, lo)
    if kind == 'rail':
        furniture.append([9, x, z, -1])
        continue
    sh = min(shelters.near(x, z, 20), key=lambda q: math.hypot(q[0] - x, q[1] - z), default=None)
    if sh and math.hypot(sh[0] - x, sh[1] - z) < 20 and not sh[2]:
        sh[2] = True
        furniture.append([4, sh[0], sh[1], 2.2])
    furniture.append([3, x, z, 0.5])
for sh in [q for c in shelters.cells.values() for q in c]:
    if not sh[2]:
        sh[2] = True
        furniture.append([4, sh[0], sh[1], 2.2])
# Off the street (gap: how far past its edge), facing it; the platform canopies run along the track instead
rail_lines = [[m(p['lat'], p['lon']) for p in e['geometry']] for e in load('rail') if e.get('tags', {}).get('railway') == 'light_rail']
placed = []
for kind, x, z, gap in furniture:
    if not in_map(x, z):
        continue
    if kind == 9:
        best = None
        for ln in rail_lines:
            for a, b in zip(ln, ln[1:]):
                d = seg_dist(x, z, a[0], a[1], b[0], b[1])[0]
                if d < 30 and (best is None or d < best[0]):
                    best = (d, math.atan2(b[1] - a[1], b[0] - a[0]))
        if best:
            placed.append((9, x, z, best[1]))
        continue
    x, z, ang = off_the_street(x, z, gap)
    if kind == 7 and ang is None:
        continue
    placed.append((kind, x, z, ang if ang is not None else 0))
furniture = placed
print('street furniture', {k: sum(1 for f in furniture if f[0] == k) for k in range(10)}, flush=True)

# Bridges: every road and path OpenStreetMap marks as a bridge gets a deck along its line. Bridge
# ways that run on from one another are chained, so each chain starts and ends on the ground, and
# the deck runs evenly between those two heights (and never below the ground, nor close over water).
def pkey(p):
    return (round(p[0], 2), round(p[1], 2))


bways = [(pts, WIDTH[hw] + 3) for _, hw, pts, t, _ in roads if hw not in ('pedestrian', 'living_street') and is_bridge(t)]
bways += [(pts, w + 1.4) for pts, w, t in paths if is_bridge(t)]
# The light rail's viaducts (the Blue Line over Lake Street and the railway), so its trains run up on them
bways += [([m(p['lat'], p['lon']) for p in e['geometry']], 9) for e in load('rail')
          if e.get('tags', {}).get('railway') == 'light_rail' and is_bridge(e.get('tags', {})) and e.get('geometry')]
ends = {}
for n, (pts, _) in enumerate(bways):
    for p in (pts[0], pts[-1]):
        ends.setdefault(pkey(p), []).append(n)
seen, bridges, chains = set(), [], []


def grow(cp, cw):
    while True:
        key = pkey(cp[-1])
        nxt = [o for o in ends.get(key, ()) if o not in seen]
        if len(ends.get(key, ())) != 2 or not nxt:
            return
        o = nxt[0]
        seen.add(o)
        p = bways[o][0] if pkey(bways[o][0][0]) == key else bways[o][0][::-1]
        cp += p[1:]
        cw += [bways[o][1]] * (len(p) - 1)


for n, (pts, w) in enumerate(bways):
    if n in seen:
        continue
    seen.add(n)
    cp, cw = list(pts), [w] * (len(pts) - 1)
    grow(cp, cw)
    cp.reverse(); cw.reverse()
    grow(cp, cw)
    cum = [0]
    for a, b in zip(cp, cp[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    if cum[-1] < 8:
        continue
    # Points every 8 m or so, each at the height the survey measured the deck there (gaps filled in
    # between, smoothed a little); where it saw no deck, evenly from one end's ground to the other's.
    dp, dw = [cp[0]], []
    for (a, b), w in zip(zip(cp, cp[1:]), cw):
        k = max(1, math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / 8))
        for q in range(1, k + 1):
            dp.append((a[0] + (b[0] - a[0]) * q / k, a[1] + (b[1] - a[1]) * q / k))
            dw.append(w)
    cp, cw = dp, dw
    cum = [0]
    for a, b in zip(cp, cp[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    seen_deck = np.array([deck_at(*p) for p in cp])
    ok = np.isfinite(seen_deck)
    unclassified = False
    if ok.sum() < 2 and DECK1 is not None:
        # None classed deck here: the decks the survey left unclassified (see fetch_ground.py). Trees
        # over a footbridge can pass for one, so a reading counts only up to 11 m over the ground, and
        # only as high over a nearer end on the ground (not one where other bridges meet it) as a ramp
        # could climb from there, and they're used only where most of the bridge has them (a deck is
        # one long sheet; trees come in clumps). Odd ones out (a truck under the deck, the bracing
        # over it) are put right by their neighbours. The readings stop near the ground, so the ramps
        # run down from the last of them to the ground at those ends.
        foot = [(0, ground(*cp[0])) if len(ends.get(pkey(cp[0]), ())) == 1 else None,
                (cum[-1], ground(*cp[-1])) if len(ends.get(pkey(cp[-1]), ())) == 1 else None]
        seen_deck = np.array([deck_at(*p, deck=DECK1) for p in cp])
        for k, p in enumerate(cp):
            if not (seen_deck[k] - ground(*p) <= 11
                    and all(abs(seen_deck[k] - h) <= 2 + 0.12 * abs(cum[k] - c) for c, h in filter(None, foot))):
                seen_deck[k] = np.nan
        if np.isfinite(seen_deck).mean() < 0.6:
            seen_deck[:] = np.nan
        pad = np.pad(seen_deck, 1, mode='edge')
        with np.errstate(all='ignore'):
            seen_deck = np.where(np.isfinite(seen_deck), np.nanmedian(np.c_[pad[:-2], pad[1:-1], pad[2:]], axis=1), np.nan)
        if np.isfinite(seen_deck).sum() >= 2:
            for e, f in ((0, foot[0]), (-1, foot[1])):
                if f and not np.isfinite(seen_deck[e]):
                    seen_deck[e] = f[1]
        ok = np.isfinite(seen_deck)
        unclassified = ok.sum() >= 2
    if ok.sum() >= 2:
        hs = np.interp(cum, np.array(cum)[ok], seen_deck[ok])
        hs = np.convolve(np.pad(hs, 1, mode='edge'), [0.25, 0.5, 0.25], mode='valid')
    else:
        ha, hb = ground(*cp[0]), ground(*cp[-1])
        hs = [ha + (hb - ha) * c / cum[-1] for c in cum]
        for n_, p in enumerate(cp):
            i, j = cell(*p)
            if 0 <= i < GH and 0 <= j < GW and wet[i, j]:
                hs[n_] = max(hs[n_], ground(*p) + 3)
    hs = [max(h, ground(*p)) for h, p in zip(hs, cp)]
    chains.append((cp, cw, hs, unclassified))

# Build the land up to meet each bridge's ends, as the real approaches are: the survey's ground runs
# down into the river or freeway the bridge crosses for a little way past its ends.
APPROACH = 40


def raise_ground(x, z, h, r):
    i0, i1 = int((x - r - X0) // GSTEP), int((x + r - X0) // GSTEP) + 1
    j0, j1 = int((z - r - Z0) // GSTEP), int((z + r - Z0) // GSTEP) + 1
    for j in range(max(0, j0), min(GNZ, j1 + 1)):
        for i in range(max(0, i0), min(GNX, i1 + 1)):
            if math.hypot(X0 + i * GSTEP - x, Z0 + j * GSTEP - z) <= r:
                ci, cj = cell(X0 + i * GSTEP, Z0 + j * GSTEP)
                if not (0 <= ci < GH and 0 <= cj < GW and grid[ci, cj] == CLS['water']):
                    GROUND[j, i] = max(GROUND[j, i], round(h, 2))


for cp, cw, hs, unclassified in chains:
    for (e, prev, h_end, w) in ((cp[0], cp[1], hs[0], cw[0]), (cp[-1], cp[-2], hs[-1], cw[-1])):
        L = math.hypot(e[0] - prev[0], e[1] - prev[1]) or 1
        ox, oz = (e[0] - prev[0]) / L, (e[1] - prev[1]) / L
        far = ground(e[0] + ox * APPROACH, e[1] + oz * APPROACH)
        if h_end - ground(*e) > 6 or (unclassified and len(ends.get(pkey(e), ())) > 1):
            continue                              # no approach on the ground here (or it runs on as another bridge): leave it be
        for t in range(0, APPROACH + 1, 4):
            k = t / APPROACH
            raise_ground(e[0] + ox * t, e[1] + oz * t, h_end + (far - h_end) * k * k * (3 - 2 * k), w / 2 + 2)
# Piers about every 30 m where the deck is well up, never in the street or path the bridge crosses, nor under a bridge
# modelled whole as a hero (HERO_BRIDGES: its own piers and arches are in heroes/).
HERO_BRIDGES = {23115958}            # the Stone Arch Bridge (heroes/model_stone_arch.py)
hero_bridge_segs = [seg for pts, w, t in paths if t.get('_id') in HERO_BRIDGES for seg in zip(pts, pts[1:])]


def under_hero_bridge(x, z):
    for (ax, az), (bx, bz) in hero_bridge_segs:
        ex, ez = bx - ax, bz - az
        L2 = ex * ex + ez * ez or 1e-9
        t = max(0, min(1, ((x - ax) * ex + (z - az) * ez) / L2))
        if math.hypot(x - ax - ex * t, z - az - ez * t) < 6:
            return True
    return False


for cp, cw, hs, _ in chains:
    cum = [0]
    for a, b in zip(cp, cp[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    next_pier = 30
    for k in range(len(cp) - 1):
        pier = 0
        if next_pier <= cum[k] < cum[-1] - 8 and hs[k] - ground(*cp[k]) > 2.5 and not on_pavement(*cp[k], 1.5) \
                and not under_hero_bridge(*cp[k]):
            pier, next_pier = 1, cum[k] + 30
        if math.hypot(cp[k + 1][0] - cp[k][0], cp[k + 1][1] - cp[k][1]) > 0.5:
            bridges.append((cp[k][0], cp[k][1], cp[k + 1][0], cp[k + 1][1], cw[k], hs[k] * 10, hs[k + 1] * 10, pier))

# Footpaths in 3D near the car too, left out over water and where they're bridges.
for pts, w, t in paths:
    if is_bridge(t):
        continue
    run = [pts[0]]
    for p, q in zip(pts, pts[1:]):
        i, j = cell((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        if 0 <= i < GH and 0 <= j < GW and wet[i, j]:
            if len(run) >= 2:
                street_pieces.append((len(order), w, 0, 0, 0, 0, run, 0, 0))
            run = [q]
        else:
            run.append(q)
    if len(run) >= 2:
        street_pieces.append((len(order), w, 0, 0, 0, 0, run, 0, 0))

# Car routes: every main street on the map, as polylines cars can drive along.
routes = []
for _, hw, pts, t, _ in roads:
    if hw not in ('primary', 'secondary', 'tertiary', 'trunk', 'motorway'):
        continue
    near = [p for p in pts if in_map(*p)]
    if len(near) >= 2 and sum(math.hypot(near[i + 1][0] - near[i][0], near[i + 1][1] - near[i][1]) for i in range(len(near) - 1)) > 120:
        routes.append((WIDTH[hw], 1 if t.get('oneway') == 'yes' or hw == 'motorway' else 0, near))
print('bridges', len(bridges), 'routes', len(routes), flush=True)

# ------------------------------------------------------------ roof colours
# Every roof takes its colour from the aerial photo (fetch_city.py), tile by tile. The colours are gathered into a
# palette of ROOF_N (k-means), which the houses, garages and flat roofs index. Without the photo, houses and garages
# keep their made-up roofs and flat roofs the game's greys.
ROOF_N = 64


def rect_ring(cx, cz, ang, w, d):
    c, s_ = math.cos(ang), math.sin(ang)
    return [(cx + u * c - v * s_, cz + u * s_ + v * c) for u, v in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]


jobs = [(h[0], h[1], 'h', k, h[12]) for k, h in enumerate(houses)] \
    + [(g[0], g[1], 'g', k, rect_ring(*g[:5])) for k, g in enumerate(boxes)] \
    + [(s['cx'], s['cz'], 'b', k, s['r']) for k, s in enumerate(solids) if s['h0'] == 0]
jobs.sort(key=lambda j: (int((j[0] - X0) // TILE), int((j[1] - Z0) // TILE)))
seen_roofs = {}
for x, z, kind, k, ring in jobs:
    c = roof_photo(ring, 0.5 if kind == 'g' else 0.8)
    if c is not None:
        seen_roofs[(kind, k)] = c
AERIAL.clear()
roof_pal = []
if len(seen_roofs) > ROOF_N * 4:
    cols = np.array(list(seen_roofs.values()), np.float32)
    rng = np.random.default_rng(5)
    cent = cols[rng.choice(len(cols), ROOF_N, replace=False)]
    for _ in range(12):
        lab = np.argmin(((cols[:, None, :] - cent[None]) ** 2).sum(-1), 1) if len(cols) < 200000 else \
            np.concatenate([np.argmin(((cols[q:q + 50000, None, :] - cent[None]) ** 2).sum(-1), 1) for q in range(0, len(cols), 50000)])
        for n in range(ROOF_N):
            if (lab == n).any():
                cent[n] = cols[lab == n].mean(0)
    lab = np.concatenate([np.argmin(((cols[q:q + 50000, None, :] - cent[None]) ** 2).sum(-1), 1) for q in range(0, len(cols), 50000)])
    roof_pal = ['#%02x%02x%02x' % tuple(int(round(v)) for v in c) for c in cent]
    for (kind, k), n in zip(seen_roofs.keys(), lab):
        n = int(n)
        if kind == 'h':
            houses[k][10] = n
        elif kind == 'g':
            boxes[k][6] |= (n + 1) << 8          # wall colour in the low byte, 1 + the roof's above it
        else:
            solids[k]['flags'] |= (n + 1) << 2   # 1 + the flat roof's colour, above the storefront and parapet bits
print('roofs from the aerial photo', len(seen_roofs), 'of', len(jobs), flush=True)
if roof_pal:
    HOUSE_ROOF = roof_pal                     # the houses index the photo's palette now

# ------------------------------------------------------------------ write
os.makedirs(os.path.join(OUT, 't'), exist_ok=True)
for old in glob.glob(os.path.join(OUT, 't', '*')):
    os.remove(old)


def mi(v):
    return int(round(v))


def tile_of(x, z):
    return int((x - X0) // TILE), int((z - Z0) // TILE)


walls = sorted({s['tint'] for s in solids})
widx = {c: i for i, c in enumerate(walls)}
data = {}


def tile_data(x, z):
    return data.setdefault(tile_of(x, z), dict(b=[], h=[], g=[], t=[], f=[], s=[], sn=[], rd=[], jn=[], cw=[], hx=[], lp=[], sg=[], fu=[]))


# Hero buildings (hero_house.py): modelled in detail, in place of whatever ordinary building, house,
# garage or tree stood inside their outline.
heroes = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(HERE, 'heroes', '*.json')))]


def in_hero(x, z, clear=False):
    for hero in heroes:
        for ring in hero['rings'] + (hero.get('clear', []) if clear else []):
            inside = False
            for (ax, az), (bx_, bz_) in zip(ring, ring[1:] + ring[:1]):
                if (az > z) != (bz_ > z) and x < ax + (z - az) * (bx_ - ax) / (bz_ - az):
                    inside = not inside
            if inside:
                return True
    return False


if heroes:
    n0 = len(solids) + len(houses) + len(boxes) + len(trees)
    solids = [s for s in solids if not in_hero(s['cx'], s['cz'])]
    houses = [h for h in houses if not in_hero(h[0], h[1], True)]
    boxes = [b for b in boxes if not in_hero(b[0], b[1], True)]
    trees = [t for t in trees if not in_hero(t[0], t[1], True)]
    lamps = [q for q in lamps if not in_hero(q[0], q[1])]
    furniture = [q for q in furniture if not in_hero(q[1], q[2])]
    for hero in heroes:
        tile_data(hero['x'], hero['z'])['hx'].append({k: v for k, v in hero.items() if k not in ('name', 'clear')})
    print('hero buildings', [h['name'] for h in heroes], 'replaced', n0 - len(solids) - len(houses) - len(boxes) - len(trees), flush=True)

for s in solids:
    rec = [s['fac'], widx[s['tint']], mi(s['h'] * 10), mi(s['h0'] * 10), s['flags'], 1 + len(s['holes'])]
    for ring in [s['r']] + s['holes']:
        rec += [len(ring)] + [mi(v) for p in ring for v in p]
    tile_data(s['cx'], s['cz'])['b'].append(rec)
for x, z, ang, w, d, eave, ridge, roof, front, wc, rc, flags, _, _ in houses:
    tile_data(x, z)['h'] += [mi(x * 10), mi(z * 10), mi(ang * 100), mi(w * 10), mi(d * 10), mi(eave * 10), mi(ridge * 10),
                             roof, front, wc, rc, flags]
for x, z, ang, w, d, h, c, _, door in boxes:
    tile_data(x, z)['g'] += [mi(x * 10), mi(z * 10), mi(ang * 100), mi(w * 10), mi(d * 10), mi(h * 10), c, door]
for x, z, ht, rad in trees:
    tile_data(x, z)['t'] += [mi(x * 10), mi(z * 10), mi(ht * 10), mi(rad * 10)]
for kind, pts in fences:
    # A fence goes in the tile its middle is in; long ones are split so each piece stays near its tile.
    for k in range(0, len(pts) - 1, 12):
        part = pts[k:k + 13]
        mx, mz = part[len(part) // 2]
        if in_map(mx, mz):
            tile_data(mx, mz)['f'].append([kind, len(part)] + [mi(v) for p in part for v in p])
for x, z, a1, n1, a2, n2 in signs:
    td = tile_data(x, z)
    for n in (n1, n2):
        if n not in td['sn']:
            td['sn'].append(n)
    td['s'] += [mi(x * 10), mi(z * 10), mi(a1 * 100), td['sn'].index(n1), mi(a2 * 100), td['sn'].index(n2)]

for cls, w, lanes, oneway, t0, t1, run, sf, bk in street_pieces:
    mx, mz = run[len(run) // 2]
    if in_map(mx, mz):
        tile_data(mx, mz)['rd'].append([cls, mi(w * 10), lanes, oneway, mi(t0 * 10), mi(t1 * 10), len(run)] + [mi(v * 10) for p in run for v in p]
                                       + [sf, bk])
for x, z, ang, style in lamps:
    tile_data(x, z)['lp'] += [mi(x * 10), mi(z * 10), mi(ang * 100), style]
for x, z in signals:
    if in_map(x, z):
        tile_data(x, z)['sg'] += [mi(x * 10), mi(z * 10)]
for kind, x, z, ang in furniture:
    tile_data(x, z)['fu'] += [kind, mi(x * 10), mi(z * 10), mi(ang * 100)]
for x, z, r in junction_pads:
    if in_map(x, z):
        tile_data(x, z)['jn'] += [mi(x * 10), mi(z * 10), mi(r * 10)]
for x, z, a, w in crosswalks:
    if in_map(x, z):
        tile_data(x, z)['cw'] += [mi(x * 10), mi(z * 10), mi(a * 100), mi(w * 10)]

# Bucket the drawing ops (and canopy shade) into the tiles they touch, keeping paint order.
buckets, shade_b = {}, {}
for op in ops:
    bx0, bz0, bx1, bz1 = op[4]
    for i in range(max(0, int((bx0 - X0) // TILE)), min(NI - 1, int((bx1 - X0) // TILE)) + 1):
        for j in range(max(0, int((bz0 - Z0) // TILE)), min(NJ - 1, int((bz1 - Z0) // TILE)) + 1):
            buckets.setdefault((i, j), []).append(op)
for x, z, rad in shade_dots:
    for i in range(max(0, int((x - rad - X0) // TILE)), min(NI - 1, int((x + rad - X0) // TILE)) + 1):
        for j in range(max(0, int((z - rad - Z0) // TILE)), min(NJ - 1, int((z + rad - Z0) // TILE)) + 1):
            shade_b.setdefault((i, j), []).append((x, z, rad))

OV = 192                                   # overview pixels per km
overview = Image.new('RGB', (NI * OV, NJ * OV), C['land'])
fill = {k: ImageColor.getrgb(v) for k, v in C.items()}
for j in range(NJ):
    for i in range(NI):
        tx0, tz0 = X0 + i * TILE, Z0 + j * TILE
        to_px = lambda x, z: ((x - tx0) * PPM, (z - tz0) * PPM)
        bucket = buckets.get((i, j), [])
        img = Image.new('RGB', (TS, TS), C['land'])
        replay(ImageDraw.Draw(img), to_px, PPM, bucket, fill.get)
        # Baked ambient occlusion: a soft darkening around every footprint, and shade under canopies.
        foot = Image.new('L', (TS, TS), 0)
        replay(ImageDraw.Draw(foot), to_px, PPM, [o for o in bucket if o[0] in ('roof', 'bldg')], lambda k: 255)
        shade = Image.new('L', (TS, TS), 0)
        sd = ImageDraw.Draw(shade)
        for x, z, rad in shade_b.get((i, j), ()):
            X, Z = to_px(x, z)
            sd.ellipse([X - rad * PPM, Z - rad * PPM, X + rad * PPM, Z + rad * PPM], fill=255)
        f = np.asarray(foot).astype(np.float32) / 255
        ao = np.asarray(foot.filter(ImageFilter.GaussianBlur(3.2 * PPM))).astype(np.float32) / 255
        sh = np.asarray(shade.filter(ImageFilter.GaussianBlur(1.5 * PPM))).astype(np.float32) / 255
        dark = 1 - (0.42 * ao * (1 - f) + 0.24 * sh * (1 - f))
        img = Image.fromarray((np.asarray(img).astype(np.float32) * dark[..., None]).astype(np.uint8))
        name = os.path.join(OUT, 't', f'{i}_{j}')
        img.resize((1024, 1024), Image.LANCZOS).save(name + '.jpg', quality=84, optimize=True, progressive=True)
        img.resize((512, 512), Image.LANCZOS).save(name + '-s.jpg', quality=84, optimize=True, progressive=True)
        overview.paste(img.resize((OV, OV), Image.LANCZOS), (i * OV, j * OV))
        json.dump(data.get((i, j), dict(b=[], h=[], g=[], t=[], f=[], s=[], sn=[], rd=[], jn=[], cw=[], hx=[], lp=[], sg=[], fu=[])), open(name + '.json', 'w'), separators=(',', ':'))
    print('row', j, flush=True)
overview.save(os.path.join(OUT, 'overview.jpg'), quality=84, optimize=True, progressive=True)

index = dict(
    note='OpenStreetMap contributors (ODbL); USGS 3DEP LiDAR; City of Minneapolis, Hennepin County, Metro Transit. Metres from 44.966N 93.259W; x east, z south.',
    bounds=[X0, X1, Z0, Z1], tile=TILE, ni=NI, nj=NJ,
    walls=walls, houseWall=HOUSE_WALLS, houseRoof=HOUSE_ROOF, boxWall=BOX_WALL, roofs=roof_pal,
    br=[mi(v) for b in bridges for v in b],
    gr=dict(step=GSTEP, nx=GNX, nz=GNZ, e0=round(E0, 2)),
    r=[[mi(w), ow] + [mi(v) for p in pts for v in p] for w, ow, pts in routes],
)
json.dump(index, open(os.path.join(OUT, 'index.json'), 'w'), separators=(',', ':'))

cm = np.round(GROUND * 100).astype(np.int32)
delta = np.concatenate([cm[:, :1], np.diff(cm, axis=1)], axis=1)
assert np.abs(delta).max() < 32768
with gzip.open(os.path.join(OUT, 'ground.bin'), 'wb', 9) as f:
    f.write(delta.astype('<i2').tobytes())
print('ground', GNX, 'x', GNZ, 'e0', round(E0, 2), 'from', float(GROUND.min()), 'to', float(GROUND.max()), flush=True)

import bake_search                        # the address and place search
bake_search.bake(OUT)
print('done')
