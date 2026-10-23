// Mpls Drive's city sound, built on Slop New York's synthesis (nyc/audio-synthesis.js, nyc/audio-events.js; MIT,
// © 2026 Mr.doob: see LICENSE here). The spatial emitter and the voice pool follow NYC's audio-system.js, cut down:
// no occlusion by buildings, and the sources are the player's car and the traffic Mpls Drive hands in each update.
import { createSynthResources, createMotorVoice, setControlRate } from './audio-synthesis.js';
import { createEventResources, playEvent, createWindVoice } from './audio-events.js';

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const smooth = (param, value, now, time = 0.035, immediate = false) => {
  param.cancelScheduledValues(now);
  if (immediate) param.setValueAtTime(value, now);
  else param.setTargetAtTime(value, now, time);
};

class SpatialEmitter {
  constructor(context, dry, reflections, refDistance, directional = false) {
    this.input = context.createGain();
    this.input.gain.value = 0;
    this.filter = context.createBiquadFilter();
    setControlRate(this.filter.frequency, this.filter.detune, this.filter.Q, this.filter.gain);
    this.filter.type = 'lowpass';
    this.filter.Q.value = 0.5;
    this.panner = context.createPanner();
    setControlRate(this.panner.positionX, this.panner.positionY, this.panner.positionZ,
      this.panner.orientationX, this.panner.orientationY, this.panner.orientationZ);
    this.panner.panningModel = 'HRTF';
    this.panner.distanceModel = 'inverse';
    this.panner.refDistance = refDistance;
    this.panner.rolloffFactor = 1.15;
    this.panner.maxDistance = 500;
    if (directional) {
      this.panner.coneInnerAngle = 120;
      this.panner.coneOuterAngle = 260;
      this.panner.coneOuterGain = 0.6;
    }
    this.input.connect(this.filter).connect(this.panner);
    this.panner.connect(dry);
    this.panner.connect(reflections);
  }

  update(source, listener, now, range = 160, snap = false, immediate = false) {
    const distance = Math.hypot(source.x - listener.x, source.y - listener.y, source.z - listener.z);
    for (const [param, v] of [[this.panner.positionX, source.x], [this.panner.positionY, source.y], [this.panner.positionZ, source.z]]) {
      if (snap) { param.cancelScheduledValues(now); param.setValueAtTime(v, now); } else smooth(param, v, now);
    }
    if (this.panner.coneOuterAngle < 360 && Number.isFinite(source.heading)) {
      smooth(this.panner.orientationX, Math.sin(source.heading), now);
      smooth(this.panner.orientationZ, Math.cos(source.heading), now);
    }
    const fade = clamp((range - distance) / (range * 0.3), 0, 1);
    smooth(this.input.gain, (source.gain ?? 1) * fade * fade * (3 - 2 * fade), now, 0.035, immediate);
    smooth(this.filter.frequency, 1800 + 14000 * Math.exp(-distance / 70), now, 0.12, immediate);
    return distance;
  }

  dispose() {
    this.input.disconnect();
    this.filter.disconnect();
    this.panner.disconnect();
  }
}

/** Plays into `output` (a GainNode of the given context). update() ten times a second is plenty. */
class CityAudio {
  constructor(context, output, { small = false } = {}) {
    this.context = context;
    this.resources = createEventResources(context, createSynthResources(context));
    this.limit = small ? 5 : 8;
    this.mix = context.createGain();
    this.mix.connect(output);
    this.reflections = context.createGain();
    this.reflections.gain.value = 0.06;
    const reverb = context.createConvolver();
    reverb.normalize = false;
    reverb.buffer = this.resources.impulse;
    const lp = context.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = 3200;
    this.reflections.connect(reverb).connect(lp).connect(this.mix);
    this.wind = createWindVoice(context, this.resources, this.mix);
    this.motors = new Map();
    this.events = [];
    this.listener = { x: 0, y: 0, z: 0 };
    this.haveListener = false;
    this.acc = 0;
    this.honkAt = new Map();
    this.lastHorn = -Infinity;
    this.params = { speed: 0, load: 0, verticalSpeed: 0, doppler: 1, seed: 0 };
    // The player's own engine, heard from inside: not positioned, so it never pans as the camera swings round.
    this.engine = null;
    this.setPlayerKind('sedan');
  }

  /** The player's motor voice: 'sedan', 'cyclist', 'helicopter', or null (on foot). */
  setPlayerKind(kind) {
    if (kind === this.engineKind) return;
    this.engine?.dispose();
    this.engine = kind ? createMotorVoice(this.context, this.resources, kind, this.mix) : null;
    this.engineKind = kind;
  }

  /** player: { speed, load }; motors: nearest first, [{ id, kind, x, y, z, speed, load, heading, seed, blocked }]. */
  update(dt, camera, player, motors, { night = 0, traffic = 0 } = {}) {
    const ctx = this.context;
    if (ctx.state !== 'running') return;
    const now = ctx.currentTime;
    this.engine?.update({ speed: player.speed, load: player.load, verticalSpeed: player.verticalSpeed || 0, seed: 1.7 }, now);
    this.acc += dt;
    if (this.acc < 0.1) return;
    dt = Math.min(this.acc, 0.25);
    this.acc %= 0.1;
    const pos = camera.position;
    if (this.haveListener && Math.hypot(pos.x - this.listener.x, pos.z - this.listener.z) > 60) this.reset();
    Object.assign(this.listener, { x: pos.x, y: pos.y, z: pos.z });
    camera.updateMatrixWorld();
    const m = camera.matrixWorld.elements, L = ctx.listener;
    const values = [pos.x, pos.y, pos.z, -m[8], -m[9], -m[10], m[4], m[5], m[6]];
    if (L.positionX) {
      const params = [L.positionX, L.positionY, L.positionZ, L.forwardX, L.forwardY, L.forwardZ, L.upX, L.upY, L.upZ];
      params.forEach((p, i) => (this.haveListener ? smooth(p, values[i], now, 0.025) : p.setValueAtTime(values[i], now)));
    } else {
      L.setPosition(values[0], values[1], values[2]);
      L.setOrientation(...values.slice(3));
    }
    this.haveListener = true;
    for (let i = this.events.length - 1; i >= 0; i--) {
      const e = this.events[i];
      if (now >= e.voice.endTime) this.removeEvent(i);
      else e.emitter.update(e.position, this.listener, now, e.range);
    }
    this.updatePool(motors, now, dt);
    // A car held up behind you for a few seconds leans on its horn.
    for (const s of motors) {
      if (!s.blocked) { this.honkAt.delete(s.id); continue; }
      const t = this.honkAt.get(s.id) ?? now + 4 + (s.seed % 1) * 3;
      this.honkAt.set(s.id, t);
      if (now > t && now - this.lastHorn > 3 && this.emit('horn', s, { intensity: 0.55 })) {
        this.honkAt.set(s.id, now + 18);
        this.lastHorn = now;
      }
    }
    this.wind.update({ speed: Math.min(player.speed, 50), altitude: pos.y, traffic, night, enclosure: 0.3 }, now);
  }

  updatePool(candidates, now, dt) {
    for (const slot of this.motors.values()) slot.selected = false;
    let count = 0;
    for (const source of candidates) {
      if (++count > this.limit) break;
      let slot = this.motors.get(source.id);
      if (!slot) {
        if (this.motors.size >= this.limit) continue;
        const emitter = new SpatialEmitter(this.context, this.mix, this.reflections, 4);
        slot = { emitter, voice: createMotorVoice(this.context, this.resources, source.kind, emitter.input), distance: 0, x: source.x, y: source.y, z: source.z, fresh: true };
        this.motors.set(source.id, slot);
      }
      slot.selected = true;
      slot.retire = 0;
      const jumped = Math.hypot(source.x - slot.x, source.y - slot.y, source.z - slot.z) > 35;
      const distance = slot.emitter.update(source, this.listener, now, 180, slot.fresh || jumped);
      const radial = slot.fresh || jumped ? 0 : clamp((distance - slot.distance) / dt, -60, 60);
      Object.assign(this.params, { speed: source.speed, load: source.load, verticalSpeed: 0, seed: source.seed, doppler: clamp(343 / (343 + radial), 0.85, 1.18) });
      slot.voice.update(this.params, now);
      Object.assign(slot, { distance, x: source.x, y: source.y, z: source.z, fresh: false });
    }
    for (const [id, slot] of this.motors) {
      if (slot.selected) continue;
      if (!slot.retire) { smooth(slot.emitter.input.gain, 0, now, 0.025); slot.retire = now + 0.12; } else if (now >= slot.retire) {
        slot.voice.dispose(); slot.emitter.dispose(); this.motors.delete(id);
      }
    }
  }

  removeEvent(i) {
    const e = this.events[i];
    e.voice.dispose(true);
    e.emitter.dispose();
    this.events.splice(i, 1);
  }

  /** A one-off sound at source ({ x, y, z, heading?, seed? }): 'crash' ({ severity, intensity }), 'horn', 'footstep'. */
  emit(kind, source, options = {}) {
    if (this.context.state !== 'running') return false;
    const now = this.context.currentTime;
    const crash = kind === 'crash';
    const severity = clamp(options.severity ?? options.intensity ?? 1, 0, 1);
    const ref = crash ? 4 + severity * 8 : kind === 'horn' ? 8 : 1.8;
    const range = crash ? 50 + severity * 110 : kind === 'horn' ? 140 : 35;
    if (this.haveListener && Math.hypot(source.x - this.listener.x, source.y - this.listener.y, source.z - this.listener.z) > range) return false;
    for (let i = this.events.length - 1; i >= 0; i--) if (now >= this.events[i].voice.endTime) this.removeEvent(i);
    if (this.events.length >= 8) this.removeEvent(0);
    const emitter = new SpatialEmitter(this.context, this.mix, this.reflections, ref, kind === 'horn');
    emitter.update(source, this.haveListener ? this.listener : source, now, range, true, crash);
    const voice = playEvent(this.context, this.resources, kind, emitter.input, { seed: source.seed ?? Math.random() * 1000, ...options });
    this.events.push({ kind, voice, emitter, range, position: { ...source } });
    return true;
  }

  reset() {
    for (const slot of this.motors.values()) { slot.voice.dispose(); slot.emitter.dispose(); }
    this.motors.clear();
    while (this.events.length) this.removeEvent(0);
    this.honkAt.clear();
  }
}

export { CityAudio };
