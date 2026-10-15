"""Build Mpls Drive's facade and roof textures: one 16-layer texture array.

    .venv/bin/python make_textures.py ../../public/mpls-drive/tex

Brick, concrete and gravel are CC0 photo-scanned materials from ambientCG
(ambientcg.com), downloaded once into osm-cache/textures/. Windows, doors,
storefronts, glass, clapboard siding, shingles and fence boards are drawn here, so
that a window always sits one per bay and one per floor however a wall is sized.

Writes facade.jpg (colour) and facade-n.jpg (normal x in red, y in green, and a
material mask in blue: 0 tinted wall, 0.5 untinted trim, 1 glass), each 512 px
wide with the layers stacked top to bottom, plus half-size -s versions for phones.
Every layer tiles seamlessly. LAYERS below says what each one is and how many
metres one tile covers; the game reads the same sizes.
"""
import io, json, os, subprocess, sys, zipfile

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1]
SRC = os.path.join(HERE, 'osm-cache', 'textures')
N = 512
rng = np.random.default_rng(11)

# name: (metres wide, metres tall) for one tile
LAYERS = [
    ('brick_red_win', 2.4, 3.6), ('brick_light_win', 2.4, 3.6), ('concrete_ribbon', 3.0, 3.6),
    ('glass_curtain', 1.5, 3.6), ('storefront', 4.8, 4.5), ('siding_win', 2.4, 2.9),
    ('siding_plain', 2.4, 2.9), ('garage_door', 3.0, 2.6), ('siding_door', 2.4, 2.9),
    ('brick_red_plain', 2.4, 3.6), ('brick_light_plain', 2.4, 3.6), ('concrete_plain', 3.0, 3.6),
    ('shingles', 2.0, 2.0), ('gravel_roof', 4.0, 4.0), ('fence', 2.4, 1.8), ('metal', 1.0, 1.0),
    ('asphalt', 4.0, 4.0), ('sidewalk', 1.5, 1.5), ('paint', 1.0, 1.0), ('grass', 2.8, 2.8),
]


# --------------------------------------------------------------- sources
def material(asset_id):
    """(colour, normal) float arrays 0..1 for an ambientCG 1K material, downloading it if needed."""
    folder = os.path.join(SRC, asset_id)
    os.makedirs(folder, exist_ok=True)
    col, nor = (os.path.join(folder, f'{asset_id}_1K-JPG_{k}.jpg') for k in ('Color', 'NormalGL'))
    if not os.path.exists(col):
        data = subprocess.run(['curl', '-sSL', '--fail', f'https://ambientcg.com/get?file={asset_id}_1K-JPG.zip'],
                              capture_output=True, check=True).stdout
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if os.path.basename(name) == name and name.endswith(('_Color.jpg', '_NormalGL.jpg')):
                    open(os.path.join(folder, name), 'wb').write(z.read(name))
    load = lambda p: np.asarray(Image.open(p).convert('RGB')).astype(np.float32) / 255
    return load(col), load(nor)


def tiled(img, rx, ry):
    """Repeat a tileable image rx by ry times and squeeze it into one N x N layer, so it still tiles."""
    return np.asarray(Image.fromarray((np.tile(img, (ry, rx, 1)) * 255).astype(np.uint8)).resize((N, N), Image.LANCZOS)).astype(np.float32) / 255


# -------------------------------------------------------------- drawing
def blank(rgb, mask=0.0):
    col = np.ones((N, N, 3), np.float32) * np.array(rgb, np.float32)
    nor = np.ones((N, N, 3), np.float32) * np.array([0.5, 0.5, 1.0], np.float32)
    return col, nor, np.full((N, N), mask, np.float32), np.zeros((N, N), np.float32)


def noise(scale, amp):
    small = rng.random((max(2, N // scale), max(2, N // scale))).astype(np.float32)
    return (np.asarray(Image.fromarray((small * 255).astype(np.uint8)).resize((N, N), Image.BICUBIC)).astype(np.float32) / 255 - 0.5) * amp


def rect(arrs, x0, y0, x1, y1, rgb=None, mask=None, depth=None):
    """Fill a box given in 0..1 tile coordinates (y down from the top of the tile)."""
    col, nor, msk, hgt = arrs
    a, b, c, d = int(round(y0 * N)), int(round(y1 * N)), int(round(x0 * N)), int(round(x1 * N))
    if rgb is not None:
        col[a:b, c:d] = rgb
    if mask is not None:
        msk[a:b, c:d] = mask
    if depth is not None:
        hgt[a:b, c:d] = depth


def window(arrs, x0, y0, x1, y1, frame=(0.93, 0.92, 0.88), bars=True, sill=(0.82, 0.8, 0.75), deep=True):
    """A punched window: trim, glass with a sky gradient, glazing bars, and a stone sill."""
    col, nor, msk, hgt = arrs
    t = 0.012
    rect(arrs, x0 - t, y0 - t, x1 + t, y1 + t, frame, 0.5, -0.2)
    rect(arrs, x0 + t, y0 + t, x1 - t, y1 - t, None, 1.0, -1.0 if deep else -0.4)
    a, b, c, d = int((y0 + t) * N), int((y1 - t) * N), int((x0 + t) * N), int((x1 - t) * N)
    g = np.linspace(0, 1, b - a)[:, None, None]
    sky = np.array([0.55, 0.66, 0.76]) * (1 - g) + np.array([0.18, 0.23, 0.28]) * g
    col[a:b, c:d] = sky + noise(64, 0.04)[a:b, c:d, None]
    if bars:
        mx = (x0 + x1) / 2
        rect(arrs, x0, (y0 + y1) / 2 - 0.006, x1, (y0 + y1) / 2 + 0.006, frame, 0.5, -0.3)
        rect(arrs, mx - 0.005, y0, mx + 0.005, y1, frame, 0.5, -0.3)
    rect(arrs, x0 - 0.03, y1, x1 + 0.03, y1 + 0.025, sill, 0.5, 0.25)


def finish(arrs, base_nor=None, strength=2.5):
    """Normals: the base material's, plus slopes from the height field (window recesses, boards)."""
    col, nor, msk, hgt = arrs
    h = np.asarray(Image.fromarray(((hgt + 1) * 100).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))).astype(np.float32) / 100
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * strength
    gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * strength
    base = (base_nor if base_nor is not None else nor) * 2 - 1
    flat = msk >= 0.4                                  # trim and glass are smooth
    base[flat] = [0, 0, 1]
    nx, ny = base[..., 0] - gx, base[..., 1] + gy
    nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0.05, 1))
    L = np.sqrt(nx * nx + ny * ny + nz * nz)
    return np.clip(col, 0, 1), np.stack([nx / L, ny / L], -1) * 0.5 + 0.5, msk


# --------------------------------------------------------------- layers
red_c, red_n = material('Bricks085')        # 2.4 x 1.2 m
lite_c, lite_n = material('Bricks060')      # whitewashed brick, about 1 m
conc_c, conc_n = material('Concrete034')
grav_c, grav_n = material('Gravel023')
asph_c, asph_n = material('Asphalt033')     # 2.5 m
grass_c, grass_n = material('Grass004')     # 1.4 m


def level(c, mean):
    """Scale a colour layer so its average brightness is mean: roads and lawns are tinted on top of it."""
    return np.clip(c * (mean / max(1e-3, float(c.mean()))), 0, 1)

brick_red = lambda: (tiled(red_c, 1, 3), tiled(red_n, 1, 3))
brick_lite = lambda: (tiled(lite_c, 2, 4) * 0.92 + 0.06, tiled(lite_n, 2, 4))
concrete = lambda: (tiled(conc_c, 3, 6) * 0.9 + 0.08, tiled(conc_n, 3, 6))


def wall(base, mask=0.0):
    c, n = base
    col, nor, msk, hgt = blank((1, 1, 1), mask)
    col[:] = c; nor[:] = n
    return [col, nor, msk, hgt], n


out = []
for name, w, h in LAYERS:
    base_n = None
    if name in ('brick_red_win', 'brick_light_win', 'brick_red_plain', 'brick_light_plain'):
        arrs, base_n = wall(brick_red() if 'red' in name else brick_lite())
        if name.endswith('win'):
            # One window per 2.4 m bay, 1.2 m wide and 1.8 m tall, sill 0.9 m above the floor.
            window(arrs, 0.25, 0.25, 0.75, 0.75, frame=(0.9, 0.88, 0.82) if 'red' in name else (0.24, 0.22, 0.2))
            rect(arrs, 0.22, 0.2, 0.78, 0.235, (0.78, 0.75, 0.68), 0.5, 0.2)      # stone lintel
    elif name in ('concrete_ribbon', 'concrete_plain'):
        arrs, base_n = wall(concrete())
        if name == 'concrete_ribbon':
            # A band of glass across the whole bay, with a mullion at each edge.
            window(arrs, 0.0, 0.32, 1.0, 0.8, frame=(0.32, 0.34, 0.36), bars=False, sill=(0.7, 0.7, 0.68), deep=False)
            rect(arrs, 0.0, 0.32, 0.015, 0.8, (0.3, 0.32, 0.34), 0.5, -0.2)
            rect(arrs, 0.985, 0.32, 1.0, 0.8, (0.3, 0.32, 0.34), 0.5, -0.2)
    elif name == 'glass_curtain':
        arrs = list(blank((0.2, 0.26, 0.32), 1.0))
        a = arrs[0]
        g = np.linspace(0, 1, N)[:, None, None]
        a[:] = np.array([0.36, 0.46, 0.56]) * (1 - g) + np.array([0.14, 0.19, 0.25]) * g + noise(48, 0.05)[..., None]
        rect(arrs, 0.0, 0.78, 1.0, 1.0, (0.16, 0.18, 0.2), 0.5, 0.0)            # spandrel at the floor slab
        rect(arrs, 0.0, 0.0, 0.025, 1.0, (0.55, 0.58, 0.6), 0.5, 0.4)           # mullions
        rect(arrs, 0.975, 0.0, 1.0, 1.0, (0.55, 0.58, 0.6), 0.5, 0.4)
        rect(arrs, 0.0, 0.775, 1.0, 0.79, (0.55, 0.58, 0.6), 0.5, 0.4)
    elif name == 'storefront':
        arrs, base_n = wall(brick_red())
        window(arrs, 0.06, 0.3, 0.94, 0.9, frame=(0.15, 0.15, 0.16), bars=False, sill=(0.3, 0.3, 0.3))
        rect(arrs, 0.06, 0.62, 0.94, 0.632, (0.15, 0.15, 0.16), 0.5, -0.3)      # transom bar
        rect(arrs, 0.5, 0.3, 0.508, 0.9, (0.15, 0.15, 0.16), 0.5, -0.3)
        rect(arrs, 0.03, 0.1, 0.97, 0.24, (0.16, 0.2, 0.22), 0.5, 0.15)         # sign band
        rect(arrs, 0.06, 0.9, 0.94, 1.0, (0.25, 0.25, 0.26), 0.5, 0.05)         # kickplate
    elif name.startswith('siding') or name in ('garage_door', 'fence'):
        # Painted clapboard: 15 cm boards, each a little shadowed under the one above.
        arrs = list(blank((0.97, 0.97, 0.96)))
        col, nor, msk, hgt = arrs
        if name == 'fence':
            x = (np.arange(N) / N * w / 0.14) % 1
            hgt[:] = np.where(x < 0.9, 0.4, -1.0)[None, :]
            col[:] = (0.9 + 0.08 * (x[None, :, None] < 0.9) - 0.4 * (x[None, :, None] >= 0.9)) + noise(24, 0.05)[..., None]
            col[:int(N * 0.02)] = 0.85
        else:
            y = (np.arange(N) / N * h / 0.15) % 1
            hgt[:] = (y * 0.8)[:, None]
            shade = (0.88 + 0.12 * y - 0.25 * (y > 0.93))[:, None, None]
            col[:] = shade + noise(32, 0.025)[..., None]
        if name == 'siding_win':
            window(arrs, 0.31, 0.2, 0.69, 0.72, frame=(0.96, 0.96, 0.94), deep=False)
        elif name == 'siding_door':
            rect(arrs, 0.27, 0.22, 0.73, 1.0, (0.96, 0.96, 0.94), 0.5, 0.1)     # door casing
            rect(arrs, 0.31, 0.26, 0.69, 1.0, (0.36, 0.17, 0.14), 0.5, -0.5)    # the door
            for k in range(3):
                rect(arrs, 0.35, 0.32 + k * 0.22, 0.65, 0.48 + k * 0.22, (0.31, 0.14, 0.12), 0.5, -0.65)
            rect(arrs, 0.61, 0.66, 0.635, 0.69, (0.8, 0.68, 0.32), 0.5, -0.2)   # knob
        elif name == 'garage_door':
            rect(arrs, 0.06, 0.12, 0.94, 1.0, (0.95, 0.95, 0.93), 0.5, -0.4)
            for k in range(4):
                rect(arrs, 0.06, 0.12 + k * 0.22, 0.94, 0.13 + k * 0.22, (0.78, 0.78, 0.76), 0.5, -0.6)
    elif name == 'shingles':
        # Three-tab asphalt shingles: 14 cm rows, 33 cm tabs, every tab its own shade.
        arrs = list(blank((0.5, 0.5, 0.5)))
        col, nor, msk, hgt = arrs
        rows = int(round(h / 0.14)); tabs = int(round(w / 0.33))
        yy, xx = np.mgrid[0:N, 0:N] / N
        r = np.floor(yy * rows)
        tab = np.floor(xx * tabs + (r % 2) * 0.5) % tabs
        tone = rng.random((rows, tabs)) * 0.25 + 0.62
        col[:] = tone[r.astype(int) % rows, tab.astype(int)][..., None] + noise(16, 0.08)[..., None]
        fy = (yy * rows) % 1
        hgt[:] = fy * 0.6
        col[fy > 0.9] *= 0.55
    elif name == 'asphalt':
        arrs, base_n = wall((level(tiled(asph_c, 2, 2), 0.55), tiled(asph_n, 2, 2)))
        arrs[0][:] += noise(6, 0.08)[..., None]            # patches of older and newer surface
    elif name == 'sidewalk':
        # One concrete panel with a tooled joint along two edges, so panels repeat every 1.5 m.
        arrs, base_n = wall((tiled(conc_c, 2, 2) * 0.85 + 0.12, tiled(conc_n, 2, 2)))
        rect(arrs, 0.0, 0.0, 1.0, 0.012, (0.55, 0.55, 0.53), 0.0, -1.0)
        rect(arrs, 0.0, 0.0, 0.012, 1.0, (0.55, 0.55, 0.53), 0.0, -1.0)
    elif name == 'paint':
        arrs = list(blank((0.95, 0.95, 0.93)))
        arrs[0][:] += noise(12, 0.08)[..., None]           # worn by tyres
    elif name == 'grass':
        arrs, base_n = wall((level(tiled(grass_c, 2, 2), 0.5), tiled(grass_n, 2, 2)))
    elif name == 'gravel_roof':
        arrs, base_n = wall((tiled(grav_c, 3, 3) * 0.7 + 0.25, tiled(grav_n, 3, 3)))
    else:   # metal
        arrs = list(blank((0.78, 0.8, 0.82), 0.5))
        arrs[0][:] += noise(8, 0.04)[..., None]
    out.append(finish(arrs, base_n))

os.makedirs(OUT, exist_ok=True)
col = np.concatenate([o[0] for o in out])
nor = np.concatenate([np.dstack([o[1], o[2][..., None]]) for o in out])
for arr, name in ((col, 'facade'), (nor, 'facade-n')):
    img = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    img.save(os.path.join(OUT, name + '.jpg'), quality=86, optimize=True)
    img.resize((N // 2, N // 2 * len(LAYERS)), Image.LANCZOS).save(os.path.join(OUT, name + '-s.jpg'), quality=86, optimize=True)
json.dump([[n, w, h] for n, w, h in LAYERS], open(os.path.join(OUT, 'layers.json'), 'w'))
print('layers', len(LAYERS))
