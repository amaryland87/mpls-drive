// [Mpls] Parked cars: Slop New York's sedans and SUVs (actor-models.js), standing still where a tile says (its hero
// buildings' pk lists: x, z, heading, body 0 sedan 1 SUV, paint), on the ground there, lamps dark. One instanced mesh
// per body for all the tiles loaded; their collision boxes are the tile's own (mpls-geo.js heroGeo).
import * as THREE from 'three/webgpu';
import { BODY_SPECS, buildCarGeometry, createLoftedCarMaterial } from './actor-models.js';
import { createContactShadowMaterial } from './tsl-materials.js';
import { ground } from './ground.js';

// The colours cars are in a Minneapolis lot: white, black, greys and silvers, then a few blues, reds and others
const PAINT = [0xf2f3f4, 0x1b1e22, 0x9aa1a8, 0x5b6067, 0xc9ced3, 0x1f3a63, 0x7a1d22, 0x2f4a3b, 0xb8ab92, 0x8e1c1c]
  .map((c) => new THREE.Color(c));
const BODIES = ['sedan', 'suv'];

export function createParkedCars(root) {
  const byTile = new Map();
  const meshes = {};
  const shadowGeo = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
  const shadowMat = createContactShadowMaterial();
  let shadows = null;
  const dummy = new THREE.Object3D();

  function mesh(kind, n) {
    const old = meshes[kind];
    if (old && old.instanceMatrix.count >= n) return old;
    if (old) { root.remove(old); old.dispose(); }
    const cap = Math.max(8, n * 2);
    const geo = buildCarGeometry(BODY_SPECS[kind], true);
    geo.setAttribute('paintColor', new THREE.InstancedBufferAttribute(new Float32Array(cap * 3), 3));
    geo.setAttribute('carState', new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4));
    const m = new THREE.InstancedMesh(geo, createLoftedCarMaterial(BODY_SPECS[kind], null, true), cap);
    m.castShadow = m.receiveShadow = true;
    m.name = 'MplsParked_' + kind;
    root.add(m);
    return (meshes[kind] = m);
  }

  // Every car of every loaded tile, laid out again whenever a tile comes or goes (a few dozen at most)
  function layout() {
    const all = [...byTile.values()].flat();
    const total = all.length;
    if (!shadows || shadows.instanceMatrix.count < total) {
      if (shadows) { root.remove(shadows); shadows.dispose(); }
      shadows = new THREE.InstancedMesh(shadowGeo, shadowMat, Math.max(8, total * 2));
      shadows.renderOrder = 998;
      root.add(shadows);
    }
    shadows.count = 0;
    for (const kind of BODIES) {
      const cars = all.filter((c) => BODIES[c.body] === kind);
      const m = mesh(kind, cars.length);
      const paint = m.geometry.attributes.paintColor;
      m.count = 0;
      for (const c of cars) {
        const fx = Math.sin(c.yaw) * 1.4, fz = Math.cos(c.yaw) * 1.4, sx = Math.cos(c.yaw) * 0.9, sz = -Math.sin(c.yaw) * 0.9;
        const y = ground.at(c.x, c.z, Infinity);
        const pitch = Math.atan2(ground.at(c.x + fx, c.z + fz, y + 1) - ground.at(c.x - fx, c.z - fz, y + 1), 2.8);
        const roll = Math.atan2(ground.at(c.x + sx, c.z + sz, y + 1) - ground.at(c.x - sx, c.z - sz, y + 1), 1.8);
        dummy.position.set(c.x, y, c.z);
        dummy.rotation.set(-pitch, c.yaw, roll, 'YXZ');
        dummy.scale.set(1, 1, 1);
        dummy.updateMatrix();
        const k = m.count++;
        m.setMatrixAt(k, dummy.matrix);
        const col = PAINT[c.paint % PAINT.length];
        paint.setXYZ(k, col.r, col.g, col.b);
        dummy.position.y = y + 0.018;
        dummy.scale.set(2.22, 1, kind === 'suv' ? 5.15 : 5.05);
        dummy.updateMatrix();
        shadows.setMatrixAt(shadows.count++, dummy.matrix);
      }
      m.instanceMatrix.needsUpdate = true;
      paint.needsUpdate = true;
      m.computeBoundingSphere();
    }
    shadows.instanceMatrix.needsUpdate = true;
    shadows.computeBoundingSphere();
  }

  return {
    /** A tile's parked cars: a flat list of x, z, heading, body, paint. */
    add(key, list) {
      const cars = [];
      for (let k = 0; k + 4 < list.length; k += 5) cars.push({ x: list[k], z: list[k + 1], yaw: list[k + 2], body: list[k + 3], paint: list[k + 4] });
      if (!cars.length) return;
      byTile.set(key, cars);
      layout();
    },
    remove(key) {
      if (byTile.delete(key)) layout();
    },
  };
}
