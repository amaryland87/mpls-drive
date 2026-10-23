// On foot, by bike or by helicopter: Slop New York's player pedestrian, cyclist and sightseeing helicopter (its
// controllers.js, MIT, © 2026 Mr.doob: see nyc/LICENSE), their models and handling as NYC has them, set loose in
// Minneapolis. Mpls Drive hands in the ground (`ground(x, z, y)`) and its building collision (`resolve(pos, radius,
// y)`); the car stays Mpls Drive's own.
import * as THREE from 'three/webgpu';
import { cityUniforms, createCarPaintMaterial, createContactShadowMaterial } from './nyc/tsl-materials.js';
import {
  buildHelicopterBodyGeometry, buildHelicopterMainRotorGeometry, buildHelicopterTailRotorGeometry, createLoftedHelicopterMaterial,
} from './nyc/actor-models.js';
import { PersonCrowd, PersonRig } from './nyc/pedestrians.js';

const BICYCLE_DRIVE = {
  speed: 12.8, boostSpeed: 19, reverseSpeed: 4.5, acceleration: 9, boostAcceleration: 13.5,
  rolling: 0.05, drag: 0.002, brake: 7.5,
};

function driveSpeed(speed, throttle, boost, dt, drive) {
  const braking = speed * throttle < 0;
  const magnitude = Math.abs(speed);
  const deceleration = drive.rolling + (braking ? Math.abs(throttle) * drive.brake : 0);
  const coasting = Math.max(0, magnitude - deceleration * dt) / (1 + drive.drag * magnitude * dt);
  if (!throttle || braking) return Math.sign(speed) * coasting;
  const limit = throttle < 0 ? drive.reverseSpeed : boost ? drive.boostSpeed : drive.speed;
  const acceleration = boost ? drive.boostAcceleration : drive.acceleration;
  return Math.sign(throttle) * Math.min(Math.max(limit, coasting), coasting + Math.abs(throttle) * acceleration * dt);
}

function contactShadow(w, d) {
  const g = new THREE.PlaneGeometry(w, d);
  g.rotateX(-Math.PI * 0.5);
  const m = new THREE.Mesh(g, createContactShadowMaterial());
  m.position.y = 0.02;
  m.renderOrder = 998;
  return m;
}

function createPerson(scene) {
  const root = new THREE.Group();
  root.name = 'PlayerPerson';
  const crowd = new PersonCrowd(1, { farDistance: Infinity });
  crowd.meshes.forEach((m) => scene.add(m));
  const rig = new PersonRig({ seed: 4.2, scale: 1.0, girth: 1.02, hair: 0.18, armSwing: 1.0 });
  root.add(contactShadow(0.95, 0.95));
  scene.add(root);
  return {
    type: 'person', label: 'On foot', mesh: root, crowd, rig, position: new THREE.Vector3(), heading: 0, speed: 0,
    verticalVel: 0, chase: 0.6, look: 1.45,
  };
}

function createCyclist(scene) {
  const root = new THREE.Group();
  root.name = 'PlayerCyclist';
  const leanPivot = new THREE.Group();
  root.add(leanPivot);
  const frameMat = createCarPaintMaterial(0x0078e8);
  const tireMat = new THREE.MeshStandardNodeMaterial({ color: 0x181a1e, roughness: 0.6 });
  const chromeMat = new THREE.MeshStandardNodeMaterial({ color: 0xe0e8f0, roughness: 0.16, metalness: 0.78 });
  const shortsMat = new THREE.MeshStandardNodeMaterial({ color: 0x1c2028, roughness: 0.55 });
  const helmetMat = new THREE.MeshStandardNodeMaterial({ color: 0xf4f7fb, emissive: 0x181c22, roughness: 0.22, metalness: 0.25 });

  const wheelTorusGeo = new THREE.TorusGeometry(0.35, 0.038, 12, 24).rotateY(Math.PI * 0.5);
  const rimTorusGeo = new THREE.TorusGeometry(0.31, 0.018, 8, 24).rotateY(Math.PI * 0.5);
  const wheel = (z) => {
    const w = new THREE.Mesh(wheelTorusGeo, tireMat);
    w.add(new THREE.Mesh(rimTorusGeo, chromeMat));
    w.position.set(0, 0.38, z);
    leanPivot.add(w);
    return w;
  };
  const frontWheel = wheel(0.58), rearWheel = wheel(-0.58);
  const tailLed = new THREE.Mesh(new THREE.SphereGeometry(0.032, 8, 8), new THREE.MeshBasicNodeMaterial({ color: 0xff1e26 }));
  tailLed.position.set(0, 0.86, -0.32);
  leanPivot.add(tailLed);
  const tube = (r0, r1, len, rx, rz, pos, mat) => {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(r0, r1, len, 10), mat);
    m.rotation.set(rx, 0, rz);
    m.position.set(...pos);
    m.castShadow = true;
    leanPivot.add(m);
    return m;
  };
  tube(0.022, 0.022, 0.72, Math.PI * 0.46, 0, [0, 0.78, 0.04], frameMat);
  tube(0.026, 0.026, 0.78, Math.PI * 0.28, 0, [0, 0.58, 0.16], frameMat);
  tube(0.022, 0.022, 0.64, -0.22, 0, [0, 0.66, -0.22], frameMat);
  tube(0.02, 0.016, 0.68, -0.24, 0, [0, 0.68, 0.48], chromeMat);
  tube(0.018, 0.018, 0.48, 0, Math.PI * 0.5, [0, 0.98, 0.4], chromeMat);
  const saddle = new THREE.Mesh(new THREE.CapsuleGeometry(0.045, 0.16, 8, 10), shortsMat);
  saddle.rotation.x = Math.PI * 0.5;
  saddle.scale.set(1.15, 1.0, 0.55);
  saddle.position.set(0, 0.96, -0.28);
  leanPivot.add(saddle);

  // Pedal cranks at the bottom bracket (they turn with the pedal phase, the pedals stay level)
  const bikeFrame = { seat: new THREE.Vector3(0, 0.98, -0.28), bars: new THREE.Vector3(0, 0.98, 0.4), gripHalf: 0.22, bracket: new THREE.Vector3(0, 0.34, -0.145), crankLength: 0.17 };
  const crankPivot = new THREE.Group();
  crankPivot.position.copy(bikeFrame.bracket);
  const crankGeo = new THREE.BoxGeometry(0.016, bikeFrame.crankLength, 0.03).translate(0, -bikeFrame.crankLength / 2, 0);
  const pedalGeo = new THREE.BoxGeometry(0.09, 0.018, 0.07);
  const pedals = [];
  for (const side of [1, -1]) {
    const arm = new THREE.Group();
    arm.rotation.x = side > 0 ? 0 : Math.PI;
    const crank = new THREE.Mesh(crankGeo, chromeMat);
    crank.position.x = side * 0.065;
    const pedal = new THREE.Mesh(pedalGeo, tireMat);
    pedal.position.set(side * 0.1, -bikeFrame.crankLength, 0);
    arm.add(crank, pedal);
    crankPivot.add(arm);
    pedals.push(pedal);
  }
  leanPivot.add(crankPivot);

  // The skinned rider, hands on the grips and feet on the pedals; the helmet rides on its head
  const riderCrowd = new PersonCrowd(1, { farDistance: Infinity });
  riderCrowd.meshes.forEach((m) => scene.add(m));
  const riderRig = new PersonRig({ seed: 12.8, scale: 1.0, girth: 0.97, hair: 0.1 });
  const helmet = new THREE.Mesh(new THREE.SphereGeometry(0.125, 14, 12), helmetMat);
  helmet.scale.set(0.95, 0.68, 1.28);
  scene.add(helmet);
  root.add(contactShadow(0.85, 2.25));
  const headLight = new THREE.SpotLight(0xf2f7ff, 0, 20, 0.34, 0.76, 1.25);
  headLight.position.set(0, 1.32, 0.62);
  headLight.target.position.set(0, 0.0, 7.6);
  leanPivot.add(headLight, headLight.target);
  scene.add(root);
  return {
    type: 'cyclist', label: 'Bicycle', mesh: root, leanPivot, frontWheel, rearWheel, crankPivot, pedals, bikeFrame,
    riderCrowd, riderRig, helmet, headLight, position: new THREE.Vector3(), heading: 0, speed: 0, leanAngle: 0,
    pedalPhase: 0, chase: 0.68, look: 1.35,
  };
}

function createHelicopter(scene) {
  const root = new THREE.Group();
  root.name = 'PlayerHelicopter';
  const tiltPivot = new THREE.Group();
  root.add(tiltPivot);
  const heliLoftMat = createLoftedHelicopterMaterial();
  const blurDiscMat = new THREE.MeshBasicNodeMaterial({ color: 0xc8d8e8, transparent: true, opacity: 0.13, side: THREE.DoubleSide, depthWrite: false });
  const body = new THREE.Mesh(buildHelicopterBodyGeometry(), heliLoftMat);
  body.castShadow = body.receiveShadow = true;
  tiltPivot.add(body);
  const mainRotorPivot = new THREE.Group();
  mainRotorPivot.position.set(0, 2.66, -0.35);
  const mainRotor = new THREE.Mesh(buildHelicopterMainRotorGeometry(), heliLoftMat);
  mainRotor.castShadow = true;
  mainRotorPivot.add(mainRotor, new THREE.Mesh(new THREE.CylinderGeometry(4.85, 4.85, 0.015, 32), blurDiscMat));
  tiltPivot.add(mainRotorPivot);
  const tailRotorPivot = new THREE.Group();
  tailRotorPivot.position.set(0.18, 2.02, -5.62);
  tailRotorPivot.add(new THREE.Mesh(buildHelicopterTailRotorGeometry(), heliLoftMat));
  tiltPivot.add(tailRotorPivot);
  // Navigation lights: port red, starboard green, the red beacon on the fin
  for (const [col, pos] of [[0xff2b2b, [-1.09, 1.54, -4.35]], [0x22ff66, [1.09, 1.54, -4.35]], [0xff3b2b, [0, 2.84, -6.04]]]) {
    const nav = new THREE.Mesh(new THREE.SphereGeometry(0.04, 8, 8), new THREE.MeshBasicNodeMaterial({ color: col }));
    nav.position.set(...pos);
    tiltPivot.add(nav);
  }
  scene.add(root);
  return {
    type: 'helicopter', label: 'Helicopter', mesh: root, tiltPivot, mainRotorPivot, tailRotorPivot,
    position: new THREE.Vector3(), heading: 0, speed: 0, verticalSpeed: 0, pitchAngle: 0, rollAngle: 0, chase: 1.6, look: 1.55,
  };
}

/**
 * The three player entities, all in the scene, hidden but the active one. keys: { forward, backward, left, right, up,
 * down, boost } (0..1). update() moves the active entity; every entity is posed each frame.
 */
export function createModes(scene, { ground, resolve, lowPower = false }) {
  const entities = { person: createPerson(scene), cyclist: createCyclist(scene), helicopter: createHelicopter(scene) };
  let active = null;

  function setActive(type, x, y, z, heading) {
    active = type ? entities[type] : null;
    for (const e of Object.values(entities)) {
      const on = e === active;
      e.mesh.visible = on;
      for (const m of [...(e.crowd?.meshes || []), ...(e.riderCrowd?.meshes || [])]) m.visible = on;
      if (e.helmet) e.helmet.visible = on;
    }
    if (!active) return;
    active.position.set(x, y, z);
    active.heading = heading;
    active.speed = 0;
    if (active.type === 'helicopter') { active.verticalSpeed = 0; active.position.y = Math.max(y, ground(x, z, y) + 0.25); }
    if (active.rig) active.rig.placed = false;
    if (active.riderRig) active.riderRig.placed = false;
  }

  function updatePerson(p, keys, dt) {
    const maxWalk = keys.boost ? 8.2 : 4.4;
    let targetSpeed = 0;
    if (keys.forward) targetSpeed = maxWalk * keys.forward;
    else if (keys.backward) targetSpeed = -maxWalk * 0.65 * keys.backward;
    if (keys.left) p.heading += 2.6 * dt * keys.left;
    if (keys.right) p.heading -= 2.6 * dt * keys.right;
    p.speed += (targetSpeed - p.speed) * Math.min(1, dt * 10);
    p.position.x += Math.sin(p.heading) * p.speed * dt;
    p.position.z += Math.cos(p.heading) * p.speed * dt;
    resolve(p.position, 0.48, p.position.y + 1.0);
    const groundY = ground(p.position.x, p.position.z, p.position.y + 0.6);
    if (keys.up && p.position.y <= groundY + 0.02) p.verticalVel = 5.2;
    p.verticalVel -= 14.5 * dt;
    p.position.y += p.verticalVel * dt;
    if (p.position.y < groundY) { p.position.y = groundY; p.verticalVel = 0; }
  }

  function updateCyclist(b, keys, dt) {
    let throttle = 0;
    if (keys.forward) throttle = keys.forward;
    else if (keys.backward) throttle = -0.6 * keys.backward;
    b.speed = driveSpeed(b.speed, throttle, keys.boost, dt, BICYCLE_DRIVE);
    let turnInput = 0;
    if (keys.left) turnInput = keys.left;
    if (keys.right) turnInput = -keys.right;
    if (Math.abs(b.speed) > 0.15) b.heading += turnInput * 2.15 * (b.speed >= 0 ? 1 : -1) * dt;
    b.position.x += Math.sin(b.heading) * b.speed * dt;
    b.position.z += Math.cos(b.heading) * b.speed * dt;
    const before = b.position.clone();
    resolve(b.position, 0.65, b.position.y + 1.0);
    if (before.distanceToSquared(b.position) > 1e-6) b.speed *= 0.6;
    b.position.y = ground(b.position.x, b.position.z, b.position.y + 0.6);
    const targetLean = -turnInput * Math.min(1.0, Math.abs(b.speed) / 9.0) * 0.34;
    b.leanAngle += (targetLean - b.leanAngle) * Math.min(1, dt * 9);
    b.leanPivot.rotation.z = b.leanAngle;
    const wheelDelta = (b.speed / 0.35) * dt;
    b.frontWheel.rotation.x += wheelDelta;
    b.rearWheel.rotation.x += wheelDelta;
    if (throttle > 0 && wheelDelta > 0) b.pedalPhase += wheelDelta / 3.2;
    b.crankPivot.rotation.x = b.pedalPhase;
    for (const pedal of b.pedals) pedal.rotation.x = -b.pedalPhase;
  }

  function updateHelicopter(h, keys, dt, elapsed) {
    const maxHorizSpeed = keys.boost ? 52.0 : 32.0, maxVertSpeed = 16.0;
    const fwdInput = keys.forward ? keys.forward : keys.backward ? -keys.backward : 0;
    const yawInput = keys.left ? keys.left : keys.right ? -keys.right : 0;
    const vertInput = keys.up ? keys.up : keys.down ? -keys.down : 0;
    if (fwdInput) h.speed = Math.max(-maxHorizSpeed * 0.6, Math.min(maxHorizSpeed, h.speed + fwdInput * 24.0 * dt));
    else h.speed *= Math.max(0, 1 - dt * 1.8);
    if (vertInput) h.verticalSpeed = Math.max(-maxVertSpeed, Math.min(maxVertSpeed, h.verticalSpeed + vertInput * 22.0 * dt));
    else h.verticalSpeed *= Math.max(0, 1 - dt * 3.5);
    h.heading += yawInput * 1.45 * dt;
    h.position.x += Math.sin(h.heading) * h.speed * dt;
    h.position.z += Math.cos(h.heading) * h.speed * dt;
    h.position.y += h.verticalSpeed * dt;
    const floor = ground(h.position.x, h.position.z, h.position.y + 1) + 0.25;
    h.position.y = Math.max(floor, Math.min(floor + 400, h.position.y));
    resolve(h.position, 4.5, h.position.y);
    const targetPitch = (h.speed / maxHorizSpeed) * 0.24, targetRoll = -yawInput * 0.28;
    h.pitchAngle += (targetPitch - h.pitchAngle) * Math.min(1, dt * 5);
    h.rollAngle += (targetRoll - h.rollAngle) * Math.min(1, dt * 5);
    h.tiltPivot.rotation.x = h.pitchAngle;
    h.tiltPivot.rotation.z = h.rollAngle;
    h.tiltPivot.position.y = Math.sin(elapsed * 2.6) * 0.18;
  }

  function update(dt, keys, elapsed) {
    const heli = entities.helicopter;
    heli.mainRotorPivot.rotation.y += dt * 24.0;
    heli.tailRotorPivot.rotation.x += dt * 32.0;
    if (active === entities.person) updatePerson(active, keys, dt);
    else if (active === entities.cyclist) updateCyclist(active, keys, dt);
    else if (active === entities.helicopter) updateHelicopter(active, keys, dt, elapsed);
    if (!active) return;
    active.mesh.position.copy(active.position);
    active.mesh.rotation.y = active.heading;
    // The bike's lamp comes on after dusk, as the car's do.
    const glow = cityUniforms.uInteriorGlow.value;
    entities.cyclist.headLight.intensity = active === entities.cyclist ? 115 * Math.min(1.28, Math.max(0, (glow - 0.6) * 1.45)) : 0;
    if (active === entities.person) {
      const p = active;
      const groundAt = (owner, x, z) => ground(x, z, p.position.y + 0.6);
      const air = p.position.y - ground(p.position.x, p.position.z, p.position.y + 0.6);
      p.rig.update(dt, p.position.x, p.position.z, p.heading, groundAt, null, air > 0.02 ? air : 0);
      p.crowd.begin(); p.crowd.add(p.rig, 0); p.crowd.end();
    } else if (active === entities.cyclist) {
      const b = active;
      b.mesh.updateMatrixWorld(true);
      b.riderRig.ride(b.leanPivot, b.pedalPhase, b.bikeFrame);
      b.riderCrowd.begin(); b.riderCrowd.add(b.riderRig, 0); b.riderCrowd.end();
      b.helmet.quaternion.copy(b.riderRig.headQuaternion);
      b.helmet.position.set(0, 0.175, -0.012).applyQuaternion(b.helmet.quaternion).add(b.riderRig.headPosition);
    }
  }

  setActive(null);
  return { entities, setActive, update, get active() { return active; } };
}
