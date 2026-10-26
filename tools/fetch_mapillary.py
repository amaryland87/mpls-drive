"""Fetch Mapillary street photos of one building, for modelling a hero building by hand (see heroes/).

    MAPILLARY_TOKEN=MLY|... .venv/bin/python fetch_mapillary.py NAME LAT LON [RADIUS_M] [MAX_PHOTOS]
    e.g. .venv/bin/python fetch_mapillary.py 2905-dean 44.9505922 -93.3154528

Finds the Mapillary photos taken within RADIUS_M metres (default 60) of the spot whose camera faces it (panoramas
always count), nearest first, and saves up to MAX_PHOTOS (default 30) at 2048 px into osm-cache/heroes/NAME/photos/,
with photos.json listing each one: id, when it was taken, where from, which way the camera faced, how far off and
in which direction the building was, and who took it.

The token is a Mapillary client token (mapillary.com: Dashboard, Developers, register an application), read from
MAPILLARY_TOKEN and sent in a request header, never in a URL. Mapillary photos are CC BY-SA 4.0: they stay in
osm-cache/ (not committed) as references for the modelling; credit the photographers (photos.json: creator) in any
model made from them.
"""
import json, math, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
API = 'https://graph.mapillary.com'
FIELDS = 'id,captured_at,compass_angle,computed_compass_angle,geometry,computed_geometry,thumb_2048_url,creator,is_pano'
FACING = 50                    # degrees either side of straight at the building that still count as facing it

NAME, LAT, LON = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
RADIUS = float(sys.argv[4]) if len(sys.argv) > 4 else 60.0
MAX = int(sys.argv[5]) if len(sys.argv) > 5 else 30
TOKEN = os.environ.get('MAPILLARY_TOKEN', '').strip()
if not TOKEN:
    sys.exit('set MAPILLARY_TOKEN to a Mapillary client token (see the top of this file)')
OUT = os.path.join(HERE, 'osm-cache', 'heroes', NAME, 'photos')
os.makedirs(OUT, exist_ok=True)


def get(url, path=None, auth=True):
    # The header goes to curl on its standard input, so the token never shows in a process list
    config = f'header = "Authorization: OAuth {TOKEN}"\n' if auth else ''
    args = ['curl', '-sS', '--fail', '--retry', '4', '-K', '-', url] + (['-o', path] if path else [])
    return subprocess.run(args, input=config.encode(), capture_output=True, check=True).stdout


def metres(lat, lon):
    """East and south of the building, in metres."""
    return (lon - LON) * 111320 * math.cos(math.radians(LAT)), (LAT - lat) * 110574


dlat = RADIUS / 110574
dlon = RADIUS / (111320 * math.cos(math.radians(LAT)))
bbox = f'{LON - dlon},{LAT - dlat},{LON + dlon},{LAT + dlat}'
found = json.loads(get(f'{API}/images?fields={FIELDS}&bbox={bbox}&limit=2000')).get('data', [])
print(len(found), 'photos in the box', flush=True)

keep = []
for im in found:
    geo = im.get('computed_geometry') or im.get('geometry')
    if not geo:
        continue
    lon, lat = geo['coordinates']
    x, z = metres(lat, lon)
    dist = math.hypot(x, z)
    if dist > RADIUS or dist < 3:
        continue
    toward = math.degrees(math.atan2(-x, z)) % 360          # compass bearing from the camera to the building
    heading = im.get('computed_compass_angle', im.get('compass_angle'))
    off = None if heading is None else (heading - toward + 180) % 360 - 180
    if not im.get('is_pano') and (off is None or abs(off) > FACING):
        continue
    keep.append(dict(id=im['id'], taken=im.get('captured_at'), lat=lat, lon=lon, dist=round(dist, 1),
                     bearing_to_building=round(toward), camera_heading=None if heading is None else round(heading),
                     off_centre=None if off is None else round(off), pano=bool(im.get('is_pano')),
                     creator=(im.get('creator') or {}).get('username'), url=im.get('thumb_2048_url')))
keep.sort(key=lambda k: k['dist'])
keep = keep[:MAX]

for k in keep:
    path = os.path.join(OUT, k['id'] + '.jpg')
    if k['url'] and not os.path.exists(path):
        get(k['url'], path, auth=False)                   # the image links are signed already
    k['file'] = os.path.basename(path)
    del k['url']
json.dump(keep, open(os.path.join(OUT, 'photos.json'), 'w'), indent=1)
years = sorted({time.gmtime(k['taken'] / 1000).tm_year for k in keep if k['taken']})   # captured_at: ms since 1970
print(f'saved {len(keep)} photos facing {NAME} to {os.path.relpath(OUT, HERE)} (taken {years})')
