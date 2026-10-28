// Minneapolis's city geometry, from the baked tiles in city/ (tools/mpls-drive/bake_tiles.py): the big
// buildings, houses, garages, fences, street signs, streets with their curbs, sidewalks and paint, street lamp spots
// and bridge decks. Pure JavaScript with no three.js objects, so it runs in mpls-worker.js: each piece comes back as
// flat typed arrays that the main thread (mpls-city.js) only has to wrap in a BufferGeometry and upload.
//
// Units are metres: x east, z south, y up, centred on 44.966 N, 93.259 W. Heights come from the LiDAR ground grid
// (setGround), so everything stands on the hills and the streets follow them.
import { ShapeUtils, Vector2 } from './mpls-shapeutils.js';

export const LAT0 = 44.966, LON0 = -93.259;
export function cityXZ(lat, lon) {
  return [(lon - LON0) * 111320 * Math.cos(LAT0 * Math.PI / 180), -(lat - LAT0) * 110574];
}
export function cityLatLon(x, z) {
  return [LAT0 - z / 110574, LON0 + x / (111320 * Math.cos(LAT0 * Math.PI / 180))];
}
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/* ---------------------------------- Colour ----------------------------------
   Vertex colours are in three.js's linear working space, as new THREE.Color('#hex') would give them.            */
const toLinear = (c) => (c < 0.04045 ? c * 0.0773993808 : Math.pow(c * 0.9478672986 + 0.0521327014, 2.4));
export function color(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [toLinear((n >> 16 & 255) / 255), toLinear((n >> 8 & 255) / 255), toLinear((n & 255) / 255)];
}
const scaled = (c, k) => [c[0] * k, c[1] * k, c[2] * k];

/* ------------------------------ Lie of the land ------------------------------
   The ground's real height from the 2022 LiDAR survey (city/ground.bin): a node every GR.step metres from the map's
   corner. Between nodes the height follows the same two triangles a cell of the ground mesh is cut into, so
   everything set on groundH() sits exactly on the ground you see.                                                */
const GR = { x0: 0, z0: 0, step: 10, nx: 2, nz: 2, h: new Float32Array(4) };
export function setGround(g) { Object.assign(GR, g); }
export function groundH(x, z) {
  const fx = clamp((x - GR.x0) / GR.step, 0, GR.nx - 1.001), fz = clamp((z - GR.z0) / GR.step, 0, GR.nz - 1.001);
  const i = fx | 0, j = fz | 0, u = fx - i, v = fz - j, k = j * GR.nx + i, H = GR.h;
  return u + v <= 1 ? H[k] + (H[k + 1] - H[k]) * u + (H[k + GR.nx] - H[k]) * v
    : H[k + GR.nx + 1] + (H[k + GR.nx] - H[k + GR.nx + 1]) * (1 - u) + (H[k + 1] - H[k + GR.nx + 1]) * (1 - v);
}
/** city/ground.bin: rows of int16 centimetre steps from the node before. */
export function decodeGround(buf, gr) {
  const d = new Int16Array(buf), h = new Float32Array(gr.nx * gr.nz);
  for (let j = 0; j < gr.nz; j++) {
    let acc = 0;
    for (let i = 0; i < gr.nx; i++) { acc += d[j * gr.nx + i]; h[j * gr.nx + i] = acc / 100; }
  }
  return h;
}
/** A spot on the ground for something standing on these footprint points: its height there, and how far below that the lowest point is. */
function seat(pts) {
  let sum = 0, lo = Infinity;
  for (const [x, z] of pts) { const h = groundH(x, z); sum += h; lo = Math.min(lo, h); }
  const y = sum / pts.length;
  return { y, foot: lo - y < -0.05 ? lo - y - 0.15 : 0 };
}

/* -------------------------------- Facades --------------------------------
   Walls and roofs share one texture array of facades (tex/, tools/mpls-drive/make_textures.py): brick
   and concrete with a window per bay and per floor, glass curtain walls, storefronts, clapboard, shingles.          */
export const LAYER = {
  brickRed: 0, brickLite: 1, concRibbon: 2, glass: 3, storefront: 4, sidingWin: 5, siding: 6, garageDoor: 7,
  sidingDoor: 8, brickRedPlain: 9, brickLitePlain: 10, concPlain: 11, shingles: 12, gravel: 13, fence: 14, metal: 15,
  asphalt: 16, sidewalk: 17, paint: 18, grass: 19,
  // [Mpls] houses by what the assessor says their walls are
  stuccoWin: 20, stuccoPlain: 21, stuccoDoor: 22, brickHouseWin: 23, brickHouseDoor: 24, shakesWin: 25, shakesPlain: 26, shakesDoor: 27,
};
// The metres one tile of each layer covers (make_textures.py LAYERS), and the window-less version of each facade.
const LAYER_M = [[2.4, 3.6], [2.4, 3.6], [3, 3.6], [1.5, 3.6], [4.8, 4.5], [2.4, 2.9], [2.4, 2.9], [3, 2.6],
  [2.4, 2.9], [2.4, 3.6], [2.4, 3.6], [3, 3.6], [2, 2], [4, 4], [2.4, 1.8], [1, 1], [4, 4], [1.5, 1.5], [1, 1], [2.8, 2.8],
  [2.4, 2.9], [2.4, 2.9], [2.4, 2.9], [2.4, 2.9], [2.4, 2.9], [2.4, 2.9], [2.4, 2.9], [2.4, 2.9]];
const PLAIN = [9, 10, 11, 3, 9, 6, 6, 6, 6, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 21, 21, 9, 9, 26, 26, 26];
// [Mpls] A house's walls (bake_tiles.py: flags >> 2): window, door and plain layers for clapboard, stucco, brick, shakes
const HOUSE_LAYERS = [[LAYER.sidingWin, LAYER.sidingDoor], [LAYER.stuccoWin, LAYER.stuccoDoor], [LAYER.brickHouseWin, LAYER.brickHouseDoor],
  [LAYER.shakesWin, LAYER.shakesDoor]];

const ROOF_GREY = ['#a8a59e', '#b9b5ad', '#9d9a94', '#c4c0b6', '#8f8d88'].map(color);
const PAL = { walls: [], houseWall: [], houseRoof: [], boxWall: [], roofs: [] };     // filled from index.json
export function setPalette(index) {
  for (const k of Object.keys(PAL)) PAL[k] = (index[k] || []).map(color);
}
// [Mpls] Roof colours come from the aerial photo (bake_tiles.py), which sees a roof's colour; shingles and gravel are
// darker than that on average in the texture array, so these bring them back up to it.
const SHINGLE_LIFT = 1.35, GRAVEL_LIFT = 1.5;
const lifted = (c, k) => [Math.min(1, c[0] * k), Math.min(1, c[1] * k), Math.min(1, c[2] * k)];
const WHITE = color('#f2f1ec'), CONCRETE = color('#c9c5bc'), BRICK = color('#ffffff');

/** A small deterministic random sequence, so the same building always gets the same details. */
function rand(seed) {
  let s = (Math.abs(Math.floor(seed)) % 2147483646) + 1;
  return () => (s = s * 16807 % 2147483647) / 2147483647;
}

/**
 * Collects triangles with a texture layer, a tint and an occlusion value per corner, then becomes flat arrays.
 * Heights are given from the ground: either lifted as one by y0 (a building stands level at y0, its walls running
 * down foot metres more to meet the lowest ground round it), or, with drape, each corner by the ground under it
 * (streets and paint, which follow the land).
 */
export class Geo {
  constructor(drape = false) { this.p = []; this.uv = []; this.la = []; this.c = []; this.drape = drape; this.y0 = 0; this.foot = 0; }
  /** Stand what comes next on the ground under these footprint points. */
  seat(pts) { const s = seat(pts); this.y0 = s.y; this.foot = s.foot; return s.y; }
  tri(a, b, c, ua, ub, uc, layer, col, aa = 1, ab = 1, ac = 1) {
    if (this.drape) this.p.push(a[0], a[1] + groundH(a[0], a[2]), a[2], b[0], b[1] + groundH(b[0], b[2]), b[2], c[0], c[1] + groundH(c[0], c[2]), c[2]);
    else this.p.push(a[0], a[1] + this.y0, a[2], b[0], b[1] + this.y0, b[2], c[0], c[1] + this.y0, c[2]);
    this.uv.push(ua[0], ua[1], ub[0], ub[1], uc[0], uc[1]);
    const r = Math.round(col[0] * 255), g = Math.round(col[1] * 255), bl = Math.round(col[2] * 255);
    for (const ao of [aa, ab, ac]) {
      this.la.push(layer, Math.round(ao * 255));
      this.c.push(r, g, bl, 255);
    }
  }
  /** Corners counter-clockwise; one uv and one occlusion value per corner. */
  quad(a, b, c, d, ua, ub, uc, ud, layer, col, ao = null) {
    const [o0, o1, o2, o3] = ao || [1, 1, 1, 1];
    this.tri(a, b, c, ua, ub, uc, layer, col, o0, o1, o2);
    this.tri(a, c, d, ua, uc, ud, layer, col, o0, o2, o3);
  }
  /** { position, normal, uv, la, color } typed arrays, or null when empty. */
  arrays() {
    if (!this.p.length) return null;
    const position = Float32Array.from(this.p);
    return {
      position, normal: flatNormals(position), uv: Float32Array.from(this.uv),
      la: Uint8Array.from(this.la), color: Uint8Array.from(this.c),
    };
  }
}
/** Per-triangle normals for unindexed triangles (what computeVertexNormals gives them). */
export function flatNormals(p) {
  const n = new Float32Array(p.length);
  for (let i = 0; i < p.length; i += 9) {
    const ax = p[i + 3] - p[i], ay = p[i + 4] - p[i + 1], az = p[i + 5] - p[i + 2];
    const bx = p[i + 6] - p[i], by = p[i + 7] - p[i + 1], bz = p[i + 8] - p[i + 2];
    let x = ay * bz - az * by, y = az * bx - ax * bz, z = ax * by - ay * bx;
    const L = Math.hypot(x, y, z) || 1;
    x /= L; y /= L; z /= L;
    for (let k = 0; k < 9; k += 3) { n[i + k] = x; n[i + k + 1] = y; n[i + k + 2] = z; }
  }
  return n;
}

/**
 * A wall from a to b ([x, z]) between heights y0 and y1: whole window bays across it, a row of windows per floor,
 * any band left at the top in the plain version, and a darker foot where it meets the ground.
 */
function wall(G, a, b, y0, y1, layer, col) {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (len < 0.05 || y1 - y0 < 0.05) return;
  const [bw, fh] = LAYER_M[layer];
  const bays = Math.max(1, Math.round(len / bw));
  const rows = Math.max(1, Math.floor((y1 - y0) / fh + 0.25));
  const top = Math.min(y1, y0 + rows * fh);
  const v = (y) => (y - y0) / (top - y0) * rows;
  if (y0 < 0.1 && G.foot < -0.05) {
    // On a slope the wall carries on down, plain and dark, to meet the ground on the low side.
    const pl = PLAIN[layer], [pw, ph] = LAYER_M[pl], pb = Math.max(1, Math.round(len / pw));
    G.quad([a[0], G.foot, a[1]], [b[0], G.foot, b[1]], [b[0], y0, b[1]], [a[0], y0, a[1]],
      [0, G.foot / ph], [pb, G.foot / ph], [pb, y0 / ph], [0, y0 / ph], pl, col, [0.45, 0.45, 0.5, 0.5]);
  }
  const band = (ya, yb, lay, va, vb, oa, ob) => G.quad(
    [a[0], ya, a[1]], [b[0], ya, b[1]], [b[0], yb, b[1]], [a[0], yb, a[1]],
    [0, va], [bays, va], [bays, vb], [0, vb], lay, col, [oa, oa, ob, ob]);
  let y = y0;
  if (y0 < 0.1 && top > 1.4) {
    band(0, 1.2, layer, v(0), v(1.2), 0.5, 0.97);
    y = 1.2;
  }
  band(y, top, layer, v(y), v(top), y0 < 0.1 && y === 0 ? 0.6 : 0.97, 1);
  if (y1 > top + 0.05) {
    const plain = PLAIN[layer], [pw, ph] = LAYER_M[plain];
    const pb = Math.max(1, Math.round(len / pw));
    G.quad([a[0], top, a[1]], [b[0], top, b[1]], [b[0], y1, b[1]], [a[0], y1, a[1]],
      [0, 0], [pb, 0], [pb, (y1 - top) / ph], [0, (y1 - top) / ph], plain, col);
  }
}
/** A flat roof (or floor) over a ring, holes cut out, textured in metres. */
function flatRoof(G, rings, y, layer, col) {
  const pts = rings.flat();
  const [lw, lh] = LAYER_M[layer];
  const contour = rings[0].map(([x, z]) => new Vector2(x, z));
  const holes = rings.slice(1).map(r => r.map(([x, z]) => new Vector2(x, z)));
  for (const [i, j, k] of ShapeUtils.triangulateShape(contour, holes)) {
    const P = (n) => [pts[n][0], y, pts[n][1]], U = (n) => [pts[n][0] / lw, pts[n][1] / lh];
    G.tri(P(i), P(j), P(k), U(i), U(j), U(k), layer, col);
  }
}
/** An upright box turned by ang, its sides one layer and its top another. */
function boxGeo(G, cx, y0, cz, sx, sy, sz, ang, side, top, col, topCol = col) {
  const cs = Math.cos(ang), sn = Math.sin(ang);
  const c = [[-sx / 2, -sz / 2], [sx / 2, -sz / 2], [sx / 2, sz / 2], [-sx / 2, sz / 2]]
    .map(([u, w]) => [cx + u * cs - w * sn, cz + u * sn + w * cs]);
  for (let i = 0; i < 4; i++) wall(G, c[i], c[(i + 1) % 4], y0, y0 + sy, side, col);
  flatRoof(G, [c], y0 + sy, top, topCol);
}
function shrink(ring, k) {
  let cx = 0, cz = 0;
  for (const [x, z] of ring) { cx += x; cz += z; }
  cx /= ring.length; cz /= ring.length;
  return ring.map(([x, z]) => [cx + (x - cx) * k, cz + (z - cz) * k]);
}
function pointInRing(x, z, r) {
  let hit = false;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
    if ((r[i][1] > z) !== (r[j][1] > z) && x < r[j][0] + (z - r[j][1]) * (r[i][0] - r[j][0]) / (r[i][1] - r[j][1])) hit = !hit;
  }
  return hit;
}

/** A building record's rings ([[x, z], ...] each), its centre, and how far its points lie from it on average. */
function buildingRings(b) {
  const rings = [];
  for (let k = 6; k < b.length;) {
    const len = b[k++], ring = [];
    for (let e = 0; e < len; e++, k += 2) ring.push([b[k], b[k + 1]]);
    rings.push(ring);
  }
  let cx = 0, cz = 0;
  for (const [x, z] of rings[0]) { cx += x; cz += z; }
  cx /= rings[0].length; cz /= rings[0].length;
  let rad = 0;
  for (const [x, z] of rings[0]) rad += Math.hypot(x - cx, z - cz);
  return { rings, cx, cz, rad: rad / rings[0].length };
}

/** One big building: facade walls (storefront below if it has one), a gravel roof, and a parapet with rooftop plant. */
function building(G, S, b) {
  const [fac, tint, H10, H010, flags] = b;
  const H = H10 / 10, H0 = H010 / 10;
  const { rings, cx, cz, rad } = buildingRings(b);
  // Neighbours and stacked 3D parts often share a wall line. Pull each one in a few
  // centimetres, taller ones more, so no two walls ever sit in the same plane and flicker.
  const k = 1 - (0.04 + H * 0.0015) / Math.max(4, rad);
  for (const ring of rings) for (const p of ring) { p[0] = cx + (p[0] - cx) * k; p[1] = cz + (p[1] - cz) * k; }
  if (S) {
    // Anything starting above head height (skyways, canopies) can be driven under.
    const base = seat(rings[0]).y;
    if (H0 < 3) for (const ring of rings) for (let i = 0; i < ring.length; i++) {
      const a = ring[i], c2 = ring[(i + 1) % ring.length];
      S.add(a[0], a[1], c2[0], c2[1], 0, base + H);
    }
    const xs = rings[0].map((p) => p[0]), zs = rings[0].map((p) => p[1]);
    S.block(Math.min(...xs), Math.min(...zs), Math.max(...xs), Math.max(...zs), base + H0 - 1, base + H);
    return;
  }
  G.seat(rings[0]);
  const col = PAL.walls[tint];
  const R = rand(cx * 31 + cz * 17);
  const seen = (flags >> 2) - 1;                       // [Mpls] the roof's colour in the aerial photo
  const roofCol = seen >= 0 && PAL.roofs[seen] ? lifted(PAL.roofs[seen], GRAVEL_LIFT) : ROOF_GREY[Math.floor(R() * ROOF_GREY.length)];
  const tall = H >= 50 && H0 === 0 && rings.length === 1;
  const body = tall ? H * 0.86 : H;
  for (const ring of rings) for (let i = 0; i < ring.length; i++) {
    const a = ring[i], c2 = ring[(i + 1) % ring.length];
    if (flags & 1) {
      wall(G, a, c2, H0, Math.min(body, 4.5), LAYER.storefront, col);
      if (body > 4.6) wall(G, a, c2, 4.5, body, fac, col);
    } else {
      wall(G, a, c2, H0, body, fac, col);
    }
  }
  if (tall) {
    // Towers step back near the top, then a darker crown.
    const mid = shrink(rings[0], 0.8), crown = shrink(rings[0], 0.55);
    flatRoof(G, rings, body, LAYER.gravel, roofCol);
    for (let i = 0; i < mid.length; i++) wall(G, mid[i], mid[(i + 1) % mid.length], body, H * 0.96, fac, col);
    flatRoof(G, [mid], H * 0.96, LAYER.gravel, roofCol);
    const dark = scaled(col, 0.7);
    for (let i = 0; i < crown.length; i++) wall(G, crown[i], crown[(i + 1) % crown.length], H * 0.96, H, PLAIN[fac], dark);
    flatRoof(G, [crown], H, LAYER.metal, dark);
    return;
  }
  flatRoof(G, rings, H, LAYER.gravel, roofCol);
  if (flags & 2) {
    // A parapet round the edge, and some rooftop units on bigger roofs.
    const inner = shrink(rings[0], Math.max(0.5, 1 - 0.35 / Math.max(4, rad)));
    for (let i = 0; i < rings[0].length; i++) {
      const a = rings[0][i], c2 = rings[0][(i + 1) % rings[0].length];
      wall(G, a, c2, H, H + 0.9, PLAIN[fac], col);
      wall(G, inner[(i + 1) % inner.length], inner[i], H, H + 0.9, PLAIN[fac], col);
      G.quad([a[0], H + 0.9, a[1]], [c2[0], H + 0.9, c2[1]], [inner[(i + 1) % inner.length][0], H + 0.9, inner[(i + 1) % inner.length][1]],
        [inner[i][0], H + 0.9, inner[i][1]], [0, 0], [1, 0], [1, 0.1], [0, 0.1], LAYER.concPlain, CONCRETE);
    }
    const xs = rings[0].map(p => p[0]), zs = rings[0].map(p => p[1]);
    const area = (Math.max(...xs) - Math.min(...xs)) * (Math.max(...zs) - Math.min(...zs));
    const units = Math.min(6, Math.floor(area / 600));
    for (let n = 0, tries = 0; n < units && tries < 30; tries++) {
      const x = Math.min(...xs) + R() * (Math.max(...xs) - Math.min(...xs)), z = Math.min(...zs) + R() * (Math.max(...zs) - Math.min(...zs));
      if (!pointInRing(x, z, inner)) continue;
      boxGeo(G, x, H, z, 2 + R() * 3, 1.2 + R() * 1.4, 1.6 + R() * 2.5, R() * 3, LAYER.metal, LAYER.metal, WHITE);
      n++;
    }
  }
}

/** Local frame of a box: world point for local (u along its length, y, w across it). */
function localFrame(x, z, ang) {
  const cs = Math.cos(ang), sn = Math.sin(ang);
  return (u, y, w) => [x + u * cs - w * sn, y, z + u * sn + w * cs];
}
// The two corners of each side (0 +x, 1 -x, 2 +z, 3 -z) of a box W long and D deep, in local (u, w).
const SIDES = (W, D) => [[[W / 2, -D / 2], [W / 2, D / 2]], [[-W / 2, D / 2], [-W / 2, -D / 2]],
  [[W / 2, D / 2], [-W / 2, D / 2]], [[-W / 2, -D / 2], [W / 2, -D / 2]]];

/**
 * A pitched or flat roof over a W by D box from height eave to ridge, with a little overhang.
 * kind 1: ridge along the length, 2: ridge across, 3: hipped, 0: flat. End gables take the wall colour.
 */
function roofGeo(G, P, W, D, eave, ridge, kind, roofCol, wallCol, wallLayer) {
  const o = 0.35;
  if (kind === 0 || ridge - eave < 0.3) {
    const c = [[-W / 2 - 0.15, -D / 2 - 0.15], [W / 2 + 0.15, -D / 2 - 0.15], [W / 2 + 0.15, D / 2 + 0.15], [-W / 2 - 0.15, D / 2 + 0.15]];
    G.quad(...c.map(([u, w]) => P(u, eave, w)), ...c.map(([u, w]) => [u / 4, w / 4]), LAYER.gravel, ROOF_GREY[0]);
    return;
  }
  // Work in a frame where the ridge runs along u: L long, S the span across it.
  const across = kind === 2;
  const L = across ? D : W, S = across ? W : D;
  const Q = across ? (u, y, w) => P(w, y, -u) : P;
  const rise = ridge - eave, half = S / 2;
  const ye = eave - o * rise / half;                         // the eave, dropped by the overhang
  const slopeLen = Math.hypot(half + o, rise + o * rise / half);
  const r = kind === 3 ? Math.max(0, (L - S) / 2) : L / 2 + o; // half-length of the ridge
  const Lo = L / 2 + o;
  for (const s of [-1, 1]) {
    // The long slopes: eave edge to ridge.
    G.quad(Q(-Lo, ye, s * (half + o)), Q(Lo, ye, s * (half + o)), Q(r, ridge, 0), Q(-r, ridge, 0),
      [-Lo / 2, 0], [Lo / 2, 0], [r / 2, slopeLen / 2], [-r / 2, slopeLen / 2], LAYER.shingles, roofCol);
    if (kind === 3) {
      // Hip ends.
      G.tri(Q(s * Lo, ye, -(half + o)), Q(s * Lo, ye, half + o), Q(s * r, ridge, 0),
        [-(half + o) / 2, 0], [(half + o) / 2, 0], [0, slopeLen / 2], LAYER.shingles, roofCol);
    } else {
      // Gable ends, in the wall's siding.
      const [, fh] = LAYER_M[wallLayer];
      G.tri(Q(s * L / 2, eave, -half), Q(s * L / 2, eave, half), Q(s * L / 2, ridge, 0),
        [0, 0], [S / 2.4, 0], [S / 4.8, rise / fh], PLAIN[wallLayer], wallCol);
    }
  }
}

/**
 * A house: walls with windows (clapboard, stucco, brick or cedar shakes, as the assessor has them), a front door toward
 * the street, its roof (in the aerial photo's colour), maybe a porch and a chimney.
 */
function houseGeo(G, h) {
  const [x10, z10, a100, w10, d10, e10, r10, kind, front, wc, rc, flags] = h;
  const x = x10 / 10, z = z10 / 10, ang = a100 / 100, W = w10 / 10, D = d10 / 10, eave = e10 / 10, ridge = r10 / 10;
  const P = localFrame(x, z, ang);
  const [winLayer, doorLayer] = HOUSE_LAYERS[(flags >> 2) & 3];
  const wallCol = PAL.houseWall[wc], roofCol = lifted(PAL.houseRoof[rc], PAL.roofs.length ? SHINGLE_LIFT : 1);
  const sides = SIDES(W, D);
  G.seat(sides.map(([a]) => { const q = P(a[0], 0, a[1]); return [q[0], q[2]]; }));
  sides.forEach(([a, b], side) => {
    const A = P(a[0], 0, a[1]), B = P(b[0], 0, b[1]);
    const pa = [A[0], A[2]], pb = [B[0], B[2]];
    if (side !== front) { wall(G, pa, pb, 0, eave, winLayer, wallCol); return; }
    // The front: a door in the middle bay of the ground floor, windows either side.
    const len = Math.hypot(pb[0] - pa[0], pb[1] - pa[1]);
    const bays = Math.max(1, Math.round(len / 2.4)), mid = Math.floor(bays / 2), gf = Math.min(eave, 2.9);
    for (let i = 0; i < bays; i++) {
      const t0 = i / bays, t1 = (i + 1) / bays;
      const p0 = [pa[0] + (pb[0] - pa[0]) * t0, pa[1] + (pb[1] - pa[1]) * t0], p1 = [pa[0] + (pb[0] - pa[0]) * t1, pa[1] + (pb[1] - pa[1]) * t1];
      wall(G, p0, p1, 0, gf, i === mid ? doorLayer : winLayer, wallCol);
    }
    if (eave > gf + 0.05) wall(G, pa, pb, gf, eave, winLayer, wallCol);
  });
  roofGeo(G, P, W, D, eave, ridge, kind, roofCol, wallCol, winLayer);
  const R = rand(x10 * 7 + z10 * 13);
  if ((flags & 1) && kind) {
    // A brick chimney poking through one slope.
    const across = kind === 2, half = (across ? W : D) / 2;
    const off = half * 0.45, at = (across ? D : W) * (R() * 0.5 - 0.25);
    const base = ridge - (ridge - eave) * off / half - 0.3;
    const [cxw, , czw] = across ? P(-off, 0, at) : P(at, 0, -off);
    boxGeo(G, cxw, base, czw, 0.75, ridge + 0.9 - base, 0.75, ang, LAYER.brickRedPlain, LAYER.concPlain, BRICK, CONCRETE);
  }
  if ((flags & 2) && front >= 0) {
    // A front porch: a deck, two posts and a shallow roof.
    const [a, b] = sides[front];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]), pw = Math.min(len * 0.7, 6), pd = 2.2;
    const nu = front === 0 ? 1 : front === 1 ? -1 : 0, nw = front === 2 ? 1 : front === 3 ? -1 : 0;
    const mu = (a[0] + b[0]) / 2 + nu * pd / 2, mw = (a[1] + b[1]) / 2 + nw * pd / 2;
    const [px, , pz] = P(mu, 0, mw);
    const pang = ang + (nu ? Math.PI / 2 : 0);
    boxGeo(G, px, 0, pz, pw, 0.45, pd, pang, LAYER.concPlain, LAYER.concPlain, CONCRETE);
    for (const s of [-1, 1]) {
      const [qx, , qz] = P(mu + (nw ? s * (pw / 2 - 0.2) : nu * (pd / 2 - 0.2)), 0, mw + (nu ? s * (pw / 2 - 0.2) : nw * (pd / 2 - 0.2)));
      boxGeo(G, qx, 0.45, qz, 0.16, 2.35, 0.16, ang, LAYER.metal, LAYER.metal, WHITE);
    }
    boxGeo(G, px, 2.8, pz, pw + 0.3, 0.18, pd + 0.2, pang, LAYER.siding, LAYER.shingles, wallCol, roofCol);
  }
}

/** A detached garage: plain siding, a low gable roof, and its doors on the side that faces the alley. */
function garageGeo(G, g) {
  const [x10, z10, a100, w10, d10, h10, wc, door] = g;
  const x = x10 / 10, z = z10 / 10, ang = a100 / 100, W = w10 / 10, D = d10 / 10, H = h10 / 10;
  const P = localFrame(x, z, ang);
  // [Mpls] the wall tint in the low byte, 1 + the roof's colour in the aerial photo above it (bake_tiles.py)
  const col = PAL.boxWall[wc & 255], seen = (wc >> 8) - 1, eave = Math.max(2.3, H - 0.9);
  G.seat(SIDES(W, D).map(([a]) => { const q = P(a[0], 0, a[1]); return [q[0], q[2]]; }));
  SIDES(W, D).forEach(([a, b], side) => {
    const A = P(a[0], 0, a[1]), B = P(b[0], 0, b[1]);
    if (side === door) {
      wall(G, [A[0], A[2]], [B[0], B[2]], 0, Math.min(eave, 2.6), LAYER.garageDoor, col);
      if (eave > 2.65) wall(G, [A[0], A[2]], [B[0], B[2]], 2.6, eave, LAYER.siding, col);
    } else {
      wall(G, [A[0], A[2]], [B[0], B[2]], 0, eave, LAYER.siding, col);
    }
  });
  const roofCol = seen >= 0 && PAL.houseRoof[seen] ? lifted(PAL.houseRoof[seen], SHINGLE_LIFT) : PAL.houseRoof[((wc & 255) + 3) % PAL.houseRoof.length];
  roofGeo(G, P, W, D, eave, Math.max(eave + 0.5, H), 1, roofCol, col, LAYER.siding);
}

const FENCE_COLS = ['#b08f6a', '#9c9a94', '#eeeeea', '#8a6e52'].map(color);
const HEDGE = color('#3d6a34'), STONE = color('#cfc6b5');
const FENCE_H = [1.8, 1.2, 1.6, 0.9];      // kind 3: a low rail fence, as along the lake paths
/** Fences, garden walls and hedges along their mapped lines. */
function fenceGeo(G, f, seed) {
  const [kind, n] = f;
  const pts = [];
  for (let i = 0; i < n; i++) {
    const q = [f[2 + i * 2], f[3 + i * 2]];
    if (pts.length) {
      // Cut long runs into pieces of 4 m or so, so each can follow the ground.
      const [px, pz] = pts[pts.length - 1], k = Math.ceil(Math.hypot(q[0] - px, q[1] - pz) / 4);
      for (let s = 1; s < k; s++) pts.push([px + (q[0] - px) * s / k, pz + (q[1] - pz) * s / k]);
    }
    pts.push(q);
  }
  const col = kind === 0 || kind === 3 ? FENCE_COLS[Math.abs(seed) % FENCE_COLS.length] : kind === 1 ? STONE : HEDGE;
  const ht = FENCE_H[kind];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    G.seat([a, b]);
    if (kind === 0 || kind === 3) { wall(G, a, b, 0, ht, LAYER.fence, col); continue; }
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (len < 0.2) continue;
    boxGeo(G, (a[0] + b[0]) / 2, 0, (a[1] + b[1]) / 2, len + (kind === 2 ? 0.6 : 0.3), ht, kind === 2 ? 0.9 : 0.35,
      Math.atan2(b[1] - a[1], b[0] - a[0]), kind === 1 ? LAYER.brickLitePlain : LAYER.gravel, kind === 1 ? LAYER.concPlain : LAYER.gravel, col);
  }
}

/* ------------------------------- Streets -------------------------------
   Real road surfaces: asphalt with crisp edges, a curb, a grass boulevard and a concrete sidewalk, the markings each
   kind of road has in Minneapolis, round intersections and crosswalks at the busy ones.                          */
export const ROAD_KINDS = ['pedestrian', 'living_street', 'residential', 'unclassified', 'tertiary_link', 'secondary_link',
  'primary_link', 'trunk_link', 'motorway_link', 'tertiary', 'secondary', 'primary', 'trunk', 'motorway', 'path'];
const ASPHALT = { local: color('#8d9194'), major: color('#7d8286'), freeway: color('#878b8e') };
const CURB = color('#d9d6cf'), WALK = color('#eceae4');
const PAINT_WHITE = color('#f4f4f0'), PAINT_YELLOW = color('#f0c23a');
// (Draped over the ground, whose triangles they don't share, so they ride a few centimetres up.)
export const ROAD_Y = 0.07, WALK_Y = 0.09, PAINT_Y = 0.095;
const TRAIL = color('#dcd3c0'), BIKE_PATH = color('#9fa3a5');
// [Mpls] Bus-only lanes are painted red in Minneapolis; protected bike lanes are kept from the traffic by white posts
const PAINT_RED = color('#a8302c'), POST_WHITE = color('#f2f2ee');

/** A flat quad, wound to face up whatever order its corners come in. */
function upQuad(G, a, b, c, d, ua, ub, uc, ud, layer, col) {
  const nY = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]);
  if (nY >= 0) G.quad(a, b, c, d, ua, ub, uc, ud, layer, col);
  else G.quad(a, d, c, b, ua, ud, uc, ub, layer, col);
}
/** Cumulative length along a polyline. */
export function arcLengths(pts) {
  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  return cum;
}
/** The stretch of a polyline between two distances along it. */
function subPath(pts, cum, s0, s1) {
  const at = (s) => {
    let i = 1;
    while (i < pts.length - 1 && cum[i] < s) i++;
    const t = (s - cum[i - 1]) / ((cum[i] - cum[i - 1]) || 1);
    return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t];
  };
  const out = [at(s0)];
  for (let i = 0; i < pts.length; i++) if (cum[i] > s0 && cum[i] < s1) out.push(pts[i]);
  out.push(at(s1));
  return out;
}
/** Sideways unit normals at each point, mitred at the bends (and capped so hairpins don't spike). */
function miters(pts) {
  const seg = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const dx = pts[i + 1][0] - pts[i][0], dz = pts[i + 1][1] - pts[i][1], L = Math.hypot(dx, dz) || 1;
    seg.push([-dz / L, dx / L]);
  }
  return pts.map((_, i) => {
    const a = seg[Math.max(0, i - 1)], b = seg[Math.min(seg.length - 1, i)];
    let nx = a[0] + b[0], nz = a[1] + b[1];
    const L = Math.hypot(nx, nz) || 1;
    nx /= L; nz /= L;
    const k = Math.min(2, 1 / Math.max(0.5, nx * b[0] + nz * b[1]));
    return [nx * k, nz * k];
  });
}
/** The polyline with extra points so no stretch is longer than step metres, so a band laid on it follows the ground. */
function densify(pts, step) {
  const out = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    const [ax, az] = pts[i - 1], [bx, bz] = pts[i], k = Math.ceil(Math.hypot(bx - ax, bz - az) / step);
    for (let s = 1; s < k; s++) out.push([ax + (bx - ax) * s / k, az + (bz - az) * s / k]);
    out.push(pts[i]);
  }
  return out;
}
/**
 * A band along a polyline from offset d0 to d1 (metres to one side, negative the other).
 * uv 'world' tiles the layer in world space (seamless where pieces overlap); 'along' runs it down the band.
 */
function band(G, pts, d0, d1, y, layer, col, uv) {
  if (pts.length < 2) return;
  if (G.drape) pts = densify(pts, 3);
  const n = miters(pts), cum = arcLengths(pts);
  const [lw, lh] = LAYER_M[layer];
  const P = (i, d) => [pts[i][0] + n[i][0] * d, y, pts[i][1] + n[i][1] * d];
  const U = (i, d, p) => uv === 'world' ? [p[0] / lw, p[2] / lh] : [cum[i] / lw, (d - d0) / lh];
  // Laid on the ground, a wide band goes down in strips no wider than 2.5 m, so it bends across a slope too.
  const strips = G.drape ? Math.max(1, Math.ceil(Math.abs(d1 - d0) / 2.5)) : 1;
  for (let k = 0; k < strips; k++) {
    const e0 = d0 + (d1 - d0) * k / strips, e1 = d0 + (d1 - d0) * (k + 1) / strips;
    for (let i = 0; i < pts.length - 1; i++) {
      const a = P(i, e0), b = P(i + 1, e0), c = P(i + 1, e1), d = P(i, e1);
      upQuad(G, a, b, c, d, U(i, e0, a), U(i + 1, e0, b), U(i + 1, e1, c), U(i, e1, d), layer, col);
    }
  }
}

/**
 * Road markings for Slop New York's paint material: a strip along a polyline, d metres to one side, its corners
 * carrying the distance along (paint.x), the dash period and the share of it painted (paint.y, .z), and the way out
 * to the strip's edge (side), which the material widens far away so thin lines don't break up.
 */
export class PaintGeo {
  constructor() { this.p = []; this.c = []; this.paint = []; this.side = []; }
  vert(x, z, y, col, s, period, duty, sx, sz) {
    this.p.push(x, groundH(x, z) + y, z);
    this.c.push(col[0], col[1], col[2]);
    this.paint.push(s, period, duty);
    this.side.push(sx, sz);
  }
  strip(pts, d, width, col, period = 1, duty = 1, s0 = 0) {
    if (pts.length < 2) return;
    pts = densify(pts, 3);
    const n = miters(pts), cum = arcLengths(pts), hw = width / 2;
    for (let i = 0; i < pts.length - 1; i++) {
      const k = [i, i + 1].flatMap((j) => [-1, 1].map((e) => [pts[j][0] + n[j][0] * (d + e * hw), pts[j][1] + n[j][1] * (d + e * hw), cum[j] + s0, n[j][0] * e * hw, n[j][1] * e * hw]));
      for (const q of [k[0], k[2], k[3], k[0], k[3], k[1]]) this.vert(q[0], q[1], PAINT_Y, col, q[2], period, duty, q[3], q[4]);
    }
  }
  arrays() {
    if (!this.p.length) return null;
    const position = Float32Array.from(this.p);
    const normal = new Float32Array(position.length);
    for (let i = 1; i < normal.length; i += 3) normal[i] = 1;
    return { position, normal, color: Float32Array.from(this.c), paint: Float32Array.from(this.paint), side: Float32Array.from(this.side) };
  }
}
/** A dashed line: dash metres of paint every period metres. */
function dashes(P, pts, d, width, dash, period, col) {
  const L = arcLengths(pts).at(-1);
  // The dashes sit centred on the stretch: the first starts (L mod period) / 2 in.
  P.strip(pts, d, width, col, period, dash / period, period / 2 - (L % period) / 2 - dash / 2);
}

/** A street record's centreline as [[x, z], ...]. */
export function roadPoints(r) {
  const n = r[6], pts = [];
  for (let i = 0; i < n; i++) pts.push([r[7 + i * 2] / 10, r[8 + i * 2] / 10]);
  return pts;
}

/**
 * One street piece: its asphalt (or [Mpls] concrete or brick, as the city's pavement map has it), and (stopping short
 * of the intersections) curbs, sidewalks and markings, with its bike lanes as the city's bikeway map has them.
 */
function streetGeo(S, r) {
  const [cls, w10, lanesTag, oneway, t010, t110, n] = r;
  const surface = r[7 + n * 2] || 0, bike = r[8 + n * 2] || 0;
  const pts = roadPoints(r);
  const kind = ROAD_KINDS[cls], w = w10 / 10, hw = w / 2;
  if (kind === 'path') {
    // A trail: crushed stone for walking, asphalt for the bike paths.
    band(S.trail, pts, -hw, hw, WALK_Y, w > 3 ? LAYER.asphalt : LAYER.sidewalk, w > 3 ? BIKE_PATH : TRAIL, 'world');
    return;
  }
  const freeway = /^(motorway|trunk)/.test(kind), major = /^(primary|secondary|tertiary)$/.test(kind);
  // Concrete and brick are laid out along the street (uv: metres along it and across it from one side), so the joints
  // and the courses run with it
  if (surface === 1 || surface === 2) band(surface === 1 ? S.concrete : S.brick, pts, -hw, hw, ROAD_Y, LAYER.metal, WHITE, 'along');
  else band(S.road, pts, -hw, hw, ROAD_Y, LAYER.asphalt, freeway ? ASPHALT.freeway : major ? ASPHALT.major : ASPHALT.local, 'world');
  const cum = arcLengths(pts), L = cum[cum.length - 1];
  const s0 = t010 / 10, s1 = L - t110 / 10;
  if (s1 - s0 < 2) return;
  const inner = subPath(pts, cum, s0, s1);
  if (!freeway) {
    for (const s of [-1, 1]) {
      band(S.curb, inner, s * hw, s * (hw + 0.3), WALK_Y, LAYER.sidewalk, CURB, 'along');
      // Downtown-style main streets have wide sidewalks to the curb; elsewhere a grass boulevard comes first.
      const [a, b] = kind === 'primary' || kind === 'secondary' ? [hw + 0.3, hw + 3.0] : [hw + 2.4, hw + 3.9];
      band(S.walk, inner, s * a, s * b, WALK_Y, LAYER.sidewalk, WALK, 'along');
    }
  }
  const lanes = lanesTag || Math.max(1, Math.round(w / 3.6));
  if (freeway) {
    for (const s of [-1, 1]) S.paint.strip(inner, s * (hw - 0.375), 0.15, s < 0 && oneway ? PAINT_YELLOW : PAINT_WHITE);
  }
  if (oneway || freeway) {
    for (let k = 1; k < lanes; k++) dashes(S.paint, inner, -hw + w * k / lanes, 0.13, 3, 12, PAINT_WHITE);
  } else if (major || /_link$/.test(kind)) {
    // A double yellow down the middle, and dashed white between lanes on four-lane streets.
    for (const s of [-1, 1]) S.paint.strip(inner, s * 0.135, 0.13, PAINT_YELLOW);
    if (lanes >= 4) for (const s of [-1, 1]) dashes(S.paint, inner, s * hw / 2, 0.13, 3, 12, PAINT_WHITE);
  }
  if (bike && bike < 5 && !freeway && w > 7) {
    // Along the curb on each side (just the right-hand one, +d, of a one-way street): a bike lane's line, a buffered
    // lane's two, a protected lane's line and posts, or a red bus lane
    for (const s of oneway ? [1] : [-1, 1]) {
      if (bike === 4) { S.paint.strip(inner, s * (hw - 1.7), 3.2, PAINT_RED); continue; }
      S.paint.strip(inner, s * (hw - 1.8), 0.15, PAINT_WHITE);
      if (bike === 2) S.paint.strip(inner, s * (hw - 2.7), 0.15, PAINT_WHITE);
      if (bike === 3) {
        const c2 = arcLengths(inner), Ln = c2[c2.length - 1];
        for (let d = 3; d < Ln - 3; d += 6) {
          const q = subPath(inner, c2, d, d + 0.1), [ax, az] = q[0], [bx, bz] = q[q.length - 1], L = Math.hypot(bx - ax, bz - az) || 1;
          S.posts.push(ax - (bz - az) / L * s * (hw - 2.1), az + (bx - ax) / L * s * (hw - 2.1));
        }
      }
    }
  }
}

/** Where a street's lamps stand: [x, z, angle that turns the arm (+x) out over the street]. */
function lampSpots(r, out) {
  const [cls, w10, , , t010, t110, n] = r;
  const kind = ROAD_KINDS[cls];
  if (kind === 'path' || kind === 'pedestrian' || /^(motorway|trunk)/.test(kind)) return;
  const pts = roadPoints(r);
  const cum = arcLengths(pts), L = cum[cum.length - 1], s0 = t010 / 10 + 4, s1 = L - t110 / 10 - 4;
  if (s1 - s0 < 6) return;
  const hw = w10 / 20, main = kind === 'primary' || kind === 'secondary' || kind === 'tertiary';
  const gap = main ? 34 : 48, off = main ? hw + 0.7 : hw + 1.3;
  const sides = main ? [1, -1] : [(cls + n) % 2 ? 1 : -1];
  for (const side of sides) {
    for (let s = s0 + (side < 0 ? gap / 2 : 0) + ((s1 - s0) % gap) / 2; s <= s1; s += gap) {
      let i = 1;
      while (i < pts.length - 1 && cum[i] < s) i++;
      const sl = cum[i] - cum[i - 1] || 1, u = (s - cum[i - 1]) / sl;
      const ux = (pts[i][0] - pts[i - 1][0]) / sl, uz = (pts[i][1] - pts[i - 1][1]) / sl;
      const nx = -uz * side, nz = ux * side;          // out from the street's middle to this side
      out.push(pts[i - 1][0] + ux * sl * u + nx * off, pts[i - 1][1] + uz * sl * u + nz * off, Math.atan2(nz, -nx));
    }
  }
}

/** A round patch of asphalt where streets meet, so the corners curve. */
function junctionGeo(R, x, z, rad) {
  const r = rad + 1.2, segs = Math.max(12, Math.ceil(r * 2 * Math.PI / 3)), rings = Math.max(2, Math.ceil(r / 2.5));
  const at = (a, rr) => [x + Math.cos(a) * rr, ROAD_Y, z + Math.sin(a) * rr], U = (p) => [p[0] / 4, p[2] / 4];
  const up = (p, b, c) => {
    const nY = (b[2] - p[2]) * (c[0] - p[0]) - (b[0] - p[0]) * (c[2] - p[2]);
    if (nY < 0) [b, c] = [c, b];
    R.tri(p, b, c, U(p), U(b), U(c), LAYER.asphalt, ASPHALT.local);
  };
  // Rings about 2.5 m apart, so a big intersection on a slope still lies on the ground.
  for (let k = 0; k < segs; k++) {
    const a0 = k / segs * Math.PI * 2, a1 = (k + 1) / segs * Math.PI * 2;
    up([x, ROAD_Y, z], at(a0, r / rings), at(a1, r / rings));
    for (let q = 1; q < rings; q++) {
      const q0 = at(a0, r * q / rings), q1 = at(a1, r * q / rings), s0 = at(a0, r * (q + 1) / rings), s1 = at(a1, r * (q + 1) / rings);
      up(q0, s0, s1);
      up(q0, s1, q1);
    }
  }
}
/** Ladder-style crosswalk: white bars 0.6 m wide running with the traffic, across the whole street. */
function crosswalkGeo(P, x, z, ang, w) {
  const ux = Math.cos(ang), uz = Math.sin(ang), nx = -uz, nz = ux;
  for (let k = -w / 2 + 0.5; k <= w / 2 - 0.3; k += 1.2) {
    const cx = x + nx * k, cz = z + nz * k;
    P.strip([[cx - ux * 1.5, cz - uz * 1.5], [cx + ux * 1.5, cz + uz * 1.5]], 0, 0.6, PAINT_WHITE);
  }
}

/** A street sign: a post at the corner, and two blades whose quads index rows of the tile's sign atlas. */
function signGeo(G, B, s, atlas) {
  const [x10, z10, a1, n1, a2, n2] = s;
  const x = x10 / 10, z = z10 / 10;
  const base = G.seat([[x, z]]);
  // The post stops just under the blades, which sit on top of it, one above the other.
  boxGeo(G, x, -0.3, z, 0.09, 3.22, 0.09, 0, LAYER.metal, LAYER.metal, WHITE);
  [[a1, n1, 2.95], [a2, n2, 3.2]].forEach(([a100, n, y]) => {
    const ang = a100 / 100, len = Math.max(0.6, atlas.lens[n] / 1024 * 2.6), hgt = 0.22;
    const ux = Math.cos(ang), uz = Math.sin(ang);
    const v0 = 1 - (n + 1) / atlas.rows, v1 = 1 - n / atlas.rows, u1 = atlas.lens[n] / 1024;
    const p = (t, yy) => [x + ux * t, base + yy, z + uz * t];
    const a = p(-len / 2, y), b = p(len / 2, y), c = p(len / 2, y + hgt), d = p(-len / 2, y + hgt);
    B.p.push(...a, ...b, ...c, ...a, ...c, ...d);
    B.uv.push(0, v0, u1, v0, u1, v1, 0, v0, u1, v1, 0, v1);
    // the back, mirrored so it reads the right way round from the other side too
    B.p.push(...b, ...a, ...d, ...b, ...d, ...c);
    B.uv.push(0, v0, u1, v0, u1, v1, 0, v0, u1, v1, 0, v1);
  });
}

/* --------------------------- [Mpls] Street furniture ---------------------------
   What the city and OpenStreetMap say stands along the streets (bake_tiles.py fu): hydrants, benches, litter bins, bus
   stop signs and shelters, Nice Ride docks, mailboxes, wooden utility poles, bike racks and the light rail's platform
   canopies. Simple boxes in the facade array's plain layers, each turned by ang (towards the street: +x local).    */
const FURN = {
  hydrant: color('#d9a91c'), cap: color('#3a3c3f'), bench: color('#2f3a33'), wood: color('#8a6a4a'), bin: color('#2b2d30'),
  sign: color('#f4f4f0'), signBand: color('#1d4f91'), steel: color('#6d7277'), glass: color('#cfe0ea'), roof: color('#3b4046'),
  nice: color('#6cae3e'), mailbox: color('#1f4e8c'), pole: color('#6b5440'), rack: color('#8b9095'),
};
// Footprints for collision: [kind] = [half length along, half width across, height] (null: nothing to hit)
export const FURN_SIZE = [[0.2, 0.2, 0.8], [0.9, 0.3, 0.9], [0.3, 0.3, 1.0], [0.05, 0.05, 2.9], [1.8, 0.8, 2.6],
  [4, 0.4, 1.2], [0.3, 0.3, 1.2], [0.16, 0.16, 11], null, null];
function furnitureGeo(G, kind, x, z, ang) {
  const base = G.seat([[x, z]]);
  const P = localFrame(x, z, ang);                  // local u: towards the street, w: along it
  const box = (u, y, w, su, sy, sw, layer, col, top = layer) => {
    const [bx, , bz] = P(u, 0, w);
    boxGeo(G, bx, y, bz, su, sy, sw, ang, layer, top, col);
  };
  const M = LAYER.metal, C = LAYER.concPlain;
  switch (kind) {
    case 0:   // a fire hydrant: barrel, bonnet and two nozzles
      box(0, 0, 0, 0.26, 0.62, 0.26, M, FURN.hydrant);
      box(0, 0.62, 0, 0.2, 0.14, 0.2, M, FURN.cap);
      box(0, 0.36, 0, 0.44, 0.1, 0.1, M, FURN.hydrant);
      break;
    case 1:   // a bench: seat and back on two legs, facing the street
      box(-0.08, 0.42, 0, 0.42, 0.06, 1.8, M, FURN.wood);
      box(-0.3, 0.45, 0, 0.06, 0.45, 1.8, M, FURN.wood);
      for (const w of [-0.75, 0.75]) box(-0.1, 0, w, 0.45, 0.42, 0.06, M, FURN.bench);
      break;
    case 2:   // a litter bin
      box(0, 0, 0, 0.55, 0.95, 0.55, M, FURN.bin);
      break;
    case 3:   // a bus stop sign: a post and a Metro Transit plate facing along the street
      box(0, 0, 0, 0.07, 2.9, 0.07, M, FURN.steel);
      box(0, 2.2, 0.26, 0.04, 0.6, 0.45, M, FURN.sign);
      box(0, 2.62, 0.26, 0.045, 0.16, 0.45, M, FURN.signBand);
      break;
    case 4:   // a bus shelter: glass back and ends, a dark roof, a bench inside, open to the street
      box(-0.75, 0, 0, 0.05, 2.3, 3.6, LAYER.glass, FURN.glass);
      for (const w of [-1.8, 1.8]) box(-0.15, 0, w, 1.2, 2.3, 0.05, LAYER.glass, FURN.glass);
      for (const [u, w] of [[-0.75, -1.8], [-0.75, 1.8], [0.45, -1.8], [0.45, 1.8]]) box(u, 0, w, 0.08, 2.4, 0.08, M, FURN.roof);
      box(-0.15, 2.4, 0, 1.6, 0.14, 3.9, M, FURN.roof);
      box(-0.5, 0.42, 0, 0.35, 0.06, 2.2, M, FURN.steel);
      break;
    case 5:   // a Nice Ride dock: the green kiosk and a row of docking posts along the curb
      box(0, 0, -3.6, 0.45, 2.1, 0.6, M, FURN.nice);
      box(0, 0, 0.6, 0.12, 0.08, 7.2, M, FURN.steel);
      for (let w = -2.6; w <= 3.8; w += 0.8) box(0, 0, w, 0.12, 0.8, 0.14, M, FURN.nice);
      break;
    case 6:   // a blue USPS mailbox
      box(0, 0, 0, 0.5, 1.15, 0.5, M, FURN.mailbox);
      break;
    case 7:   // a wooden utility pole with its crossarm
      box(0, -0.3, 0, 0.28, 11.3, 0.28, LAYER.fence, FURN.pole);
      box(0, 10.2, 0, 0.12, 0.12, 2.4, LAYER.fence, FURN.pole);
      break;
    case 8:   // a bike rack: three hoops along the walk
      for (const w of [-0.8, 0, 0.8]) {
        box(0, 0, w - 0.3, 0.05, 0.85, 0.05, M, FURN.rack);
        box(0, 0, w + 0.3, 0.05, 0.85, 0.05, M, FURN.rack);
        box(0, 0.82, w, 0.05, 0.05, 0.65, M, FURN.rack);
      }
      break;
    case 9: { // a light rail platform's canopy, 30 m along the track: posts every 6 m and a roof
      const Q = localFrame(x, z, ang);
      for (let u = -15; u <= 15; u += 6) { const [bx, , bz] = Q(u, 0, 0); boxGeo(G, bx, 0, bz, 0.2, 3.3, 0.2, ang, M, M, FURN.steel); }
      const [bx, , bz] = Q(0, 0, 0);
      boxGeo(G, bx, 3.3, bz, 31, 0.18, 3.4, ang, M, M, FURN.roof);
      boxGeo(G, bx, 0, bz, 30, 0.3, 3.0, ang, C, C, CONCRETE);
      break;
    }
  }
  return base;
}

/**
 * A hero building (tools/mpls-drive/hero_house.py): one real building modelled in detail from the full LiDAR survey
 * and an aerial photo, triangle by triangle, standing on the ground at its centre.
 */
function heroGeo(G, S, hx) {
  const base = groundH(hx.x, hx.z);
  for (const ring of hx.rings) for (let i = 0; i < ring.length; i++) {
    const a = ring[i], b = ring[(i + 1) % ring.length];
    S.add(a[0], a[1], b[0], b[1], 0, base + hx.top);
  }
  // its parked cars (mpls-parked.js) are solid too: a 4.6 x 1.85 m box each
  for (const [x, z, yaw] of hx.pk || []) {
    const s = Math.sin(yaw), c = Math.cos(yaw), top = groundH(x, z) + 1.5;
    const corner = (f, r) => [x + s * f + c * r, z + c * f - s * r];
    const q = [corner(2.3, 0.92), corner(2.3, -0.92), corner(-2.3, -0.92), corner(-2.3, 0.92)];
    for (let k = 0; k < 4; k++) S.add(q[k][0], q[k][1], q[(k + 1) % 4][0], q[(k + 1) % 4][1], 0, top);
  }
  const cols = hx.col.map(color), p = hx.p, uv = hx.uv;
  G.y0 = base; G.foot = 0;
  const P = (k) => [p[k * 3] / 100, p[k * 3 + 1] / 100, p[k * 3 + 2] / 100], U = (k) => [uv[k * 2] / 100, uv[k * 2 + 1] / 100];
  for (let t = 0; t < hx.f.length / 2; t++) {
    G.tri(P(t * 3), P(t * 3 + 1), P(t * 3 + 2), U(t * 3), U(t * 3 + 1), U(t * 3 + 2), hx.f[t * 2], cols[hx.f[t * 2 + 1]]);
  }
}

/* --------------------------- Collision solids ---------------------------
   Every solid thing is a capsule in plan view: building walls and house sides are segments with zero radius, tree
   trunks and sign posts are points with a radius. h is the top (absolute height). A tile buckets its own into 16 m
   cells (finish), which the main thread turns into Slop New York's box colliders as the player comes near.        */
export const SOLID_CELL = 16;
export class Solids {
  constructor() { this.x1 = []; this.z1 = []; this.x2 = []; this.z2 = []; this.r = []; this.h = []; this.blocks = []; }
  /**
   * A whole building as one box, for the sound (audio-acoustics.js: what stands between a sound and the listener):
   * minX, minZ, maxX, maxZ, minY, maxY, and for a turned box its centre, half sizes and turn (cs, sn), else zeros.
   */
  block(minX, minZ, maxX, maxZ, minY, maxY, cx = 0, cz = 0, hx = 0, hz = 0, cs = 1, sn = 0) {
    this.blocks.push(minX, minZ, maxX, maxZ, minY, maxY, cx, cz, hx, hz, cs, sn);
  }
  add(x1, z1, x2, z2, r, h) {
    this.x1.push(x1); this.z1.push(z1); this.x2.push(x2); this.z2.push(z2); this.r.push(r); this.h.push(h);
  }
  /** Typed arrays and the cell index: { n, x1, z1, x2, z2, r, h, minX, minZ, gw, gh, start, items }. */
  finish() {
    const S = {};
    const n = S.n = this.x1.length;
    for (const k of ['x1', 'z1', 'x2', 'z2', 'r', 'h']) S[k] = Float32Array.from(this[k], (v) => (v === Infinity ? 1e5 : v));
    let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
    for (let i = 0; i < n; i++) {
      minX = Math.min(minX, S.x1[i] - S.r[i], S.x2[i] - S.r[i]); maxX = Math.max(maxX, S.x1[i] + S.r[i], S.x2[i] + S.r[i]);
      minZ = Math.min(minZ, S.z1[i] - S.r[i], S.z2[i] - S.r[i]); maxZ = Math.max(maxZ, S.z1[i] + S.r[i], S.z2[i] + S.r[i]);
    }
    Object.assign(S, { minX, minZ, maxX, maxZ, blocks: Float32Array.from(this.blocks) });
    if (!n) return S;
    const gw = S.gw = Math.max(1, Math.ceil((maxX - minX) / SOLID_CELL)), gh = S.gh = Math.max(1, Math.ceil((maxZ - minZ) / SOLID_CELL));
    const cx = (v) => clamp(Math.floor((v - minX) / SOLID_CELL), 0, gw - 1), cz = (v) => clamp(Math.floor((v - minZ) / SOLID_CELL), 0, gh - 1);
    const counts = new Uint32Array(gw * gh + 1);
    const each = (i, fn) => {
      const xa = cx(Math.min(S.x1[i], S.x2[i]) - S.r[i]), xb = cx(Math.max(S.x1[i], S.x2[i]) + S.r[i]);
      const za = cz(Math.min(S.z1[i], S.z2[i]) - S.r[i]), zb = cz(Math.max(S.z1[i], S.z2[i]) + S.r[i]);
      for (let z = za; z <= zb; z++) for (let x = xa; x <= xb; x++) fn(z * gw + x);
    };
    for (let i = 0; i < n; i++) each(i, (c) => counts[c + 1]++);
    for (let c = 0; c < gw * gh; c++) counts[c + 1] += counts[c];
    S.start = counts;
    S.items = new Uint32Array(counts[gw * gh]);
    const fill = counts.slice(0, gw * gh);
    for (let i = 0; i < n; i++) each(i, (c) => { S.items[fill[c]++] = i; });
    return S;
  }
}

/* --------------------------------- Tiles ---------------------------------
   Each 1 km tile's big buildings come in 500 m pieces with the tile; houses, garages, fences, signs, trees, streets
   and lamps are built a piece at a time when the camera comes near (buildDetail).                                 */
export const PIECE = 500;

/**
 * A tile's city: { pieces: [{ key, cx, cz, city: arrays }], solids, stadium: [rings], corners, streetNames }, plus the
 * pieces' raw detail records, kept by the caller (the worker) for buildDetail. isStadium(b, x, z) picks out the
 * building another module draws.
 */
export function buildTile(x0, z0, tile, data, isStadium) {
  const pieces = new Map();
  const pieceAt = (x, z) => {
    const n = tile / PIECE;
    const i = clamp(Math.floor((x - x0) / PIECE), 0, n - 1), j = clamp(Math.floor((z - z0) / PIECE), 0, n - 1);
    let T = pieces.get(j * 8 + i);
    if (!T) {
      T = { key: j * 8 + i, cx: x0 + (i + 0.5) * PIECE, cz: z0 + (j + 0.5) * PIECE, G: new Geo(), h: [], g: [], t: [], f: [], s: [], rd: [], jn: [], cw: [], lp: [], fu: [] };
      pieces.set(j * 8 + i, T);
    }
    return T;
  };
  const S = new Solids();
  const stadium = [];
  for (const b of data.b) {
    const { cx, cz } = buildingRings(b);
    building(null, S, b.slice());
    if (isStadium(b, cx, cz)) { stadium.push(buildingRings(b).rings[0]); continue; }
    building(pieceAt(cx, cz).G, null, b.slice());
  }
  for (const hx of data.hx || []) heroGeo(pieceAt(hx.x, hx.z).G, S, hx);
  // Collision for everything now; the shapes of the small things wait until they're near.
  const footprint = (x, z, ang, W, D, H, block = false) => {
    const P = localFrame(x, z, ang);
    const k = SIDES(W, D).map(([a]) => P(a[0], 0, a[1]));
    for (let e = 0; e < 4; e++) S.add(k[e][0], k[e][2], k[(e + 1) % 4][0], k[(e + 1) % 4][2], 0, H);
    if (block) {
      const xs = k.map((q) => q[0]), zs = k.map((q) => q[2]);
      S.block(Math.min(...xs), Math.min(...zs), Math.max(...xs), Math.max(...zs), groundH(x, z) - 1, H, x, z, W / 2, D / 2, Math.cos(ang), -Math.sin(ang));
    }
  };
  for (let i = 0; i < data.h.length; i += 12) {
    const h = data.h.slice(i, i + 12);
    pieceAt(h[0] / 10, h[1] / 10).h.push(h);
    footprint(h[0] / 10, h[1] / 10, h[2] / 100, h[3] / 10, h[4] / 10, groundH(h[0] / 10, h[1] / 10) + h[6] / 10, true);
  }
  for (let i = 0; i < data.g.length; i += 8) {
    const g = data.g.slice(i, i + 8);
    pieceAt(g[0] / 10, g[1] / 10).g.push(g);
    footprint(g[0] / 10, g[1] / 10, g[2] / 100, g[3] / 10, g[4] / 10, groundH(g[0] / 10, g[1] / 10) + g[5] / 10);
  }
  for (let i = 0; i < data.t.length; i += 4) {
    const t = data.t.slice(i, i + 4);
    pieceAt(t[0] / 10, t[1] / 10).t.push(t);
    // up to the crown (as tall as the tree): the helicopter flies over it
    S.add(t[0] / 10, t[1] / 10, t[0] / 10, t[1] / 10, 0.25 + t[2] / 10 * 0.012, groundH(t[0] / 10, t[1] / 10) + t[2] / 10);
  }
  data.f.forEach((f) => {
    pieceAt(f[2], f[3]).f.push(f);
    for (let i = 0; i < f[1] - 1; i++) {
      const top = Math.max(groundH(f[2 + i * 2], f[3 + i * 2]), groundH(f[4 + i * 2], f[5 + i * 2])) + FENCE_H[f[0]];
      S.add(f[2 + i * 2], f[3 + i * 2], f[4 + i * 2], f[5 + i * 2], f[0] === 2 ? 0.45 : 0.1, top);
    }
  });
  for (let i = 0; i < data.s.length; i += 6) {
    const s = data.s.slice(i, i + 6);
    pieceAt(s[0] / 10, s[1] / 10).s.push(s);
    S.add(s[0] / 10, s[1] / 10, s[0] / 10, s[1] / 10, 0.1, groundH(s[0] / 10, s[1] / 10) + 3.5);
  }
  for (const r of data.rd || []) {
    const mid = 7 + Math.floor(r[6] / 2) * 2;
    pieceAt(r[mid] / 10, r[mid + 1] / 10).rd.push(r);
  }
  for (let i = 0; i < (data.jn || []).length; i += 3) pieceAt(data.jn[i] / 10, data.jn[i + 1] / 10).jn.push(data.jn.slice(i, i + 3));
  for (let i = 0; i < (data.cw || []).length; i += 4) pieceAt(data.cw[i] / 10, data.cw[i + 1] / 10).cw.push(data.cw.slice(i, i + 4));
  // [Mpls] The city's street lights (bake_tiles.py lp: x, z, angle to the street, fixture) and the street furniture
  // (fu: kind, x, z, angle), solid where they'd stop a car
  for (let i = 0; i < (data.lp || []).length; i += 4) {
    const l = data.lp.slice(i, i + 4);
    pieceAt(l[0] / 10, l[1] / 10).lp.push(l);
    S.add(l[0] / 10, l[1] / 10, l[0] / 10, l[1] / 10, 0.14, groundH(l[0] / 10, l[1] / 10) + 6);
  }
  for (let i = 0; i < (data.fu || []).length; i += 4) {
    const f = data.fu.slice(i, i + 4), x = f[1] / 10, z = f[2] / 10, size = FURN_SIZE[f[0]];
    pieceAt(x, z).fu.push(f);
    if (!size) continue;
    if (f[0] === 4 || f[0] === 5 || f[0] === 1) {
      // its back (or its row of posts) as a wall along the street
      const a = f[3] / 100, u = f[0] === 4 ? -0.75 : 0, ca = Math.cos(a), sa = Math.sin(a), hw = size[0];
      const P = (w) => [x + u * ca - w * sa, z + u * sa + w * ca];
      const [p, q] = [P(-hw), P(hw)];
      S.add(p[0], p[1], q[0], q[1], 0.15, groundH(x, z) + size[2]);
    } else S.add(x, z, x, z, size[0], groundH(x, z) + size[2]);
  }
  const out = [];
  for (const T of pieces.values()) {
    out.push({ key: T.key, cx: T.cx, cz: T.cz, city: T.G.arrays(), detail: T.h.length + T.g.length + T.t.length + T.f.length + T.s.length + T.rd.length + T.lp.length + T.fu.length > 0 });
    T.G = null;
  }
  const corners = [];
  for (let i = 0; i < data.s.length; i += 6) corners.push(...data.s.slice(i, i + 6));
  return { pieces: out, raw: pieces, solids: S.finish(), stadium, corners: Float32Array.from(corners), streetNames: data.sn, map: mapShapes(data) };
}

/**
 * [Mpls] The survey's trees where the game draws something else under them. On water (wetAt: the tile map's lake and
 * river blue) or under a bridge deck it would grow up through, a tree goes. Standing on a sidewalk (sidewalkAt, from
 * mpls-blocks.js buildSidewalks: the whole street graph's), it moves onto the grass (grassAt) nearest the walk: the
 * boulevard between walk and curb on a residential street, else the lawn behind the walk (else the boulevard anyway);
 * on a main street with no grass either side it stands in a tree pit by the curb. On a trail it moves to beside it. One that would still end
 * up on a street goes. Rewrites data.t for the tile at (x0, z0); bridges is bridgeList()'s.
 */
export function fitTrees(data, x0, z0, tile, { wetAt, grassAt, sidewalkAt, bridges }) {
  const CELL = 16, cells = new Map();
  for (const r of data.rd || []) {
    if (ROAD_KINDS[r[0]] !== 'path') continue;
    const hw = r[1] / 20, n = r[6];
    for (let k = 0; k + 1 < n; k++) {
      const s = { ax: r[7 + k * 2] / 10, az: r[8 + k * 2] / 10, bx: r[9 + k * 2] / 10, bz: r[10 + k * 2] / 10, hw };
      const m = hw + 2;
      for (let i = Math.floor((Math.min(s.ax, s.bx) - m) / CELL); i <= Math.floor((Math.max(s.ax, s.bx) + m) / CELL); i++) {
        for (let j = Math.floor((Math.min(s.az, s.bz) - m) / CELL); j <= Math.floor((Math.max(s.az, s.bz) + m) / CELL); j++) {
          const key = i * 100000 + j;
          if (!cells.has(key)) cells.set(key, []);
          cells.get(key).push(s);
        }
      }
    }
  }
  const decks = bridges.filter((br) => {
    const bx = br.ax + br.ux * br.L, bz = br.az + br.uz * br.L, m = br.w / 2 + 2;
    return Math.max(br.ax, bx) + m > x0 && Math.min(br.ax, bx) - m < x0 + tile && Math.max(br.az, bz) + m > z0 && Math.min(br.az, bz) - m < z0 + tile;
  });
  const underDeck = (x, z) => decks.some((br) => {
    const dx = x - br.ax, dz = z - br.az, t = dx * br.ux + dz * br.uz;
    return t > -2 && t < br.L + 2 && Math.abs(-dx * br.uz + dz * br.ux) < br.w / 2 + 1.5;
  });
  const out = [];
  let moved = 0, gone = 0;
  for (let i = 0; i < data.t.length; i += 4) {
    let x = data.t[i] / 10, z = data.t[i + 1] / 10;
    if (wetAt(x, z) || underDeck(x, z)) { gone++; continue; }
    const w = sidewalkAt.walkOf(x, z);
    if (w && w.r > 1e-3) {
      const ux = (x - w.px) / w.r, uz = (z - w.pz) / w.r;
      const at = (d) => [w.px + ux * (w.hw + d), w.pz + uz * (w.hw + d)];
      const spots = (w.main ? [3.6, 4.6] : [1.35, 4.6]).map(at).filter(([px, pz]) => !sidewalkAt(px, pz));
      const spot = spots.find(([px, pz]) => grassAt(px, pz)) || (w.main ? null : spots[0]);
      if (spot) [x, z] = spot;
      else if (w.main) [x, z] = at(0.9);
      else { gone++; continue; }
      moved++;
    }
    for (const s of cells.get(Math.floor(x / CELL) * 100000 + Math.floor(z / CELL)) || []) {
      const dx = s.bx - s.ax, dz = s.bz - s.az, L2 = dx * dx + dz * dz || 1;
      const t = Math.max(0, Math.min(1, ((x - s.ax) * dx + (z - s.az) * dz) / L2));
      const px = s.ax + dx * t, pz = s.az + dz * t, r = Math.hypot(x - px, z - pz);
      if (r - s.hw < 0.3 && r > 1e-3) {
        x = px + (x - px) / r * (s.hw + 0.9);
        z = pz + (z - pz) / r * (s.hw + 0.9);
        moved++;
      }
    }
    const x10 = Math.round(x * 10), z10 = Math.round(z * 10);
    if (sidewalkAt(x10 / 10, z10 / 10) === 'road') { gone++; continue; }
    out.push(x10, z10, data.t[i + 2], data.t[i + 3]);
  }
  data.t = out;
  return { moved, gone };
}

/**
 * What the maps draw of a tile (mpls-map.js): roads as [kind, width, n, x, z, ...] and footprints (buildings, houses,
 * garages) as [n, x, z, ...], flat.
 */
function mapShapes(data) {
  const roads = [], shapes = [];
  for (const r of data.rd || []) {
    const pts = roadPoints(r);
    roads.push(r[0], r[1] / 10, pts.length, ...pts.flat());
  }
  for (const b of data.b) {
    const ring = buildingRings(b).rings[0];
    shapes.push(ring.length, ...ring.flat());
  }
  const box = (x, z, ang, W, D) => {
    const P = localFrame(x, z, ang);
    shapes.push(4, ...SIDES(W, D).flatMap(([a]) => { const q = P(a[0], 0, a[1]); return [q[0], q[2]]; }));
  };
  for (let i = 0; i < data.h.length; i += 12) box(data.h[i] / 10, data.h[i + 1] / 10, data.h[i + 2] / 100, data.h[i + 3] / 10, data.h[i + 4] / 10);
  for (let i = 0; i < data.g.length; i += 8) box(data.g[i] / 10, data.g[i + 1] / 10, data.g[i + 2] / 100, data.g[i + 3] / 10, data.g[i + 4] / 10);
  return { roads: Float32Array.from(roads), shapes: Float32Array.from(shapes) };
}

/**
 * A piece's detail: houses, garages, fences, signs and street furniture (city), streets (road, concrete, brick, walk,
 * curb, trail, paint), sign blades (signs), lamp spots ([x, z, angle, fixture] flat) and tree sites ([x, y, z, h, r] flat).
 */
export function buildDetail(T, atlas) {
  const G = new Geo();
  for (const h of T.h) houseGeo(G, h);
  for (const g of T.g) garageGeo(G, g);
  T.f.forEach((f, n) => fenceGeo(G, f, n + f[2]));
  const B = { p: [], uv: [] };
  if (atlas) for (const s of T.s) signGeo(G, B, s, atlas);
  for (const [kind, x10, z10, a100] of T.fu) furnitureGeo(G, kind, x10 / 10, z10 / 10, a100 / 100);
  const S = {
    road: new Geo(true), walk: new Geo(true), curb: new Geo(true), trail: new Geo(true), paint: new PaintGeo(),
    concrete: new Geo(true), brick: new Geo(true), posts: [],
  };
  for (const r of T.rd) streetGeo(S, r);
  // protected bike lanes' posts
  for (let k = 0; k < S.posts.length; k += 2) {
    G.seat([[S.posts[k], S.posts[k + 1]]]);
    boxGeo(G, S.posts[k], 0, S.posts[k + 1], 0.1, 0.9, 0.1, 0, LAYER.metal, LAYER.metal, POST_WHITE);
  }
  for (const [x, z, r] of T.jn) junctionGeo(S.road, x / 10, z / 10, r / 10);
  for (const [x, z, a, w] of T.cw) crosswalkGeo(S.paint, x / 10, z / 10, a / 100, w / 10);
  // [Mpls] The city's own lights where it has them; along a street with none of them near, lamps spaced as Slop New
  // York's (lampSpots: the lights the city doesn't own, Xcel Energy's, aren't in its data)
  const lamps = [];
  // (lamp angles turn the arm, +x, by a about up: towards (cos a, -sin a); the bake's point at the street, (cos, sin))
  for (const [x10, z10, a100, style] of T.lp) lamps.push(x10 / 10, z10 / 10, -a100 / 100, style);
  const lit = new Map();
  for (const [x10, z10] of T.lp) {
    const key = Math.floor(x10 / 400) * 100000 + Math.floor(z10 / 400);
    if (!lit.has(key)) lit.set(key, []);
    lit.get(key).push([x10 / 10, z10 / 10]);
  }
  const litNear = (x, z, r) => {
    for (let i = Math.floor((x - r) / 40); i <= Math.floor((x + r) / 40); i++) for (let j = Math.floor((z - r) / 40); j <= Math.floor((z + r) / 40); j++) {
      for (const [lx, lz] of lit.get(i * 100000 + j) || []) if (Math.hypot(lx - x, lz - z) < r) return true;
    }
    return false;
  };
  for (const r of T.rd) {
    const pts = roadPoints(r), mid = pts[Math.floor(pts.length / 2)];
    if (litNear(mid[0], mid[1], r[1] / 20 + 30)) continue;
    const spots = [];
    lampSpots(r, spots);
    for (let k = 0; k < spots.length; k += 3) lamps.push(spots[k], spots[k + 1], spots[k + 2], 0);
  }
  const trees = [];
  for (const [x10, z10, h10, r10] of T.t) trees.push(x10 / 10, groundH(x10 / 10, z10 / 10), z10 / 10, h10 / 10, r10 / 10);
  let signs = null;
  if (B.p.length) {
    const position = Float32Array.from(B.p);
    signs = { position, normal: flatNormals(position), uv: Float32Array.from(B.uv) };
  }
  return {
    city: G.arrays(), road: S.road.arrays(), walk: S.walk.arrays(), curb: S.curb.arrays(), trail: S.trail.arrays(),
    concrete: S.concrete.arrays(), brick: S.brick.arrays(),
    paint: S.paint.arrays(), signs, lamps: Float32Array.from(lamps), trees: Float32Array.from(trees),
  };
}

/**
 * A tile's ground mesh: a node every step metres (the ground grid's), laid out round the tile's centre, with smooth
 * normals: { position, normal, mid (its middle height), span (half its height range) }.
 */
export function groundGrid(x0, z0, tile) {
  const n = Math.round(tile / GR.step), w = n + 1, half = tile / 2;
  const position = new Float32Array(w * w * 3), normal = new Float32Array(w * w * 3);
  let lo = Infinity, hi = -Infinity;
  for (let j = 0; j <= n; j++) for (let i = 0; i <= n; i++) {
    const x = i * GR.step, z = j * GR.step, k = (j * w + i) * 3, h = groundH(x0 + x, z0 + z);
    position[k] = x - half; position[k + 1] = h; position[k + 2] = z - half;
    lo = Math.min(lo, h); hi = Math.max(hi, h);
  }
  for (let j = 0; j <= n; j++) for (let i = 0; i <= n; i++) {
    const k = (j * w + i) * 3, s = 2 * GR.step;
    const hx = groundH(x0 + (i + 1) * GR.step, z0 + j * GR.step) - groundH(x0 + (i - 1) * GR.step, z0 + j * GR.step);
    const hz = groundH(x0 + i * GR.step, z0 + (j + 1) * GR.step) - groundH(x0 + i * GR.step, z0 + (j - 1) * GR.step);
    const L = Math.hypot(hx, s, hz);
    normal[k] = -hx / L; normal[k + 1] = s / L; normal[k + 2] = -hz / L;
  }
  return { position, normal, mid: (lo + hi) / 2, span: (hi - lo) / 2 };
}

/**
 * The river and the lakes on a tile: flat quads over its deep-water cells (surface: the tile's map read back, n by n,
 * 2 = deep water), a cell every `step` map pixels, runs along each row merged (no longer than 64 m, so the water
 * still steps down the river), each run level at its corners' mean height: { position, normal } or null.
 */
export function waterArrays(surface, n, x0, z0, tile, step = 2) {
  const cells = n / step, size = tile / cells, maxRun = Math.max(1, Math.round(64 / size));
  const wet = (i, j) => surface[(j * step + (step >> 1)) * n + i * step + (step >> 1)] === 2;
  const pos = [];
  for (let j = 0; j < cells; j++) {
    for (let i = 0; i < cells;) {
      if (!wet(i, j)) { i++; continue; }
      let e = i;
      while (e < cells && wet(e, j) && e - i < maxRun) e++;
      const ax = x0 + i * size, bx = x0 + e * size, az = z0 + j * size, bz = az + size;
      const y = (groundH(ax, az) + groundH(bx, az) + groundH(ax, bz) + groundH(bx, bz)) / 4 + 0.15;
      pos.push(ax, y, az, ax, y, bz, bx, y, az, bx, y, az, ax, y, bz, bx, y, bz);
      i = e;
    }
  }
  if (!pos.length) return null;
  const position = Float32Array.from(pos), normal = new Float32Array(position.length);
  for (let k = 1; k < normal.length; k += 3) normal[k] = 1;
  return { position, normal };
}

/* -------------------------------- Bridges --------------------------------
   Every bridge OpenStreetMap knows, over water, freeways or rail, as straight deck pieces from index.json. Each runs
   evenly between the heights baked for its two ends, which meet the ground where it lands.                         */
export function bridgeList(br8) {
  const out = [];
  for (let i = 0; i < br8.length; i += 8) {
    const [ax, az, bx, bz, w, ha10, hb10, pier] = br8.slice(i, i + 8);
    const L = Math.hypot(bx - ax, bz - az);
    if (L < 0.5) continue;
    out.push({ ax, az, ux: (bx - ax) / L, uz: (bz - az) / L, L, w, ha: ha10 / 10, hb: hb10 / 10, pier, arch: L > 180 && (i / 8) % 2 === 0 });
  }
  return out;
}
export const bridgeHeightAt = (br, t) => br.ha + (br.hb - br.ha) * clamp(t / br.L, 0, 1);

/** Decks with railings, piers down to the ground and a steel arch on the long spans: { position, color } flat-shaded. */
export function bridgeArrays(list) {
  const pos = [], col = [];
  const tri = (p, q, r, c) => { for (const v of [p, q, r]) { pos.push(v[0], v[1], v[2]); col.push(c[0], c[1], c[2]); } };
  const box = (cx, cy, cz, sx, sy, sz, ang, c) => {
    const cs = Math.cos(ang), sn = Math.sin(ang);
    const P = (x, y, z) => [cx + x * cs - z * sn, cy + y, cz + x * sn + z * cs];
    const hx = sx / 2, hz = sz / 2;
    const v = [P(-hx, 0, -hz), P(hx, 0, -hz), P(hx, 0, hz), P(-hx, 0, hz), P(-hx, sy, -hz), P(hx, sy, -hz), P(hx, sy, hz), P(-hx, sy, hz)];
    [[4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]].forEach(([a, b, cc, d], k) => {
      const shade = k === 0 ? c : scaled(c, 0.86);
      tri(v[a], v[b], v[cc], shade);
      tri(v[a], v[cc], v[d], shade);
    });
  };
  const deckCol = color('#a7adb3'), railCol = color('#eceae4');
  const archCol = color('#4f7fb3'), pierCol = color('#c9c2b2'), sideCol = color('#8f959b');
  for (const br of list) {
    const { ax, az, ux, uz, L, w } = br;
    const nx = -uz, nz = ux;
    const steps = Math.max(1, Math.ceil(L / 6));
    const P = (t, s, dy) => [ax + ux * t + nx * s, bridgeHeightAt(br, t) + dy, az + uz * t + nz * s];
    for (let k = 0; k < steps; k++) {
      const t0 = L * k / steps, t1 = L * (k + 1) / steps;
      const hw = w / 2;
      tri(P(t0, -hw, 0.06), P(t1, hw, 0.06), P(t1, -hw, 0.06), deckCol);
      tri(P(t0, -hw, 0.06), P(t0, hw, 0.06), P(t1, hw, 0.06), deckCol);
      for (const s of [-1, 1]) {
        tri(P(t0, s * hw, 0.06), P(t1, s * hw, 0.06), P(t1, s * hw, -0.7), sideCol);
        tri(P(t0, s * hw, 0.06), P(t1, s * hw, -0.7), P(t0, s * hw, -0.7), sideCol);
        const rs = s * (hw - 0.15);
        tri(P(t0, rs, 0.06), P(t1, rs, 0.06), P(t1, rs, 1.0), railCol);
        tri(P(t0, rs, 0.06), P(t1, rs, 1.0), P(t0, rs, 1.0), railCol);
      }
      tri(P(t0, -hw, -0.7), P(t1, -hw, -0.7), P(t1, hw, -0.7), sideCol);
      tri(P(t0, -hw, -0.7), P(t1, hw, -0.7), P(t0, hw, -0.7), sideCol);
    }
    const ang = Math.atan2(uz, ux);
    if (br.pier) {
      const g = groundH(ax, az), top = br.ha - 0.6;
      if (top - g > 2.5) box(ax, g - 1, az, 2.5, top - g + 1, w * 0.7, ang, pierCol);
    }
    if (br.arch) {
      for (const s of [-1, 1]) {
        const ox = nx * s * (w / 2 - 0.15), oz = nz * s * (w / 2 - 0.15);
        const archH = Math.min(40, L * 0.16), segs = 16;
        for (let k = 0; k < segs; k++) {
          const t0 = k / segs, t1 = (k + 1) / segs;
          const y0 = Math.sin(Math.PI * t0) * archH + bridgeHeightAt(br, t0 * L), y1 = Math.sin(Math.PI * t1) * archH + bridgeHeightAt(br, t1 * L);
          const segL = Math.hypot((t1 - t0) * L, y1 - y0);
          box(ax + ux * L * (t0 + t1) / 2 + ox, Math.min(y0, y1), az + uz * L * (t0 + t1) / 2 + oz, segL, Math.abs(y1 - y0) + 1.2, 1.2, ang, archCol);
        }
      }
    }
  }
  if (!pos.length) return null;
  const position = Float32Array.from(pos);
  return { position, normal: flatNormals(position), color: Float32Array.from(col) };
}
