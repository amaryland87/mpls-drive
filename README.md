# Mpls Drive

Minneapolis on [Slop New York](https://github.com/mrdoob/slop-newyork)'s engine (Mr.doob, MIT: see LICENSE). Everything
but the city is Slop New York's, copied from commit `be65d0a`: the main loop, the controllers and car physics, the
cameras, the traffic, the sound, the HUD and the CSS. Changes to those files are marked `[Mpls]`. three.js is pinned to
one commit of its dev branch (index.html, js/mpls-shapeutils.js).

Minneapolis comes from the baked city in `city/` and `tex/` (tools/mpls-drive/bake_tiles.py, make_textures.py):

- `js/mpls-geo.js`: Mpls Drive's city builder (buildings, houses, streets, lamps, bridges, collision), with no three.js
  objects, so it runs in `js/mpls-worker.js`. Tiles are built off the main thread; the page only wraps the arrays.
- `js/mpls-city.js`: streams the 1 km tiles round the camera, and answers the engine's questions: ground and bridge
  height (`js/ground.js`), box colliders near a point, whole buildings for the sound.
- `js/city-config.js`, `js/landmarks.js`, `js/nyc-geodata.js`: the names the engine imports from Manhattan's geography,
  with Minneapolis behind them.
- `js/mpls-traffic.js`: Slop New York's traffic on `data/roads.json`, the street graph baked by
  `tools/mpls-drive/bake_roads.mjs`.
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

Hero buildings (`tools/mpls-drive/heroes/`) are real buildings modelled in detail: 3800 Beard Ave S, 2905 and 2915
Dean Parkway, and next door the Calhoun Beach Club and its apartment towers (`tools/mpls-drive/hero_massing.py`, for
big stepped buildings, from the LiDAR and the aerial photo) with the Club's grounds (with 2905's garage and lot, front walks out to the parkway's sidewalk, house numbers, dressed windows,
fire escapes and the rest round the back). Cars a hero lists (`pk`) stand parked there, drawn by `js/mpls-parked.js`
with the traffic's own car models, lamps dark, and solid. `tools/mpls-drive/place_heroes.py` puts one into the baked tiles without a full re-bake.

Not yet: pedestrians crossing at the crosswalks (NYC's crossings follow Manhattan's grid), and street furniture beyond
the lamps and signals.

Add `#debug` to the URL for a test hook (`window.__mpls`).
