import { NYC_LANDMARKS, MAP as BOUNDS, ISLAND_BOUNDS, getLocationLabel, isTypingInField, ROADS } from './city-config.js';

// The radar and the full-screen map, after Slop New York's nyc-map.js: the same controls ([M], drag to pan, wheel or
// buttons to zoom, click to teleport, search) and the same graphite look. Minneapolis's own map is drawn from the
// city's loaded tiles (mpls-city.js: their streets and footprints) over the whole map's overview image, dimmed.
// World frame: 1 unit = 1 m, x east, z south. Both maps face true north.

const MIN_ZOOM = 0.04; // full map, pixels per metre: the whole of the map
const MAX_ZOOM = 3.0; // single lots
const RADAR_SCALE = 0.32; // radar pixels per metre on the ground (zooms out with altitude)

// Map palette, as Slop New York's (in step with css/style.css)
const MAP = {
  water: '#0a1118',
  land: '#151a20',
  streets: '#3a434f',
  local: '#323a45',
  path: '#24302a',
  highway: '#b27a35',
  buildings: '#262c35',
  buildingEdge: '#171b21',
  route: '#ffc21a',
  search: '#5fd0ff',
  halo: 'rgba(8, 11, 15, 0.9)'
};
const FONT = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';

class MapView {
  constructor(cx, cz, s, w, h, dpr = 1) {
    this.cx = cx;
    this.cz = cz;
    this.s = s;
    this.w = w;
    this.h = h;
    this.dpr = dpr;
    this.minX = cx - w / (2 * s);
    this.maxX = cx + w / (2 * s);
    this.minZ = cz - h / (2 * s);
    this.maxZ = cz + h / (2 * s);
  }

  /** Canvas transform for world metres */
  world(ctx) {
    const { s, dpr } = this;
    ctx.setTransform(s * dpr, 0, 0, s * dpr, dpr * (this.w * 0.5 - this.cx * s), dpr * (this.h * 0.5 - this.cz * s));
  }

  /** Canvas transform for CSS pixels from the canvas centre (what toX / toY return) */
  screen(ctx) {
    ctx.setTransform(this.dpr, 0, 0, this.dpr, this.dpr * this.w * 0.5, this.dpr * this.h * 0.5);
  }

  toX(x) {
    return (x - this.cx) * this.s;
  }

  toY(z) {
    return (z - this.cz) * this.s;
  }
}

// Player heading arrow at the (already rotated) origin: white, on a dark halo
function drawPlayerArrow(ctx, tipY, halfWidth, tailY) {
  ctx.beginPath();
  ctx.moveTo(0, tipY);
  ctx.lineTo(halfWidth, tailY);
  ctx.lineTo(0, tailY * 0.45);
  ctx.lineTo(-halfWidth, tailY);
  ctx.closePath();
  ctx.lineJoin = 'round';
  ctx.strokeStyle = MAP.halo;
  ctx.lineWidth = 3;
  ctx.stroke();
  ctx.fillStyle = '#ffffff';
  ctx.fill();
}

// Route from the player to the waypoint, as the crow flies: taxi yellow on a dark casing
function drawRoute(ctx, x0, y0, x1, y1, width) {
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.strokeStyle = MAP.halo;
  ctx.lineWidth = width + 3;
  ctx.stroke();
  ctx.strokeStyle = MAP.route;
  ctx.lineWidth = width;
  ctx.stroke();
}

// Waypoint: a taxi-yellow target
function drawWaypoint(ctx, x, y, r) {
  ctx.fillStyle = MAP.halo;
  ctx.beginPath();
  ctx.arc(x, y, r + 2, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = MAP.route;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = MAP.halo;
  ctx.beginPath();
  ctx.arc(x, y, r * 0.38, 0, Math.PI * 2);
  ctx.fill();
}

class MplsMapSystem {
  constructor({ controllerManager, cameraSystem, city, onTeleport, onToggle }) {
    this.controllerManager = controllerManager;
    this.cameraSystem = cameraSystem;
    this.city = city;
    this.trafficSystem = null;
    this.onTeleport = onTeleport;
    this.onToggle = onToggle;

    this.miniCanvas = document.getElementById('minimap-canvas');
    this.miniCtx = this.miniCanvas ? this.miniCanvas.getContext('2d') : null;
    this.miniScale = RADAR_SCALE;
    this.miniCache = null; // { canvas, cx, cz, s, tiles }: the radar's ground layers, twice the radar's size

    this.modal = document.getElementById('fullmap-modal');
    this.fullCanvas = document.getElementById('fullmap-canvas');
    this.fullCanvasWrap = document.getElementById('fullmap-canvas-wrap');
    this.fullCtx = this.fullCanvas ? this.fullCanvas.getContext('2d') : null;
    this.fullDpr = 1;
    this.fullStatic = null;
    this.fullStaticKey = '';
    this.elHoverInfo = document.getElementById('fullmap-hover-info');
    this.elPlayerInfo = document.getElementById('fullmap-player-info');
    this.elSearchInput = document.getElementById('fullmap-search');

    this.isFullMapOpen = false;
    this.viewCenterX = 0;
    this.viewCenterZ = 0;
    this.viewZoom = 0.22;
    this.isPanning = false;
    this.panPointerId = null;
    this.panStart = { x: 0, y: 0, cx: 0, cz: 0 };
    this.dragMoved = false;
    this.searchHit = null;
    this.waypoint = null;

    // The whole map, small (city/overview.jpg), for where no tile is loaded
    // dimmed to the graphite palette once, when it arrives (a filter on every redraw is far too slow)
    this.overview = null;
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      const g = c.getContext('2d');
      g.filter = 'grayscale(0.55) brightness(0.32) contrast(1.15)';
      g.drawImage(img, 0, 0);
      this.overview = c;
      this.fullStaticKey = '';
      this.miniCache = null;
    };
    img.src = city.overviewURL;

    this.initEvents();
  }

  initEvents() {
    const closeBtn = document.getElementById('close-fullmap-btn');
    const miniCard = document.getElementById('minimap-card');
    const zoomInBtn = document.getElementById('map-zoom-in');
    const zoomOutBtn = document.getElementById('map-zoom-out');
    const centerPlayerBtn = document.getElementById('map-center-player');
    const fullMapBtn = document.getElementById('map-view-all');

    if (miniCard) miniCard.addEventListener('click', () => this.toggleFullMap(true));
    if (closeBtn) closeBtn.addEventListener('click', () => this.toggleFullMap(false));
    if (zoomInBtn) {
      zoomInBtn.addEventListener('click', () => {
        this.viewZoom = Math.min(MAX_ZOOM, this.viewZoom * 1.45);
        this.renderFullMap();
      });
    }
    if (zoomOutBtn) {
      zoomOutBtn.addEventListener('click', () => {
        this.viewZoom = Math.max(MIN_ZOOM, this.viewZoom / 1.45);
        this.renderFullMap();
      });
    }
    if (centerPlayerBtn) {
      centerPlayerBtn.addEventListener('click', () => {
        const ent = this.controllerManager.getActiveEntity();
        this.viewCenterX = ent.position.x;
        this.viewCenterZ = ent.position.z;
        this.viewZoom = 0.9; // street-by-street
        this.renderFullMap();
      });
    }
    if (fullMapBtn) fullMapBtn.addEventListener('click', () => { this.fitAll(); this.renderFullMap(); });
    if (this.elSearchInput) this.elSearchInput.addEventListener('input', () => this.search(this.elSearchInput.value));

    window.addEventListener('keydown', (e) => {
      if (e.code === 'Escape' && this.isFullMapOpen) {
        this.toggleFullMap(false);
      } else if (e.code === 'KeyM' && !isTypingInField(e)) {
        this.toggleFullMap(!this.isFullMapOpen);
      }
    });

    if (!this.fullCanvas) return;
    this.fullCanvas.style.touchAction = 'none';
    this.fullCanvas.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || !this.isFullMapOpen || this.panPointerId !== null) return;
      e.preventDefault();
      this.panPointerId = e.pointerId;
      this.fullCanvas.setPointerCapture(e.pointerId);
      this.isPanning = true;
      this.dragMoved = false;
      this.panStart.x = e.clientX;
      this.panStart.y = e.clientY;
      this.panStart.cx = this.viewCenterX;
      this.panStart.cz = this.viewCenterZ;
      if (this.fullCanvasWrap) this.fullCanvasWrap.classList.add('is-panning');
    });
    this.fullCanvas.addEventListener('pointermove', (e) => {
      if (!this.isFullMapOpen) return;
      if (this.isPanning ? e.pointerId !== this.panPointerId : e.pointerType !== 'mouse') return;
      const rect = this.fullCanvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      if (this.isPanning) {
        e.preventDefault();
        const dx = e.clientX - this.panStart.x;
        const dy = e.clientY - this.panStart.y;
        if (Math.hypot(dx, dy) > 5) this.dragMoved = true;
        this.viewCenterX = this.panStart.cx - dx / this.viewZoom;
        this.viewCenterZ = this.panStart.cz - dy / this.viewZoom;
        this.renderFullMap();
        return;
      }
      if (mx >= 0 && mx <= rect.width && my >= 0 && my <= rect.height && this.elHoverInfo) {
        const p = this.screenToWorld(mx, my, rect.width, rect.height);
        this.elHoverInfo.textContent = `${getLocationLabel(p.x, p.z)} · Click to teleport here`;
      }
    });
    this.fullCanvas.addEventListener('pointerup', (e) => {
      if (e.pointerId !== this.panPointerId) return;
      const clicked = !this.dragMoved && Math.hypot(e.clientX - this.panStart.x, e.clientY - this.panStart.y) <= 5;
      this.cancelPan();
      if (!clicked || !this.isFullMapOpen) return;
      const rect = this.fullCanvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      if (mx < 0 || mx > rect.width || my < 0 || my > rect.height) return;
      const p = this.clampToMap(this.screenToWorld(mx, my, rect.width, rect.height));
      this.waypoint = { x: p.x, z: p.z, name: getLocationLabel(p.x, p.z) };
      if (this.onTeleport) this.onTeleport(p.x, p.z);
      this.renderFullMap();
    });
    for (const type of ['pointercancel', 'lostpointercapture']) {
      this.fullCanvas.addEventListener(type, (e) => {
        if (e.pointerId === this.panPointerId) this.cancelPan();
      });
    }
    window.addEventListener('blur', () => this.cancelPan());
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this.cancelPan();
    });
    // Wheel zoom about the cursor (the place under it stays put)
    this.fullCanvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const rect = this.fullCanvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const before = this.screenToWorld(mx, my, rect.width, rect.height);
      this.viewZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, this.viewZoom * (e.deltaY < 0 ? 1.18 : 1 / 1.18)));
      this.viewCenterX = before.x - (mx - rect.width * 0.5) / this.viewZoom;
      this.viewCenterZ = before.z - (my - rect.height * 0.5) / this.viewZoom;
      this.renderFullMap();
    }, { passive: false });
  }

  /** Search the places to find, then the street names seen so far: frames the first that matches. */
  search(text) {
    const q = String(text || '').trim().toLowerCase();
    this.searchHit = null;
    if (q) {
      const lm = NYC_LANDMARKS.find((l) => l.name.toLowerCase().includes(q) || l.short.toLowerCase().includes(q));
      if (lm) {
        this.searchHit = { x: lm.x, z: lm.z, name: lm.name };
      } else {
        const road = ROADS.find((r) => r.name.toLowerCase().includes(q));
        const at = road && this.findStreet(road.name);
        if (at) this.searchHit = { ...at, name: road.name };
      }
      if (this.searchHit) {
        this.viewCenterX = this.searchHit.x;
        this.viewCenterZ = this.searchHit.z;
        this.viewZoom = Math.max(this.viewZoom, 0.6);
      }
    }
    this.fullStaticKey = '';
    this.renderFullMap();
  }

  // The loaded corner nearest the player that carries a street name
  findStreet(name) {
    const p = this.controllerManager.getActiveEntity().position;
    let best = null, bd = Infinity;
    for (const t of this.city.ready) {
      if (!t.corners) continue;
      const names = t.streetNames.map((n) => n && n.toLowerCase());
      for (let k = 0; k < t.corners.length; k += 6) {
        const a = names[t.corners[k + 3]], b = names[t.corners[k + 5]];
        if (!a?.startsWith(name.toLowerCase().split(' ')[0]) && !b?.startsWith(name.toLowerCase().split(' ')[0])) continue;
        const x = t.corners[k] / 10, z = t.corners[k + 1] / 10, d = Math.hypot(x - p.x, z - p.z);
        if (d < bd) { bd = d; best = { x, z }; }
      }
    }
    return best;
  }

  cancelPan() {
    const id = this.panPointerId;
    this.panPointerId = null;
    this.isPanning = false;
    if (this.fullCanvasWrap) this.fullCanvasWrap.classList.remove('is-panning');
    if (id !== null && this.fullCanvas && this.fullCanvas.hasPointerCapture(id)) this.fullCanvas.releasePointerCapture(id);
  }

  toggleFullMap(open) {
    this.isFullMapOpen = Boolean(open);
    if (!this.isFullMapOpen) this.cancelPan();
    if (this.onToggle) this.onToggle(this.isFullMapOpen);
    if (!this.modal) return;
    this.modal.classList.toggle('hidden', !this.isFullMapOpen);
    if (this.isFullMapOpen) {
      // the HUD's popovers live in the top layer, above the map
      for (const pop of document.querySelectorAll('.popover[popover]')) {
        if (typeof pop.hidePopover === 'function' && pop.matches(':popover-open')) pop.hidePopover();
      }
      const ent = this.controllerManager.getActiveEntity();
      this.viewCenterX = ent.position.x;
      this.viewCenterZ = ent.position.z;
      this.resizeFullCanvas();
      this.renderFullMap();
    }
  }

  fitAll() {
    const { w, h } = this.fullSize();
    this.viewCenterX = (BOUNDS.x0 + BOUNDS.x1) * 0.5;
    this.viewCenterZ = (BOUNDS.z0 + BOUNDS.z1) * 0.5;
    this.viewZoom = Math.max(MIN_ZOOM, Math.min(w / ((BOUNDS.x1 - BOUNDS.x0) * 1.08), h / ((BOUNDS.z1 - BOUNDS.z0) * 1.08)));
  }

  resizeFullCanvas() {
    if (!this.fullCanvas) return;
    const w = this.fullCanvas.clientWidth || window.innerWidth;
    const h = this.fullCanvas.clientHeight || window.innerHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(6e6 / Math.max(1, w * h)));
    this.fullDpr = dpr;
    this.fullCanvas.width = Math.max(1, Math.floor(w * dpr));
    this.fullCanvas.height = Math.max(1, Math.floor(h * dpr));
  }

  // Full map size in CSS pixels
  fullSize() {
    const dpr = this.fullDpr || 1;
    if (!this.fullCanvas) return { w: 1200, h: 800 };
    return { w: this.fullCanvas.width / dpr, h: this.fullCanvas.height / dpr };
  }

  screenToWorld(sx, sy, width, height) {
    return {
      x: this.viewCenterX + (sx - width * 0.5) / this.viewZoom,
      z: this.viewCenterZ + (sy - height * 0.5) / this.viewZoom
    };
  }

  // Teleports land inside the map
  clampToMap(p) {
    const B = ISLAND_BOUNDS;
    return { x: Math.max(B.minX + 25, Math.min(B.maxX - 25, p.x)), z: Math.max(B.minZ + 25, Math.min(B.maxZ - 25, p.z)) };
  }

  /** The ground of view v: the overview image dimmed, then every loaded tile's footprints and streets over it */
  drawWorld(ctx, v) {
    v.world(ctx);
    ctx.fillStyle = MAP.water;
    ctx.fillRect(v.minX, v.minZ, v.maxX - v.minX, v.maxZ - v.minZ);
    if (this.overview) ctx.drawImage(this.overview, BOUNDS.x0, BOUNDS.z0, BOUNDS.x1 - BOUNDS.x0, BOUNDS.z1 - BOUNDS.z0);
    // every loaded tile's own map (mpls-worker.js draws it): footprints and streets
    const T = this.city.MAP.tile;
    for (const t of this.city.ready) {
      if (!t.mapImage || t.x0 > v.maxX || t.x0 + T < v.minX || t.z0 > v.maxZ || t.z0 + T < v.minZ) continue;
      ctx.drawImage(t.mapImage, t.x0, t.z0, T, T);
    }
  }

  update() {
    // The full map covers the whole screen, radar included
    if (this.isFullMapOpen) this.renderFullMap();
    else this.renderMinimap();
  }

  /* ----------------------------- Radar (bottom left) ----------------------------- */
  renderMinimap() {
    if (!this.miniCtx || !this.miniCanvas) return;
    // Nothing to draw while the radar is hidden (narrow screens, clean view)
    if (!this.miniCanvas.offsetParent || document.body.classList.contains('hud-minimized')) return;
    const ctx = this.miniCtx;
    const w = this.miniCanvas.clientWidth;
    const h = this.miniCanvas.clientHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const bw = Math.round(w * dpr);
    const bh = Math.round(h * dpr);
    if (this.miniCanvas.width !== bw || this.miniCanvas.height !== bh) {
      this.miniCanvas.width = bw;
      this.miniCanvas.height = bh;
      this.miniCache = null;
    }

    const ent = this.controllerManager.getActiveEntity();
    const px = ent.position.x;
    const pz = ent.position.z;
    // Ground-level radar shows ~800 m of the city; it zooms out as the camera climbs (helicopter)
    const above = ent.position.y - this.city.groundH(px, pz);
    const target = Math.max(0.05, RADAR_SCALE / (1 + Math.max(0, above - 25) / 180));
    this.miniScale += (target - this.miniScale) * 0.08;
    const scale = this.miniScale;

    // The ground comes from a cached render twice the radar's size, redrawn when the player nears its edge, the zoom
    // drifts or more tiles arrive
    let c = this.miniCache;
    const n = this.city.ready.length;
    if (!c || c.tiles !== n || Math.abs(scale / c.s - 1) > 0.12 ||
      Math.abs(px - c.cx) > w / c.s - w / (2 * scale) - 8 / scale ||
      Math.abs(pz - c.cz) > h / c.s - h / (2 * scale) - 8 / scale) {
      if (!c) {
        c = this.miniCache = { canvas: document.createElement('canvas') };
        c.canvas.width = bw * 2;
        c.canvas.height = bh * 2;
        c.ctx = c.canvas.getContext('2d');
      }
      c.cx = px;
      c.cz = pz;
      c.s = scale;
      c.tiles = n;
      this.drawWorld(c.ctx, new MapView(px, pz, scale, w * 2, h * 2, dpr));
    }

    const v = new MapView(px, pz, scale, w, h, dpr);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = MAP.water;
    ctx.fillRect(0, 0, bw, bh);
    const k = scale / c.s;
    ctx.drawImage(c.canvas, dpr * ((c.cx - w / c.s - px) * scale + w * 0.5), dpr * ((c.cz - h / c.s - pz) * scale + h * 0.5),
      dpr * w * 2 * k, dpr * h * 2 * k);

    v.screen(ctx);
    const toX = (wx) => v.toX(wx);
    const toY = (wz) => v.toY(wz);

    // Live traffic blips
    const cars = this.trafficSystem?.cars;
    if (cars) {
      ctx.fillStyle = 'rgba(226, 232, 240, 0.34)';
      for (let i = 0; i < cars.length; i += 2) {
        const cx = toX(cars[i].x);
        const cy = toY(cars[i].z);
        if (Math.abs(cx) < w * 0.5 && Math.abs(cy) < h * 0.5) ctx.fillRect(cx - 1, cy - 1, 2, 2);
      }
    }

    if (this.waypoint) {
      const wx = toX(this.waypoint.x);
      const wy = toY(this.waypoint.z);
      drawRoute(ctx, 0, 0, wx, wy, 3);
      drawWaypoint(ctx, wx, wy, 4.5);
    }

    // Places to find
    for (const lm of NYC_LANDMARKS) {
      const lx = toX(lm.x);
      const ly = toY(lm.z);
      if (Math.abs(lx) < w * 0.48 && Math.abs(ly) < h * 0.48) {
        ctx.fillStyle = MAP.halo;
        ctx.beginPath();
        ctx.arc(lx, ly, 4.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(lx, ly, 2.8, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // The camera's view cone and the player's arrow at the centre
    const camDir = this.cameraSystem.currentLookAt.clone().sub(this.cameraSystem.currentPos);
    const camAngle = Math.atan2(camDir.x, camDir.z);
    ctx.save();
    ctx.rotate(-camAngle + Math.PI);
    const grad = ctx.createRadialGradient(0, 0, 2, 0, 0, 58);
    grad.addColorStop(0, 'rgba(255, 255, 255, 0.3)');
    grad.addColorStop(1, 'rgba(255, 255, 255, 0.0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.arc(0, 0, 58, -Math.PI * 0.72, -Math.PI * 0.28);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    ctx.save();
    ctx.rotate(-ent.heading + Math.PI);
    drawPlayerArrow(ctx, -9, 6.5, 7);
    ctx.restore();
    ctx.restore();
  }

  /* ----------------------------- Full map ([M]) ----------------------------- */
  renderFullMap() {
    if (!this.fullCtx || !this.fullCanvas || !this.isFullMapOpen) return;
    const ctx = this.fullCtx;
    const dpr = this.fullDpr || 1;
    const { w, h } = this.fullSize();
    const v = new MapView(this.viewCenterX, this.viewCenterZ, this.viewZoom, w, h, dpr);

    const ent = this.controllerManager.getActiveEntity();
    if (this.elPlayerInfo) {
      const text = `You are at ${getLocationLabel(ent.position.x, ent.position.z)}`;
      if (text !== this.playerInfoText) {
        this.playerInfoText = text;
        this.elPlayerInfo.textContent = text;
      }
    }

    // The ground and the place pins: re-rendered only when the view, the search or the tiles change
    const key = `${v.cx}|${v.cz}|${v.s}|${this.fullCanvas.width}|${this.fullCanvas.height}|${this.city.ready.length}`;
    if (!this.fullStatic) this.fullStatic = document.createElement('canvas');
    if (key !== this.fullStaticKey) {
      this.fullStaticKey = key;
      const sc = this.fullStatic;
      if (sc.width !== this.fullCanvas.width || sc.height !== this.fullCanvas.height) {
        sc.width = this.fullCanvas.width;
        sc.height = this.fullCanvas.height;
      }
      const sctx = sc.getContext('2d');
      this.drawWorld(sctx, v);
      v.screen(sctx);
      this.drawPlaces(sctx, v);
    }

    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(this.fullStatic, 0, 0);
    v.screen(ctx);
    const toX = (wx) => v.toX(wx);
    const toY = (wz) => v.toY(wz);
    if (this.searchHit) {
      ctx.strokeStyle = MAP.search;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(toX(this.searchHit.x), toY(this.searchHit.z), 14, 0, Math.PI * 2);
      ctx.stroke();
    }
    if (this.waypoint) {
      const wx = toX(this.waypoint.x);
      const wy = toY(this.waypoint.z);
      drawRoute(ctx, toX(ent.position.x), toY(ent.position.z), wx, wy, 4);
      drawWaypoint(ctx, wx, wy, 7);
    }
    // The player, with a slow pulse to find it at a glance
    ctx.save();
    ctx.translate(toX(ent.position.x), toY(ent.position.z));
    const pulse = (performance.now() % 1800) / 1800;
    ctx.fillStyle = `rgba(255, 255, 255, ${0.24 * (1 - pulse)})`;
    ctx.beginPath();
    ctx.arc(0, 0, 10 + pulse * 20, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = 'rgba(255, 255, 255, 0.12)';
    ctx.beginPath();
    ctx.arc(0, 0, 13, 0, Math.PI * 2);
    ctx.fill();
    ctx.rotate(-ent.heading + Math.PI);
    drawPlayerArrow(ctx, -11, 7.5, 8);
    ctx.restore();
    ctx.restore();
  }

  // Place pins and their names (CSS pixels from the centre)
  drawPlaces(ctx, v) {
    ctx.font = `600 12px ${FONT}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const lm of NYC_LANDMARKS) {
      const x = v.toX(lm.x), y = v.toY(lm.z);
      if (Math.abs(x) > v.w * 0.5 + 40 || Math.abs(y) > v.h * 0.5 + 40) continue;
      ctx.fillStyle = MAP.halo;
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
      if (v.s > 0.08) {
        ctx.lineWidth = 3;
        ctx.strokeStyle = MAP.halo;
        ctx.strokeText(lm.short, x, y + 9);
        ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
        ctx.fillText(lm.short, x, y + 9);
      }
    }
  }
}

export { MplsMapSystem };
