// Mpls Drive's tree field: the LiDAR survey's trees grown as Slop New York's procedural planes, honey locusts and
// elms (trees.js, with NYC's own TSL tree material from tsl-materials.js), each fitted to its measured height
// and spread. Trees are added and dropped a map piece at a time and regrouped by species, variant and level of detail
// into instanced meshes that follow the camera, each tree dissolving from one level into the next.
import * as THREE from 'three/webgpu';
import { createLeafAtlas, buildTreeGeometries, TREE_SPECIES } from './trees.js';
import { createTreeMaterial } from './tsl-materials.js';

const clampN = (v, a, b) => Math.max(a, Math.min(b, v));
function hashPos(x, y, z) {
  const s = Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453;
  return s - Math.floor(s);
}

/**
 * opts: { lowPower, castShadow }. Returns { group, add(key, sites), remove(key), update(cameraPosition) }.
 * A site is { x, y, z, h, r }: ground position, measured height and crown radius in metres.
 */
export function createTreeField(opts = {}) {
  const LOD_NEAR = opts.lowPower ? 35 : 70;      // full detail within (m)
  const LOD_MID = opts.lowPower ? 140 : 260;     // coarse cards and branches within; whole-crown cards beyond
  const MAX_D = opts.lowPower ? 750 : 1150;
  // [Mpls] A tree doesn't jump from one level to the next: over FADE metres past each of those distances it's drawn
  // at both, one dissolving into the other (createTreeMaterial's fade), and it dissolves away over the last FADE_OUT
  // metres before MAX_D, so the far trees come and go softly too. A tree is in a level's mesh a little before it
  // shows there (EDGE: the camera moves a few metres between regroupings).
  const FADE = [opts.lowPower ? 15 : 25, opts.lowPower ? 40 : 60], FADE_OUT = opts.lowPower ? 100 : 160, EDGE = 8;
  const RANGE = [[-Infinity, LOD_NEAR + FADE[0] + EDGE], [LOD_NEAR - EDGE, LOD_MID + FADE[1] + EDGE], [LOD_MID - EDGE, MAX_D]];
  const group = new THREE.Group();
  group.name = 'Trees';
  const atlas = createLeafAtlas();
  const mats = [
    createTreeMaterial(atlas.texture, { far: [LOD_NEAR, LOD_NEAR + FADE[0]] }),
    createTreeMaterial(atlas.texture, { near: [LOD_NEAR, LOD_NEAR + FADE[0]], far: [LOD_MID, LOD_MID + FADE[1]] }),
    createTreeMaterial(atlas.texture, { near: [LOD_MID, LOD_MID + FADE[1]], far: [MAX_D - FADE_OUT, MAX_D - EDGE] }),
  ];

  const geos = TREE_SPECIES.map((_, s) => [0, 1].map((v) => buildTreeGeometries(s, v, atlas.tileMeters)));
  const fit = geos.map((v) => {
    const bb = v[0][0].boundingBox;
    return { h: bb.max.y, r: Math.max(bb.max.x - bb.min.x, bb.max.z - bb.min.z) / 2 };
  });
  const meshes = [];
  const meshIndex = TREE_SPECIES.map((sp, s) => ({
    l: [0, 1].map((v) => [0, 1].map((l) => meshes.push({ geo: geos[s][v][l], lod: l }) - 1)),
    far: meshes.push({ geo: geos[s][0][2], lod: 2 }) - 1,
  }));
  const instanced = meshes.map((m) => {
    const geo = new THREE.BufferGeometry();
    for (const name of Object.keys(m.geo.attributes)) geo.setAttribute(name, m.geo.attributes[name]);
    geo.setIndex(m.geo.index);
    geo.boundingSphere = m.geo.boundingSphere;
    geo.setAttribute('aTreeData', new THREE.InstancedBufferAttribute(new Float32Array(4), 4));
    geo.setAttribute('aTreePos', new THREE.InstancedBufferAttribute(new Float32Array(3), 3));
    const mesh = new THREE.InstancedMesh(geo, mats[m.lod], 1);
    mesh.count = 0;
    mesh.visible = false;
    mesh.frustumCulled = false;                  // instances surround the camera: the levels do the culling
    mesh.castShadow = !!opts.castShadow;
    mesh.receiveShadow = true;
    group.add(mesh);
    return mesh;
  });

  const pieces = new Map();
  let all = null;                                 // every tree in every piece, rebuilt when pieces come and go
  const dummy = new THREE.Object3D();
  const tint = new THREE.Color();
  function plant(sites) {
    const N = sites.length, P = { N, mats: new Float32Array(N * 16), data: new Float32Array(N * 4), pos: new Float32Array(N * 3), meshOf: new Int16Array(N * 3) };
    sites.forEach((t, i) => {
      const r1 = hashPos(t.x, 1.3, t.z), r2 = hashPos(t.z, 7.1, t.x), r3 = hashPos(t.x + t.z, 3.3, 0.7);
      // Broad crowns as elms, slim ones as honey locusts, planes (standing in for maples and lindens) among them.
      const spread = t.r / Math.max(4, t.h);
      const sp = spread > 0.42 ? (r1 < 0.7 ? 2 : 0) : spread < 0.3 ? (r1 < 0.6 ? 1 : 0) : Math.floor(r1 * 2.999);
      const variant = hashPos(t.x, 5.9, t.z) < 0.5 ? 0 : 1;
      const sy = clampN(t.h / fit[sp].h, 0.35, 2.6);
      const sxz = clampN(t.r / fit[sp].r, sy * 0.6, sy * 1.6);
      dummy.position.set(t.x, t.y - 0.15, t.z);
      dummy.rotation.set(0, r2 * Math.PI * 2, 0);
      dummy.scale.set(sxz * (0.92 + r3 * 0.16), sy, sxz * (0.92 + r2 * 0.16));
      dummy.updateMatrix();
      dummy.matrix.toArray(P.mats, i * 16);
      tint.setHex(TREE_SPECIES[sp].tints[Math.floor(r3 * 2.999)]).multiplyScalar(0.82 + r1 * 0.36);
      P.data.set([tint.r, tint.g, tint.b, sp + r2 * 0.999], i * 4);
      P.pos.set([t.x, t.y + t.h * 0.6, t.z], i * 3);
      const mi = meshIndex[sp];
      P.meshOf.set([mi.l[variant][0], mi.l[variant][1], mi.far], i * 3);
    });
    return P;
  }
  function gather() {
    let N = 0;
    for (const P of pieces.values()) N += P.N;
    all = { N, list: [...pieces.values()], lod: new Uint8Array(N) };       // lod: a bit for each level the tree's drawn at
    const caps = new Array(instanced.length).fill(0);
    for (const P of all.list) for (let i = 0; i < P.N * 3; i++) caps[P.meshOf[i]]++;
    instanced.forEach((mesh, k) => {
      if (mesh.instanceMatrix.count >= caps[k] && mesh.instanceMatrix.count < caps[k] * 3 + 64) return;
      const cap = Math.max(1, Math.ceil(caps[k] * 1.3));
      mesh.instanceMatrix = new THREE.InstancedBufferAttribute(new Float32Array(cap * 16), 16);
      mesh.geometry.setAttribute('aTreeData', new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4));
      mesh.geometry.setAttribute('aTreePos', new THREE.InstancedBufferAttribute(new Float32Array(cap * 3), 3));
    });
    last.set(Infinity, Infinity, Infinity);
  }
  const counts = new Array(instanced.length).fill(0);
  function rebuild() {
    counts.fill(0);
    let o = 0;
    for (const P of all.list) {
      for (let i = 0; i < P.N; i++) {
        const bits = all.lod[o + i];
        for (let l = 0; l < 3; l++) {
          if (!(bits & (1 << l))) continue;
          const mi = P.meshOf[i * 3 + l], mesh = instanced[mi], c = counts[mi]++;
          mesh.instanceMatrix.array.set(P.mats.subarray(i * 16, i * 16 + 16), c * 16);
          mesh.geometry.attributes.aTreeData.array.set(P.data.subarray(i * 4, i * 4 + 4), c * 4);
          mesh.geometry.attributes.aTreePos.array.set(P.pos.subarray(i * 3, i * 3 + 3), c * 3);
        }
      }
      o += P.N;
    }
    instanced.forEach((mesh, mi) => {
      const n = counts[mi];
      if (n > 0) {
        mesh.instanceMatrix.needsUpdate = true;
        mesh.geometry.attributes.aTreeData.needsUpdate = true;
        mesh.geometry.attributes.aTreePos.needsUpdate = true;
      }
      mesh.count = n;
      mesh.visible = n > 0;
    });
  }
  const last = new THREE.Vector3(Infinity, Infinity, Infinity);
  let dirty = false;
  function update(cam) {
    if (dirty) { gather(); dirty = false; }
    if (!all || cam.distanceToSquared(last) < 16) return;
    last.copy(cam);
    let changed = false, o = 0;
    for (const P of all.list) {
      for (let i = 0; i < P.N; i++, o++) {
        const dx = P.pos[i * 3] - cam.x, dy = P.pos[i * 3 + 1] - cam.y, dz = P.pos[i * 3 + 2] - cam.z;
        const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
        const v = (d < RANGE[0][1] ? 1 : 0) | (d > RANGE[1][0] && d < RANGE[1][1] ? 2 : 0) | (d > RANGE[2][0] && d < RANGE[2][1] ? 4 : 0);
        if (v !== all.lod[o]) { all.lod[o] = v; changed = true; }
      }
    }
    if (changed) rebuild();
  }
  return {
    group,
    add(key, sites) { if (sites.length) { pieces.set(key, plant(sites)); dirty = true; } },
    remove(key) { if (pieces.delete(key)) dirty = true; },
    update,
  };
}
