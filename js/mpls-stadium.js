/* US Bank Stadium, built in code over its OpenStreetMap footprint.
   A single ridge runs from the prow at the west end (83 m, pointing at downtown)
   east and a little north, falling as it goes. North of it the roof is steep dark
   zinc; south of it a long, shallow slope of clear ETFE pillows, with a zinc band
   at the eave. The walls are dark zinc panels over a glazed concourse band, and the
   west faces, onto the plaza, are the five tall glass doors. Through the roof you
   can see the purple bowl and the field.

   createStadium({ ring, base, foot, night }) -> meshes, in world coordinates:
   ring is the footprint as [x, z] pairs, base the ground height it stands on, foot
   how far its walls run down to meet the lowest ground round it, night a 0..1
   uniform. */
import * as THREE from 'three/webgpu';
import { uv, fract, smoothstep, step, mix, max, min, fwidth, vec3, float } from 'three/tsl';

const PROW = [-17, -823], RIDGE_END = [230, -890];   // the ridge, from the prow at the west end
const PROW_H = 83, END_H = 55, EAVE_MIN = 22;
const SLOPE_N = 0.42, SLOPE_S = 0.2;                  // metres down per metre off the ridge
const ETFE_W = 125;                                   // the clear roof runs this far south of the ridge
const CUT_STEP = 16;                                  // roof facets along the ridge

// Lines on a surface, w wide every p metres, softened by the pixel footprint so they do not shimmer.
const lines = (x, p, w) => {
  const f = fract(x.div(p)), d = min(f, float(1).sub(f)).mul(p);
  const aa = fwidth(x).max(1e-4);
  const crisp = float(1).sub(smoothstep(w * 0.5, aa.add(w * 0.5), d));
  return mix(crisp, float(w / p), smoothstep(w * 0.5, w * 3, aa));      // far off, the lines' average share
};

function materials(night) {
  const zinc = new THREE.MeshStandardNodeMaterial({ roughness: 0.42, metalness: 0.65, side: THREE.DoubleSide });
  const seam = max(lines(uv().x, 1.4, 0.06), lines(uv().y, 6, 0.1));
  zinc.colorNode = mix(vec3(0.24, 0.26, 0.29), vec3(0.13, 0.14, 0.16), seam);

  const glass = new THREE.MeshStandardNodeMaterial({ side: THREE.DoubleSide });
  const mull = max(max(lines(uv().x, 3, 0.1), lines(uv().y, 4.5, 0.14)), lines(uv().x, 16, 0.5));
  glass.colorNode = mix(vec3(0.07, 0.1, 0.13), vec3(0.42, 0.45, 0.49), mull);
  glass.roughnessNode = mix(float(0.05), float(0.45), mull);
  glass.metalnessNode = mix(float(0.5), float(0.75), mull);
  glass.emissiveNode = vec3(1, 0.78, 0.5).mul(night.mul(float(1).sub(mull)).mul(0.3));

  // ETFE: pale, see-through pillows in a dark frame; lit from inside after dark.
  const etfe = new THREE.MeshStandardNodeMaterial({ transparent: true, depthWrite: false, roughness: 0.18, metalness: 0, side: THREE.DoubleSide });
  const frame = max(lines(uv().x, 8, 0.35), lines(uv().y, 14, 0.45));
  etfe.colorNode = mix(vec3(0.88, 0.93, 0.95), vec3(0.3, 0.32, 0.36), frame);
  etfe.opacityNode = mix(float(0.38), float(0.95), frame);
  etfe.emissiveNode = vec3(1, 0.92, 0.78).mul(night.mul(float(1).sub(frame)).mul(0.45));

  const field = new THREE.MeshStandardNodeMaterial({ roughness: 0.9, metalness: 0 });
  const yard = lines(uv().x, 9.144, 0.12);
  field.colorNode = mix(mix(vec3(0.2, 0.42, 0.18), vec3(0.24, 0.48, 0.21), step(0.5, fract(uv().x.div(18.288)))), vec3(0.92), yard);
  field.emissiveNode = vec3(0.3, 0.42, 0.28).mul(night.mul(0.35));

  const seats = new THREE.MeshStandardNodeMaterial({ roughness: 0.8, metalness: 0, side: THREE.DoubleSide });
  seats.colorNode = mix(vec3(0.31, 0.15, 0.51), vec3(0.16, 0.08, 0.27), lines(uv().y, 0.9, 0.12));
  return { zinc, glass, etfe, field, seats };
}

/** Collects triangles (absolute positions, uvs in metres) for one material, then becomes one mesh. */
class Tris {
  constructor() { this.p = []; this.uv = []; }
  tri(a, b, c, ua, ub, uc) { this.p.push(...a, ...b, ...c); this.uv.push(...ua, ...ub, ...uc); }
  quad(a, b, c, d, ua, ub, uc, ud) { this.tri(a, b, c, ua, ub, uc); this.tri(a, c, d, ua, uc, ud); }
  mesh(mat, shadows) {
    if (!this.p.length) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(this.p, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(this.uv, 2));
    g.computeVertexNormals();
    g.computeBoundingSphere();
    const m = new THREE.Mesh(g, mat);
    m.castShadow = m.receiveShadow = shadows;
    return m;
  }
}

export function createStadium({ ring, base, foot = 0, night, castShadow = true }) {
  const M = materials(night);
  const len = Math.hypot(RIDGE_END[0] - PROW[0], RIDGE_END[1] - PROW[1]);
  const D = [(RIDGE_END[0] - PROW[0]) / len, (RIDGE_END[1] - PROW[1]) / len];
  const N = [-D[1], D[0]];                                         // across the ridge, to the south (+z)
  const along = (p) => (p[0] - PROW[0]) * D[0] + (p[1] - PROW[1]) * D[1];
  const across = (p) => (p[0] - PROW[0]) * N[0] + (p[1] - PROW[1]) * N[1];
  const roofH = (p) => {
    const t = Math.min(1, Math.max(0, along(p) / len));
    const d = Math.hypot(p[0] - PROW[0] - D[0] * t * len, p[1] - PROW[1] - D[1] * t * len);
    return Math.max(EAVE_MIN, PROW_H + (END_H - PROW_H) * t - d * (across(p) < 0 ? SLOPE_N : SLOPE_S));
  };

  // The footprint, its edges split where the roof's two cut lines cross them, so the walls meet the roof's facets.
  const cuts = [0, ETFE_W];
  let R = ring.map(p => [p[0], p[1]]);
  for (const c of cuts) {
    const out = [];
    for (let i = 0; i < R.length; i++) {
      const a = R[i], b = R[(i + 1) % R.length], sa = across(a) - c, sb = across(b) - c;
      out.push(a);
      if (sa * sb < 0 && Math.abs(sa) > 1e-6 && Math.abs(sb) > 1e-6) {
        const k = sa / (sa - sb);
        out.push([a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]);
      }
    }
    R = out;
  }
  let cx = 0, cz = 0;
  for (const [x, z] of R) { cx += x; cz += z; }
  cx /= R.length; cz /= R.length;
  let area2 = 0;
  for (let i = 0; i < R.length; i++) { const a = R[i], b = R[(i + 1) % R.length]; area2 += a[0] * b[1] - b[0] * a[1]; }
  const outSign = area2 > 0 ? 1 : -1;                            // which side of an edge is outside

  const zinc = new Tris(), glass = new Tris(), etfe = new Tris(), field = new Tris(), seats = new Tris();
  const Y = (h) => base + h;

  /* ---- Walls: dark zinc over a glazed concourse; the west faces all glass, the doors onto the plaza. ---- */
  let run = 0;
  for (let i = 0; i < R.length; i++) {
    const a = R[i], b = R[(i + 1) % R.length];
    const L = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (L < 0.05) continue;
    const nx = outSign * (b[1] - a[1]) / L;                      // outward normal's x
    const ha = roofH(a), hb = roofH(b);
    const band = (T, y0, y1a, y1b) => T.quad(
      [a[0], Y(y0), a[1]], [b[0], Y(y0), b[1]], [b[0], Y(y1b), b[1]], [a[0], Y(y1a), a[1]],
      [run, y0], [run + L, y0], [run + L, y1b], [run, y1a]);
    if (foot < -0.05) band(zinc, foot, 0, 0);
    if (nx < -0.55) {
      // The doors: glass up to 50 m, zinc over them up into the prow.
      const DOOR = 50;
      band(glass, 0, Math.min(ha, DOOR), Math.min(hb, DOOR));
      if (ha > DOOR || hb > DOOR) band(zinc, DOOR, Math.max(ha, DOOR), Math.max(hb, DOOR));
    } else {
      band(zinc, 0, 3, 3);
      band(glass, 3, 9, 9);
      band(zinc, 9, ha, hb);
    }
    run += L;
  }

  /* ---- Roof: the footprint cut along the ridge and the edge of the clear panels, each part triangulated. ---- */
  const clip = (poly, f) => {
    const out = [];
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length], fa = f(a), fb = f(b);
      if (fa >= -1e-6) out.push(a);
      if ((fa > 1e-6 && fb < -1e-6) || (fa < -1e-6 && fb > 1e-6)) {
        const k = fa / (fa - fb);
        out.push([a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]);
      }
    }
    return out.filter((p, i) => { const q = out[(i + 1) % out.length]; return Math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-3; });
  };
  // Along a cut line, facet points every CUT_STEP metres (the same on both sides, so the parts meet without cracks).
  const facet = (poly) => {
    const out = [];
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length];
      out.push(a);
      const onCut = cuts.some(c => Math.abs(across(a) - c) < 1e-3 && Math.abs(across(b) - c) < 1e-3);
      if (!onCut) continue;
      const ua = along(a), ub = along(b), dir = Math.sign(ub - ua);
      for (let u = (dir > 0 ? Math.floor(ua / CUT_STEP) + 1 : Math.ceil(ua / CUT_STEP) - 1) * CUT_STEP; dir * (ub - u) > 0.5; u += dir * CUT_STEP) {
        if (dir * (u - ua) < 0.5) continue;
        const k = (u - ua) / (ub - ua);
        out.push([a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]);
      }
    }
    return out;
  };
  const roofPart = (poly, T) => {
    if (poly.length < 3) return;
    const pts = facet(poly);
    const tris = THREE.ShapeUtils.triangulateShape(pts.map(([x, z]) => new THREE.Vector2(x, z)), []);
    const P = (p) => [p[0], Y(roofH(p)), p[1]], U = (p) => [along(p), across(p)];
    for (const [i, j, k] of tris) {
      let [a, b, c] = [pts[i], pts[j], pts[k]];
      // Wound to face up.
      if ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 0) [b, c] = [c, b];
      T.tri(P(a), P(b), P(c), U(a), U(b), U(c));
    }
  };
  roofPart(clip(R, p => -across(p)), zinc);
  roofPart(clip(clip(R, p => across(p)), p => ETFE_W - across(p)), etfe);
  roofPart(clip(R, p => across(p) - ETFE_W), zinc);

  /* ---- Inside: the field along the long axis, and the purple bowl rising to the walls. ---- */
  const FIELD_L = 64, FIELD_W = 34, BOWL = 48;
  const inner = [], outer = [];
  for (let k = 0; k < BOWL; k++) {
    const th = (k / BOWL) * Math.PI * 2, c = Math.cos(th), s = Math.sin(th);
    const u = FIELD_L * Math.sign(c) * Math.abs(c) ** 0.35, w = FIELD_W * Math.sign(s) * Math.abs(s) ** 0.35;
    const p = [cx + D[0] * u + N[0] * w, cz + D[1] * u + N[1] * w];
    // Out from the middle through this point to the footprint, then back in a little.
    const dx = p[0] - cx, dz = p[1] - cz;
    let best = Infinity;
    for (let i = 0; i < R.length; i++) {
      const a = R[i], b = R[(i + 1) % R.length], ex = b[0] - a[0], ez = b[1] - a[1];
      const den = dx * ez - dz * ex;
      if (Math.abs(den) < 1e-9) continue;
      const t = ((a[0] - cx) * ez - (a[1] - cz) * ex) / den, e = ((a[0] - cx) * dz - (a[1] - cz) * dx) / den;
      if (t > 0 && e >= 0 && e <= 1) best = Math.min(best, t);
    }
    const t = (best === Infinity ? 1.5 : best) * 0.9;
    inner.push(p);
    outer.push([cx + dx * t, cz + dz * t]);
  }
  const fieldPts = inner.map(([x, z]) => new THREE.Vector2(x, z));
  for (const [i, j, k] of THREE.ShapeUtils.triangulateShape(fieldPts, [])) {
    let [a, b, c] = [inner[i], inner[j], inner[k]];
    if ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 0) [b, c] = [c, b];
    const P = (p) => [p[0], Y(0.4), p[1]], U = (p) => [along(p), across(p)];
    field.tri(P(a), P(b), P(c), U(a), U(b), U(c));
  }
  for (let k = 0; k < BOWL; k++) {
    const k2 = (k + 1) % BOWL;
    const top = (p) => Math.min(26, roofH(p) - 5);
    const mid = (a, b) => [a[0] + (b[0] - a[0]) * 0.5, a[1] + (b[1] - a[1]) * 0.5];
    const m1 = mid(inner[k], outer[k]), m2 = mid(inner[k2], outer[k2]);
    const ya = 1.2, ym1 = top(outer[k]) * 0.38, ym2 = top(outer[k2]) * 0.38, yo1 = top(outer[k]), yo2 = top(outer[k2]);
    const rowsA = Math.hypot(m1[0] - inner[k][0], m1[1] - inner[k][1]);
    seats.quad([inner[k][0], Y(ya), inner[k][1]], [inner[k2][0], Y(ya), inner[k2][1]], [m2[0], Y(ym2), m2[1]], [m1[0], Y(ym1), m1[1]],
      [0, 0], [1, 0], [1, rowsA], [0, rowsA]);
    const rowsB = rowsA + Math.hypot(outer[k][0] - m1[0], outer[k][1] - m1[1]) * 1.2;
    seats.quad([m1[0], Y(ym1), m1[1]], [m2[0], Y(ym2), m2[1]], [outer[k2][0], Y(yo2), outer[k2][1]], [outer[k][0], Y(yo1), outer[k][1]],
      [0, rowsA], [1, rowsA], [1, rowsB], [0, rowsB]);
  }

  const meshes = [];
  for (const [T, mat, sh] of [[zinc, M.zinc, castShadow], [glass, M.glass, castShadow], [field, M.field, castShadow],
    [seats, M.seats, castShadow], [etfe, M.etfe, false]]) {
    const m = T.mesh(mat, sh);
    if (m) { m.name = 'US Bank Stadium'; meshes.push(m); }
  }
  meshes.at(-1).renderOrder = 2;                                 // the clear roof after what's under it
  return meshes;
}
