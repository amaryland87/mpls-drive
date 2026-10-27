"""Get the City of Minneapolis, Hennepin County and Metro Transit data that bake_tiles.py dresses the city with.

    .venv/bin/python fetch_city.py              # after fetch_osm.py; about 700 MB, cached in osm-cache/city/

Everything is public open data, fetched once (delete a file in osm-cache/city/ to fetch it again):
  parcels.json    every parcel inside the map: its outline, and from the city assessor (2025) its building's outside
                  wall (stucco, siding, brick, wood shake...), roof (gable, hip, gambrel, flat...), year built and
                  stories. Matched up by parcel id. (City of Minneapolis Assessing Department; no owners are kept.)
  lights.json     every city-owned street light: where it stands and its fixture (cobra head, lantern, acorn, the
                  Park Board's teardrop, shoebox, the Loring Greenway's globes). (Minneapolis Public Works)
  hydrants.json   fire hydrants. (Minneapolis Public Works)
  niceride.json   Nice Ride bike-share docks.
  pavement.json   street pavement by block: asphalt, concrete, brick or gravel. (Minneapolis Public Works)
  bikeways.json   on-street bike lanes, buffered and protected lanes and bike boulevards. (Minneapolis Public Works)
  gtfs.zip        Metro Transit's schedule: the light rail and bus routes, their stops and every trip.
  aerial/i_j.jpg  Hennepin County's 2022 aerial photo over each 1 km tile, about 0.5 m a pixel, for the roof colours,
                  and i_j.json the [west, south, east, north] it covers (degrees).
"""
import json, math, os, subprocess, sys, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from area import LAT0, LON0, MX, MY, TILE, X0, X1, Z0, Z1

OUT = os.path.join(HERE, 'osm-cache', 'city')
os.makedirs(os.path.join(OUT, 'aerial'), exist_ok=True)
CITY = 'https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services/'
AERIAL = 'https://gis.hennepin.us/arcgis/rest/services/Imagery/UTM_Aerial_2022/MapServer/export'
GTFS = 'https://svc.metrotransit.org/mtgtfs/gtfs.zip'
MARGIN = 100
S, N = LAT0 - (Z1 + MARGIN) / MY, LAT0 - (Z0 - MARGIN) / MY
W, E = LON0 + (X0 - MARGIN) / MX, LON0 + (X1 + MARGIN) / MX


def curl(url, path=None):
    args = ['curl', '-sS', '--fail', '--retry', '4', '--retry-all-errors', '--max-time', '300', url] + (['-o', path] if path else [])
    return subprocess.run(args, capture_output=True, check=True).stdout


def features(layer, fields, where='1=1', geometry=True, page=1000):
    """Every feature of a city layer inside the map (or every row, for a table): [{attributes, geometry}]."""
    out, offset = [], 0
    while True:
        q = dict(where=where, outFields=','.join(fields), f='json', resultOffset=offset, resultRecordCount=page,
                 returnGeometry='true' if geometry else 'false')
        if geometry:
            q.update(geometry=f'{W},{S},{E},{N}', geometryType='esriGeometryEnvelope', inSR=4326, outSR=4326,
                     spatialRel='esriSpatialRelIntersects')
        d = json.loads(curl(CITY + layer + '/FeatureServer/0/query?' + urllib.parse.urlencode(q)))
        if 'error' in d:
            sys.exit(f'{layer}: {d["error"]}')
        out += d['features']
        print(' ', layer, len(out), flush=True)
        if not d.get('exceededTransferLimit') and len(d['features']) < page:
            return out
        offset += len(d['features'])


def save(name, fetch):
    path = os.path.join(OUT, name)
    if os.path.exists(path):
        return
    print(name, flush=True)
    data = fetch()
    json.dump(data, open(path + '.part', 'w'), separators=(',', ':'))
    os.rename(path + '.part', path)
    print(name, len(data), flush=True)


def pt(g):
    return [round(g['y'], 7), round(g['x'], 7)]


def lines(g):
    return [[[round(y, 7), round(x, 7)] for x, y in p] for p in g.get('paths', [])]


def parcels():
    shapes = {}
    for f in features('Assessor_Parcels_2024', ['PID']):
        g = f.get('geometry') or {}
        if g.get('rings'):
            shapes[f['attributes']['PID']] = [[[round(y, 7), round(x, 7)] for x, y in r] for r in g['rings']]
    out = []
    for f in features('Assessing_Department_Parcel_Data_2025', ['TAX_MAP_UFMT', 'EXTERIORWALL', 'ROOF', 'YEARBUILT', 'STORIES',
                                                                'BUILDINGUSE'], geometry=False, page=2000):
        a = f['attributes']
        rings = shapes.get((a['TAX_MAP_UFMT'] or '').lstrip('p'))
        if rings:
            out.append(dict(rings=rings, wall=(a['EXTERIORWALL'] or '').strip().upper(), roof=(a['ROOF'] or '').strip().upper(),
                            year=a['YEARBUILT'] or 0, stories=a['STORIES'] or 0, use=a['BUILDINGUSE'] or ''))
    return out


save('parcels.json', parcels)
save('lights.json', lambda: [pt(f['geometry']) + [(f['attributes']['Type'] or '').strip()]
                             for f in features('Minneapolis_Owned_Light_Fixtures', ['Type']) if f.get('geometry')])
save('hydrants.json', lambda: [pt(f['geometry']) for f in features('Hydrants', ['OBJECTID']) if f.get('geometry')])
save('niceride.json', lambda: [pt(f['geometry']) + [f['attributes']['NiceRideDock']]
                               for f in features('NiceRideDocks', ['NiceRideDock']) if f.get('geometry')])
save('pavement.json', lambda: [dict(surface=(f['attributes']['SURFACE'] or '').strip(), lines=lines(f['geometry']))
                               for f in features('MPLS_STREET_PAVEMENT_DATA', ['SURFACE']) if f.get('geometry')])
save('bikeways.json', lambda: [dict(type=(f['attributes']['TYPE_1'] or '').strip(), lines=lines(f['geometry']))
                               for f in features('Existing_Bikeways', ['TYPE_1']) if f.get('geometry')])

if not os.path.exists(os.path.join(OUT, 'gtfs.zip')):
    print('gtfs.zip', flush=True)
    curl(GTFS, os.path.join(OUT, 'gtfs.zip.part'))
    os.rename(os.path.join(OUT, 'gtfs.zip.part'), os.path.join(OUT, 'gtfs.zip'))

# The aerial photo over each 1 km tile, in degrees (game metres are degrees scaled: see area.py), so 2000 px across and
# as many down as keep the pixels square in degrees; the server says what it covers.
for i in range((X1 - X0) // TILE):
    for j in range((Z1 - Z0) // TILE):
        path = os.path.join(OUT, 'aerial', f'{i}_{j}.jpg')
        if os.path.exists(path):
            continue
        x0, z0 = X0 + i * TILE, Z0 + j * TILE
        lon0, lon1 = LON0 + x0 / MX, LON0 + (x0 + TILE) / MX
        lat1, lat0 = LAT0 - z0 / MY, LAT0 - (z0 + TILE) / MY
        h = round(2000 * (lat1 - lat0) / (lon1 - lon0))
        d = json.loads(curl(f'{AERIAL}?bbox={lon0},{lat0},{lon1},{lat1}&bboxSR=4326&imageSR=4326&size=2000,{h}&format=jpg&f=json'))
        ex = d['extent']
        curl(d['href'], path + '.part')
        json.dump([ex['xmin'], ex['ymin'], ex['xmax'], ex['ymax']], open(path[:-4] + '.json', 'w'))
        os.rename(path + '.part', path)
        print('aerial', i, j, flush=True)
print('done')
