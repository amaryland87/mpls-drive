// Lofted cars from Slop New York (https://github.com/mrdoob/slop-newyork, MIT, © 2026 Mr.doob: see LICENSE here).
// Sections 1-2 (loft geometry, body specs, bodies, glasshouses, wheels, mirrors, rails, taxi sign) are NYC's own,
// unchanged but for the imports. Section 3 is a WebGL / GLSL port of its TSL car material, which paints the glass,
// seals, lamps, grilles, plates, shut lines and alloys from object-space position and normal in one draw.
import * as THREE from 'three';
import { mergeGeometries, mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';

//   crowned roofs, LatheGeometry tyres & recessed 5-spoke alloy wheels, side mirrors, roof signs & TSL fascia/seams)

const _vector = new THREE.Vector3();
const _down = new THREE.Vector3(0, -1, 0);

// ============================================================================
// 1. LOFT GEOMETRY (Ported from three/addons/geometries/LoftGeometry.js)
// ============================================================================
class LoftGeometry extends THREE.BufferGeometry {
  constructor(sections = [], options = {}) {
    super();
    this.type = 'LoftGeometry';

    const { closed = true, capStart = false, capEnd = false } = options;
    const rows = sections.length;
    if (rows < 2) return;
    const columns = sections[0].length;
    for (let i = 1; i < rows; i++) {
      if (sections[i].length !== columns) return;
    }

    const pointsPerRow = closed ? columns + 1 : columns;
    const indices = [];
    const vertices = [];
    const uvs = [];

    const rowU = [0];
    for (let i = 1; i < rows; i++) {
      let distance = 0;
      for (let j = 0; j < columns; j++) {
        distance += sections[i][j].distanceTo(sections[i - 1][j]);
      }
      rowU.push(rowU[i - 1] + distance / columns);
    }
    const totalU = rowU[rows - 1];

    for (let i = 0; i < rows; i++) {
      const section = sections[i];
      const colV = [0];
      for (let j = 1; j < pointsPerRow; j++) {
        colV.push(colV[j - 1] + section[j % columns].distanceTo(section[(j - 1) % columns]));
      }
      const totalV = colV[pointsPerRow - 1];

      for (let j = 0; j < pointsPerRow; j++) {
        const point = section[j % columns];
        vertices.push(point.x, point.y, point.z);
        uvs.push(
          totalU > 0 ? rowU[i] / totalU : i / (rows - 1),
          totalV > 0 ? colV[j] / totalV : j / (pointsPerRow - 1)
        );
      }
    }

    for (let i = 0; i < rows - 1; i++) {
      for (let j = 0; j < pointsPerRow - 1; j++) {
        const a = i * pointsPerRow + j;
        const b = i * pointsPerRow + j + 1;
        const c = (i + 1) * pointsPerRow + j + 1;
        const d = (i + 1) * pointsPerRow + j;
        indices.push(a, b, d);
        indices.push(b, c, d);
      }
    }

    function generateCap(sectionIndex) {
      const section = sections[sectionIndex];
      const centroid = new THREE.Vector3();
      const normal = new THREE.Vector3();

      for (let i = 0; i < columns; i++) {
        const p = section[i];
        const q = section[(i + 1) % columns];
        centroid.add(p);
        normal.x += (p.y - q.y) * (p.z + q.z);
        normal.y += (p.z - q.z) * (p.x + q.x);
        normal.z += (p.x - q.x) * (p.y + q.y);
      }
      centroid.divideScalar(columns);
      normal.normalize();

      const neighbor = sections[sectionIndex === 0 ? 1 : rows - 2];
      _vector.set(0, 0, 0);
      for (let i = 0; i < columns; i++) _vector.add(neighbor[i]);
      _vector.divideScalar(columns).sub(centroid);
      if (normal.dot(_vector) > 0) normal.negate();

      const tangent = new THREE.Vector3(1, 0, 0);
      if (Math.abs(normal.x) > 0.9) tangent.set(0, 1, 0);
      const bitangent = new THREE.Vector3().crossVectors(normal, tangent).normalize();
      tangent.crossVectors(bitangent, normal);

      const contour = [];
      const points = section.slice();
      for (let i = 0; i < columns; i++) {
        _vector.subVectors(points[i], centroid);
        contour.push(new THREE.Vector2(_vector.dot(tangent), _vector.dot(bitangent)));
      }

      if (THREE.ShapeUtils.isClockWise(contour) === true) {
        contour.reverse();
        points.reverse();
      }

      const faces = THREE.ShapeUtils.triangulateShape(contour, []);
      const minV = new THREE.Vector2(Infinity, Infinity);
      const maxV = new THREE.Vector2(-Infinity, -Infinity);
      for (let i = 0; i < columns; i++) {
        minV.min(contour[i]);
        maxV.max(contour[i]);
      }
      const width = Math.max(maxV.x - minV.x, Number.EPSILON);
      const height = Math.max(maxV.y - minV.y, Number.EPSILON);

      const indexOffset = vertices.length / 3;
      for (let i = 0; i < columns; i++) {
        const point = points[i];
        vertices.push(point.x, point.y, point.z);
        uvs.push((contour[i].x - minV.x) / width, (contour[i].y - minV.y) / height);
      }
      for (let i = 0; i < faces.length; i++) {
        const face = faces[i];
        indices.push(indexOffset + face[0], indexOffset + face[1], indexOffset + face[2]);
      }
    }

    if (capStart === true) generateCap(0);
    if (capEnd === true) generateCap(rows - 1);

    this.setIndex(indices);
    this.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    this.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
    this.computeVertexNormals();

    if (closed === true) {
      const normals = this.getAttribute('normal');
      for (let i = 0; i < rows; i++) {
        const a = i * pointsPerRow;
        const b = i * pointsPerRow + (pointsPerRow - 1);
        _vector.set(
          normals.getX(a) + normals.getX(b),
          normals.getY(a) + normals.getY(b),
          normals.getZ(a) + normals.getZ(b)
        ).normalize();
        normals.setXYZ(a, _vector.x, _vector.y, _vector.z);
        normals.setXYZ(b, _vector.x, _vector.y, _vector.z);
      }
    }
  }
}

function part(geometry, id) {
  const g = geometry.index ? geometry : mergeVertices(geometry);
  if (!g.attributes.uv) {
    g.setAttribute('uv', new THREE.Float32BufferAttribute(new Float32Array(g.attributes.position.count * 2), 2));
  }
  g.setAttribute('partId', new THREE.BufferAttribute(new Float32Array(g.attributes.position.count).fill(id), 1));
  return g;
}

// ============================================================================
// 2. LOFTED VEHICLE GEOMETRY & TSL MATERIAL
// ============================================================================
// Car bodies are lofted from ~45 cross-sections generated along the car out of a few smooth side- & plan-view curves
// (monotone cubic splines) plus elliptical roundings into the nose and tail: rounded plan-view corners, a hood that
// rolls down into the fascia, a tucked-in sill, crowned hood & deck, fender flares and circular wheel arches. A second,
// open loft sits on the belt line as the glasshouse (raked windshield & backlight, tumblehome side glass, crowned roof
// with rounded rails). All the detail (glass, seals, pillars, lamps, grilles, plates, door seams, NYPD & taxi liveries,
// brake lights & turn signals) is painted by one TSL material from object-space position & normal, so each body type
// stays a single instanced draw call.
const CAR_PARTS = {
  BODY: 0,
  WINDOW: 1,
  TYRE: 2,
  ALLOY: 3,
  TRIM: 4,
  MIRROR: 5,
  SIGN: 6,
  FRONT: 7,
  REAR: 8
};

// Design tables. Curves are [z, value] control points (z = +front); nose / tail entries are [length, tip value,
// superellipse exponent] roundings of the same quantities into the tips.
const BODY_SPECS = {
  sedan: {
    name: 'sedan',
    zFront: 2.25,
    zRear: -2.25,
    wheelRadius: 0.35,
    wheelZ: 1.38,
    wheelX: 0.83,
    archGap: 0.065, // wheel arch radius = wheelRadius + archGap
    archFlare: 0.02, // extra half-width over the wheels
    tuck: 0.075, // sill tucked in from the widest point
    halfWidth: [[2.25, 0.91], [1.38, 0.922], [0, 0.928], [-1.38, 0.926], [-2.25, 0.915]],
    sill: [[2.25, 0.29], [1.2, 0.265], [-1.2, 0.265], [-2.25, 0.3]],
    shoulder: [[2.25, 0.66], [0, 0.7], [-2.25, 0.76]],
    edge: [[2.1, 0.79], [1.5, 0.85], [0.85, 0.935], [0.55, 0.955], [-1.0, 0.985], [-1.62, 1.015], [-2.1, 1.03]],
    crown: [[2.1, 0.035], [0.95, 0.03], [0.66, 0.004], [-1.56, 0.004], [-1.78, 0.022], [-2.25, 0.026]],
    tumble: [[2.25, 0.11], [0.9, 0.09], [-1.6, 0.085], [-2.25, 0.105]],
    nose: { halfWidth: [0.36, 0.6, 2], edge: [0.22, 0.6, 2.4], crown: [0.22, 0.01, 2], sill: [0.13, 0.4, 2], shoulder: [0.3, 0.52, 2] },
    tail: { halfWidth: [0.3, 0.66, 2], edge: [0.11, 0.88, 2.4], crown: [0.11, 0, 2], sill: [0.14, 0.44, 2], shoulder: [0.2, 0.68, 2] },
    cabin: {
      cowl: 0.86,
      roofFront: 0.0,
      roofRear: -1.0,
      deck: -1.68,
      roofY: [[0.0, 1.435], [-0.5, 1.455], [-1.0, 1.42]],
      rail: [0.645, 0.625], // roof rail half-width at the front & rear of the roof
      inset: 0.035, // side glass base inset from the body's top edge
      bulge: 0.012, // side glass outward curvature
      roofEdge: 0.05, // roof rail rounding height
      roofCrown: 0.035,
      roofRound: 4,
      pillars: [-0.3] // B (and C) pillar centres
    },
    doors: [0.84, -0.3, -1.02], // door shut lines
    handles: [-0.13, -0.86],
    headlight: [0.56, 0.705, 0.2, 0.058], // centre |x|, y, half-width, half-height
    taillight: [0.585, 0.87, 0.235, 0.052],
    grille: [0.7, 0.27, 0.02], // upper slot between the headlights: y, half-width, half-height
    intake: [0.46, 0.43, 0.095], // lower grille
    plates: [0.47, 0.66], // front / rear plate centre heights
    bumperLine: [0.775, 0.595], // hood / bumper and trunk / bumper shut lines on the nose & tail
    chrome: true, // chrome strip along the side windows' sills
    cladding: 0, // height of the unpainted lower body cladding (SUVs)
    sign: false,
    rails: false
  },
  suv: {
    name: 'suv',
    zFront: 2.3,
    zRear: -2.3,
    wheelRadius: 0.39,
    wheelZ: 1.4,
    wheelX: 0.87,
    archGap: 0.075,
    archFlare: 0.03,
    tuck: 0.07,
    halfWidth: [[2.3, 0.948], [1.4, 0.96], [0, 0.966], [-1.4, 0.964], [-2.3, 0.956]],
    sill: [[2.3, 0.39], [1.2, 0.35], [-1.2, 0.35], [-2.3, 0.41]],
    shoulder: [[2.3, 0.8], [0, 0.84], [-2.3, 0.88]],
    edge: [[2.1, 0.99], [1.5, 1.045], [0.85, 1.1], [0.6, 1.12], [-1.0, 1.145], [-2.0, 1.175], [-2.3, 1.18]],
    crown: [[2.1, 0.035], [0.9, 0.03], [0.6, 0.004], [-2.3, 0.004]],
    tumble: [[2.3, 0.1], [0.9, 0.08], [-2.3, 0.08]],
    nose: { halfWidth: [0.3, 0.7, 2], edge: [0.2, 0.84, 2.6], crown: [0.2, 0.01, 2], sill: [0.12, 0.5, 2], shoulder: [0.24, 0.66, 2] },
    tail: { halfWidth: [0.24, 0.76, 2], edge: [0.08, 1.1, 2.6], crown: [0.08, 0, 2], sill: [0.14, 0.52, 2], shoulder: [0.18, 0.84, 2] },
    cabin: {
      cowl: 0.8,
      roofFront: 0.08,
      roofRear: -1.96,
      deck: -2.2,
      roofY: [[0.08, 1.735], [-0.9, 1.76], [-1.96, 1.745]],
      rail: [0.71, 0.7],
      inset: 0.035,
      bulge: 0.012,
      roofEdge: 0.055,
      roofCrown: 0.03,
      roofRound: 4,
      pillars: [-0.3, -1.18]
    },
    doors: [0.78, -0.3, -1.18],
    handles: [-0.13, -1.0],
    headlight: [0.6, 0.9, 0.2, 0.055],
    taillight: [0.66, 1.0, 0.2, 0.07],
    grille: [0.83, 0.36, 0.1],
    intake: [0.52, 0.44, 0.06],
    plates: [0.6, 0.76],
    bumperLine: [0.965, 0.84],
    chrome: false,
    cladding: 0.5,
    sign: false,
    rails: true
  }
};
BODY_SPECS.taxi = Object.assign({}, BODY_SPECS.sedan, { name: 'taxi', sign: true });
for (const spec of Object.values(BODY_SPECS)) {
  // Kept for code that places lamp flares: lamp heights (front, rear) and centres across the car
  spec.lamps = [spec.headlight[1], spec.taillight[1]];
  spec.lampX = [spec.headlight[0], spec.taillight[0]];
}

const lerp = (a, b, t) => a + (b - a) * t;

// Monotone cubic (Fritsch-Carlson) interpolation through [x, y] control points: smooth, never overshoots
function smoothCurve(points) {
  const pts = points.slice().sort((a, b) => a[0] - b[0]);
  const n = pts.length;
  if (n === 1) return () => pts[0][1];
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const h = [];
  const d = [];
  for (let i = 0; i < n - 1; i++) {
    h.push(xs[i + 1] - xs[i]);
    d.push((ys[i + 1] - ys[i]) / h[i]);
  }
  const m = [d[0]];
  for (let i = 1; i < n - 1; i++) {
    if (d[i - 1] * d[i] <= 0) {
      m.push(0);
    } else {
      const w1 = 2 * h[i] + h[i - 1];
      const w2 = h[i] + 2 * h[i - 1];
      m.push((w1 + w2) / (w1 / d[i - 1] + w2 / d[i]));
    }
  }
  m.push(d[n - 2]);
  return (x) => {
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    let i = 0;
    while (x > xs[i + 1]) i++;
    const t = (x - xs[i]) / h[i];
    const t2 = t * t;
    const t3 = t2 * t;
    return (2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i] + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1];
  };
}

// 1 along the body, falling to 0 at the tip along a superelliptic quarter (vertical tangent at the tip)
function endFactor(z, zTip, length, exponent = 2) {
  const u = zTip > 0 ? (z - (zTip - length)) / length : (zTip + length - z) / length;
  if (u <= 0) return 1;
  if (u >= 1) return 0;
  return Math.pow(1 - Math.pow(u, exponent), 1 / exponent);
}

/**
 * Evaluates a body spec's curves into the cross-section parameters along the vehicle (memoized on the spec):
 *   body(z) -> { W: half-width, yB: sill, yS: shoulder (widest), yE / xE: top edge, yT: crown, xB: sill half-width }
 */
function bodyProfile(spec) {
  if (spec._body) return spec._body;
  const W0 = smoothCurve(spec.halfWidth);
  const B0 = smoothCurve(spec.sill);
  const S0 = smoothCurve(spec.shoulder);
  const E0 = smoothCurve(spec.edge);
  const C0 = smoothCurve(spec.crown);
  const T0 = smoothCurve(spec.tumble);
  const archR = spec.wheelRadius + spec.archGap;
  const axles = [spec.wheelZ, -spec.wheelZ];

  const rounded = (z, value, key) => {
    const nose = spec.nose[key];
    const tail = spec.tail[key];
    if (nose && z > 0) value = nose[1] + (value - nose[1]) * endFactor(z, spec.zFront, nose[0], nose[2]);
    if (tail && z < 0) value = tail[1] + (value - tail[1]) * endFactor(z, spec.zRear, tail[0], tail[2]);
    return value;
  };

  const body = (z) => {
    let flare = 0;
    for (const axle of axles) {
      const d = (z - axle) / (archR + 0.4);
      if (Math.abs(d) < 1) flare = Math.max(flare, (1 - d * d) ** 2);
    }
    const W = rounded(z, W0(z) + spec.archFlare * flare, 'halfWidth');
    let yB = rounded(z, B0(z), 'sill');
    for (const axle of axles) {
      const d = Math.abs(z - axle);
      if (d < archR) yB = Math.max(yB, spec.wheelRadius + Math.sqrt(archR * archR - d * d));
    }
    const yE = rounded(z, E0(z), 'edge');
    const yT = yE + Math.max(0, rounded(z, C0(z), 'crown'));
    const yS = Math.min(Math.max(rounded(z, S0(z), 'shoulder'), yB + 0.035), yE - 0.035);
    const xE = Math.max(W - T0(z), W * 0.55);
    return { z, W, yB, yS, yE, yT, xE, xB: W - spec.tuck };
  };
  spec._body = body;
  return body;
}

/**
 * A car's body profile plus its glasshouse (memoized on the spec):
 *   cabin(z) -> { beltX, beltY: side glass base, railX, railY: top of the side glass, h: roof / glass crown height }
 */
function carLayout(spec) {
  if (spec._layout) return spec._layout;
  const body = bodyProfile(spec);
  const archR = spec.wheelRadius + spec.archGap;
  const cab = spec.cabin;
  const roofY = smoothCurve(cab.roofY);
  const H = cab.roofEdge + cab.roofCrown;
  const belt = (z) => {
    const s = body(z);
    return { x: s.xE - cab.inset, y: s.yE - 0.004 };
  };
  const bc = belt(cab.cowl);
  const bd = belt(cab.deck);
  const railF = { x: cab.rail[0], y: roofY(cab.roofFront) - H };
  const railR = { x: cab.rail[1], y: roofY(cab.roofRear) - H };
  const roofMid = (cab.roofFront + cab.roofRear) / 2;
  const railM = { x: (cab.rail[0] + cab.rail[1]) / 2, y: roofY(roofMid) - H };
  // At the cowl & deck the glass arch stays under the hood / trunk crown, so the glass grows out of the panel
  const hCowl = Math.max(0.006, body(cab.cowl).yT - bc.y - 0.008);
  const hDeck = Math.max(0.006, body(cab.deck).yT - bd.y - 0.008);

  const cabin = (z) => {
    const b = belt(z);
    let railX;
    let railY;
    let h;
    if (z >= cab.roofFront) {
      const t = (cab.cowl - z) / (cab.cowl - cab.roofFront);
      railX = lerp(bc.x, railF.x, t);
      railY = lerp(bc.y, railF.y, t);
      h = lerp(hCowl, H, Math.min(1, t * 1.6));
    } else if (z <= cab.roofRear) {
      const t = (z - cab.deck) / (cab.roofRear - cab.deck);
      railX = lerp(bd.x, railR.x, t);
      railY = lerp(bd.y, railR.y, t);
      h = lerp(hDeck, H, Math.min(1, t * 1.6));
    } else {
      const t = (cab.roofFront - z) / (cab.roofFront - cab.roofRear);
      railX = lerp(railF.x, railR.x, t);
      railY = roofY(z) - H;
      h = H;
    }
    return { z, beltX: Math.max(b.x, railX), beltY: Math.min(b.y, railY), railX, railY, h, bulge: cab.bulge };
  };

  // Height of the glasshouse's top surface (roof / windshield crown) at |x| for a cabin section
  const cabinTop = (c, x) => {
    const n = cab.roofRound;
    const ratio = Math.min(1, Math.abs(x) / Math.max(c.railX, 1e-4));
    const th = Math.acos(Math.pow(ratio, n / 2));
    return c.railY + c.h * Math.pow(Math.sin(th), 2 / n);
  };

  spec._layout = { spec, body, cabin, cabinTop, archR, belt: { cowl: bc, deck: bd }, rail: { front: railF, mid: railM, rear: railR, roofMid } };
  return spec._layout;
}

// Section winding used by every car loft in this file: left (-x) bottom, up & over the top, right (+x) bottom
function mirrorSection(right, center, z) {
  const pts = [];
  for (const [x, y] of right) pts.push(new THREE.Vector3(-x, y, z));
  if (center) pts.push(new THREE.Vector3(center[0], center[1], z));
  for (let i = right.length - 1; i >= 0; i--) pts.push(new THREE.Vector3(right[i][0], right[i][1], z));
  return pts;
}

const BODY_LOWER_ROUND = 2.8;
const BODY_UPPER_ROUND = 3.2;

// Right half of a body cross-section: superelliptic lower corner (sill -> widest point), superelliptic upper corner
// (widest point -> top edge) and a parabolic crown. Specs may sharpen the corners (lowerRound / upperRound) and sample
// the upper corner more densely (upperSamples).
function bodyHalfProfile(s, detail, spec = {}) {
  const n1 = spec.lowerRound || BODY_LOWER_ROUND;
  const n2 = spec.upperRound || BODY_UPPER_ROUND;
  const right = [];
  const low = detail ? [0, 0.32, 0.64, 1] : [0, 1];
  const up = detail ? spec.upperSamples || [0.38, 0.72, 1] : [1];
  const top = detail ? [0.66, 0.33] : [0.5];
  for (const a of low) {
    const th = (a * Math.PI) / 2;
    right.push([s.xB + (s.W - s.xB) * Math.pow(Math.sin(th), 2 / n1), s.yS - (s.yS - s.yB) * Math.pow(Math.cos(th), 2 / n1)]);
  }
  for (const a of up) {
    const th = (a * Math.PI) / 2;
    right.push([s.xE + (s.W - s.xE) * Math.pow(Math.cos(th), 2 / n2), s.yS + (s.yE - s.yS) * Math.pow(Math.sin(th), 2 / n2)]);
  }
  for (const f of top) right.push([s.xE * f, s.yE + (s.yT - s.yE) * (1 - f * f)]);
  return right;
}

function bodyStations(spec, detail) {
  const zs = [];
  const add = (z) => zs.push(Math.min(spec.zFront, Math.max(spec.zRear, z)));
  const step = detail ? spec.stationStep || 0.28 : 0.75;
  for (let z = spec.zRear; z < spec.zFront; z += step) add(z);
  add(spec.zFront);
  const noseLen = Math.max(...Object.values(spec.nose).map((v) => v[0]));
  const tailLen = Math.max(...Object.values(spec.tail).map((v) => v[0]));
  for (const u of detail ? [0, 0.3, 0.52, 0.7, 0.83, 0.92, 0.97, 0.993] : [0, 0.6, 0.92]) {
    add(spec.zFront - noseLen * (1 - u));
    add(spec.zRear + tailLen * (1 - u));
  }
  const archR = spec.wheelRadius + spec.archGap;
  const k = detail ? 8 : 4;
  for (const axle of [spec.wheelZ, -spec.wheelZ]) {
    for (let i = 0; i <= k; i++) add(axle + archR * Math.cos((i / k) * Math.PI));
    add(axle + archR + 0.006);
    add(axle - archR - 0.006);
  }
  if (detail && spec.cabin) {
    add(spec.cabin.cowl);
    add(spec.cabin.deck);
  }
  zs.sort((a, b) => b - a);
  const eps = detail ? 0.004 : 0.04;
  const out = [];
  for (const z of zs) {
    if (!out.length || out[out.length - 1] - z > eps) out.push(z);
  }
  out[0] = spec.zFront;
  out[out.length - 1] = spec.zRear;
  return out;
}

function buildBodyLoft(spec, detail = 1) {
  const body = bodyProfile(spec);
  const sections = bodyStations(spec, detail).map((z) => {
    const s = body(z);
    return mirrorSection(bodyHalfProfile(s, detail, spec), [0, s.yT], z);
  });
  return new LoftGeometry(sections, { capStart: true, capEnd: true });
}

function buildCarBody(spec, detail = 1) {
  return part(buildBodyLoft(spec, detail), CAR_PARTS.BODY);
}

function cabinSection(c, detail, roundness) {
  const right = [[c.beltX, c.beltY]];
  if (detail) {
    for (const s of [1 / 3, 2 / 3]) {
      right.push([lerp(c.beltX, c.railX, s) + c.bulge * 4 * s * (1 - s), lerp(c.beltY, c.railY, s)]);
    }
  }
  right.push([c.railX, c.railY]);
  for (const f of detail ? [0.2, 0.42, 0.68] : [0.5]) {
    const th = (f * Math.PI) / 2;
    right.push([c.railX * Math.pow(Math.cos(th), 2 / roundness), c.railY + c.h * Math.pow(Math.sin(th), 2 / roundness)]);
  }
  return mirrorSection(right, [0, c.railY + c.h], c.z);
}

function cabinStations(spec, detail) {
  const cab = spec.cabin;
  const zs = [];
  for (const t of detail ? [0, 0.1, 0.24, 0.42, 0.62, 0.82] : [0, 0.5]) zs.push(lerp(cab.cowl, cab.roofFront, t));
  for (const t of detail ? [0, 0.25, 0.5, 0.75] : [0, 0.5]) zs.push(lerp(cab.roofFront, cab.roofRear, t));
  for (const t of detail ? [1, 0.8, 0.6, 0.4, 0.22, 0.1, 0] : [1, 0.5, 0]) zs.push(lerp(cab.deck, cab.roofRear, t));
  return zs;
}

function buildCarCabin(spec, detail = 1) {
  const L = carLayout(spec);
  const sections = cabinStations(spec, detail).map((z) => cabinSection(L.cabin(z), detail, spec.cabin.roofRound));
  return part(new LoftGeometry(sections, { closed: false }), CAR_PARTS.WINDOW);
}

/**
 * Half-width of a body's outer skin at height y of the cross-section at z (for decals & signs that hug the sides)
 */
function carBodyHalfWidthAt(spec, z, y) {
  const s = bodyProfile(spec)(z);
  const n1 = spec.lowerRound || BODY_LOWER_ROUND;
  const n2 = spec.upperRound || BODY_UPPER_ROUND;
  const pts = [];
  for (let i = 0; i <= 16; i++) {
    const th = ((i / 16) * Math.PI) / 2;
    pts.push([s.xB + (s.W - s.xB) * Math.pow(Math.sin(th), 2 / n1), s.yS - (s.yS - s.yB) * Math.pow(Math.cos(th), 2 / n1)]);
  }
  for (let i = 1; i <= 16; i++) {
    const th = ((i / 16) * Math.PI) / 2;
    pts.push([s.xE + (s.W - s.xE) * Math.pow(Math.cos(th), 2 / n2), s.yS + (s.yE - s.yS) * Math.pow(Math.sin(th), 2 / n2)]);
  }
  if (y <= pts[0][1]) return pts[0][0];
  for (let i = 1; i < pts.length; i++) {
    if (y <= pts[i][1]) {
      const t = (y - pts[i - 1][1]) / Math.max(pts[i][1] - pts[i - 1][1], 1e-6);
      return lerp(pts[i - 1][0], pts[i][0], t);
    }
  }
  return s.xE;
}

/**
 * A thin grid patch lying `offset` m off the body side (side = +1: +x) over z0..z1, y0..y1. UVs read from the
 * front of the car to the back on both sides (u = 0 at the front on the +x side, at the back on the -x side).
 */
function buildCarSidePatch(spec, side, z0, z1, y0, y1, offset = 0.003, nz = 10, ny = 6) {
  const positions = [];
  const uvs = [];
  const indices = [];
  for (let j = 0; j <= ny; j++) {
    const v = j / ny;
    const y = lerp(y0, y1, v);
    for (let i = 0; i <= nz; i++) {
      const u = i / nz;
      const z = side > 0 ? lerp(z1, z0, u) : lerp(z0, z1, u);
      positions.push(side * (carBodyHalfWidthAt(spec, z, y) + offset), y, z);
      uvs.push(u, v);
      if (i < nz && j < ny) {
        const a = j * (nz + 1) + i;
        const b = a + 1;
        const c = a + nz + 1;
        const d = c + 1;
        if (side > 0) indices.push(a, b, c, b, d, c);
        else indices.push(a, c, b, b, c, d);
      }
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  g.setIndex(indices);
  g.computeVertexNormals();
  return g;
}

function roundedRectShape(hw, hh, r) {
  const s = new THREE.Shape();
  s.moveTo(-hw + r, -hh);
  s.lineTo(hw - r, -hh);
  s.quadraticCurveTo(hw, -hh, hw, -hh + r);
  s.lineTo(hw, hh - r);
  s.quadraticCurveTo(hw, hh, hw - r, hh);
  s.lineTo(-hw + r, hh);
  s.quadraticCurveTo(-hw, hh, -hw, hh - r);
  s.lineTo(-hw, -hh + r);
  s.quadraticCurveTo(-hw, -hh, -hw + r, -hh);
  return s;
}

// Rounded box extruded along z, centred on the origin
function roundedBox(hw, hh, depth, r, bevel = 0.012) {
  const g = new THREE.ExtrudeGeometry(roundedRectShape(hw - bevel, hh - bevel, Math.max(0.002, r - bevel)), {
    depth: Math.max(0.001, depth - 2 * bevel),
    bevelEnabled: true,
    bevelThickness: bevel,
    bevelSize: bevel,
    bevelSegments: 1,
    curveSegments: 2
  });
  return g.translate(0, 0, -(depth - 2 * bevel) / 2);
}

/**
 * Builds a single wheel assembly (LatheGeometry tyre + recessed alloy lip + dished hub)
 * centered at the origin (for steerable/spinning player wheels) or translated to (x, r, z).
 */
function buildWheelParts(spec, side, translateToAxle = false, z = 0) {
  const r = spec.wheelRadius;
  const rim = r * 0.64;
  const width = r * 0.68;
  const wheelProfile = [
    new THREE.Vector2(rim + 0.014, -width * 0.44),
    new THREE.Vector2(r * 0.96, -width * 0.33),
    new THREE.Vector2(r, -width * 0.05),
    new THREE.Vector2(r, width * 0.05),
    new THREE.Vector2(r * 0.96, width * 0.33),
    new THREE.Vector2(rim + 0.014, width * 0.44)
  ];

  const x = translateToAxle ? side * spec.wheelX : 0;
  const y = translateToAxle ? r : 0;
  const zOff = translateToAxle ? z : 0;

  const tyre = new THREE.LatheGeometry(wheelProfile, 20)
    .rotateZ(-side * Math.PI * 0.5)
    .translate(x, y, zOff);
  const lip = new THREE.LatheGeometry(
    [new THREE.Vector2(rim + 0.014, width * 0.44), new THREE.Vector2(rim, width * 0.29)],
    20
  )
    .rotateZ(-side * Math.PI * 0.5)
    .translate(x, y, zOff);
  const backLip = new THREE.LatheGeometry(
    [new THREE.Vector2(rim, -width * 0.29), new THREE.Vector2(rim + 0.014, -width * 0.44)],
    20
  )
    .rotateZ(-side * Math.PI * 0.5)
    .translate(x, y, zOff);
  const hub = new THREE.CircleGeometry(rim, 20);
  hub.attributes.position.setZ(0, -0.015);
  hub.computeVertexNormals();
  hub.rotateY(side * Math.PI * 0.5).translate(x + side * width * 0.29, y, zOff);

  const backHub = new THREE.CircleGeometry(rim, 20);
  backHub.attributes.position.setZ(0, -0.015);
  backHub.computeVertexNormals();
  backHub.rotateY(-side * Math.PI * 0.5).translate(x - side * width * 0.29, y, zOff);

  const list = [
    part(tyre, CAR_PARTS.TYRE),
    part(lip, CAR_PARTS.ALLOY),
    part(backLip, CAR_PARTS.ALLOY),
    part(hub, CAR_PARTS.ALLOY),
    part(backHub, CAR_PARTS.ALLOY)
  ];

  if (translateToAxle) list.push(buildWheelWell(spec, side, z));
  return list;
}

// Dark arch liner behind a wheel, so the arch never shows through to the other side of the car
function buildWheelWell(spec, side, z) {
  const r = spec.wheelRadius;
  const width = r * 0.68;
  const wellOuter = new THREE.CircleGeometry(spec.wheelRadius + spec.archGap + 0.01, 10, 0, Math.PI)
    .rotateY(side * Math.PI * 0.5)
    .translate(side * (spec.wheelX - (width * 0.5 + 0.02)), r, z);
  const wellInner = new THREE.CircleGeometry(spec.wheelRadius + spec.archGap + 0.01, 10, 0, Math.PI)
    .rotateY(-side * Math.PI * 0.5)
    .translate(side * (spec.wheelX - (width * 0.5 + 0.02)), r, z);
  return part(mergeGeometries([wellOuter, wellInner]), CAR_PARTS.TRIM);
}

function buildSteerableWheelGeo(spec, side) {
  return mergeGeometries(buildWheelParts(spec, side, false));
}

function buildMirrors(spec) {
  const L = carLayout(spec);
  const z = spec.cabin.cowl - 0.17;
  const c = L.cabin(z);
  const list = [];
  for (const side of [-1, 1]) {
    const housing = roundedBox(0.1, 0.06, 0.085, 0.035, 0.014)
      .rotateY(side * 0.12)
      .translate(side * (c.beltX + 0.15), c.beltY + 0.085, z - 0.02);
    const arm = new THREE.BoxGeometry(0.12, 0.035, 0.06)
      .rotateZ(side * 0.35)
      .translate(side * (c.beltX + 0.04), c.beltY + 0.045, z);
    list.push(part(housing, CAR_PARTS.MIRROR), part(arm, CAR_PARTS.TRIM));
  }
  return list;
}

function buildRoofRails(spec) {
  const L = carLayout(spec);
  const cab = spec.cabin;
  const list = [];
  for (const side of [-1, 1]) {
    const sections = [0.04, 0.1, 0.9, 0.96].map((t, i) => {
      const z = lerp(cab.roofFront, cab.roofRear, t);
      const c = L.cabin(z);
      const x = side * c.railX * 0.8;
      const y = L.cabinTop(c, x) + (i === 0 || i === 3 ? 0.004 : 0.05);
      return [
        new THREE.Vector3(x - 0.02, y - 0.016, z),
        new THREE.Vector3(x + 0.02, y - 0.016, z),
        new THREE.Vector3(x + 0.02, y + 0.016, z),
        new THREE.Vector3(x - 0.02, y + 0.016, z)
      ].reverse();
    });
    list.push(part(new LoftGeometry(sections, { capStart: true, capEnd: true }), CAR_PARTS.TRIM));
  }
  return list;
}

// NYC medallion roof light: a lit, gently tapered box on a black mount
function taxiSignPlacement(spec) {
  const L = carLayout(spec);
  const cab = spec.cabin;
  const z = lerp(cab.roofFront, cab.roofRear, 0.45);
  const c = L.cabin(z);
  return { z, y: c.railY + c.h };
}

function buildTaxiSign(spec) {
  const { z, y } = taxiSignPlacement(spec);
  const shape = new THREE.Shape();
  const hw0 = 0.3;
  const hw1 = 0.27;
  const h = 0.15;
  const r = 0.035;
  shape.moveTo(-hw0, 0);
  shape.lineTo(hw0, 0);
  shape.lineTo(hw1, h - r);
  shape.quadraticCurveTo(hw1 - 0.004, h, hw1 - r, h);
  shape.lineTo(-hw1 + r, h);
  shape.quadraticCurveTo(-hw1 + 0.004, h, -hw1, h - r);
  shape.lineTo(-hw0, 0);
  const sign = new THREE.ExtrudeGeometry(shape, {
    depth: 0.12,
    bevelEnabled: true,
    bevelThickness: 0.025,
    bevelSize: 0.012,
    bevelSegments: 2,
    curveSegments: 3
  }).translate(0, y + 0.03, z - 0.06);
  const mount = new THREE.BoxGeometry(0.46, 0.04, 0.12).translate(0, y + 0.012, z);
  return [part(sign, CAR_PARTS.SIGN), part(mount, CAR_PARTS.TRIM)];
}

function buildCarGeometry(spec, includeWheels = true) {
  const parts = [buildCarBody(spec, 1), buildCarCabin(spec, 1), ...buildMirrors(spec)];
  for (const side of [-1, 1]) {
    for (const z of [-spec.wheelZ, spec.wheelZ]) {
      if (includeWheels) parts.push(...buildWheelParts(spec, side, true, z));
      else parts.push(buildWheelWell(spec, side, z));
    }
  }
  if (spec.rails) parts.push(...buildRoofRails(spec));
  if (spec.sign) parts.push(...buildTaxiSign(spec));
  return mergeGeometries(parts);
}

// A ~250-triangle stand-in for distant cars (a few pixels tall): the same body & glasshouse lofted from a handful of
// coarse sections, dark wheel blocks and the taxi's roof sign. Same attributes (partId, uv, normal) as the full
// model, so it renders with the same material and per-instance paint.
function buildCarProxyGeometry(spec) {
  const parts = [buildCarBody(spec, 0), buildCarCabin(spec, 0)];
  const r = spec.wheelRadius;
  for (const side of [-1, 1]) {
    for (const z of [-spec.wheelZ, spec.wheelZ]) {
      parts.push(part(new THREE.BoxGeometry(r * 0.6, r * 1.7, r * 1.7).translate(side * spec.wheelX, r * 0.88, z), CAR_PARTS.TYRE));
    }
  }
  if (spec.sign) {
    const { z, y } = taxiSignPlacement(spec);
    parts.push(part(new THREE.BoxGeometry(0.58, 0.16, 0.16).translate(0, y + 0.1, z), CAR_PARTS.SIGN));
  }
  return mergeGeometries(parts);
}

// NYPD roof light bar (red on the -x half, blue on the +x half) for a body spec's roof, lit by createLightbarMaterial
function buildLightbarGeometry(spec = BODY_SPECS.sedan) {
  const L = carLayout(spec);
  const cab = spec.cabin;
  const z = lerp(cab.roofFront, cab.roofRear, 0.32);
  const c = L.cabin(z);
  const y = c.railY + c.h;
  const bar = roundedBox(0.13, 0.045, 1.12, 0.04, 0.02).rotateY(Math.PI / 2).translate(0, y + 0.075, z);
  const parts = [part(bar, CAR_PARTS.SIGN)];
  for (const side of [-1, 1]) {
    parts.push(part(new THREE.BoxGeometry(0.06, 0.05, 0.16).translate(side * 0.42, y + 0.02, z), CAR_PARTS.TRIM));
  }
  return mergeGeometries(parts);
}

let _lightbarMat = null;

// Light bar lenses: red & blue halves flashing in alternation (double strobes), each car on its own phase
function polygonPlanes(points, margins) {
  const planes = [];
  for (let i = 0; i < points.length; i++) {
    const [ax, ay] = points[i];
    const [bx, by] = points[(i + 1) % points.length];
    const len = Math.hypot(bx - ax, by - ay);
    const nx = (by - ay) / len;
    const ny = -(bx - ax) / len;
    planes.push([nx, ny, ax * nx + ay * ny - margins[i]]);
  }
  return planes;
}

// ============================================================================
// 3. CAR MATERIAL (GLSL port of NYC's createLoftedCarMaterial)
// ============================================================================
const f = (v) => { const s = (+v).toFixed(5); return s.includes('.') ? s : s + '.0'; };
const hex = (h) => { const c = new THREE.Color(h); return `vec3(${f(c.r)}, ${f(c.g)}, ${f(c.b)})`; };
// Signed distance to a convex polygon of outward half-planes, corners rounded by a smooth max (as GLSL source).
function polyDist(px, py, planes, k) {
  let d = null;
  for (const [nx, ny, c] of planes) {
    const e = `(${px} * ${f(nx)} + ${py} * ${f(ny)} - ${f(c)})`;
    d = d === null ? e : `smax(${d}, ${e}, ${f(k)})`;
  }
  return d;
}

const CAR_GLSL_HELPERS = `
float carCover(float d) { float w = max(fwidth(d), 0.0008); return smoothstep(w, -w, d); }
float rrect(vec2 p, vec2 hs, float r) {
  vec2 q = abs(p) - hs + r;
  float d = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - r;
  float e = max(fwidth(d), 0.001);
  return smoothstep(e, -e, d);
}
float smax(float a, float b, float k) { float h = max(k - abs(a - b), 0.0) / k; return max(a, b) + h * h * k * 0.25; }
float isPart(float id, float want) { return step(abs(id - want), 0.25); }`;

/**
 * spec: a BODY_SPECS entry. opts.instanced: paint and state come from the per-instance attributes `paintColor` (vec3)
 * and `carState` (vec4: brake, left turn, right turn, unused); otherwise from material.userData.paint (Color) and
 * .carState (Vector4). opts.night: a { value } uniform, 0 by day to 1 at night, that switches the headlamps on.
 */
function createCarMaterial(spec, opts = {}) {
  const L = carLayout(spec);
  const cab = spec.cabin;
  const P = CAR_PARTS;
  const bc = L.belt.cowl, bd = L.belt.deck, rf = L.rail.front, rm = L.rail.mid, rr = L.rail.rear;
  const sidePoly = [[cab.cowl, bc.y], [cab.roofFront, rf.y], [L.rail.roofMid, rm.y], [cab.roofRear, rr.y], [cab.deck, bd.y]];
  const frontPoly = [[-1, cab.cowl], [-1, cab.roofFront], [rf.x, cab.roofFront], [bc.x, cab.cowl]];
  const rearPoly = [[-1, cab.roofRear], [-1, cab.deck], [bd.x, cab.deck], [rr.x, cab.roofRear]];
  const [hlX, hlY, hlW, hlH] = spec.headlight;
  const [tlX, tlY, tlW, tlH] = spec.taillight;
  const [grY, grW, grH] = spec.grille;
  const [inY, inW, inH] = spec.intake;
  const [plateF, plateR] = spec.plates;
  const frontZone = spec.zFront - 0.55, rearZone = spec.zRear + 0.55;
  const sillY = spec.sill[1][1], rearSill = spec.tail.sill[1];
  const signY = taxiSignPlacement(spec).y + 0.105;
  const doorMid = (spec.doors[0] + spec.doors[1]) / 2;
  const pillars = cab.pillars.map((zp) => `sideG = max(sideG, 0.036 - abs(p.z - ${f(zp)}));`).join('\n');
  const doors = spec.doors.map((zd) => `seams = max(seams, smoothstep(0.009, 0.003, abs(p.z - ${f(zd)})));`).join('\n');
  const handles = spec.handles.map((zh) => `seams = max(seams, rrect(vec2(p.z - ${f(zh)}, p.y - (belt - 0.095)), vec2(0.06, 0.011), 0.008));`).join('\n');
  let spokes = '';
  for (let k = 0; k < 5; k++) {
    const a = (k * Math.PI * 2) / 5, cs = Math.cos(a), sn = Math.sin(a);
    spokes += `spokes = max(spokes, smoothstep(0.034, 0.018, abs(wDir.x * ${f(sn)} - wDir.y * ${f(cs)}) * wheelDist) * step(0.0, wDir.x * ${f(cs)} + wDir.y * ${f(sn)}));\n`;
  }

  const frag = `
    vec3 p = vCarP, n = normalize(vCarN);
    float partId = vCarPart;
    float isBody = isPart(partId, ${f(P.BODY)}), isWindow = isPart(partId, ${f(P.WINDOW)}), isTyre = isPart(partId, ${f(P.TYRE)});
    float isAlloy = isPart(partId, ${f(P.ALLOY)}), isTrim = isPart(partId, ${f(P.TRIM)}), isMirror = isPart(partId, ${f(P.MIRROR)}), isSign = isPart(partId, ${f(P.SIGN)});
    float ax = abs(p.x);
    float isSide = smoothstep(0.45, 0.7, abs(n.x));
    float front = smoothstep(0.12, 0.38, n.z) * step(${f(frontZone)}, p.z) * isBody;
    float rear = smoothstep(0.12, 0.38, -n.z) * step(p.z, ${f(rearZone)}) * isBody;
    float under = smoothstep(-0.25, -0.55, n.y) * isBody;
    float belt = mix(${f(bd.y)}, ${f(bc.y)}, clamp((p.z - ${f(cab.deck)}) / ${f(cab.cowl - cab.deck)}, 0.0, 1.0));

    // Glasshouse: side windows minus the pillars, windshield and backlight, their seals, the chrome sill strip.
    float sideG = ${polyDist('p.z', 'p.y', polygonPlanes(sidePoly, [0.05, 0.03, 0.03, 0.065, 0.02]), 0.07)};
    ${pillars}
    float backlight = carCover(${polyDist('ax', 'p.z', polygonPlanes(rearPoly, [0, 0.045, 0.065, 0.05]), 0.09)}) * isWindow;
    float glass = max(max(carCover(sideG), carCover(${polyDist('ax', 'p.z', polygonPlanes(frontPoly, [0, 0.045, 0.06, 0.05]), 0.09)})), backlight / max(isWindow, 1e-4)) * isWindow;
    float seal = max(carCover(${polyDist('p.z', 'p.y', polygonPlanes(sidePoly, [0.034, 0.016, 0.016, 0.05, 0.004]), 0.07)}),
      max(carCover(${polyDist('ax', 'p.z', polygonPlanes(frontPoly, [0, 0.03, 0.045, 0.035]), 0.09)}), carCover(${polyDist('ax', 'p.z', polygonPlanes(rearPoly, [0, 0.03, 0.05, 0.035]), 0.09)}))) * isWindow;
    float chromeBelt = ${spec.chrome ? `smoothstep(0.003, 0.006, p.y - belt) * smoothstep(0.016, 0.012, p.y - belt) * smoothstep(0.5, 0.7, abs(n.x)) * step(${f(cab.deck + 0.05)}, p.z) * step(p.z, ${f(cab.cowl - 0.08)}) * isWindow` : '0.0'};
    float chmsl = rrect(vec2(p.x, p.z - ${f(cab.roofRear - 0.075)}), vec2(0.14, 0.012), 0.005) * backlight * step(n.z, -0.1);

    // Wheel arches: distance from the nearest axle in side view, or from the hub of a centred, spinning wheel.
    float wheelR = ${f(spec.wheelRadius)};
    float isCenteredWheel = step(abs(p.z), wheelR + 0.05) * max(isTyre, isAlloy);
    vec2 wheelVec = mix(vec2(abs(p.z) - ${f(spec.wheelZ)}, p.y - wheelR), vec2(p.z, p.y), isCenteredWheel);
    float wheelDist = length(wheelVec);

    // Lamps, grilles and plates on the nose and tail.
    vec2 hlUV = vec2(ax - ${f(hlX)}, p.y - ${f(hlY)} - (ax - ${f(hlX)}) * 0.1);
    float headlight = rrect(hlUV, vec2(${f(hlW)}, ${f(hlH)}), ${f(hlH * 0.8)}) * smoothstep(0.02, 0.25, n.z) * step(${f(frontZone)}, p.z) * isBody;
    float headlightLens = rrect(vec2(ax - ${f(hlX - hlW * 0.3)}, hlUV.y - ${f(hlH * 0.12)}), vec2(${f(hlW * 0.42)}, ${f(hlH * 0.4)}), ${f(hlH * 0.38)}) * headlight;
    float drlDist = abs(hlUV.y + ${f(hlH * 0.6)});
    float drl = smoothstep(max(fwidth(drlDist), 0.012), 0.0, drlDist) * headlight;
    float turnFront = smoothstep(${f(hlX + hlW * 0.42)}, ${f(hlX + hlW * 0.52)}, ax) * headlight;
    float grille = rrect(vec2(p.x, p.y - ${f(grY)}), vec2(${f(grW)}, ${f(grH)}), ${f(grH * 0.9)}) * front;
    float intake = rrect(vec2(p.x, p.y - ${f(inY)}), vec2(${f(inW)}, ${f(inH)}), 0.04) * front;
    float plateFront = rrect(vec2(p.x, p.y - ${f(plateF)}), vec2(0.155, 0.055), 0.008) * front;
    float taillight = rrect(vec2(ax - ${f(tlX)}, p.y - ${f(tlY)}), vec2(${f(tlW)}, ${f(tlH)}), ${f(tlH * 0.6)}) * smoothstep(0.02, 0.25, -n.z) * step(p.z, ${f(rearZone)}) * isBody;
    float turnRear = smoothstep(${f(tlX + tlW * 0.35)}, ${f(tlX + tlW * 0.45)}, ax) * taillight;
    float plateRear = rrect(vec2(p.x, p.y - ${f(plateR)}), vec2(0.155, 0.06), 0.008) * rear;
    float plateRecess = rrect(vec2(p.x, p.y - ${f(plateR)}), vec2(0.185, 0.082), 0.02) * rear;
    float diffuser = rrect(vec2(p.x, p.y - ${f(rearSill + 0.035)}), vec2(0.58, 0.028), 0.02) * rear;
    float reflector = rrect(vec2(ax - ${f(tlX + 0.06)}, p.y - ${f(rearSill + 0.1)}), vec2(0.065, 0.011), 0.006) * rear;
    float bumperSeam = max(smoothstep(0.006, 0.0025, abs(p.y - ${f(spec.bumperLine[0])})) * step(ax, ${f(hlX - hlW * 0.6)}) * front,
      smoothstep(0.006, 0.0025, abs(p.y - ${f(spec.bumperLine[1])})) * step(ax, ${f(tlX)}) * rear);
    float cowlPanel = smoothstep(${f(cab.cowl + 0.085)}, ${f(cab.cowl + 0.07)}, p.z) * smoothstep(${f(cab.cowl - 0.04)}, ${f(cab.cowl - 0.02)}, p.z) * step(0.6, n.y) * isBody;
    float signFace = smoothstep(0.55, 0.75, abs(n.z)) * isSign;
    float signGlyph = step(0.42, sin(p.x * 90.0)) * step(ax, 0.17) * smoothstep(0.045, 0.04, abs(p.y - ${f(signY)}));
    float mirrorGlass = isMirror * step(0.55, -n.z);
    float lamp = max(headlight, taillight);
    float plates = max(plateFront, plateRear);
    float cladding = ${spec.cladding > 0 ? `max(smoothstep(${f(spec.cladding + 0.01)}, ${f(spec.cladding - 0.01)}, p.y), smoothstep(${f(L.archR + 0.075)}, ${f(L.archR + 0.06)}, wheelDist)) * isBody * (1.0 - lamp) * (1.0 - plates)` : '0.0'};

    // Five-spoke alloys with rim ring and hub, lug ribs on the tread.
    vec2 wDir = wheelVec / max(wheelDist, 0.0001);
    float spokes = 0.0;
    ${spokes}
    float rimRing = smoothstep(wheelR * 0.56, wheelR * 0.6, wheelDist);
    float centerHub = smoothstep(0.068, 0.042, wheelDist);
    float centerCap = smoothstep(0.03, 0.018, wheelDist);
    float valveDot = smoothstep(0.028, 0.014, length(wheelVec - vec2(0.0, wheelR * -0.48)));
    float alloyMetal = clamp(max(max(spokes, valveDot), max(rimRing, centerHub)) - centerCap * 0.85, 0.0, 1.0);
    float matte = max(max(max(isTyre, isTrim), max(intake, grille)), max(max(diffuser, under), max(max(cowlPanel, cladding), seal * (1.0 - max(glass, chromeBelt)))));

    // Colour.
    vec3 painted = vCarPaint;
    ${spec.sign ? `
    float badge = rrect(vec2(p.z - ${f(doorMid)}, p.y - 0.66), vec2(0.21, 0.052), 0.012) * isSide * isBody;
    float emblem = smoothstep(0.042, 0.036, length(vec2(abs(p.z - ${f(doorMid)}) - 0.15, p.y - 0.66)));
    float letters = step(0.35, sin(p.z * 95.0)) * step(abs(p.z - ${f(doorMid)}), 0.1) * smoothstep(0.03, 0.026, abs(p.y - 0.66));
    painted = mix(mix(painted, ${hex(0x121417)}, badge), ${hex(0xffbe14)}, max(emblem, letters) * badge);` : ''}
    float archLip = smoothstep(${f(L.archR + 0.05)}, ${f(L.archR - 0.005)}, wheelDist) * smoothstep(0.6, 0.9, ax);
    float carAO = (smoothstep(0.2, 0.62, p.y) * 0.22 + 0.78) * (1.0 - archLip * 0.55);
    float onDoors = isSide * smoothstep(${f(sillY + 0.04)}, ${f(sillY + 0.07)}, p.y) * smoothstep(0.0, -0.015, p.y - belt);
    float seams = 0.0;
    ${doors}
    ${handles}
    vec3 body = mix(painted * carAO, ${hex(0x1e2124)}, cladding);
    body *= (1.0 - seams * onDoors * 0.55) * (1.0 - bumperSeam * 0.5);
    body = mix(body, ${hex(0x15181b)}, cowlPanel);
    float slats = step(0.5, fract(p.y * 42.0)) * 0.4 + 0.6;
    body = mix(body, ${hex(0x111417)} * slats, max(intake, grille));
    body = mix(body, mix(mix(${hex(0x23292f)}, ${hex(0xdfe9f2)}, headlightLens), vec3(1.0), drl), headlight);
    body = mix(body, ${hex(0x15181b)}, diffuser);
    body = mix(body, ${hex(0x7a0a10)}, reflector);
    body = mix(body, mix(${hex(0x8c0a12)}, ${hex(0xc24d10)}, turnRear), taillight);
    body = mix(body, body * 0.55, plateRecess);
    body = mix(body, ${hex(0xe8ecef)}, plates);
    body = mix(body, ${hex(0x0e1013)}, under);
    vec3 glassCol = mix(${hex(0x0a1016)}, ${hex(0x1a2632)}, smoothstep(0.2, 0.9, n.y));
    vec3 windowCol = mix(mix(mix(mix(vCarPaint, ${hex(0x111315)}, seal), glassCol, glass), ${hex(0xc9ced3)}, chromeBelt), ${hex(0x6a0a0e)}, chmsl);
    vec3 mirrorCol = mix(vCarPaint, ${hex(0x7c8a94)}, mirrorGlass);
    vec3 signCol = mix(${hex(0xf3efe2)}, mix(${hex(0xfff1b8)}, ${hex(0x15181b)}, signGlyph), signFace);
    vec3 alloyCol = mix(${hex(0x0b0e12)}, ${hex(0xd8e0e8)}, alloyMetal);
    float treadZone = smoothstep(wheelR * 0.74, wheelR * 0.83, wheelDist);
    float tyreBase = smoothstep(wheelR * 0.85, wheelR * 0.94, wheelDist) * 0.22 + 0.78;
    vec3 tyreCol = ${hex(0x16181b)} * (tyreBase + spokes * treadZone * 0.24);
    vec3 col = mix(body, windowCol, isWindow);
    col = mix(col, mirrorCol, isMirror);
    col = mix(col, signCol, isSign);
    col = mix(col, ${hex(0x1b1e21)}, isTrim);
    col = mix(col, alloyCol, isAlloy);
    col = mix(col, tyreCol, isTyre);
    diffuseColor.rgb = col;

    // Roughness and metalness.
    float alloySpokes = max(spokes, rimRing) * isAlloy;
    float glossy = max(max(max(glass, chromeBelt), mirrorGlass), lamp);
    float carRough = mix(0.26, 0.15, glossy);
    carRough = mix(carRough, 0.4, plates);
    carRough = mix(carRough, 0.35, isSign);
    carRough = mix(carRough, 0.82, max(matte, isAlloy - alloySpokes));
    float carMetal = mix(0.34, 0.14, glass);
    carMetal = mix(carMetal, 0.6, max(lamp, mirrorGlass));
    carMetal = mix(carMetal, 0.95, chromeBelt);
    carMetal = mix(carMetal, 0.86, alloySpokes);
    carMetal = mix(carMetal, 0.08, plates);
    carMetal = mix(carMetal, 0.04, max(matte, isSign));

    // Emissive: headlamps after dark, tail and brake lights, CHMSL, turn signals, the taxi's roof light.
    float brake = vCarState.x;
    float blink = max(vCarState.y * step(0.0, p.x), vCarState.z * step(p.x, 0.0));
    float nightLamp = smoothstep(0.3, 0.7, carNight);
    vec3 carEmit = ${hex(0xd9efff)} * (headlight * 1.15 + headlightLens * 1.15 + drl * 0.65) * (nightLamp * 0.9 + 0.1) * (1.0 - turnFront * blink) * 2.0;
    carEmit += ${hex(0xff0a12)} * taillight * (1.0 - turnRear) * (brake * 1.65 + 0.35 + nightLamp * 0.6);
    carEmit += ${hex(0xff0a12)} * chmsl * brake * 2.1;
    carEmit += ${hex(0xff9a14)} * max(turnFront, turnRear) * blink * 2.2;
    carEmit += ${hex(0xffe28a)} * signFace * (1.0 - signGlyph * 0.9) * 1.65;`;

  const mat = new THREE.MeshStandardMaterial({ roughness: 0.3, metalness: 0.3 });
  const inst = !!opts.instanced;
  mat.userData.paint = new THREE.Color(0xd23a2e);
  mat.userData.carState = new THREE.Vector4(0, 0, 0, 0);
  const night = opts.night || { value: 0 };
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.carNight = night;
    if (!inst) {
      sh.uniforms.carPaint = { value: mat.userData.paint };
      sh.uniforms.carStateU = { value: mat.userData.carState };
    }
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', `#include <common>
        attribute float partId;
        ${inst ? 'attribute vec3 paintColor;\nattribute vec4 carState;' : 'uniform vec3 carPaint;\nuniform vec4 carStateU;'}
        varying vec3 vCarP; varying vec3 vCarN; varying float vCarPart; varying vec3 vCarPaint; varying vec4 vCarState;`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vCarP = position; vCarN = normal; vCarPart = partId;
        ${inst ? 'vCarPaint = paintColor; vCarState = carState;' : 'vCarPaint = carPaint; vCarState = carStateU;'}`);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>
        uniform float carNight;
        varying vec3 vCarP; varying vec3 vCarN; varying float vCarPart; varying vec3 vCarPaint; varying vec4 vCarState;
        ${CAR_GLSL_HELPERS}`)
      .replace('#include <map_fragment>', frag)
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = carRough;')
      .replace('#include <metalnessmap_fragment>', 'float metalnessFactor = carMetal;')
      .replace('#include <emissivemap_fragment>', 'totalEmissiveRadiance += carEmit;');
  };
  mat.customProgramCacheKey = () => `nyc-car-${spec.name}-${inst ? 'i' : 'u'}`;
  return mat;
}

export { CAR_PARTS, BODY_SPECS, carLayout, buildCarGeometry, buildCarProxyGeometry, buildSteerableWheelGeo, createCarMaterial };
