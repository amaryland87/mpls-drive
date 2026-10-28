// [Mpls] The METRO Blue and Green Lines: their trains running to Metro Transit's timetable (data/transit.json, baked by
// tools/bake_transit.py from its GTFS), and the poles and wire over their tracks. The clock is the time of
// day the sky shows (lighting.js presets), running on in real time from it; the day is today's (a weekday, a Saturday
// or a Sunday in Minneapolis). Each train is three Siemens S70 cars, 28.6 m long, that follow the track round the
// curves, stand at the stations for their dwell and keep to the right of the line's centre. Trains are drawn, not
// solid: the traffic and the car drive round them as they would a train on its own right of way.
import * as THREE from 'three/webgpu';
import { mix, smoothstep, vec3 } from 'three/tsl';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { cityUniforms } from './tsl-materials.js';

const CAR_L = 28.6, CAR_GAP = 0.9, CARS = 3, CAR_W = 2.65;
const RIGHT = 1.9;                     // metres right of the line's centre each way runs
const MAX_TRAINS = 48;
// The hour each sky shows (lighting.js presets)
const HOUR = { midday: 12.5, golden: 17.75, twilight: 18.75, midnight: 0.25 };
// Catenary: a pole every POLE_GAP metres beside one of each line's ways, the wire WIRE_Y over the track
const POLE_GAP = 55, POLE_H = 7.2, WIRE_Y = 5.8;

/** A path along a shape: points, their distance along the timetable's measure, and where a distance puts you. */
function pathOf(flat, along) {
  const pts = [];
  for (let i = 0; i < flat.length; i += 2) pts.push([flat[i] / 10, flat[i + 1] / 10]);
  const d = along.map((v) => v / 10);
  return {
    pts, d, start: d[0], end: d[d.length - 1],
    /** [x, z, dx, dz] at distance s along it (clamped to its ends), shifted `right` metres to the right. */
    at(s, right = 0) {
      let lo = 0, hi = d.length - 1;
      s = Math.max(d[0], Math.min(d[hi], s));
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (d[m] <= s) lo = m; else hi = m; }
      const a = pts[lo], b = pts[hi], t = (s - d[lo]) / ((d[hi] - d[lo]) || 1);
      let dx = b[0] - a[0], dz = b[1] - a[1];
      const L = Math.hypot(dx, dz) || 1;
      dx /= L; dz /= L;
      return [a[0] + (b[0] - a[0]) * t - dz * right, a[1] + (b[1] - a[1]) * t + dx * right, dx, dz];
    },
  };
}

/** One S70 car, nose along +z: white body, dark window band, a yellow stripe, a pantograph (the skirt is its own). */
function carGeometry() {
  const parts = [];
  const add = (g, hex) => {
    const c = new THREE.Color(hex), n = g.attributes.position.count, col = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) col.set([c.r, c.g, c.b], i * 3);
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    parts.push(g.toNonIndexed());
  };
  const L = CAR_L, W = CAR_W;
  add(new THREE.BoxGeometry(W, 1.1, L - 1.2).translate(0, 2.0, 0), 0xeeeeea);              // body
  add(new THREE.BoxGeometry(W - 0.04, 1.05, L - 1.6).translate(0, 3.05, 0), 0x22282e);     // window band
  add(new THREE.BoxGeometry(W - 0.2, 0.35, L - 1.4).translate(0, 3.75, 0), 0xe4e4e0);      // roof
  add(new THREE.BoxGeometry(W - 0.1, 0.08, L - 1.3).translate(0, 1.47, 0), 0xf2c200);      // yellow stripe
  for (const s of [-1, 1]) {
    // tapered ends, and the bogies under them
    add(new THREE.BoxGeometry(W - 0.3, 2.9, 0.7).translate(0, 2.0, s * (L / 2 - 0.35)), 0xeeeeea);
    add(new THREE.BoxGeometry(W - 0.4, 0.9, 0.62).translate(0, 3.0, s * (L / 2 - 0.3)), 0x22282e);
    add(new THREE.BoxGeometry(W - 0.4, 0.55, 2.6).translate(0, 0.28, s * (L / 2 - 4.5)), 0x2a2c2e);
  }
  add(new THREE.BoxGeometry(1.4, 0.1, 0.1).translate(0, 4.4, 2), 0x3a3d40);                // pantograph
  add(new THREE.BoxGeometry(0.08, 0.6, 0.08).rotateX(0.5).translate(0, 4.1, 2.2), 0x3a3d40);
  return mergeGeometries(parts);
}

export async function createTransit(scene, { surfaceY, url = './data/transit.json' }) {
  const data = await fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const group = new THREE.Group();
  group.name = 'MplsTransit';
  scene.add(group);
  if (!data || !data.rail?.length) return { group, update() {}, trains: () => 0 };

  const lines = data.rail.map((L) => ({
    color: new THREE.Color(L.color),
    paths: L.shapes.map((s, k) => pathOf(s, L.along[k])),
    patterns: L.patterns.map((p) => {
      const n = p[1];
      return { shape: p[0], d: p.slice(2, 2 + n).map((v) => v / 10), arr: p.slice(2 + n, 2 + 2 * n), dep: p.slice(2 + 2 * n, 2 + 3 * n) };
    }),
    trips: L.trips,
  }));

  // The cars: one instanced mesh, each car in its line's colour along the skirt; windows lit after dark
  const geo = carGeometry();
  const mat = new THREE.MeshStandardNodeMaterial({ vertexColors: true, roughness: 0.4, metalness: 0.15 });
  const cars = new THREE.InstancedMesh(geo, mat, MAX_TRAINS * CARS);
  // the skirt, in the line's colour
  const skirt = new THREE.InstancedMesh(new THREE.BoxGeometry(CAR_W, 1.0, CAR_L - 1.2).translate(0, 0.95, 0),
    new THREE.MeshStandardNodeMaterial({ roughness: 0.4, metalness: 0.15 }), MAX_TRAINS * CARS);
  const glowMat = new THREE.MeshBasicNodeMaterial();
  glowMat.colorNode = mix(vec3(0.05, 0.06, 0.07), vec3(1.0, 0.92, 0.75).mul(1.6), smoothstep(0.4, 1.1, cityUniforms.uInteriorGlow));
  const glow = new THREE.InstancedMesh(new THREE.BoxGeometry(CAR_W + 0.02, 0.7, CAR_L - 2.4).translate(0, 3.05, 0), glowMat, MAX_TRAINS * CARS);
  cars.castShadow = cars.receiveShadow = skirt.receiveShadow = true;
  cars.frustumCulled = glow.frustumCulled = skirt.frustumCulled = false;
  cars.count = glow.count = skirt.count = 0;
  group.add(cars, skirt, glow);

  // The overhead line: poles beside one way of each line and the wire over both, from its longest two shapes
  {
    const poles = [], wires = [];
    for (const L of lines) {
      const byLen = [...L.paths].sort((a, b) => (b.end - b.start) - (a.end - a.start));
      const done = [];
      for (const P of byLen) {
        // skip a shape that runs along one already wired (the same track, a shorter trip's)
        const mid = P.at((P.start + P.end) / 2);
        if (done.some((Q) => { for (let s = Q.start; s <= Q.end; s += 20) { const q = Q.at(s); if (Math.hypot(q[0] - mid[0], q[1] - mid[1]) < 2) return true; } return false; })) continue;
        done.push(P);
        let prev = null;
        for (let s = P.start; s <= P.end; s += POLE_GAP) {
          const [x, z, dx, dz] = P.at(s, RIGHT + 2.4);
          const y = surfaceY(x, z);
          poles.push([x, y, z, Math.atan2(dx, dz)]);
          const [wx, wz] = P.at(s, RIGHT);
          const wy = surfaceY(wx, wz) + WIRE_Y;
          if (prev) wires.push([prev, [wx, wy, wz]]);
          prev = [wx, wy, wz];
        }
        if (done.length >= 2) break;
      }
    }
    const metal = new THREE.MeshStandardNodeMaterial({ color: 0x5b6066, roughness: 0.5, metalness: 0.6 });
    const poleGeo = mergeGeometries([
      new THREE.CylinderGeometry(0.12, 0.16, POLE_H, 8).translate(0, POLE_H / 2, 0),
      new THREE.BoxGeometry(2.6, 0.08, 0.08).translate(-1.3, WIRE_Y + 0.4, 0),
    ].map((g) => g.toNonIndexed()));
    const pm = new THREE.InstancedMesh(poleGeo, metal, Math.max(1, poles.length));
    const wm = new THREE.InstancedMesh(new THREE.BoxGeometry(0.025, 0.025, 1).translate(0, 0, 0.5), metal, Math.max(1, wires.length));
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), one = new THREE.Vector3(1, 1, 1), up = new THREE.Vector3(0, 1, 0);
    poles.forEach(([x, y, z, yaw], i) => pm.setMatrixAt(i, m.compose(v.set(x, y, z), q.setFromAxisAngle(up, yaw + Math.PI / 2), one)));
    const a = new THREE.Vector3(), b = new THREE.Vector3(), sc = new THREE.Vector3();
    wires.forEach(([p, r], i) => {
      a.set(...p); b.set(...r);
      const len = a.distanceTo(b);
      const o = new THREE.Object3D();
      o.position.copy(a);
      o.lookAt(b);
      wm.setMatrixAt(i, m.compose(a, o.quaternion, sc.set(1, 1, len)));
    });
    pm.count = poles.length;
    wm.count = wires.length;
    pm.castShadow = true;
    for (const mesh of [pm, wm]) { mesh.computeBoundingSphere(); group.add(mesh); }
  }

  // Today in Minneapolis: a weekday, a Saturday or a Sunday
  const weekday = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', weekday: 'short' }).format(new Date());
  const day = weekday === 'Sat' ? 'sa' : weekday === 'Sun' ? 'su' : 'wk';
  const yesterday = day === 'su' ? 'sa' : day === 'wk' && weekday === 'Mon' ? 'su' : 'wk';

  // Where a trip's train is at time t (seconds after its first departure): its head's distance along its shape, or null
  function headAt(p, t) {
    const n = p.d.length;
    if (t < 0 || t > p.arr[n - 1]) return null;
    for (let k = 0; k < n; k++) {
      if (t <= p.dep[k]) {
        if (t >= p.arr[k] || k === 0) return p.d[k];                // standing at the platform
        const t0 = p.dep[k - 1], t1 = p.arr[k], f = (t - t0) / ((t1 - t0) || 1);
        const e = f * f * (3 - 2 * f);                              // pulling away and braking in
        return p.d[k - 1] + (p.d[k] - p.d[k - 1]) * (e * 0.6 + f * 0.4);
      }
    }
    return p.d[n - 1];
  }

  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), one = new THREE.Vector3(1, 1, 1);
  const e = new THREE.Euler();
  const colorOf = new Map();
  let base = 0, preset = '', active = 0;
  /** Every frame: the clock from the sky's hour, and every train on the map where its timetable puts it now. */
  function update(elapsed, presetId) {
    if (presetId !== preset) { preset = presetId; base = (HOUR[presetId] ?? 12) * 3600 - elapsed; }
    const now = base + elapsed;
    let n = 0;
    for (const L of lines) {
      for (const [list, t] of [[L.trips[day] || [], now], [L.trips[yesterday] || [], now + 86400]]) {
        for (let k = 0; k < list.length && n < MAX_TRAINS; k += 2) {
          const p = L.patterns[list[k]];
          const s = headAt(p, t - list[k + 1]);
          if (s === null) continue;
          const P = L.paths[p.shape];
          const tail = s - CARS * (CAR_L + CAR_GAP);
          if (s < P.start || tail > P.end) continue;
          for (let c = 0; c < CARS; c++) {
            // each car on the track between its two bogies, 10 m either side of its middle
            const mid = s - CAR_L / 2 - c * (CAR_L + CAR_GAP);
            const f = P.at(mid + 10, RIGHT), b = P.at(mid - 10, RIGHT);
            const yf = surfaceY(f[0], f[1]), yb = surfaceY(b[0], b[1]);
            e.set(-Math.atan2(yf - yb, 20), Math.atan2(f[0] - b[0], f[1] - b[1]), 0, 'YXZ');
            m.compose(v.set((f[0] + b[0]) / 2, (yf + yb) / 2 - 0.05, (f[1] + b[1]) / 2), q.setFromEuler(e), one);
            const i = n * CARS + c;
            cars.setMatrixAt(i, m);
            glow.setMatrixAt(i, m);
            skirt.setMatrixAt(i, m);
            if (colorOf.get(i) !== L.color) { skirt.setColorAt(i, L.color); colorOf.set(i, L.color); }
          }
          n++;
        }
      }
    }
    active = n;
    cars.count = glow.count = skirt.count = n * CARS;
    cars.instanceMatrix.needsUpdate = glow.instanceMatrix.needsUpdate = skirt.instanceMatrix.needsUpdate = true;
    if (skirt.instanceColor) skirt.instanceColor.needsUpdate = true;
  }
  return { group, update, trains: () => active };
}
