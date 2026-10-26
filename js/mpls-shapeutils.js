// three.js's polygon triangulation (ShapeUtils, earcut) and the Vector2 it works on, on their own, for mpls-geo.js:
// a module worker can't use the page's import map, so they come straight from the page's pinned three.js build.
export { ShapeUtils } from 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@fa57cf648fc36a9c5999f0076bfeea4960de50f6/src/extras/ShapeUtils.js';
export { Vector2 } from 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@fa57cf648fc36a9c5999f0076bfeea4960de50f6/src/math/Vector2.js';
