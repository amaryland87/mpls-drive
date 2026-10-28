// The traffic on Minneapolis's streets: Slop New York's traffic.js, cars, buses and their drivers unchanged, on a road
// network that road-network.js builds from Minneapolis's street centrelines (data/roads.json, baked by
// tools/mpls-drive/bake_roads.mjs) instead of Manhattan's grid. The corners OpenStreetMap has traffic signals at get
// them (bake_roads.mjs signals; failing those, where main streets meet), and the buses keep to Metro Transit's routes.
import * as THREE from 'three/webgpu';
import { GEO } from './nyc-geodata.js';
import { setBlockLookup, setPedestrianShare, setSidewalkLookup } from './city-config.js';
import { buildBlocks, buildSidewalks } from './mpls-blocks.js';
import { createTrafficSystem, setTrafficDensity, setBusRoutes } from './traffic.js';
import { createSignals } from './mpls-signals.js';

// How much of Slop New York's traffic drives here: 60% of it downtown, a quarter of it elsewhere, eased between over
// the few hundred metres round downtown (centred on Nicollet Mall, metres east and south of the map's origin).
const DOWNTOWN = { x: -800, z: -1150, inner: 1100, outer: 1700 };
const DOWNTOWN_SHARE = 0.6, ELSEWHERE_SHARE = 0.25;
function density(x, z) {
  const d = Math.hypot(x - DOWNTOWN.x, z - DOWNTOWN.z);
  const t = Math.min(1, Math.max(0, (d - DOWNTOWN.inner) / (DOWNTOWN.outer - DOWNTOWN.inner)));
  return DOWNTOWN_SHARE + (ELSEWHERE_SHARE - DOWNTOWN_SHARE) * t * t * (3 - 2 * t);
}
// The pedestrians thin out the same way: all of them downtown, half of them elsewhere
function pedestrianShare(x, z) {
  const d = Math.hypot(x - DOWNTOWN.x, z - DOWNTOWN.z);
  const t = Math.min(1, Math.max(0, (d - DOWNTOWN.inner) / (DOWNTOWN.outer - DOWNTOWN.inner)));
  return 1 - 0.5 * t * t * (3 - 2 * t);
}

// Street kinds (bake_roads.mjs names: 1 + the road kind's index in mpls-geo.js ROAD_KINDS): the arterials (secondary,
// primary, trunk) and the collectors (tertiary)
const ARTERIAL = new Set([11, 12, 13]);
const COLLECTOR = 10;

export async function createMplsTraffic(scene, url) {
  const graph = await fetch(url).then((r) => { if (!r.ok) throw new Error('roads: ' + r.status); return r.json(); });
  GEO.roadGraph = graph;
  // The city blocks the pedestrians walk round
  setBlockLookup(buildBlocks(graph));
  // ...on the sidewalks drawn along the streets (mpls-geo.js), not on the streets themselves
  setSidewalkLookup(buildSidewalks(graph));
  setPedestrianShare(pedestrianShare);
  // The signalled corners OpenStreetMap knows (bake_roads.mjs). Without them: signals where an arterial meets another
  // arterial or a collector: three or more streets at the corner, at least one of them an arterial and three of them
  // arterials or collectors (about 500 corners, as many as Minneapolis has)
  const signalIntersections = (graph.signals || []).map((n) => ({ x: graph.nodes[n * 2], z: graph.nodes[n * 2 + 1], near: 14 }));
  const arterial = new Map(), main = new Map(), all = new Map();
  for (const [a, b, ni] of graph.links) {
    for (const n of [a, b]) {
      all.set(n, (all.get(n) || 0) + 1);
      if (ARTERIAL.has(ni)) arterial.set(n, (arterial.get(n) || 0) + 1);
      if (ARTERIAL.has(ni) || ni === COLLECTOR) main.set(n, (main.get(n) || 0) + 1);
    }
  }
  if (!signalIntersections.length) for (const [n, k] of main) {
    if (k >= 3 && arterial.get(n) >= 1 && all.get(n) >= 3) signalIntersections.push({ x: graph.nodes[n * 2], z: graph.nodes[n * 2 + 1] });
  }
  setTrafficDensity(density);
  setBusRoutes(graph.buses);
  const trafficSystem = createTrafficSystem(scene, [], [], signalIntersections);
  // No elevated freeway of NYC's own to run cars on: an empty stand-in for the sound. The signal heads (mpls-signals.js)
  // stand in for NYC's street details: their walk signals chirp.
  const highwayTraffic = { cars: [], group: new THREE.Group(), update() {} };
  const streetDetails = createSignals(scene, trafficSystem.network);
  scene.add(highwayTraffic.group);
  return { trafficSystem, highwayTraffic, streetDetails, signalIntersections };
}
