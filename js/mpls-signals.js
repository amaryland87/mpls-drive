// Traffic signals at Minneapolis's signalled corners (mpls-traffic.js: where two main streets cross): on each approach a
// dark mast pole on the right-hand corner, an arm out over the lanes and a three-lamp head facing the traffic, lit by
// the same cycle the traffic obeys (city-config.js signalPhase). Their walk signals chirp for Slop New York's sound
// (audio-sources.js reads streetDetails.audioSignals).
import * as THREE from 'three/webgpu';
import { signalPhase } from './city-config.js';
import { ground } from './ground.js';

const POLE_H = 6.4, ARM_Y = 6.1;
const LAMP_ON = {
  red: new THREE.Color(0xff2a1a).multiplyScalar(4),
  amber: new THREE.Color(0xffa318).multiplyScalar(4),
  green: new THREE.Color(0x2bff8a).multiplyScalar(3.5)
};
const LAMP_OFF = new THREE.Color(0x1a1c1e);
const ORDER = ['red', 'amber', 'green'];

export function createSignals(scene, network) {
  // One head per approach: on the right-hand corner at the stop line, its arm reaching out over the middle of the lanes
  const heads = [];
  for (const n of network.nodes) {
    if (!n.signal) continue;
    for (const e of n.in) {
      const ex = e.sx + e.dx * e.len, ez = e.sz + e.dz * e.len;
      const px = ex + e.rx * (e.half + 1.0), pz = ez + e.rz * (e.half + 1.0);
      const mid = (e.lanes[0] + e.lanes[e.lanes.length - 1]) / 2;
      heads.push({
        px, pz, py: ground.at(px, pz, Infinity), yaw: Math.atan2(e.dx, e.dz),
        reach: Math.max(1.5, e.half + 1.0 - mid), avenue: e.axisIndex === 0
      });
    }
  }
  const count = Math.max(1, heads.length);
  const group = new THREE.Group();
  group.name = 'MplsSignals';
  const metal = new THREE.MeshStandardNodeMaterial({ color: 0x2c3034, roughness: 0.5, metalness: 0.7 });
  // In each head's frame +z is the way its traffic drives and the corner it stands on is -x (the road network's right
  // is (-dz, dx)): the arm reaches out to +x, over the lanes, and the lamps face -z, the drivers coming up to it
  const poles = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.11, 0.14, POLE_H, 10).translate(0, POLE_H / 2, 0), metal, count);
  const arms = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 0.12, 0.12).translate(0.5, ARM_Y, 0), metal, count);
  const boxes = new THREE.InstancedMesh(new THREE.BoxGeometry(0.38, 1.05, 0.28).translate(0, -0.55, 0), metal, count);
  const lamps = new THREE.InstancedMesh(new THREE.CircleGeometry(0.11, 12).rotateY(Math.PI), new THREE.MeshBasicNodeMaterial(), count * 3);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
  const v = new THREE.Vector3(), one = new THREE.Vector3(1, 1, 1), stretch = new THREE.Vector3();
  heads.forEach((h, i) => {
    q.setFromAxisAngle(up, h.yaw);
    poles.setMatrixAt(i, m.compose(v.set(h.px, h.py, h.pz), q, one));
    arms.setMatrixAt(i, m.compose(v, q, stretch.set(h.reach, 1, 1)));
    const ox = Math.cos(h.yaw) * h.reach, oz = -Math.sin(h.yaw) * h.reach;      // the arm's end
    boxes.setMatrixAt(i, m.compose(v.set(h.px + ox, h.py + ARM_Y, h.pz + oz), q, one));
    const fx = -Math.sin(h.yaw) * 0.15, fz = -Math.cos(h.yaw) * 0.15;          // just in front of the head
    for (let k = 0; k < 3; k++) {
      lamps.setMatrixAt(i * 3 + k, m.compose(v.set(h.px + ox + fx, h.py + ARM_Y - 0.22 - k * 0.32, h.pz + oz + fz), q, one));
      lamps.setColorAt(i * 3 + k, LAMP_OFF);
    }
  });
  poles.count = arms.count = boxes.count = heads.length;
  lamps.count = heads.length * 3;
  for (const mesh of [poles, arms, boxes, lamps]) {
    mesh.castShadow = mesh !== lamps;
    mesh.receiveShadow = true;
    mesh.computeBoundingSphere();
    group.add(mesh);
  }
  scene.add(group);

  // The walk signals' chirps, one per corner
  const audioSignals = [];
  for (const n of network.nodes) if (n.signal) audioSignals.push({ x: n.x, y: ground.at(n.x, n.z, Infinity) + 2.5, z: n.z, isAvenue: true });

  // The lamps change only when the phases do
  let lastAve = '', lastSt = '';
  function update(elapsed) {
    const ave = signalPhase(elapsed, true), st = signalPhase(elapsed, false);
    if (ave === lastAve && st === lastSt) return;
    lastAve = ave;
    lastSt = st;
    heads.forEach((h, i) => {
      const phase = h.avenue ? ave : st;
      for (let k = 0; k < 3; k++) lamps.setColorAt(i * 3 + k, ORDER[k] === phase ? LAMP_ON[phase] : LAMP_OFF);
    });
    if (lamps.instanceColor) lamps.instanceColor.needsUpdate = true;
  }
  return { group, update, audioSignals, heads: heads.length };
}
