// Minneapolis in place of Slop New York's Manhattan geography: the names the engine modules import from NYC's
// city-config.js (controllers.js, traffic.js, tsl-materials.js, road-network.js, audio-sources.js...), with
// Minneapolis's map, places and street names behind them.
//
// World frame: 1 unit = 1 m, x east, z south (north = -z), origin at 44.966 N, 93.259 W (mpls-geo.js), the map
// running 11 km east-west and 10 km north-south (city/index.json bounds). The ground has its real
// hills (mpls-city.js); everything here is in plan.
import { cityXZ } from './mpls-geo.js';

const MAP = { x0: -7000, x1: 4000, z0: -4000, z1: 6000 };
const EDGE_IN = 150; // the player is kept this far inside the map's edge

// The playable area. sidewalkHeight is how far the sidewalks stand over the street (mpls-geo.js WALK_Y - ROAD_Y);
// there is no harbour.
const ISLAND_BOUNDS = {
  minX: MAP.x0 + EDGE_IN, maxX: MAP.x1 - EDGE_IN, minZ: MAP.z0 + EDGE_IN, maxZ: MAP.z1 - EDGE_IN,
  sidewalkHeight: 0.02, waterLevel: -40
};
// The whole map is open to the sky (tsl-materials.js darkens the sky light in Manhattan's street canyons outside
// Central Park), and it has no shoreline to keep to: the edge of the map is the limit.
const CENTRAL_PARK_BOUNDS = { minX: -1e6, maxX: 1e6, minZ: -1e6, maxZ: 1e6 };
const getIslandBoundsAtZ = () => ({ westX: ISLAND_BOUNDS.minX - 8, eastX: ISLAND_BOUNDS.maxX + 8 });
const NJ_SHORELINE_POLYGON = [];
const LONG_ISLAND_POLYGONS = [];
// No numbered-street grid to look up (controllers.js asks for 37th St to spawn on; main.js places the player).
const streetZ = () => 0;
// No raised curb blocks for the ground (the sidewalks are draped over it with the streets); the city blocks the
// pedestrians keep to are the street graph's faces (mpls-blocks.js), set when the traffic is built.
const BLOCKS = [];
let blockLookup = () => null;
const blockAt = (x, z) => blockLookup(x, z);
function setBlockLookup(fn) { blockLookup = fn; }
// What the ground is at a point (mpls-blocks.js buildSidewalks): 'road', 'walk' (a sidewalk) or null (anything else),
// and the share of the pedestrians who walk there (mpls-traffic.js): all of them downtown, half elsewhere
let sidewalkLookup = () => null;
const sidewalkAt = (x, z) => sidewalkLookup(x, z);
function setSidewalkLookup(fn) { sidewalkLookup = fn; }
let pedestrianShareFn = () => 1;
const pedestrianShare = (x, z) => pedestrianShareFn(x, z);
function setPedestrianShare(fn) { pedestrianShareFn = fn; }
// The road network (road-network.js) comes from Minneapolis's street centrelines alone, with no Manhattan grid.
const ALL_AVENUES = [];
const ALL_STREETS = [];

// Places to find, and to teleport to: [name, short name, latitude, longitude, district, radius (m)].
const PLACES = [
  ['IDS Center', 'IDS Center', 44.97611, -93.27206, 'Downtown'],
  ['Foshay Tower', 'Foshay', 44.97492, -93.27170, 'Downtown'],
  ['US Bank Stadium', 'US Bank Stadium', 44.97372, -93.25748, 'Downtown East'],
  ['Target Center', 'Target Center', 44.97946, -93.27608, 'North Loop'],
  ['Target Field', 'Target Field', 44.98183, -93.27766, 'North Loop'],
  ['Guthrie Theater', 'Guthrie', 44.97810, -93.25560, 'Mill District'],
  ['Mill City Museum', 'Mill City', 44.97887, -93.25710, 'Mill District'],
  ['Stone Arch Bridge', 'Stone Arch Bridge', 44.98070, -93.25300, 'Mississippi River', 170],
  ['Gold Medal Park', 'Gold Medal Park', 44.97700, -93.25300, 'Mill District'],
  ['Saint Anthony Main', 'St Anthony Main', 44.98500, -93.25550, 'Marcy-Holmes'],
  ['Nicollet Island', 'Nicollet Island', 44.98600, -93.26300, 'Mississippi River', 140],
  ['Convention Center', 'Convention Ctr', 44.96960, -93.27370, 'Downtown'],
  ['Loring Park', 'Loring Park', 44.96910, -93.28290, 'Loring Park', 130],
  ['Basilica of Saint Mary', 'Basilica', 44.97300, -93.28530, 'Loring Park'],
  ['Sculpture Garden', 'Sculpture Garden', 44.96980, -93.28930, 'Lowry Hill', 130],
  ['Cedar-Riverside', 'Cedar-Riverside', 44.96900, -93.24700, 'Cedar-Riverside'],
  ['University of Minnesota', 'U of M', 44.97640, -93.23540, 'University', 160],
  ['Huntington Bank Stadium', 'Huntington Stadium', 44.97650, -93.22460, 'University'],
  ['Minneapolis Institute of Art', 'Mia', 44.95860, -93.27410, 'Whittier'],
  ['Midtown Global Market', 'Midtown Global Mkt', 44.94850, -93.26080, 'Phillips'],
  ['Powderhorn Park', 'Powderhorn Park', 44.94170, -93.25700, 'Powderhorn', 160],
  ['Lake of the Isles', 'Lake of the Isles', 44.95700, -93.30200, 'Kenwood', 260],
  ['Uptown', 'Uptown', 44.94860, -93.29850, 'Uptown', 130],
  ['Bde Maka Ska', 'Bde Maka Ska', 44.94291, -93.31141, 'Uptown', 700],
  ['Lakewood Cemetery', 'Lakewood', 44.93373, -93.30545, 'Linden Hills', 300],
  ['Lake Harriet Bandshell', 'Lake Harriet', 44.92815, -93.30774, 'Linden Hills', 150],
  ['Lyndale Park Rose Garden', 'Rose Garden', 44.92712, -93.29632, 'Linden Hills', 130],
  ['Minnehaha Falls', 'Minnehaha Falls', 44.91530, -93.21110, 'Minnehaha', 160],
];
const NYC_LANDMARKS = PLACES.map(([name, short, lat, lon, district, r = 100]) => {
  const [x, z] = cityXZ(lat, lon);
  return { id: name.toLowerCase().replace(/[^a-z]+/g, '-'), name, short, x, z, district, r };
});

// Street-level arrivals for the teleport menu (index.html's data-teleport keys), each on a street in front of the
// place, facing it. Heading 0 faces south (+z), PI north. main.js puts each on the nearest road when it is used.
const at = (lat, lon, heading) => { const [x, z] = cityXZ(lat, lon); return { x, z, heading }; };
const TELEPORT_LOCATIONS = {
  downtown: at(44.97380, -93.27420, -2.6),       // Nicollet Mall at 10th St
  ids: at(44.97660, -93.27160, Math.PI * 0.75),  // Nicollet Mall at 7th St, under the IDS Center
  stadium: at(44.97500, -93.25960, Math.PI / 2), // Chicago Avenue, the stadium's prow
  stonearch: at(44.97950, -93.25560, 0),         // West River Parkway by Mill City
  stanthony: at(44.98460, -93.25660, 0),         // Main Street by Saint Anthony Main
  uptown: at(44.94860, -93.29850, Math.PI / 2),  // Hennepin & Lake
  bdemakaska: at(44.95000, -93.31200, 0),        // the lake's north shore
  minnehaha: at(44.91700, -93.21300, 0)          // Minnehaha Parkway by the falls
};

// Named roads, for the location label (main.js): filled in as the city's tiles load their street names.
const ROADS = [];
const roadNames = new Set();

// The city's tiles, for the street names at each corner (mpls-city.js: corners as [x10, z10, a1, n1, a2, n2])
let city = null;
function setCity(c) { city = c; }

const SIGN_ABBR = [[/\bAvenue\b/g, 'Ave'], [/\bStreet\b/g, 'St'], [/\bBoulevard\b/g, 'Blvd'], [/\bParkway\b/g, 'Pkwy'],
  [/\bDrive\b/g, 'Dr'], [/\bRoad\b/g, 'Rd'], [/\bLane\b/g, 'Ln'], [/\bPlace\b/g, 'Pl'], [/\bTerrace\b/g, 'Ter'],
  [/\bCircle\b/g, 'Cir'], [/\bSoutheast\b/g, 'SE'], [/\bNortheast\b/g, 'NE'], [/\bSouthwest\b/g, 'SW'],
  [/\bNorthwest\b/g, 'NW'], [/\bSouth\b/g, 'S'], [/\bNorth\b/g, 'N'], [/\bEast\b/g, 'E'], [/\bWest\b/g, 'W']];
const shortName = (name) => SIGN_ABBR.reduce((s, [re, ab]) => s.replace(re, ab), name);

/** The two street names at the nearest corner within `range` of (x, z): [a, b], or null. */
function nearestCorner(x, z, range = 90) {
  if (!city) return null;
  let best = null, bestD = range;
  for (const t of city.ready) {
    if (!t.corners || x < t.x0 - range || x > t.x0 + city.MAP.tile + range || z < t.z0 - range || z > t.z0 + city.MAP.tile + range) continue;
    const C = t.corners;
    for (let k = 0; k < C.length; k += 6) {
      const d = Math.hypot(C[k] / 10 - x, C[k + 1] / 10 - z);
      if (d < bestD) { bestD = d; best = [t.streetNames[C[k + 3]], t.streetNames[C[k + 5]]]; }
    }
  }
  if (!best) return null;
  for (const n of best) {
    if (n && !roadNames.has(shortName(n))) { roadNames.add(shortName(n)); ROADS.push({ name: shortName(n) }); }
  }
  return best.filter(Boolean).map(shortName);
}

/** Where (x, z) is: a place's name and the corner, or just the corner's two street names. */
function getLocationLabel(x, z) {
  const corner = nearestCorner(x, z);
  const streets = corner && corner.length === 2 ? `${corner[0]} & ${corner[1]}` : corner?.[0] || '';
  for (const lm of NYC_LANDMARKS) {
    if (Math.hypot(x - lm.x, z - lm.z) < Math.max(80, lm.r)) return streets ? `${lm.name} · ${streets}` : lm.name;
  }
  if (streets) return streets;
  return 'Minneapolis';
}

// Keyboard shortcuts are ignored while typing into a form field (e.g. the map's street search box)
function isTypingInField(e) {
  return e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT');
}

// Traffic signal cycle shared by the traffic (traffic.js) and the walk signals (audio-sources.js), in seconds, as in
// Slop New York: the major road green until avenueAmber, amber until avenueRed; the cross street green from
// avenueRed until streetAmber, amber until the end of the cycle. Pedestrians step off only on the WALK.
const SIGNAL_TIMING = { cycle: 60, avenueAmber: 26, avenueRed: 30, streetAmber: 56, walk: 7 };

// 'green', 'amber' or 'red' for major road (avenue) or cross street traffic at a given time
function signalPhase(time, isAvenue) {
  const { cycle, avenueAmber, avenueRed, streetAmber } = SIGNAL_TIMING;
  const t = ((time % cycle) + cycle) % cycle;
  if (isAvenue) return t < avenueAmber ? 'green' : t < avenueRed ? 'amber' : 'red';
  return t < avenueRed ? 'red' : t < streetAmber ? 'green' : 'amber';
}

// Do pedestrians walking alongside the major road (or cross street) traffic have the WALK at a given time?
function walkSignal(time, isAvenue) {
  const { cycle, avenueRed, walk } = SIGNAL_TIMING;
  const t = (((time - (isAvenue ? 0 : avenueRed)) % cycle) + cycle) % cycle;
  return t < walk;
}

export {
  MAP,
  ISLAND_BOUNDS,
  CENTRAL_PARK_BOUNDS,
  getIslandBoundsAtZ,
  NJ_SHORELINE_POLYGON,
  LONG_ISLAND_POLYGONS,
  BLOCKS,
  ALL_AVENUES,
  ALL_STREETS,
  ROADS,
  NYC_LANDMARKS,
  TELEPORT_LOCATIONS,
  SIGNAL_TIMING,
  streetZ,
  blockAt,
  setBlockLookup,
  sidewalkAt,
  setSidewalkLookup,
  pedestrianShare,
  setPedestrianShare,
  setCity,
  nearestCorner,
  shortName,
  getLocationLabel,
  isTypingInField,
  signalPhase,
  walkSignal
};
