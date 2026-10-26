// Mpls Drive's game: find Minneapolis's places (city-config.js NYC_LANDMARKS). Each has a pin standing high over it, amber
// until you get there, green once found; finding one chimes and says so, and what you have found is remembered on this
// device. The count shows on the full map's legend.
import * as THREE from 'three/webgpu';
import { NYC_LANDMARKS } from './city-config.js';
import { ground } from './ground.js';

const STORE = 'mpls-found';
const PIN_Y = 48;
const AMBER = { pin: '#f2a541', glow: '#c46a12', beam: '#ffd08e' };
const GREEN = { pin: '#3fa35b', glow: '#1d6b33', beam: '#7fd394' };

function labelTexture(text) {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 128;
  const g = c.getContext('2d');
  g.font = '700 44px Inter, -apple-system, "Segoe UI", sans-serif';
  const w = Math.min(500, g.measureText(text).width + 56);
  g.fillStyle = 'rgba(14, 17, 22, 0.82)';
  g.beginPath();
  g.roundRect(256 - w / 2, 22, w, 84, 42);
  g.fill();
  g.fillStyle = '#ffffff';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText(text, 256, 66, 460);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** opts.audio: the CityAudioSystem, for the chime. Returns { update(playerPosition), found, total }. */
export function createPlaces(scene, { audio } = {}) {
  let found;
  try { found = new Set(JSON.parse(localStorage.getItem(STORE)) || []); } catch { found = new Set(); }
  const save = () => { try { localStorage.setItem(STORE, JSON.stringify([...found])); } catch { /* storage is optional */ } };

  const group = new THREE.Group();
  group.name = 'MplsPlaces';
  const pinGeo = new THREE.OctahedronGeometry(5, 0).scale(1, 1.5, 1);
  const beamGeo = new THREE.CylinderGeometry(0.6, 0.6, 1, 8, 1, true).translate(0, 0.5, 0);
  const pins = NYC_LANDMARKS.map((lm) => {
    const look = found.has(lm.name) ? GREEN : AMBER;
    const g = new THREE.Group();
    g.position.set(lm.x, ground.at(lm.x, lm.z, Infinity), lm.z);
    const pin = new THREE.Mesh(pinGeo, new THREE.MeshStandardNodeMaterial({ color: look.pin, emissive: look.glow, emissiveIntensity: 0.55, roughness: 0.35, metalness: 0.1 }));
    pin.position.y = PIN_Y;
    const beam = new THREE.Mesh(beamGeo, new THREE.MeshBasicNodeMaterial({ color: look.beam, transparent: true, opacity: 0.35, depthWrite: false }));
    beam.scale.y = PIN_Y - 6;
    const label = new THREE.Sprite(new THREE.SpriteNodeMaterial({ map: labelTexture(lm.name), transparent: true, depthTest: false }));
    label.scale.set(32, 8, 1);
    label.position.y = PIN_Y + 14;
    label.renderOrder = 5;
    g.add(pin, beam, label);
    group.add(g);
    return { lm, g, pin, beam, label };
  });
  scene.add(group);

  // A message at the top of the screen for a few seconds
  const toast = document.createElement('div');
  toast.className = 'panel place-toast';
  toast.setAttribute('role', 'status');
  document.body.appendChild(toast);
  let toastTimer = 0;
  function say(text) {
    toast.textContent = text;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 3200);
  }

  function chime() {
    const ctx = audio?.context, out = audio?.mix;
    if (!ctx || !out || !audio.enabled || ctx.state !== 'running') return;
    [660, 880, 1320].forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain(), t = ctx.currentTime + i * 0.09;
      o.type = 'triangle';
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.18, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
      o.connect(g).connect(out);
      o.start(t);
      o.stop(t + 0.55);
    });
  }

  const counts = document.getElementById('fullmap-counts');
  const showCount = () => { if (counts) counts.textContent = `${found.size}/${pins.length} places found`; };
  showCount();

  let spin = 0, last = performance.now();
  function update(p) {
    const now = performance.now(), dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    spin += dt * 1.2;
    for (const P of pins) {
      const d = Math.hypot(P.lm.x - p.x, P.lm.z - p.z);
      P.pin.rotation.y = spin;
      P.pin.position.y = PIN_Y + Math.sin(now * 0.0015 + P.lm.x) * 2;
      P.label.visible = d < 700;
      if (d < P.lm.r && !found.has(P.lm.name)) {
        found.add(P.lm.name);
        save();
        P.pin.material.color.set(GREEN.pin);
        P.pin.material.emissive.set(GREEN.glow);
        P.beam.material.color.set(GREEN.beam);
        chime();
        showCount();
        say(found.size === pins.length ? `${P.lm.name}: you've found every place!` : `Found ${P.lm.name} (${found.size}/${pins.length})`);
      }
    }
  }
  return { update, found, total: pins.length };
}
