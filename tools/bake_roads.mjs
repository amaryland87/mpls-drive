// Minneapolis's street network for Slop New York's traffic (public/mpls-drive-next/js/road-network.js reads it as
// GEO.roadGraph): every drivable street piece of the baked tiles (public/mpls-drive/city/t/*.json, made by
// bake_tiles.py, which cuts each street at its intersections), joined where their ends meet, and the road bridges
// (index.json br, left out of the street pieces) joined onto them where they land.
//
//   node tools/mpls-drive/bake_roads.mjs
//
// Writes public/mpls-drive-next/data/roads.json:
//   nodes  [x, z, ...] junctions and street ends, metres (x east, z south)
//   links  [[a, b, name, width, lanes, dir, [x, z, ...inner points]], ...] dir 1 one-way a -> b, 0 two-way
//   names  ['', ...] (the street pieces carry no names; the kind of road stands in)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CITY = path.join(HERE, '../../public/mpls-drive/city');
const OUT = path.join(HERE, '../../public/mpls-drive-next/data/roads.json');

const KINDS = ['pedestrian', 'living_street', 'residential', 'unclassified', 'tertiary_link', 'secondary_link',
  'primary_link', 'trunk_link', 'motorway_link', 'tertiary', 'secondary', 'primary', 'trunk', 'motorway', 'path'];
const DRIVE = new Set(KINDS.filter((k) => k !== 'pedestrian' && k !== 'path'));
// Road bridges are as wide as their road plus 3 m (bake_tiles.py); footbridges are narrower.
const ROAD_BRIDGE_W = 11;
const SNAP = 2.5;   // bridge ends join a street end this close

const index = JSON.parse(fs.readFileSync(path.join(CITY, 'index.json'), 'utf8'));
const nodes = [];
const nodeAt = new Map();      // street ends, exact (decimetres)
const grid = new Map();        // 8 m cells -> node ids, for snapping the bridges on
const cellKey = (x, z) => `${Math.floor(x / 8)},${Math.floor(z / 8)}`;
function addNode(x, z) {
  const id = nodes.length;
  nodes.push([x, z]);
  const k = cellKey(x, z);
  if (!grid.has(k)) grid.set(k, []);
  grid.get(k).push(id);
  return id;
}
function exactNode(x10, z10) {
  const key = `${x10},${z10}`;
  if (!nodeAt.has(key)) nodeAt.set(key, addNode(x10 / 10, z10 / 10));
  return nodeAt.get(key);
}
function nearNode(x, z, r) {
  let best = -1, bd = r;
  for (let i = Math.floor((x - r) / 8); i <= Math.floor((x + r) / 8); i++) {
    for (let j = Math.floor((z - r) / 8); j <= Math.floor((z + r) / 8); j++) {
      for (const id of grid.get(`${i},${j}`) || []) {
        const d = Math.hypot(nodes[id][0] - x, nodes[id][1] - z);
        if (d < bd) { bd = d; best = id; }
      }
    }
  }
  return best;
}

const names = ['', ...KINDS];
const links = [];
let pieces = 0;
for (const f of fs.readdirSync(path.join(CITY, 't')).filter((f) => f.endsWith('.json')).sort()) {
  const data = JSON.parse(fs.readFileSync(path.join(CITY, 't', f), 'utf8'));
  for (const r of data.rd || []) {
    const [cls, w10, lanes, oneway, , , n] = r;
    if (!DRIVE.has(KINDS[cls]) || n < 2) continue;
    pieces++;
    const a = exactNode(r[7], r[8]), b = exactNode(r[7 + (n - 1) * 2], r[8 + (n - 1) * 2]);
    if (a === b) continue;
    const inner = [];
    for (let i = 1; i < n - 1; i++) inner.push(r[7 + i * 2] / 10, r[8 + i * 2] / 10);
    links.push([a, b, 1 + cls, w10 / 10, lanes, oneway ? 1 : 0, inner]);
  }
}

// The road bridges: chains of deck segments, end to end. Each chain becomes one link between the street ends it
// lands on (or new ends, when it lands on another bridge or nothing mapped).
const br = index.br;
const segs = [];
for (let i = 0; i < br.length; i += 8) segs.push(br.slice(i, i + 8));
const startAt = new Map();
segs.forEach((s, k) => startAt.set(`${s[0]},${s[1]}`, k));
const used = new Set();
let bridgeLinks = 0;
for (let k = 0; k < segs.length; k++) {
  if (used.has(k) || segs[k][4] < ROAD_BRIDGE_W) continue;
  // walk back to the chain's first segment
  let first = k;
  const seenBack = new Set([k]);
  for (;;) {
    const prev = segs.findIndex((s, j) => !seenBack.has(j) && s[2] === segs[first][0] && s[3] === segs[first][1] && s[4] === segs[first][4]);
    if (prev < 0) break;
    seenBack.add(prev);
    first = prev;
  }
  const pts = [[segs[first][0], segs[first][1]]];
  let cur = first;
  while (cur !== undefined && !used.has(cur)) {
    used.add(cur);
    pts.push([segs[cur][2], segs[cur][3]]);
    const next = startAt.get(`${segs[cur][2]},${segs[cur][3]}`);
    cur = next !== undefined && segs[next][4] === segs[cur][4] ? next : undefined;
  }
  let len = 0;
  for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
  if (len < 8) continue;
  const end = (p) => { const id = nearNode(p[0], p[1], SNAP); return id >= 0 ? id : addNode(p[0], p[1]); };
  const a = end(pts[0]), b = end(pts[pts.length - 1]);
  if (a === b) continue;
  const w = segs[first][4] - 3;
  links.push([a, b, 0, w, 0, w >= 23 ? 1 : 0, pts.slice(1, -1).flat()]);
  bridgeLinks++;
}

const round = (v) => Math.round(v * 10) / 10;
const out = {
  note: 'OpenStreetMap contributors (ODbL). Made by tools/mpls-drive/bake_roads.mjs from public/mpls-drive/city.',
  nodes: nodes.flatMap(([x, z]) => [round(x), round(z)]),
  links: links.map(([a, b, ni, w, lanes, dir, inner]) => [a, b, ni, round(w), lanes, dir, inner.map(round)]),
  names
};
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(out));
console.log(`street pieces ${pieces}, bridge links ${bridgeLinks}, nodes ${nodes.length}, links ${links.length}, ${(fs.statSync(OUT).size / 1e6).toFixed(2)} MB`);
