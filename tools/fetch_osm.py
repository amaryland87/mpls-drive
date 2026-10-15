"""Get the OpenStreetMap data that bake_tiles.py turns into Mpls Drive's city.

    python3 -m venv .venv && .venv/bin/pip install osmium numpy pillow   # once
    .venv/bin/python fetch_osm.py

Downloads Geofabrik's daily Minnesota extract into osm-cache/ (about 290 MB,
skipped if already there), then pulls out everything inside the map (see
area.py) into small JSON files shaped like Overpass API `out geom;` results:
roads_all, paths (footways, cycleways and trails), water, green, rail, bld_all, barriers (fences, walls,
hedges), paved (surface parking lots), plus names.json with the centres of a
few named places used as landmarks, and search.json with every street address
and named place, for the address search. Delete osm-cache/ to start fresh.

Map data (c) OpenStreetMap contributors, ODbL.
"""
import json, os, subprocess, sys

import osmium

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY, X0, X1, Z0, Z1

CACHE = os.path.join(HERE, 'osm-cache')
PBF = os.path.join(CACHE, 'minnesota-latest.osm.pbf')
URL = 'https://download.geofabrik.de/north-america/us/minnesota-latest.osm.pbf'
MARGIN = 300   # metres of data beyond the map so roads and parks run off the edge cleanly
S, N = LAT0 - (Z1 + MARGIN) / MY, LAT0 - (Z0 - MARGIN) / MY
W, E = LON0 + (X0 - MARGIN) / MX, LON0 + (X1 + MARGIN) / MX

HW = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'residential', 'unclassified', 'living_street',
      'pedestrian', 'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link'}
PATHS = {'footway', 'cycleway', 'path', 'bridleway'}
LEISURE = {'park', 'golf_course', 'pitch', 'nature_reserve', 'garden'}
LANDUSE = {'grass', 'cemetery', 'recreation_ground', 'forest', 'meadow', 'village_green'}
NAMES = {'Bde Maka Ska', 'Lake Harriet', 'Lake Harriet Bandshell', 'Lakewood Cemetery', 'Minnehaha Falls',
         'Minnehaha Regional Park', 'Lake of the Isles', 'The Mall', 'Uptown Theater', 'Calhoun Square',
         'Rose Garden', 'Lyndale Park Rose Garden', 'Lake Harriet Park', 'Bde Maka Ska Park'}
# Named things worth searching for by name (not streets: those come from the roads).
PLACE_KEYS = ('amenity', 'shop', 'tourism', 'leisure', 'historic', 'building', 'office', 'sport', 'craft',
              'healthcare', 'public_transport', 'natural', 'landuse', 'waterway')
NEIGHBOURHOODS = {'neighbourhood', 'suburb', 'quarter'}


def pts(nodes):
    out = []
    for n in nodes:
        if n.location.valid():
            out.append({'lat': round(n.lat, 7), 'lon': round(n.lon, 7)})
    return out


def touches(geom):
    return any(S <= p['lat'] <= N and W <= p['lon'] <= E for p in geom)


class Cut(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.out = {k: [] for k in ('roads_all', 'paths', 'water', 'green', 'rail', 'bld_all', 'barriers', 'paved')}
        self.names = {}
        self.places = []

    def way(self, w):
        t = w.tags
        hw, rail, ww = t.get('highway'), t.get('railway'), t.get('waterway')
        bucket = ('roads_all' if hw in HW else 'paths' if hw in PATHS else 'rail' if rail == 'rail' else 'water' if ww == 'river'
                  else 'barriers' if t.get('barrier') in ('fence', 'wall', 'hedge', 'retaining_wall') else None)
        if not bucket:
            return
        g = pts(w.nodes)
        if len(g) >= 2 and touches(g):
            self.out[bucket].append({'type': 'way', 'id': w.id, 'tags': dict(t), 'geometry': g})

    def area(self, a):
        t = a.tags
        if 'building' in t or 'building:part' in t:
            bucket = 'bld_all'
        elif t.get('natural') == 'water' or t.get('waterway') == 'riverbank':
            bucket = 'water'
        elif t.get('amenity') == 'parking' and t.get('parking') not in ('underground', 'multi-storey', 'rooftop'):
            bucket = 'paved'
        elif t.get('leisure') in LEISURE or t.get('landuse') in LANDUSE or t.get('natural') == 'wood':
            bucket = 'green'
        else:
            bucket = None
        name = t.get('name')
        searchable = name and 'highway' not in t and any(k in t for k in PLACE_KEYS)
        if not bucket and name not in NAMES and not searchable:
            return
        rings = []
        for outer in a.outer_rings():
            rings.append(('outer', pts(outer)))
            for inner in a.inner_rings(outer):
                rings.append(('inner', pts(inner)))
        if not rings or not any(touches(g) for _, g in rings):
            return
        g = rings[0][1]
        mid = [sum(p['lat'] for p in g) / len(g), sum(p['lon'] for p in g) / len(g)]
        if name in NAMES:
            self.names.setdefault(name, mid)
        if searchable:
            self.places.append([name] + mid)
        if not bucket:
            return
        tags = dict(t)
        if a.from_way() and len(rings) == 1:
            self.out[bucket].append({'type': 'way', 'id': a.orig_id(), 'tags': tags, 'geometry': rings[0][1]})
        else:
            tags['type'] = 'multipolygon'
            self.out[bucket].append({'type': 'relation', 'id': a.orig_id(), 'tags': tags,
                                     'members': [{'type': 'way', 'role': r, 'geometry': g} for r, g in rings]})


os.makedirs(CACHE, exist_ok=True)
if not os.path.exists(PBF):
    print('downloading', URL, flush=True)
    subprocess.run(['curl', '-sSL', '--fail', '-o', PBF + '.part', URL], check=True)
    os.rename(PBF + '.part', PBF)
h = Cut()
h.apply_file(PBF, locations=True, idx='flex_mem')
for k, v in h.out.items():
    json.dump({'elements': v}, open(os.path.join(CACHE, k + '.json'), 'w'), separators=(',', ':'))
    print(k, len(v), flush=True)
json.dump(h.names, open(os.path.join(CACHE, 'names.json'), 'w'), indent=1)
print('names', h.names)

# Second, quicker pass: street addresses (on nodes and building outlines) and named points.
addresses, places = [], h.places
for o in osmium.FileProcessor(PBF).with_locations().with_filter(osmium.filter.KeyFilter('addr:housenumber', 'name')):
    if o.is_node():
        if not o.location.valid():
            continue
        lat, lon = o.location.lat, o.location.lon
    elif o.is_way():
        g = pts(o.nodes)
        if not g:
            continue
        lat, lon = sum(p['lat'] for p in g) / len(g), sum(p['lon'] for p in g) / len(g)
    else:
        continue
    if not (S <= lat <= N and W <= lon <= E):
        continue
    t = o.tags
    if 'addr:housenumber' in t and 'addr:street' in t:
        addresses.append([t['addr:street'], t['addr:housenumber'], lat, lon])
    name = t.get('name')
    # Named buildings and areas came with the first pass; here only points, plus neighbourhood names.
    if name and 'highway' not in t and (t.get('place') in NEIGHBOURHOODS or (o.is_node() and any(k in t for k in PLACE_KEYS))):
        places.append([name, lat, lon])
json.dump({'addresses': addresses, 'places': places}, open(os.path.join(CACHE, 'search.json'), 'w'), separators=(',', ':'))
print('addresses', len(addresses), 'places', len(places))
