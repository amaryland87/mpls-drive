# Mpls Drive

Minneapolis on [Slop New York](https://github.com/mrdoob/slop-newyork)'s engine (Mr.doob, MIT: see LICENSE). Everything
but the city is Slop New York's, copied from commit `be65d0a`: the main loop, the controllers and car physics, the
cameras, the traffic, the sound, the HUD and the CSS. Changes to those files are marked `[Mpls]`. three.js is pinned to
one commit of its dev branch (index.html, js/mpls-shapeutils.js).

Play it at [sometimesfunctional.com/mpls-drive](https://sometimesfunctional.com/mpls-drive/): the portfolio's build
takes this repo's `main` (everything but `tools/`). To run it here, serve the repo's root, e.g. `python3 -m http.server`,
and open http://localhost:8000/.

Minneapolis comes from the baked city in `city/` and `tex/` (tools/bake_tiles.py, make_textures.py; the
OpenStreetMap extract comes from Geofabrik, or OpenStreetMap France's US Midwest one where Geofabrik can't be reached):

- `js/mpls-geo.js`: Mpls Drive's city builder (buildings, houses, streets, lamps, bridges, collision), with no three.js
  objects, so it runs in `js/mpls-worker.js`. Tiles are built off the main thread; the page only wraps the arrays.
- `js/mpls-city.js`: streams the 1 km tiles round the camera, and answers the engine's questions: ground and bridge
  height (`js/ground.js`), box colliders near a point, whole buildings for the sound.
- `js/city-config.js`, `js/landmarks.js`, `js/nyc-geodata.js`: the names the engine imports from Manhattan's geography,
  with Minneapolis behind them.
- `js/mpls-traffic.js`: Slop New York's traffic on `data/roads.json`, the street graph baked by
  `tools/bake_roads.mjs`.
- `js/mpls-map.js`: the radar and full map, with NYC's controls and look.

Also Minneapolis's own: `js/mpls-blocks.js` (city blocks from the street graph, for the pedestrians),
`js/mpls-signals.js` (signal heads at the signalled corners), `js/mpls-places.js` (the places to find), and water on
the river and lakes. Traffic is 60% of NYC's downtown and a quarter of it elsewhere, and the pedestrians all of NYC's
downtown and half elsewhere (`js/mpls-traffic.js`). They walk the sidewalks drawn along the streets
(`buildSidewalks` in `js/mpls-blocks.js`), stopping short of the cross streets. The car is sharper into the turns than
NYC's cab, and Space (A on a pad, Drift on a touch screen) is a handbrake that throws it into a drift.

Traffic keeps to the streets: a centreline street's lanes run in straight pieces no more than 0.6 m off its curve
(`js/road-network.js`, CURVE_TOL), and divided roads mapped as two roadways keep each way's lanes on its own. The trees
stand on the grass: `fitTrees` (`js/mpls-geo.js`) takes them off water and out from under bridge decks, and off the
sidewalks onto the boulevard or the lawn behind (or a tree pit at the curb on a main street with no grass).

Hero buildings (`tools/heroes/`) are real buildings modelled in detail: 3800 Beard Ave S, 2905 and 2915
Dean Parkway, and next door the Calhoun Beach Club and its apartment towers (`tools/hero_massing.py`, for
big stepped buildings, from the LiDAR and the aerial photo) with the Club's grounds (with 2905's garage and lot, front walks out to the parkway's sidewalk, house numbers, dressed windows,
fire escapes and the rest round the back). Downtown's towers are modelled whole from the survey by `tools/hero_tower.py`:
the Foshay Tower's tapering obelisk and pyramid cap with its name under it, Wells Fargo Center's setbacks and crown, and
the IDS Center (the tower's notched corners, the Crystal Court's stepped roof, the Marquette Hotel and the low wings),
Capella Tower with its open steel ring on the drum, City Hall's clock tower with its four clocks, the Basilica's dome and
lantern, Rand Tower, and the Gold Medal Flour elevator under its sign. The Stone Arch Bridge's arches, piers and the steel
truss span over the lock are traced from the survey under the deck (`tools/heroes/model_stone_arch.py`). Cars a hero lists (`pk`) stand parked there, drawn by `js/mpls-parked.js`
with the traffic's own car models, lamps dark, and solid. `tools/place_heroes.py` puts one into the baked tiles without a full re-bake.

Dressed from the city's own records (`tools/fetch_city.py`, `bake_transit.py`):

- Houses have the walls the City of Minneapolis assessor lists for their parcel (clapboard, stucco, brick or cedar
  shakes, new texture layers in `tex/`), its roof type (gable or hip), its storeys, and front porches and chimneys as
  often as houses of its year have them. Every roof, houses' and garages' shingles and the big buildings' flat roofs
  alike, takes its colour from Hennepin County's 2022 aerial photo.
- Street lights stand where the city's 18,000-odd lights are, each as its fixture: cobra heads, the residential lanterns,
  acorns, downtown's teardrops, shoeboxes, the Loring Greenway's globes. Streets with none of the city's lights near
  (Xcel Energy owns those, and they aren't in its data) keep evenly spaced cobra heads.
- Traffic signals are at the corners OpenStreetMap has them (`data/roads.json` signals).
- Street furniture (`mpls-geo.js` furnitureGeo): the city's hydrants and Nice Ride docks, a sign at every Metro Transit
  bus stop and a shelter where OpenStreetMap has one, the light rail's platform canopies, and OpenStreetMap's benches,
  litter bins, mailboxes, wooden utility poles and bike racks.
- Streets are asphalt, concrete or brick as the city's pavement map has them (`createPavedStreetMaterial`), with bike
  lanes painted where its bikeway map has them: a lane line, a buffered lane's two, posts along a protected lane, red
  bus lanes.
- The Blue and Green Line trains run to Metro Transit's timetable (`js/mpls-transit.js`, `data/transit.json`) under
  their overhead wire, at the hour the sky shows; the buses keep to Metro Transit's routes and show them on their signs.

Not yet: pedestrians crossing at the crosswalks (NYC's crossings follow Manhattan's grid). The trains don't stop the car.

Add `#debug` to the URL for a test hook (`window.__mpls`).
