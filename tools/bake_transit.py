"""Bake Metro Transit's schedule for Mpls Drive's trains and buses.

    .venv/bin/python bake_transit.py            # after fetch_city.py, before bake_tiles.py

Reads osm-cache/city/gtfs.zip (Metro Transit's GTFS) and writes:
  public/mpls-drive/data/transit.json
    rail    the light rail lines through the map: [{name, color, shapes: [[x*10, z*10, ...]], patterns, trips}]
            shapes  each way the trains run, as track centrelines in game metres (x east, z south), cut to the map
                    and a little beyond
            patterns [[shape, n, along*10 ..., arrive ..., depart ...]]: the stops a train calls at, as metres along
                    its shape, and its times there as seconds after it leaves the first of them
            trips   {wk, sa, su}: [pattern, seconds after midnight it sets off, ...] for a weekday, a Saturday and a
                    Sunday of the schedule (local time; past midnight runs on past 86400)
    bus     the bus routes through the map: [{name, color, n, shape: [x*10, z*10, ...]}] (n: trips on a weekday;
            shape the longest of the route's variants through the map, for the traffic to keep its buses to)
  osm-cache/city/stops.json  [[lat, lon, kind, name]] every stop in the map, kind 'bus' or 'rail', for bake_tiles.py
                             to stand bus stop signs and platform shelters at.

Schedule data: Metro Transit (metrotransit.org), public GTFS.
"""
import csv, datetime, io, json, math, os, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import X0, X1, Z0, Z1
from footprints import m

CACHE = os.path.join(HERE, 'osm-cache', 'city')
OUT = os.path.join(HERE, '..', '..', 'public', 'mpls-drive', 'data', 'transit.json')
MARGIN = 600            # metres of track kept beyond the map, so trains come in from off it
RAIL_ROUTES = {'901', '902'}     # METRO Blue and Green Lines (906 is the airport's shuttle, off the map)

z = zipfile.ZipFile(os.path.join(CACHE, 'gtfs.zip'))


def rows(name):
    return csv.DictReader(io.TextIOWrapper(z.open(name), 'utf-8-sig'))


def near_map(x, zz, margin=MARGIN):
    return X0 - margin <= x <= X1 + margin and Z0 - margin <= zz <= Z1 + margin


def secs(t):
    h, mi, s = t.split(':')
    return int(h) * 3600 + int(mi) * 60 + int(s)


# ----------------------------------------------------------- service days
cal = list(rows('calendar.txt'))
exc = {}
for r in rows('calendar_dates.txt'):
    exc.setdefault(r['date'], {})[r['service_id']] = r['exception_type']
DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def services_on(d):
    key = d.strftime('%Y%m%d')
    on = {r['service_id'] for r in cal if r['start_date'] <= key <= r['end_date'] and r[DAYS[d.weekday()]] == '1'}
    for sid, kind in exc.get(key, {}).items():
        (on.add if kind == '1' else on.discard)(sid)
    return on


# A Wednesday, a Saturday and a Sunday early in the schedule, with no holiday about (the most services running)
start = datetime.datetime.strptime(min(r['start_date'] for r in cal), '%Y%m%d').date()
day_of = {}
for want, k in ((2, 'wk'), (5, 'sa'), (6, 'su')):
    cands = [start + datetime.timedelta(days=d) for d in range(7, 50) if (start + datetime.timedelta(days=d)).weekday() == want]
    day_of[k] = max(cands, key=lambda d: len(services_on(d)))
svc = {k: services_on(d) for k, d in day_of.items()}
print('days', {k: str(d) for k, d in day_of.items()}, flush=True)

# ---------------------------------------------------------------- routes
routes = {r['route_id']: r for r in rows('routes.txt')}
trips = {}
for r in rows('trips.txt'):
    trips[r['trip_id']] = r

shapes = {}
for r in rows('shapes.txt'):
    shapes.setdefault(r['shape_id'], []).append((int(r['shape_pt_sequence']), float(r['shape_pt_lat']), float(r['shape_pt_lon']),
                                                 float(r['shape_dist_traveled'] or 0)))
for k in shapes:
    shapes[k].sort()
print('shapes', len(shapes), flush=True)


def shape_xz(sid):
    """The shape in game metres, with each point's distance along it."""
    out = []
    for _, la, lo, d in shapes[sid]:
        x, zz = m(la, lo)
        out.append((x, zz, d))
    return out


def clip(pts):
    """The longest run of the shape near the map: [(x, z, dist)]."""
    best, run = [], []
    for p in pts:
        if near_map(p[0], p[1]):
            run.append(p)
        else:
            if len(run) > len(best):
                best = run
            run = []
    return run if len(run) > len(best) else best


def simplify(pts, tol):
    """Douglas-Peucker on [(x, z, ...)]."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, az, bx, bz = pts[a][0], pts[a][1], pts[b][0], pts[b][1]
        L = math.hypot(bx - ax, bz - az) or 1e-9
        worst, wi = 0, -1
        for i in range(a + 1, b):
            d = abs((bx - ax) * (az - pts[i][1]) - (ax - pts[i][0]) * (bz - az)) / L
            if d > worst:
                worst, wi = d, i
        if worst > tol:
            keep[wi] = True
            stack += [(a, wi), (wi, b)]
    return [p for p, k in zip(pts, keep) if k]


# ------------------------------------------------------------ stop times
stops = {r['stop_id']: r for r in rows('stops.txt')}
rail_trips = {tid for tid, t in trips.items() if t['route_id'] in RAIL_ROUTES}
calls = {}                  # rail trip -> [(seq, dist, arrive, depart)]
stop_routes = {}            # stop -> 'rail' / 'bus'
bus_count = {}              # route -> trips on the weekday that touch the map
wk_trips = {tid for tid, t in trips.items() if t['service_id'] in svc['wk']}
for r in rows('stop_times.txt'):
    tid = r['trip_id']
    t = trips.get(tid)
    if not t:
        continue
    rail = tid in rail_trips
    stop_routes.setdefault(r['stop_id'], set()).add('rail' if rail else 'bus')
    if rail:
        calls.setdefault(tid, []).append((int(r['stop_sequence']), float(r['shape_dist_traveled'] or 0), secs(r['arrival_time']),
                                          secs(r['departure_time'])))
print('rail trips', len(calls), flush=True)

# ------------------------------------------------------------- the trains
rail_out = []
for rid in sorted(RAIL_ROUTES):
    R = routes[rid]
    shape_ids = sorted({trips[t]['shape_id'] for t in calls if trips[t]['route_id'] == rid})
    shape_idx, shape_pts, shape_off = {}, [], []
    for sid in shape_ids:
        c = clip(shape_xz(sid))
        if len(c) < 2:
            continue
        shape_idx[sid] = len(shape_pts)
        # Keep each point's own distance along the whole shape, so the stops' distances still fit it
        c = simplify(c, 0.4)
        shape_pts.append(c)
        shape_off.append(c[0][2])
    pattern_idx, patterns = {}, []
    out_trips = {k: [] for k in svc}
    for tid, cs in calls.items():
        t = trips[tid]
        if t['route_id'] != rid or t['shape_id'] not in shape_idx:
            continue
        si = shape_idx[t['shape_id']]
        lo, hi = shape_pts[si][0][2], shape_pts[si][-1][2]
        cs.sort()
        inside = [c for c in cs if lo - 50 <= c[1] <= hi + 50]
        if len(inside) < 2:
            continue
        # One stop either side of the run through the map, so trains run on in and out of it
        a = max(0, cs.index(inside[0]) - 1)
        b = min(len(cs), cs.index(inside[-1]) + 2)
        cs = cs[a:b]
        t0 = cs[0][3]
        key = (si, tuple((round(c[1] - lo, 1), c[2] - t0, c[3] - t0) for c in cs))
        if key not in pattern_idx:
            pattern_idx[key] = len(patterns)
            patterns.append([si, len(cs)] + [round((c[1] - lo) * 10) for c in cs] + [c[2] - t0 for c in cs] + [c[3] - t0 for c in cs])
        for k, on in svc.items():
            if t['service_id'] in on:
                out_trips[k] += [pattern_idx[key], t0]
    rail_out.append(dict(name=R['route_long_name'], color='#' + R['route_color'], patterns=patterns, trips=out_trips,
                         shapes=[[round(v * 10) for p in s for v in (p[0], p[1])] for s in shape_pts],
                         along=[[round((p[2] - s[0][2]) * 10) for p in s] for s in shape_pts]))
    print(R['route_long_name'], 'shapes', len(shape_pts), 'patterns', len(patterns), {k: len(v) // 2 for k, v in out_trips.items()}, flush=True)

# --------------------------------------------------------------- the buses
bus_out = []
by_route = {}
for tid, t in trips.items():
    R = routes.get(t['route_id'])
    if not R or R['route_type'] != '3':
        continue
    by_route.setdefault(t['route_id'], {}).setdefault(t['shape_id'], 0)
    if tid in wk_trips:
        by_route[t['route_id']][t['shape_id']] += 1
for rid, shp in sorted(by_route.items()):
    best, n = None, 0
    for sid, cnt in shp.items():
        if sid not in shapes:
            continue
        pts = [(x, zz) for x, zz, _ in shape_xz(sid)]
        inside = [p for p in pts if near_map(*p, 0)]
        if len(inside) < 2:
            continue
        n += cnt
        L = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(inside, inside[1:]))
        if best is None or L > best[0]:
            best = (L, pts)
    if not best or n == 0 or best[0] < 300:
        continue
    R = routes[rid]
    run = simplify([p for p in best[1] if near_map(*p, 200)], 2.0)
    bus_out.append(dict(name=R['route_short_name'] or R['route_long_name'], color='#' + (R['route_color'] or '0053a0'), n=n,
                        shape=[round(v * 10) for p in run for v in p]))
print('bus routes', len(bus_out), flush=True)

json.dump(dict(note='Metro Transit GTFS (metrotransit.org). Made by tools/mpls-drive/bake_transit.py.',
               days={k: str(d) for k, d in day_of.items()}, rail=rail_out, bus=bus_out),
          open(OUT, 'w'), separators=(',', ':'))
print('transit.json', round(os.path.getsize(OUT) / 1e6, 2), 'MB')

# Every stop on the map, for bake_tiles.py
out = []
for sid, kinds in stop_routes.items():
    s = stops.get(sid)
    if not s or s.get('location_type', '0') not in ('', '0'):
        continue
    la, lo = float(s['stop_lat']), float(s['stop_lon'])
    if near_map(*m(la, lo), 0):
        out.append([la, lo, 'rail' if 'rail' in kinds else 'bus', s['stop_name']])
json.dump(out, open(os.path.join(CACHE, 'stops.json'), 'w'))
print('stops', len(out))
