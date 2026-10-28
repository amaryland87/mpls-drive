// Minneapolis's city blocks, for Slop New York's pedestrians (pedestrian-routes.js keeps each walker on one block's
// sidewalks, and rounds its corners within a few metres of the block's curb). Manhattan's blocks come from its open
// data; here they are the faces of the street graph (data/roads.json): every loop of streets closes a block. Each block
// carries its outline along the street centrelines (to find the block a point is in) and its curb line, the outline
// pulled in by each street's half width (what the sidewalks follow).

const CELL = 64;

/** Builds the blocks from the street graph; returns blockAt(x, z): the block there, or null on no block. */
export function buildBlocks(graph) {
  const N = graph.nodes.length / 2;
  const node = (i) => ({ x: graph.nodes[i * 2], z: graph.nodes[i * 2 + 1] });
  // Half-edges: each link both ways, with its points from its start to its end, and the street's half width
  const half = [];
  const out = Array.from({ length: N }, () => []);
  for (const [a, b, , w, , , inner] of graph.links) {
    if (a === b) continue;
    const pts = [node(a)];
    for (let k = 0; k < inner.length; k += 2) pts.push({ x: inner[k], z: inner[k + 1] });
    pts.push(node(b));
    const hw = Math.max(2.5, w / 2);
    const h0 = { from: a, to: b, pts, hw, used: false }, h1 = { from: b, to: a, pts: [...pts].reverse(), hw, used: false };
    h0.twin = h1; h1.twin = h0;
    for (const h of [h0, h1]) {
      h.angle = Math.atan2(h.pts[1].z - h.pts[0].z, h.pts[1].x - h.pts[0].x);
      out[h.from].push(h);
      half.push(h);
    }
  }
  for (const list of out) list.sort((p, q) => p.angle - q.angle);
  // Arriving along h, turn onto the street just before its way back in angle order: walking the faces that way keeps
  // each block on the same side
  const next = (h) => {
    const list = out[h.to], k = list.indexOf(h.twin);
    return list[(k - 1 + list.length) % list.length];
  };
  const faces = [];
  for (const h0 of half) {
    if (h0.used) continue;
    const ring = [], widths = [];
    let h = h0, steps = 0;
    do {
      h.used = true;
      for (let k = 0; k < h.pts.length - 1; k++) { ring.push(h.pts[k]); widths.push(h.hw); }
      h = next(h);
    } while (h && h !== h0 && ++steps < 400);
    if (h !== h0 || ring.length < 3) continue;
    let area = 0;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) area += ring[j].x * ring[i].z - ring[i].x * ring[j].z;
    faces.push({ ring, widths, area: area / 2 });
  }
  // The blocks are the faces wound one way; the outside of everything (and of each separate island of streets) the
  // other. Which way is which: the way most faces go.
  const sign = Math.sign(faces.reduce((s, f) => s + Math.sign(f.area), 0)) || 1;
  const blocks = [];
  for (const f of faces) {
    const A = Math.abs(f.area);
    if (Math.sign(f.area) !== sign || A < 200 || A > 2.5e6) continue;
    blocks.push(makeBlock(f.ring, f.widths, sign, A));
  }
  // A grid of which blocks reach into each cell
  const cells = new Map();
  for (const b of blocks) {
    for (let i = Math.floor(b.minX / CELL); i <= Math.floor(b.maxX / CELL); i++) {
      for (let j = Math.floor(b.minZ / CELL); j <= Math.floor(b.maxZ / CELL); j++) {
        const k = i * 100000 + j;
        if (!cells.has(k)) cells.set(k, []);
        cells.get(k).push(b);
      }
    }
  }
  for (const list of cells.values()) list.sort((p, q) => p.area - q.area);   // the smallest that holds a point wins
  console.info(`[blocks] ${blocks.length} blocks from ${faces.length} faces of the street graph`);
  return function blockAt(x, z) {
    for (const b of cells.get(Math.floor(x / CELL) * 100000 + Math.floor(z / CELL)) || []) {
      if (x < b.minX || x > b.maxX || z < b.minZ || z > b.maxZ) continue;
      if (inside(b.outline, x, z)) return b;
    }
    return null;
  };
}

function inside(P, x, z) {
  let hit = false;
  for (let i = 0, j = P.length - 1; i < P.length; j = i++) {
    const a = P[i], c = P[j];
    if ((a.z > z) !== (c.z > z) && x < ((c.x - a.x) * (z - a.z)) / (c.z - a.z) + a.x) hit = !hit;
  }
  return hit;
}

// A block from its outline along the centrelines: its curb line (poly) is each side pulled in by its street's half
// width, mitred at the corners (and capped, so a sharp corner doesn't throw a spike).
function makeBlock(ring, widths, sign, area) {
  const n = ring.length;
  const normals = [];
  for (let i = 0; i < n; i++) {
    const a = ring[i], b = ring[(i + 1) % n];
    const dx = b.x - a.x, dz = b.z - a.z, L = Math.hypot(dx, dz) || 1;
    // inward: to the left of the way round for one winding, the right for the other
    normals.push({ x: (-dz / L) * sign, z: (dx / L) * sign });
  }
  const poly = [];
  for (let i = 0; i < n; i++) {
    const p = (i - 1 + n) % n;
    const n0 = normals[p], n1 = normals[i], w0 = widths[p], w1 = widths[i];
    let mx = n0.x * w0 + n1.x * w1, mz = n0.z * w0 + n1.z * w1;
    const cos = n0.x * n1.x + n0.z * n1.z;
    const k = 1 / Math.max(0.35, 1 + cos);
    mx *= k; mz *= k;
    const L = Math.hypot(mx, mz), cap = 2.5 * Math.max(w0, w1);
    if (L > cap) { mx *= cap / L; mz *= cap / L; }
    poly.push({ x: ring[i].x + mx, z: ring[i].z + mz });
  }
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const q of ring) { minX = Math.min(minX, q.x); maxX = Math.max(maxX, q.x); minZ = Math.min(minZ, q.z); maxZ = Math.max(maxZ, q.z); }
  return { outline: ring, poly, minX, maxX, minZ, maxZ, area, park: 0, median: false, cx: (minX + maxX) / 2, cz: (minZ + maxZ) / 2 };
}

// The street kinds (bake_roads.mjs: 1 + the kind's index in mpls-geo.js ROAD_KINDS; 0 a road bridge) and where their
// sidewalks run, out from the centreline past the half width, as mpls-geo.js streetGeo draws them: wide sidewalks to
// the curb on the main streets, a grass boulevard and then the sidewalk elsewhere, none along the freeways and bridges
const MAIN_WALK = [0.3, 3.0], WALK = [2.4, 3.9];
const walkBand = (ni) => (ni === 0 || [8, 9, 13, 14].includes(ni) ? null : ni === 11 || ni === 12 ? MAIN_WALK : WALK);
const WALK_CELL = 32;

/** The street surfaces from the street graph; returns sidewalkAt(x, z): 'road' (on a street or its curb), 'walk' (on
 *  a sidewalk) or null (anywhere else). */
export function buildSidewalks(graph) {
  const cells = new Map();
  const node = (i) => [graph.nodes[i * 2], graph.nodes[i * 2 + 1]];
  for (const [a, b, ni, w, , , inner] of graph.links) {
    const pts = [node(a)];
    for (let k = 0; k < inner.length; k += 2) pts.push([inner[k], inner[k + 1]]);
    pts.push(node(b));
    const hw = w / 2, band = walkBand(ni), far = hw + (band ? band[1] : 0.3);
    for (let k = 0; k + 1 < pts.length; k++) {
      const [ax, az] = pts[k], [bx, bz] = pts[k + 1];
      const s = { ax, az, bx, bz, hw, band };
      for (let i = Math.floor((Math.min(ax, bx) - far) / WALK_CELL); i <= Math.floor((Math.max(ax, bx) + far) / WALK_CELL); i++) {
        for (let j = Math.floor((Math.min(az, bz) - far) / WALK_CELL); j <= Math.floor((Math.max(az, bz) + far) / WALK_CELL); j++) {
          const key = i * 100000 + j;
          if (!cells.has(key)) cells.set(key, []);
          cells.get(key).push(s);
        }
      }
    }
  }
  function sidewalkAt(x, z) {
    let walk = false;
    for (const s of cells.get(Math.floor(x / WALK_CELL) * 100000 + Math.floor(z / WALK_CELL)) || []) {
      const dx = s.bx - s.ax, dz = s.bz - s.az;
      const t = Math.max(0, Math.min(1, ((x - s.ax) * dx + (z - s.az) * dz) / (dx * dx + dz * dz || 1)));
      const d = Math.hypot(x - s.ax - dx * t, z - s.az - dz * t) - s.hw;
      if (d < 0.3) return 'road';
      if (s.band && d >= s.band[0] && d <= s.band[1]) walk = true;
    }
    return walk ? 'walk' : null;
  }
  /** The sidewalk (x, z) is on: { hw, main (a main street's, to the curb), px, pz (the nearest point of the street's
   *  centreline), r (how far from it) }, or null. */
  sidewalkAt.walkOf = (x, z) => {
    for (const s of cells.get(Math.floor(x / WALK_CELL) * 100000 + Math.floor(z / WALK_CELL)) || []) {
      if (!s.band) continue;
      const dx = s.bx - s.ax, dz = s.bz - s.az;
      const t = Math.max(0, Math.min(1, ((x - s.ax) * dx + (z - s.az) * dz) / (dx * dx + dz * dz || 1)));
      const px = s.ax + dx * t, pz = s.az + dz * t, r = Math.hypot(x - px, z - pz);
      if (r - s.hw >= s.band[0] && r - s.hw <= s.band[1]) return { hw: s.hw, main: s.band === MAIN_WALK, px, pz, r };
    }
    return null;
  };
  /** [Mpls] The street whose roadway (x, z) is in, the nearest if more than one: { hw, px, pz, r } as walkOf's, or null. */
  sidewalkAt.roadOf = (x, z) => {
    let best = null;
    for (const s of cells.get(Math.floor(x / WALK_CELL) * 100000 + Math.floor(z / WALK_CELL)) || []) {
      const dx = s.bx - s.ax, dz = s.bz - s.az;
      const t = Math.max(0, Math.min(1, ((x - s.ax) * dx + (z - s.az) * dz) / (dx * dx + dz * dz || 1)));
      const px = s.ax + dx * t, pz = s.az + dz * t, r = Math.hypot(x - px, z - pz);
      if (r - s.hw < 0.3 && (!best || r - s.hw < best.r - best.hw)) best = { hw: s.hw, px, pz, r };
    }
    return best;
  };
  return sidewalkAt;
}
