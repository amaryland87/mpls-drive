// Minneapolis, for the Slop New York engine: the ground and its hills, the city's buildings, houses, streets, lamps,
// trees, bridges and US Bank Stadium, streamed in 1 km tiles around the camera. The tiles are built off the main
// thread (mpls-worker.js); here they only become meshes. Also the questions the engine asks of the city: how high
// the ground (or a bridge deck) is anywhere, and which solid things stand near a point, as Slop New York's box
// colliders (controllers.js).
import * as THREE from 'three/webgpu';
import {
  Fn, uniform, texture, uv, attribute, vertexColor, positionWorld, materialRoughness, float, vec2, vec3, mix,
  smoothstep, step, max, min, floor, fract, dot, round, normalMap, fwidth,
} from 'three/tsl';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import {
  cityUniforms, evaluateApartmentInterior, createRoadSurfaceMaterial, createRoadPaintMaterial, createSidewalkMaterial,
  createCurbMaterial, createWaterMaterial, createPavedStreetMaterial,
} from './tsl-materials.js';
import { decodeGround, setGround, groundH, bridgeList, bridgeHeightAt, bridgeArrays, cityXZ, PIECE, ROAD_Y, WALK_Y, SOLID_CELL } from './mpls-geo.js';
import { createTreeField } from './mpls-trees.js';
import { createStadium } from './mpls-stadium.js';
import { ground as sharedGround } from './ground.js';
import { createParkedCars } from './mpls-parked.js';

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const SURF_N = 512;

/**
 * Loads index.json and the ground, starts the worker and returns the city:
 * { bounds, index, groundH, deckAt, surfaceY, surfaceAt, nearColliders, update(camera), whenReady(x, z, r), tiles }.
 * opts: { scene, renderer, base (the city data folder), tex (the facade textures), lowPower }.
 */
export async function createCity({ scene, renderer, base, tex, lowPower = false }) {
  const LOAD_R = lowPower ? 1500 : 2400;        // tiles this close are loaded: their big buildings, ground and collision
  const DROP_R = LOAD_R + 600;                   // and dropped again past this
  const DETAIL_R = lowPower ? 650 : 1000;        // houses, streets, lamps and trees within this of the camera
  const MAX_ANISO = renderer.getMaxAnisotropy();

  const index = await fetch(base + 'index.json').then((r) => { if (!r.ok) throw new Error('index.json: ' + r.status); return r.json(); });
  const [x0, x1, z0, z1] = index.bounds;
  const MAP = { x0, x1, z0, z1, tile: index.tile, ni: index.ni, nj: index.nj };
  let buf = await fetch(base + 'ground.bin').then((r) => { if (!r.ok) throw new Error('ground.bin: ' + r.status); return r.arrayBuffer(); });
  const head = new Uint8Array(buf, 0, 2);
  if (head[0] === 0x1f && head[1] === 0x8b) {     // still gzipped (no server unpacked it on the way)
    buf = await new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
  }
  const ground = { x0, z0, step: index.gr.step, nx: index.gr.nx, nz: index.gr.nz, h: decodeGround(buf, index.gr) };
  setGround(ground);

  const worker = new Worker(new URL('./mpls-worker.js', import.meta.url), { type: 'module' });
  worker.postMessage({
    type: 'init', base: new URL(base, location.href).href,
    ground: { ...ground, h: ground.h.slice() },
    palette: { walls: index.walls, houseWall: index.houseWall, houseRoof: index.houseRoof, boxWall: index.boxWall, roofs: index.roofs },
    bridges: index.br,
  });

  /* ------------------------------- Materials ------------------------------- */
  const placeholderArray = () => { const t = new THREE.DataArrayTexture(new Uint8Array([255, 255, 255, 255]), 1, 1, 1); t.needsUpdate = true; return t; };
  const facadeColorTex = texture(placeholderArray());
  const facadeNormalTex = texture(placeholderArray());
  await loadFacades();
  async function loadFacades() {
    const n = lowPower ? 256 : 512;
    const read = (file) => new Promise((res, rej) => {
      const img = new Image();
      img.onload = () => res(img);
      img.onerror = () => rej(new Error('texture ' + file));
      img.src = tex + file;
    });
    const [c, nm] = await Promise.all([read(lowPower ? 'facade-s.jpg' : 'facade.jpg'), read(lowPower ? 'facade-n-s.jpg' : 'facade-n.jpg')]);
    const layers = Math.round(c.naturalHeight / c.naturalWidth);
    const toArray = (img, srgb) => {
      // The layers are stacked top to bottom, which is exactly a texture array's memory layout.
      const cv = document.createElement('canvas');
      cv.width = n; cv.height = n * layers;
      const g = cv.getContext('2d', { willReadFrequently: true });
      g.drawImage(img, 0, 0, n, n * layers);
      const t = new THREE.DataArrayTexture(new Uint8Array(g.getImageData(0, 0, n, n * layers).data.buffer), n, n, layers);
      t.wrapS = t.wrapT = THREE.RepeatWrapping;
      t.minFilter = THREE.LinearMipmapLinearFilter;
      t.generateMipmaps = true;
      t.anisotropy = MAX_ANISO;
      t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      t.needsUpdate = true;
      return t;
    };
    facadeColorTex.value = toArray(c, true);
    facadeNormalTex.value = toArray(nm, false);
  }

  // A standard material whose colour and normal come from the texture array (layer per vertex), with glass made
  // shiny and trim kept untinted by the mask in the normal map's blue channel. Behind the windows, Slop New York's
  // apartment interiors (tsl-materials.js), ray-marched from the view, along the facade uvs (a bay and a floor per
  // unit). After dark a share of them light up, more of the shops on the ground floor.
  function makeCityMat(extra = {}) {
    const mat = new THREE.MeshStandardNodeMaterial({ roughness: 0.92, metalness: 0, side: THREE.DoubleSide, ...extra });
    const la = attribute('la', 'vec2');                    // texture layer, sky occlusion (bytes, normalised)
    const layer = round(la.x.mul(255));
    const fUV = uv();
    const t = facadeColorTex.sample(fUV).depth(layer);
    const nrm = facadeNormalTex.sample(fUV).depth(layer);
    const trim = smoothstep(0.2, 0.45, nrm.b), glass = smoothstep(0.7, 0.9, nrm.b);
    const windowed = glass.mul(min(step(layer, 5.5).add(step(19.5, layer)), 1));     // [Mpls] and the houses' new walls
    const shop = step(3.5, layer).mul(step(layer, 4.5));
    const seed = dot(vertexColor().rgb, vec3(97.1, 53.7, 31.3)).add(layer.mul(7.3));
    const room = evaluateApartmentInterior(fUV.x.mul(2.6), fUV.y.mul(3.4), fract(fUV), floor(fUV), 2.6, 3.4, seed, 0.62,
      mix(0.42, 0.85, shop).mul(0.65), vec2(fwidth(fUV.x), fwidth(fUV.y)));
    const wallCol = t.rgb.mul(mix(vertexColor().rgb, vec3(1), trim)).mul(la.y);
    mat.colorNode = mix(wallCol, room.xyz.mul(vec3(0.71, 0.78, 0.75)).mul(0.5), windowed.mul(0.75));
    mat.roughnessNode = mix(materialRoughness, 0.06, glass);
    mat.metalnessNode = mix(0.0, 0.35, glass);
    const nxy = nrm.rg.mul(2).sub(1);
    const nz = max(float(1).sub(dot(nxy, nxy)), 0).sqrt();
    mat.normalNode = normalMap(vec3(nrm.rg, nz.mul(0.5).add(0.5)), vec2(1.4));
    mat.emissiveNode = room.xyz.mul(room.w).mul(windowed).mul(cityUniforms.uInteriorGlow).mul(0.72);
    return mat;
  }
  const cityMat = makeCityMat();
  // Streets lie a couple of centimetres over the ground and the paint just over them: pulled towards the camera in
  // the depth test so they never flicker against what's beneath.
  const trailMat = makeCityMat({ side: THREE.FrontSide, roughness: 0.95, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4 });
  // Slop New York's asphalt (patches, cracks, oil, puddles after dark), sidewalk flags, curbs and worn paint.
  const lift = (mat, k) => Object.assign(mat, { polygonOffset: true, polygonOffsetFactor: -k, polygonOffsetUnits: -2 * k });
  const roadMat = lift(createRoadSurfaceMaterial(), 2);
  const walkMat = lift(createSidewalkMaterial(), 2);
  const curbMat = lift(createCurbMaterial(), 2);
  // [Mpls] the concrete and brick streets
  const concreteMat = lift(createPavedStreetMaterial('concrete'), 2);
  const brickMat = lift(createPavedStreetMaterial('brick'), 2);
  const paintMat = lift(createRoadPaintMaterial(), 4);
  paintMat.side = THREE.DoubleSide;
  const bridgeMat = new THREE.MeshStandardNodeMaterial({ vertexColors: true, roughness: 0.85, side: THREE.DoubleSide });
  // The Mississippi and the lakes: Slop New York's water (waves, sky and reflections), laid over the deep-water cells
  const waterMat = lift(createWaterMaterial(), 3);

  // The ground: each tile's baked street map, lit like everything else. Lawns take real grass and parking lots real
  // asphalt from the facade array, keeping the map's own light and shade (occlusion, canopy shadow) but not its colour.
  const grain = (() => {
    const cv = document.createElement('canvas');
    cv.width = cv.height = 256;
    const g = cv.getContext('2d');
    const img = g.createImageData(256, 256);
    for (let i = 0; i < 256 * 256; i++) {
      const v = 200 + Math.random() * 55;
      img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v;
      img.data[i * 4 + 3] = 255;
    }
    g.putImageData(img, 0, 0);
    const t = new THREE.CanvasTexture(cv);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = MAX_ANISO;
    return t;
  })();
  const solidTexture = (hex) => {
    const c = new THREE.Color(hex);
    const t = new THREE.DataTexture(new Uint8Array([c.r * 255, c.g * 255, c.b * 255, 255]), 1, 1);
    t.colorSpace = THREE.SRGBColorSpace;
    t.needsUpdate = true;
    return t;
  };
  const mapBounds = new THREE.Vector4(x0, x1, z0, z1);
  function groundMaterial(bounds, detail) {
    const mat = new THREE.MeshStandardNodeMaterial({ roughness: 0.96, metalness: 0, transparent: !!bounds });
    const mapNode = texture(solidTexture('#a9d17c'));
    mat.userData.mapNode = mapNode;
    const xz = positionWorld.xz;
    mat.colorNode = Fn(() => {
      const c = mapNode.rgb.toVar();
      const fine = texture(grain, xz.mul(0.35)).r, broad = texture(grain, xz.mul(0.021)).r;
      c.mulAssign(fine.mul(0.12).add(broad.mul(0.1)).add(0.74));
      c.assign(mix(vec3(dot(c, vec3(0.333))), c, 0.92));      // NYC's grade adds the colour back
      if (detail) {
        const lawn = smoothstep(0.03, 0.12, c.g.sub(max(c.r, c.b)));
        const paved = float(1).sub(lawn).mul(smoothstep(0.08, 0.02, max(c.r, max(c.g, c.b)).sub(min(c.r, min(c.g, c.b)))));
        const grass = facadeColorTex.sample(xz.div(2.8)).depth(19).rgb.mul(1.45);
        const asph = facadeColorTex.sample(xz.div(4.0)).depth(16).rgb.mul(vec3(1.05, 1.1, 1.18));
        const shade = dot(c, vec3(0.3, 0.6, 0.1)).div(0.55);
        c.assign(mix(c, grass.mul(min(shade, 1.1)), lawn.mul(0.85)));
        c.assign(mix(c, asph, paved.mul(0.7)));
      }
      return c.mul(0.85);
    })();
    if (bounds) {
      // The sharp tiles fade out over the last stretch of the map, onto the wide map below.
      const B = uniform(new THREE.Vector4().copy(bounds));
      const edge = min(min(xz.x.sub(B.x), B.y.sub(xz.x)), min(xz.y.sub(B.z), B.w.sub(xz.y)));
      mat.opacityNode = smoothstep(0.0, 160.0, edge);
    }
    return mat;
  }
  // Beyond the loaded tiles: the whole map's ground, coarse (a node every 50 m), with the overview image on it, and the
  // wide map round it out to the horizon. Both are the bottom layer: they write no depth and draw first, so the tiles
  // (and anything else) always cover them, and they sit a little lower than the tiles' finer ground.
  const COARSE = 50, nx = Math.round((x1 - x0) / COARSE) + 1, nz = Math.round((z1 - z0) / COARSE) + 1;
  const coarse = (() => {
    const pos = new Float32Array(nx * nz * 3), uvs = new Float32Array(nx * nz * 2), idx = [];
    for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
      const x = x0 + i * COARSE, z = z0 + j * COARSE, k = j * nx + i;
      pos.set([x, groundH(x, z) - 1.5, z], k * 3);
      uvs.set([(x - x0) / (x1 - x0), 1 - (z - z0) / (z1 - z0)], k * 2);
    }
    for (let j = 0; j < nz - 1; j++) for (let i = 0; i < nx - 1; i++) {
      const a = j * nx + i, b = a + 1, c = a + nx, d = c + 1;
      idx.push(a, c, b, b, c, d);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
    g.setIndex(idx);
    g.computeVertexNormals();
    g.computeBoundingSphere();
    return g;
  })();
  // The wide map: a frame of four quads round the map, at the height its edge eases back to
  const frame = (() => {
    const R = 20000, y = groundH(x0, z0) - 1.5;
    const quads = [[-R, -R, R, z0], [-R, z1, R, R], [-R, z0, x0, z1], [x1, z0, R, z1]];
    const pos = [], uvs = [];
    const P = (x, z) => { pos.push(x, y, z); uvs.push(0.5 + x / (2 * R), 0.5 - z / (2 * R)); };
    for (const [ax, az, bx, bz] of quads) { P(ax, az); P(ax, bz); P(bx, az); P(bx, az); P(ax, bz); P(bx, bz); }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
    g.computeVertexNormals();
    g.computeBoundingSphere();
    return g;
  })();
  const loadInto = (url, mat) => new THREE.TextureLoader().load(url, (t) => {
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = MAX_ANISO;
    mat.userData.mapNode.value = t;
  });
  for (const [geo, name, url] of [[coarse, 'MplsCoarseGround', new URL('overview.jpg', new URL(base, location.href)).href],
    [frame, 'MplsFarGround', new URL('../mpls-map-far.jpg', new URL(base, location.href)).href]]) {
    const m = new THREE.Mesh(geo, groundMaterial(null, false));
    m.material.depthWrite = false;
    m.renderOrder = -2;
    m.receiveShadow = true;
    m.name = name;
    scene.add(m);
    loadInto(url, m.material);
  }

  /* -------------------------------- Bridges -------------------------------- */
  const bridges = bridgeList(index.br);
  const BRIDGE_CELL = 64, bridgeCells = new Map();
  for (const br of bridges) {
    const xs = [br.ax, br.ax + br.ux * br.L], zs = [br.az, br.az + br.uz * br.L], r = br.w / 2 + 1;
    for (let i = Math.floor((Math.min(...xs) - r) / BRIDGE_CELL); i <= Math.floor((Math.max(...xs) + r) / BRIDGE_CELL); i++) {
      for (let j = Math.floor((Math.min(...zs) - r) / BRIDGE_CELL); j <= Math.floor((Math.max(...zs) + r) / BRIDGE_CELL); j++) {
        const key = i * 100000 + j;
        if (!bridgeCells.has(key)) bridgeCells.set(key, []);
        bridgeCells.get(key).push(br);
      }
    }
  }
  {
    const A = bridgeArrays(bridges);
    if (A) {
      const g = new THREE.BufferGeometry();
      for (const [k, v] of Object.entries(A)) g.setAttribute(k, new THREE.BufferAttribute(v, 3));
      g.computeBoundingSphere();
      const m = new THREE.Mesh(g, bridgeMat);
      m.castShadow = m.receiveShadow = !lowPower;
      m.name = 'MplsBridges';
      scene.add(m);
    }
  }
  const noBridges = [];
  /** The highest deck at (x, z) that something at height y can stand on: { h, br, t, s }, or null for the ground. */
  function deckAt(x, z, y = Infinity) {
    let best = null;
    for (const br of bridgeCells.get(Math.floor(x / BRIDGE_CELL) * 100000 + Math.floor(z / BRIDGE_CELL)) || noBridges) {
      const dx = x - br.ax, dz = z - br.az;
      const t = dx * br.ux + dz * br.uz;
      if (t < -3 || t > br.L + 3) continue;          // a little past its ends, so the bank can't drop away first
      const s = -dx * br.uz + dz * br.ux;
      if (Math.abs(s) > br.w / 2 + 0.2) continue;
      const h = bridgeHeightAt(br, t);
      if (h - y > 2) continue;                      // a deck overhead: passing underneath
      if (!best || h > best.h) best = { h, br, t, s };
    }
    return best;
  }
  /**
   * What something at height y stands on at (x, z): a deck under it, or else the street over the ground. (deckAt's
   * test, inline and without allocating: the traffic and the cameras ask this thousands of times a frame.)
   */
  function surfaceY(x, z, y = Infinity) {
    let h = groundH(x, z) + ROAD_Y;
    const list = bridgeCells.get(Math.floor(x / BRIDGE_CELL) * 100000 + Math.floor(z / BRIDGE_CELL));
    if (!list) return h;
    for (let k = 0; k < list.length; k++) {
      const br = list[k], dx = x - br.ax, dz = z - br.az;
      const t = dx * br.ux + dz * br.uz;
      if (t < -3 || t > br.L + 3 || Math.abs(-dx * br.uz + dz * br.ux) > br.w / 2 + 0.2) continue;
      const d = bridgeHeightAt(br, t);
      if (d - y <= 2 && d + 0.06 > h) h = d + 0.06;
    }
    return h;
  }

  // The engine's modules stand their traffic and people on this (ground.js)
  sharedGround.at = surfaceY;

  /* ----------------------------- Street lamps -----------------------------
     The city's street lights by fixture ([Mpls] bake_tiles.py lp; elsewhere Slop New York's cobra heads): a dark metal
     pole and its head, whose lens is a pale diffuser by day and glows warm after dusk. 0 cobra head on an arm out over
     the street, 1 the lantern on a short ornamental post, 2 the acorn, 3 the teardrop hung from a tall curved arm,
     4 the shoebox, 5 a globe, 6 a knee-high accent light. After dark the lamps nearest the camera each get a real light
     from a shared pool: point lights, which the clustered lighting sorts so each pixel only works out the few lamps
     that reach it.                                                                                                  */
  const LAMP_H = 8.4, LAMP_ARM = 2.6;
  const merged = (gs) => mergeGeometries(gs.map((g) => g.toNonIndexed()));
  const cyl = (r0, r1, h, y, x = 0) => new THREE.CylinderGeometry(r0, r1, h, 10).translate(x, y + h / 2, 0);
  const box = (sx, sy, sz, x, y) => new THREE.BoxGeometry(sx, sy, sz).translate(x, y, 0);
  const LAMP_KINDS = [
    { // 0 cobra head
      pole: merged([cyl(0.06, 0.06, LAMP_H, 0), cyl(0.16, 0.2, 0.5, 0), box(LAMP_ARM - 0.3, 0.09, 0.09, (LAMP_ARM - 0.3) / 2, LAMP_H - 0.2),
        new THREE.SphereGeometry(1, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2).scale(0.7, 0.2, 0.3).translate(LAMP_ARM, LAMP_H - 0.32, 0)]),
      lens: new THREE.CircleGeometry(1, 16).rotateX(Math.PI / 2).scale(0.6, 1, 0.24).translate(LAMP_ARM, LAMP_H - 0.325, 0),
      head: [LAMP_ARM, LAMP_H - 0.4], reach: 0.8,
    },
    { // 1 lantern: black fluted post, a four-sided glass lantern with a cap and finial
      pole: merged([cyl(0.08, 0.11, 3.9, 0), cyl(0.2, 0.24, 0.7, 0), cyl(0.14, 0.1, 0.18, 3.9), cyl(0.05, 0.32, 0.25, 4.85), cyl(0.04, 0.04, 0.25, 5.1)]),
      lens: new THREE.CylinderGeometry(0.27, 0.17, 0.75, 4).rotateY(Math.PI / 4).translate(0, 4.47, 0),
      head: [0, 4.5], reach: 0,
    },
    { // 2 acorn
      pole: merged([cyl(0.08, 0.11, 3.8, 0), cyl(0.2, 0.24, 0.7, 0), cyl(0.12, 0.08, 0.15, 3.8), cyl(0.04, 0.2, 0.2, 4.55)]),
      lens: new THREE.SphereGeometry(0.24, 14, 10).scale(1, 1.6, 1).translate(0, 4.32, 0),
      head: [0, 4.3], reach: 0,
    },
    { // 3 teardrop: tall pole, a curved arm, the pendant hanging from its end
      pole: merged([cyl(0.1, 0.14, 8.6, 0), cyl(0.22, 0.26, 0.8, 0), box(1.0, 0.08, 0.08, 0.5, 8.75), box(0.7, 0.08, 0.08, 1.25, 8.6),
        cyl(0.03, 0.03, 0.4, 7.95, 1.6), cyl(0.06, 0.24, 0.2, 7.75, 1.6)]),
      lens: new THREE.SphereGeometry(0.26, 14, 10).scale(1, 1.5, 1).translate(1.6, 7.45, 0),
      head: [1.6, 7.4], reach: 0.3,
    },
    { // 4 shoebox
      pole: merged([cyl(0.08, 0.1, 9.0, 0), cyl(0.18, 0.22, 0.5, 0), box(1.2, 0.09, 0.09, 0.6, 8.9), box(0.75, 0.18, 0.45, 1.5, 8.9)]),
      lens: new THREE.PlaneGeometry(0.66, 0.38).rotateX(Math.PI / 2).translate(1.5, 8.8, 0),
      head: [1.5, 8.75], reach: 0.5,
    },
    { // 5 globe
      pole: merged([cyl(0.07, 0.1, 3.5, 0), cyl(0.18, 0.22, 0.6, 0), cyl(0.1, 0.07, 0.15, 3.5)]),
      lens: new THREE.SphereGeometry(0.3, 16, 12).translate(0, 3.92, 0),
      head: [0, 3.9], reach: 0,
    },
    { // 6 accent: a bollard light
      pole: merged([cyl(0.1, 0.1, 0.85, 0), cyl(0.12, 0.12, 0.08, 1.05)]),
      lens: new THREE.CylinderGeometry(0.09, 0.09, 0.2, 10, 1, true).translate(0, 0.95, 0),
      head: [0, 0.95], reach: 0,
    },
  ];
  const lampPoleMat = new THREE.MeshStandardNodeMaterial({ color: 0x3b4046, roughness: 0.45, metalness: 0.78 });
  const lampLensMat = new THREE.MeshBasicNodeMaterial({ side: THREE.DoubleSide });
  lampLensMat.colorNode = mix(vec3(new THREE.Color(0x8f918c)), vec3(new THREE.Color(0xfff1d6)).mul(2.1), smoothstep(0.4, 1.1, cityUniforms.uInteriorGlow));
  const lampSites = new Map();                        // piece -> [{ x, y, z, tx, tz, gy }] lamp heads and where they aim
  // spots: [x, z, angle, fixture] flat
  function lampMeshes(P, spots) {
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), one = new THREE.Vector3(1, 1, 1), up = new THREE.Vector3(0, 1, 0);
    const sites = [], meshes = [];
    LAMP_KINDS.forEach((K, kind) => {
      const mine = [];
      for (let k = 0; k < spots.length; k += 4) if (spots[k + 3] === kind) mine.push(k);
      if (!mine.length) return;
      const pole = new THREE.InstancedMesh(K.pole, lampPoleMat, mine.length), lens = new THREE.InstancedMesh(K.lens, lampLensMat, mine.length);
      mine.forEach((k, n) => {
        const x = spots[k], z = spots[k + 1], a = spots[k + 2];
        const y = groundH(x, z) + WALK_Y;
        m.compose(v.set(x, y, z), q.setFromAxisAngle(up, a), one);
        pole.setMatrixAt(n, m);
        lens.setMatrixAt(n, m);
        const [hx, hy] = K.head, ca = Math.cos(a), sa = Math.sin(a);
        if (kind !== 6) sites.push({ x: x + ca * hx, y: y + hy, z: z - sa * hx, tx: x + ca * (hx + K.reach), tz: z - sa * (hx + K.reach), gy: y });
      });
      for (const mesh of [pole, lens]) { mesh.computeBoundingSphere(); mesh.castShadow = !lowPower && mesh === pole; mesh.receiveShadow = true; meshes.push(mesh); }
    });
    lampSites.set(P, sites);
    return meshes;
  }
  const LAMP_LIGHTS = 36, LAMP_LIGHT_R = 115;
  let lampLightCount = lowPower ? 12 : 36;
  const lampGroup = new THREE.Group();
  lampGroup.name = 'MplsLampLights';
  scene.add(lampGroup);
  const lampLights = [];
  for (let i = 0; i < LAMP_LIGHTS; i++) {
    const lamp = new THREE.PointLight(0xffe8c2, 0, 22, 1.25);
    lamp.position.set(0, -1000, 0);
    lampGroup.add(lamp);
    lampLights.push(lamp);
  }
  const nearLamps = [];
  function stepLampLights(camera) {
    const glow = cityUniforms.uInteriorGlow.value;
    const scale = Math.min(1.25, Math.max(0, (glow - 0.36) * 1.15));
    nearLamps.length = 0;
    if (scale > 0.001) {
      const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z, me = camera.matrixWorld.elements;
      for (const sites of lampSites.values()) for (const s of sites) {
        const dx = s.x - cx, dz = s.z - cz, dy = s.gy - cy;
        const d = Math.sqrt(dx * dx + dz * dz + dy * dy);
        if (d > LAMP_LIGHT_R) continue;
        s.eff = d + Math.max(0, 6 - (dx * -me[8] + dz * -me[10])) * 2.8;      // the ones behind count as further
        if (s.eff < LAMP_LIGHT_R) nearLamps.push(s);
      }
      nearLamps.sort((a, b) => a.eff - b.eff);
    }
    const cutoff = nearLamps.length > lampLightCount ? Math.min(LAMP_LIGHT_R, nearLamps[lampLightCount].eff) : LAMP_LIGHT_R;
    lampLights.forEach((lamp, i) => {
      const s = i < lampLightCount ? nearLamps[i] : null;
      if (!s) { lamp.intensity = 0; lamp.position.set(0, -1000, 0); return; }
      const t = clamp((cutoff - s.eff) / (cutoff * 0.38), 0, 1);
      lamp.position.set(s.x + (s.tx - s.x) * 0.15, s.y - 0.9, s.z + (s.tz - s.z) * 0.15);
      lamp.intensity = 80 * scale * t * t * (3 - 2 * t);
    });
    lampGroup.updateMatrixWorld();
  }

  // Trees from the LiDAR survey, grown as Slop New York's procedural elms, locusts and planes (mpls-trees.js).
  const trees = createTreeField({ lowPower, castShadow: !lowPower });
  scene.add(trees.group);

  // US Bank Stadium is drawn by mpls-stadium.js: prow, zinc, ETFE roof and glass doors, lit from inside after dark.
  const stadiumNight = smoothstep(0.45, 1.25, cityUniforms.uInteriorGlow);

  /* ------------------------------- Tiles ------------------------------- */
  const root = new THREE.Group();
  root.name = 'Minneapolis';
  scene.add(root);
  const parked = createParkedCars(root);
  const tiles = new Map();          // 'i_j' -> tile, while loading or loaded
  const ready = [];                 // loaded tiles
  let loading = 0;
  const queue = [];                 // worker results waiting to become meshes, a few milliseconds a frame
  const pendingDetail = new Set();

  // Each tile's ground is a grid on the height nodes, laid out round the tile's centre (positions and normals from the
  // worker: mpls-geo.js groundGrid); the uvs and the triangles are the same for every tile.
  let tileGrid = null;
  function tileGroundGeo(A) {
    const w = Math.round(Math.sqrt(A.position.length / 3)), n = w - 1;
    if (!tileGrid || tileGrid.n !== n) {
      const uvs = new Float32Array(w * w * 2), idx = new Uint32Array(n * n * 6);
      for (let j = 0; j <= n; j++) for (let i = 0; i <= n; i++) { uvs[(j * w + i) * 2] = i / n; uvs[(j * w + i) * 2 + 1] = j / n; }
      let k = 0;
      for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
        const a = j * w + i, b = a + 1, c = a + w, d = c + 1;
        idx.set([a, c, b, b, c, d], k);
        k += 6;
      }
      tileGrid = { n, uv: new THREE.BufferAttribute(uvs, 2), index: new THREE.BufferAttribute(idx, 1) };
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(A.position, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(A.normal, 3));
    g.setAttribute('uv', tileGrid.uv);
    g.setIndex(tileGrid.index);
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, A.mid, 0), MAP.tile * 0.75 + A.span);
    return g;
  }

  const bufferGeo = (A) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(A.position, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(A.normal, 3));
    if (A.uv) g.setAttribute('uv', new THREE.BufferAttribute(A.uv, 2));
    if (A.la) g.setAttribute('la', new THREE.BufferAttribute(A.la, 2, true));
    if (A.color) g.setAttribute('color', A.color instanceof Uint8Array ? new THREE.BufferAttribute(A.color, 4, true) : new THREE.BufferAttribute(A.color, 3));
    if (A.paint) g.setAttribute('paint', new THREE.BufferAttribute(A.paint, 3));
    if (A.side) g.setAttribute('side', new THREE.BufferAttribute(A.side, 2));
    g.computeBoundingSphere();
    return g;
  };
  const meshOf = (A, mat, cast) => {
    if (!A) return null;
    const m = new THREE.Mesh(bufferGeo(A), mat);
    m.castShadow = cast && !lowPower;
    m.receiveShadow = true;
    m.matrixAutoUpdate = false;
    m.updateMatrix();
    return m;
  };

  function tileDistance(i, j, x, z) {
    const tx = MAP.x0 + i * MAP.tile, tz = MAP.z0 + j * MAP.tile;
    return Math.hypot(Math.max(tx - x, 0, x - tx - MAP.tile), Math.max(tz - z, 0, z - tz - MAP.tile));
  }
  function tileAt(x, z) {
    const i = Math.floor((x - MAP.x0) / MAP.tile), j = Math.floor((z - MAP.z0) / MAP.tile);
    if (i < 0 || j < 0 || i >= MAP.ni || j >= MAP.nj) return null;
    const t = tiles.get(i + '_' + j);
    return t && t.ready ? t : null;
  }
  function loadTile(i, j) {
    const key = i + '_' + j;
    const t = { key, i, j, x0: MAP.x0 + i * MAP.tile, z0: MAP.z0 + j * MAP.tile, ready: false, dropped: false, failed: 0, objects: [], pieces: [] };
    tiles.set(key, t);
    loading++;
    worker.postMessage({ type: 'tile', key, x0: t.x0, z0: t.z0, tile: MAP.tile, small: lowPower });
  }
  function finishTile(msg) {
    const t = tiles.get(msg.key);
    if (!t || t.dropped) { msg.image?.close?.(); return; }
    const tex = new THREE.Texture(msg.image);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = MAX_ANISO;
    tex.flipY = false;
    tex.needsUpdate = true;
    t.tex = tex;
    t.image = msg.image;
    const mat = groundMaterial(mapBounds, true);
    mat.userData.mapNode.value = tex;
    const g = new THREE.Mesh(tileGroundGeo(msg.ground), mat);
    g.position.set(t.x0 + MAP.tile / 2, 0, t.z0 + MAP.tile / 2);
    g.receiveShadow = true;
    g.renderOrder = -1;                              // it writes depth, so a hill hides what's over it
    g.matrixAutoUpdate = false;
    g.updateMatrix();
    g.name = 'MplsGround';
    t.ground = g;
    t.surface = msg.surface;
    t.solids = msg.solids;
    t.colliders = new Map();
    t.corners = msg.corners;
    t.streetNames = msg.streetNames;
    t.mapImage = msg.mapImage;
    if (msg.signs) {
      t.signTex = new THREE.Texture(msg.signs.image);
      t.signTex.colorSpace = THREE.SRGBColorSpace;
      t.signTex.anisotropy = MAX_ANISO;
      t.signTex.flipY = false;
      t.signTex.needsUpdate = true;
      t.signMat = new THREE.MeshStandardNodeMaterial({ map: t.signTex, roughness: 0.5 });
    }
    if (msg.water) {
      const w = meshOf(msg.water, waterMat, false);
      w.name = 'MplsWater';
      t.objects.push(w);
    }
    for (const p of msg.pieces) {
      const m = meshOf(p.city, cityMat, true);
      if (m) t.objects.push(m);
      if (p.detail) t.pieces.push({ key: p.key, cx: p.cx, cz: p.cz, tile: t, built: null, requested: false });
    }
    for (const ring of msg.stadium) {
      let sum = 0, lo = Infinity;
      for (const [x, z] of ring) { const h = groundH(x, z); sum += h; lo = Math.min(lo, h); }
      const y = sum / ring.length;
      for (const m of createStadium({ ring, base: y, foot: lo - y < -0.05 ? lo - y - 0.15 : 0, night: stadiumNight, castShadow: !lowPower })) t.objects.push(m);
    }
    root.add(g, ...t.objects);
    if (msg.parked?.length) parked.add(t.key, msg.parked);
    t.ready = true;
    ready.push(t);
  }
  function finishDetail(msg) {
    const t = tiles.get(msg.key);
    const P = t && t.ready && t.pieces.find((p) => p.key === msg.piece);
    pendingDetail.delete(msg.key + '/' + msg.piece);
    if (!P || !P.requested || P.built) return;
    const D = msg.detail;
    const out = [];
    if (D) {
      for (const [A, mat, cast] of [[D.city, cityMat, true], [D.road, roadMat, false], [D.concrete, concreteMat, false], [D.brick, brickMat, false],
        [D.walk, walkMat, false], [D.curb, curbMat, false],
        [D.trail, trailMat, false], [D.paint, paintMat, false]]) {
        const m = meshOf(A, mat, cast);
        if (m) out.push(m);
      }
      if (D.signs && t.signMat) {
        const m = meshOf(D.signs, t.signMat, false);
        if (m) out.push(m);
      }
      if (D.lamps.length) out.push(...lampMeshes(P, D.lamps));
      const sites = [];
      for (let k = 0; k < D.trees.length; k += 5) sites.push({ x: D.trees[k], y: D.trees[k + 1], z: D.trees[k + 2], h: D.trees[k + 3], r: D.trees[k + 4] });
      trees.add(P, sites);
    }
    for (const o of out) { o.updateMatrixWorld(); root.add(o); }
    P.built = out;
  }
  function dropDetail(P) {
    trees.remove(P);
    lampSites.delete(P);
    for (const m of P.built || []) {
      root.remove(m);
      if (m.isInstancedMesh) m.dispose();
      else m.geometry.dispose();
    }
    P.built = null;
    P.requested = false;
  }
  function dropTile(t) {
    t.dropped = true;
    tiles.delete(t.key);
    worker.postMessage({ type: 'drop', key: t.key });
    if (!t.ready) return;
    const k = ready.indexOf(t);
    if (k >= 0) ready.splice(k, 1);
    root.remove(t.ground);
    t.ground.geometry.dispose();
    t.ground.material.dispose();
    t.tex.dispose();
    t.image?.close?.();
    t.mapImage?.close?.();
    for (const m of t.objects) { root.remove(m); m.geometry.dispose(); }
    for (const P of t.pieces) if (P.built) dropDetail(P);
    t.signTex?.dispose();
    t.signMat?.dispose();
    parked.remove(t.key);
    t.objects = t.pieces = t.surface = t.solids = t.colliders = null;
  }

  worker.onerror = (e) => console.error('[mpls] worker failed to start', e.message || e);
  worker.onmessage = ({ data: msg }) => {
    if (msg.type === 'tile') loading--;
    if (msg.type === 'error') {
      console.warn('[mpls] worker', msg.message);
      if (msg.piece === undefined) {
        loading--;
        const t = tiles.get(msg.key);
        if (t) t.failed = performance.now();
      } else pendingDetail.delete(msg.key + '/' + msg.piece);
      return;
    }
    queue.push(msg);
  };

  /** Load what's near (x, z), nearest first, and drop what's far. */
  function stream(x, z) {
    const want = [];
    const now = performance.now();
    for (let j = 0; j < MAP.nj; j++) for (let i = 0; i < MAP.ni; i++) {
      const d = tileDistance(i, j, x, z);
      const t = tiles.get(i + '_' + j);
      if (t && t.failed && now - t.failed > 4000) tiles.delete(t.key);   // try a failed tile again
      else if (t && d > DROP_R) dropTile(t);
      else if (!t && d < LOAD_R) want.push([d, i, j]);
    }
    want.sort((a, b) => a[0] - b[0]);
    for (const [, i, j] of want) {
      if (loading >= 3) break;
      loadTile(i, j);
    }
  }
  /** Ask the worker for the nearest unbuilt pieces' detail, and drop the far ones. */
  function streamDetail(x, z) {
    const near = [];
    for (const t of ready) for (const P of t.pieces) {
      const d = Math.hypot(P.cx - x, P.cz - z) - PIECE * 0.71;
      if (P.requested && d > DETAIL_R + 300) dropDetail(P);
      else if (!P.requested && d < DETAIL_R) near.push([d, P]);
    }
    near.sort((a, b) => a[0] - b[0]);
    for (const [, P] of near) {
      if (pendingDetail.size >= 2) break;
      P.requested = true;
      pendingDetail.add(P.tile.key + '/' + P.key);
      worker.postMessage({ type: 'detail', key: P.tile.key, piece: P.key });
    }
  }
  const BUILD_MS = lowPower ? 4 : 6;
  /** Turn finished work into meshes, nearest first, a few milliseconds a frame (all of it with urgent). */
  function drain(x, z, urgent = false) {
    const t0 = performance.now();
    while (queue.length && (urgent || performance.now() - t0 < BUILD_MS)) {
      let best = 0, bd = Infinity;
      for (let k = 0; k < queue.length; k++) {
        const m = queue[k], t = tiles.get(m.key);
        const d = t ? tileDistance(t.i, t.j, x, z) : -1;
        if (d < bd) { bd = d; best = k; }
      }
      const msg = queue.splice(best, 1)[0];
      try {
        if (msg.type === 'tile') finishTile(msg);
        else finishDetail(msg);
      } catch (err) {
        // leave the tile (or the piece) out rather than stop the game
        console.error('[mpls] building', msg.key, err);
        const t = tiles.get(msg.key);
        if (msg.type === 'tile' && t) t.failed = performance.now();
      }
    }
  }

  let streamTimer = 0;
  const focus = new THREE.Vector3();
  /** Every frame, with the camera: stream tiles and detail round it, place the lamp lights, regroup the trees. */
  function update(dt, camera, player = camera.position) {
    focus.copy(player);
    streamTimer -= dt;
    if (streamTimer <= 0) {
      streamTimer = 0.25;
      stream(focus.x, focus.z);
      streamDetail(camera.position.x, camera.position.z);
    }
    drain(focus.x, focus.z, !tileAt(focus.x, focus.z));
    stepLampLights(camera);
    trees.update(camera.position);
  }
  /** Resolves once the tiles within r of (x, z) and the detail within detailR of it are built (the loading screen). */
  async function whenReady(x, z, r = 700, detailR = 450, onProgress = () => {}) {
    for (;;) {
      stream(x, z);
      streamDetail(x, z);
      drain(x, z, true);
      const near = [];
      for (let j = 0; j < MAP.nj; j++) for (let i = 0; i < MAP.ni; i++) if (tileDistance(i, j, x, z) < r) near.push(tiles.get(i + '_' + j));
      const pieces = [];
      for (const t of near) if (t?.ready) for (const P of t.pieces) if (Math.hypot(P.cx - x, P.cz - z) - PIECE * 0.71 < detailR) pieces.push(P);
      const done = near.filter((t) => t?.ready).length + pieces.filter((P) => P.built).length;
      const total = near.length + pieces.length;
      onProgress(done / Math.max(1, total));
      if (near.every((t) => t?.ready) && pieces.every((P) => P.built)) break;
      await new Promise((res) => setTimeout(res, 50));
    }
  }

  /* -------------------------------- Surface -------------------------------- */
  /** 0 grass, 1 pavement, 2 deep water (from the tile's map), 1 where the map isn't loaded. */
  function surfaceAt(x, z) {
    if (x < MAP.x0 || x >= MAP.x1 || z < MAP.z0 || z >= MAP.z1) return 0;
    const t = tileAt(x, z);
    if (!t) return 1;
    const i = Math.min(SURF_N - 1, Math.floor((x - t.x0) / MAP.tile * SURF_N));
    const j = Math.min(SURF_N - 1, Math.floor((z - t.z0) / MAP.tile * SURF_N));
    return t.surface[j * SURF_N + i];
  }

  /* -------------------------------- Colliders --------------------------------
     Slop New York's controllers push the player out of boxes ({ minX, maxX, minZ, maxZ, minY, maxY, obb }). Every
     solid here is a capsule in plan view, so a wall segment becomes a thin box along it and a trunk or a post a
     square round it; each is made the first time the player comes near it and kept with its tile.                */
  const WALL_HALF = 0.35;
  function colliderOf(t, i) {
    let c = t.colliders.get(i);
    if (c) return c;
    const S = t.solids;
    const ax = S.x1[i], az = S.z1[i], bx = S.x2[i], bz = S.z2[i], r = S.r[i];
    const L = Math.hypot(bx - ax, bz - az);
    const cx = (ax + bx) / 2, cz = (az + bz) / 2;
    const hx = L / 2 + r, hz = Math.max(r, L > 0.01 ? WALL_HALF : r);
    const ux = L > 0.01 ? (bx - ax) / L : 1, uz = L > 0.01 ? (bz - az) / L : 0;
    const ex = Math.abs(ux) * hx + Math.abs(uz) * hz, ez = Math.abs(uz) * hx + Math.abs(ux) * hz;
    c = {
      minX: cx - ex, maxX: cx + ex, minZ: cz - ez, maxZ: cz + ez, minY: -1e4, maxY: S.h[i],
      obb: { cx, cz, hx, hz, cs: ux, sn: -uz }, _order: (t.i * 64 + t.j) * 4194304 + i,
    };
    t.colliders.set(i, c);
    return c;
  }
  const nearList = [];
  let stamp = 0;
  const stamps = new Map();
  /** The box colliders within r of (x, z), in a fixed order (controllers.js sorts by it). */
  function nearColliders(x, z, r) {
    nearList.length = 0;
    stamp++;
    const xa = x - r, xb = x + r, za = z - r, zb = z + r;
    for (const t of ready) {
      const S = t.solids;
      if (!S || !S.n || xb < S.minX || xa > S.maxX || zb < S.minZ || za > S.maxZ) continue;
      let seen = stamps.get(t);
      if (!seen || seen.length !== S.n) stamps.set(t, (seen = new Uint32Array(S.n)));
      const gx0 = clamp(Math.floor((xa - S.minX) / SOLID_CELL), 0, S.gw - 1), gx1 = clamp(Math.floor((xb - S.minX) / SOLID_CELL), 0, S.gw - 1);
      const gz0 = clamp(Math.floor((za - S.minZ) / SOLID_CELL), 0, S.gh - 1), gz1 = clamp(Math.floor((zb - S.minZ) / SOLID_CELL), 0, S.gh - 1);
      for (let gz = gz0; gz <= gz1; gz++) for (let gx = gx0; gx <= gx1; gx++) {
        const c = gz * S.gw + gx;
        for (let k = S.start[c]; k < S.start[c + 1]; k++) {
          const i = S.items[k];
          if (seen[i] === stamp) continue;
          seen[i] = stamp;
          nearList.push(colliderOf(t, i));
        }
      }
    }
    if (nearList.length > 1) nearList.sort((a, b) => a._order - b._order);
    return nearList;
  }

  /** Whole buildings within r of (x, z) as boxes, for the sound (audio-acoustics.js), made once per tile. */
  const buildingList = [];
  function nearBuildings(x, z, r) {
    buildingList.length = 0;
    for (const t of ready) {
      const S = t.solids;
      if (!S || x + r < S.minX || x - r > S.maxX || z + r < S.minZ || z - r > S.maxZ) continue;
      if (!t.blocks) {
        const B = S.blocks;
        t.blocks = [];
        for (let k = 0; k < B.length; k += 12) {
          t.blocks.push({ minX: B[k], minZ: B[k + 1], maxX: B[k + 2], maxZ: B[k + 3], minY: B[k + 4], maxY: B[k + 5],
            obb: B[k + 8] > 0 ? { cx: B[k + 6], cz: B[k + 7], hx: B[k + 8], hz: B[k + 9], cs: B[k + 10], sn: B[k + 11] } : null });
        }
      }
      for (const c of t.blocks) if (c.maxX > x - r && c.minX < x + r && c.maxZ > z - r && c.minZ < z + r) buildingList.push(c);
    }
    return buildingList;
  }

  return {
    MAP, index, nearBuildings, bounds: { x0, x1, z0, z1 }, bridges, tiles, ready, worker,
    groundH, deckAt, surfaceY, surfaceAt, nearColliders, tileAt, update, whenReady,
    setLampLightCount(n) { lampLightCount = clamp(n, 0, LAMP_LIGHTS); },
    trees, cityXZ, overviewURL: new URL('overview.jpg', new URL(base, location.href)).href,
  };
}
