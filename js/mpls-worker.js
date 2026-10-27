// Builds Minneapolis's tiles off the main thread (mpls-geo.js), so driving never waits on the city: the page asks
// for a tile, this fetches its data and map image, builds its big buildings, collision and surface map, and sends
// them back as transferable typed arrays; then, piece by piece as the camera comes near, the houses, streets, lamps
// and trees. The page (mpls-city.js) only wraps the arrays in geometries.
import { setGround, setPalette, buildTile, buildDetail, groundGrid, waterArrays, cityXZ, ROAD_KINDS } from './mpls-geo.js';

const tiles = new Map();       // key -> { raw: piece -> detail records, atlas }
let base = '';
let stadiumXZ = [0, 0];
const isStadium = (b, x, z) => b[2] >= 700 && Math.hypot(x - stadiumXZ[0], z - stadiumXZ[1]) < 150;

const buffersOf = (obj, out = []) => {
  if (!obj) return out;
  if (ArrayBuffer.isView(obj)) { out.push(obj.buffer); return out; }
  if (obj instanceof ImageBitmap) { out.push(obj); return out; }
  if (typeof obj === 'object') for (const v of Object.values(obj)) buffersOf(v, out);
  return [...new Set(out)];
};

// Street signs: green blades with the two street names. One canvas of every name in a tile, a row each.
const SIGN_ABBR = [[/\bAvenue\b/g, 'Av'], [/\bStreet\b/g, 'St'], [/\bBoulevard\b/g, 'Blvd'], [/\bParkway\b/g, 'Pkwy'],
  [/\bDrive\b/g, 'Dr'], [/\bRoad\b/g, 'Rd'], [/\bLane\b/g, 'Ln'], [/\bPlace\b/g, 'Pl'], [/\bTerrace\b/g, 'Ter'],
  [/\bCircle\b/g, 'Cir'], [/\bSoutheast\b/g, 'SE'], [/\bNortheast\b/g, 'NE'], [/\bSouthwest\b/g, 'SW'],
  [/\bNorthwest\b/g, 'NW'], [/\bSouth\b/g, 'S'], [/\bNorth\b/g, 'N'], [/\bEast\b/g, 'E'], [/\bWest\b/g, 'W']];
const signText = (name) => SIGN_ABBR.reduce((s, [re, ab]) => s.replace(re, ab), name);
const SIGN_ROW = 64;
function signAtlas(names) {
  const c = new OffscreenCanvas(1024, Math.max(1, names.length) * SIGN_ROW), g = c.getContext('2d');
  g.font = '600 46px "Overpass", "Arial Narrow", Arial, sans-serif';
  g.textBaseline = 'middle';
  const lens = names.map((name, i) => {
    const text = signText(name);
    const w = Math.min(1000, g.measureText(text).width + 48);
    g.fillStyle = '#1d6b3c';
    g.fillRect(0, i * SIGN_ROW, 1024, SIGN_ROW);
    g.strokeStyle = '#f4f4ef';
    g.lineWidth = 4;
    g.strokeRect(4, i * SIGN_ROW + 4, w - 8, SIGN_ROW - 8);
    g.fillStyle = '#f4f4ef';
    g.fillText(text, 24, i * SIGN_ROW + SIGN_ROW / 2 + 2, 950);
    return w;
  });
  return { image: c.transferToImageBitmap(), lens, rows: names.length };
}

// Each tile's map is read back once into a grid, about 2 m a cell: 0 grass, 1 pavement, 2 deep water.
const SURF_N = 512;
function readSurface(bitmap) {
  const c = new OffscreenCanvas(SURF_N, SURF_N), g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(bitmap, 0, 0, SURF_N, SURF_N);
  const d = g.getImageData(0, 0, SURF_N, SURF_N).data;
  const surface = new Uint8Array(SURF_N * SURF_N);
  for (let i = 0; i < SURF_N * SURF_N; i++) {
    const r = d[i * 4], gg = d[i * 4 + 1], b = d[i * 4 + 2];
    if (b - r > 112 && b > gg + 30) surface[i] = 2;
    else if (gg > r + 18 && gg > b + 24) surface[i] = 0;
    else surface[i] = 1;
  }
  return surface;
}

// The tile as the maps draw it (mpls-map.js), in Slop New York's graphite palette: footprints, then paths, local
// streets, main streets and freeways, MAP_PX pixels across the tile, drawn once here rather than on every redraw.
const MAP_PX = 768;
const MAPC = { land: '#151a20', buildings: '#262c35', path: '#24302a', local: '#323a45', main: '#3a434f', highway: '#b27a35' };
function mapImage(map, x0, z0, tile) {
  const c = new OffscreenCanvas(MAP_PX, MAP_PX), g = c.getContext('2d');
  const k = MAP_PX / tile;
  g.fillStyle = MAPC.land;
  g.fillRect(0, 0, MAP_PX, MAP_PX);
  g.setTransform(k, 0, 0, k, -x0 * k, -z0 * k);
  const S = map.shapes;
  g.beginPath();
  for (let i = 0; i < S.length;) {
    const n = S[i++];
    for (let e = 0; e < n; e++, i += 2) (e ? g.lineTo : g.moveTo).call(g, S[i], S[i + 1]);
    g.closePath();
  }
  g.fillStyle = MAPC.buildings;
  g.fill();
  g.lineCap = g.lineJoin = 'round';
  const R = map.roads;
  for (const [cls, col] of [['path', MAPC.path], ['local', MAPC.local], ['main', MAPC.main], ['highway', MAPC.highway]]) {
    g.strokeStyle = col;
    for (let i = 0; i < R.length;) {
      const kind = ROAD_KINDS[R[i]], w = R[i + 1], n = R[i + 2];
      i += 3;
      const which = kind === 'path' ? 'path' : /^(motorway|trunk)/.test(kind) ? 'highway' : /^(primary|secondary)/.test(kind) ? 'main' : 'local';
      if (which !== cls) { i += n * 2; continue; }
      g.beginPath();
      for (let e = 0; e < n; e++, i += 2) (e ? g.lineTo : g.moveTo).call(g, R[i], R[i + 1]);
      g.lineWidth = Math.max(kind === 'path' ? 1.5 : w, 2.4 / k);
      g.stroke();
    }
  }
  return c.transferToImageBitmap();
}

async function loadTile({ key, x0, z0, tile, small }) {
  const url = base + 't/' + key;
  const [data, blob] = await Promise.all([
    fetch(url + '.json').then((r) => { if (!r.ok) throw new Error('tile ' + key + ': ' + r.status); return r.json(); }),
    fetch(url + (small ? '-s.jpg' : '.jpg')).then((r) => { if (!r.ok) throw new Error('image ' + key + ': ' + r.status); return r.blob(); }),
  ]);
  const image = await createImageBitmap(blob);
  const surface = readSurface(image);
  const built = buildTile(x0, z0, tile, data, isStadium);
  const atlas = data.sn.length ? signAtlas(data.sn) : null;
  tiles.set(key, { raw: built.raw, atlas });
  return {
    type: 'tile', key, image, surface, ground: groundGrid(x0, z0, tile), water: waterArrays(surface, SURF_N, x0, z0, tile), pieces: built.pieces, solids: built.solids, stadium: built.stadium,
    corners: built.corners, streetNames: built.streetNames, mapImage: mapImage(built.map, x0, z0, tile),
    signs: atlas && { image: atlas.image, rows: atlas.rows },
    parked: Float32Array.from((data.hx || []).flatMap((h) => (h.pk || []).flat())),   // mpls-parked.js
  };
}

self.onmessage = async ({ data: msg }) => {
  try {
    if (msg.type === 'init') {
      base = msg.base;
      setGround(msg.ground);
      setPalette(msg.palette);
      stadiumXZ = cityXZ(44.97372, -93.25748);
      return;
    }
    if (msg.type === 'tile') {
      const out = await loadTile(msg);
      self.postMessage(out, buffersOf(out));
      return;
    }
    if (msg.type === 'detail') {
      const t = tiles.get(msg.key), T = t?.raw.get(msg.piece);
      const out = { type: 'detail', key: msg.key, piece: msg.piece, detail: T ? buildDetail(T, t.atlas) : null };
      self.postMessage(out, buffersOf(out));
      return;
    }
    if (msg.type === 'drop') tiles.delete(msg.key);
  } catch (err) {
    self.postMessage({ type: 'error', key: msg.key, piece: msg.piece, message: String(err && err.stack || err) });
  }
};
