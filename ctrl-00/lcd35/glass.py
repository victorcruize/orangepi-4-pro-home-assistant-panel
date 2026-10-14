"""Liquid-glass look for the panel.

A soft colour wallpaper sits behind everything. Every tile, button and key is a pane of frosted glass:
it shows the wallpaper blurred and slightly lit, has a bright rim that is stronger at the top, a gloss
that fades down from the upper edge, and a soft shadow underneath. Active controls are tinted glass.

The views keep calling the ordinary drawing API. GlassDraw recognises the theme's fill colours in
rounded_rectangle() and paints glass instead, so the whole interface follows one rule.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from lcd import W, H
from theme import TILE, TILE_HI, AMBER, CYAN, GREEN, RED, ORANGE

MIN_GLASS = 16                      # smaller shapes (signal bars, dots) stay flat
SHADOW_PAD = 8

_rng = np.random.default_rng(11)
_NOISE = _rng.uniform(-3.0, 3.0, (H, W, 1)).astype(np.float32)   # baked-in dither: hides banding on the 16-bit LCD


def _to_image(a):
    return Image.fromarray(np.clip(a + _NOISE, 0, 255).astype(np.uint8), "RGB")


def _wallpaper():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    a = np.zeros((H, W, 3), np.float32) + np.array((8, 11, 24), np.float32)
    blobs = (((70, 40), 250, (46, 66, 196)),      # indigo, upper left
             ((430, 70), 220, (126, 58, 178)),    # violet, upper right
             ((330, 330), 260, (14, 128, 150)),   # teal, lower right
             ((30, 320), 190, (28, 44, 132)))     # deep blue, lower left
    for (cx, cy), size, colour in blobs:
        g = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * (size * 0.5) ** 2))[..., None]
        a += g * np.array(colour, np.float32) * 0.74
    return np.clip(a, 0, 255)


_wall = _wallpaper()
_frost = np.asarray(Image.fromarray(_wall.astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(16)), np.float32)

WALLPAPER = _to_image(_wall)
_LAYERS = {
    "panel": _to_image(_frost * 0.62 + 255 * 0.085),     # resting tile: darker than the wallpaper, so text reads
    "raised": _to_image(_frost * 0.78 + 255 * 0.17),     # button: lighter, sits above the tiles
}
_KINDS = {TILE: "panel", TILE_HI: "raised"}
_TINTS = (AMBER, CYAN, GREEN, RED, ORANGE)
_cache = {}


def _tint_layer(colour):
    key = ("tint", colour)
    if key not in _cache:
        _cache[key] = _to_image(_frost * 0.22 + np.array(colour, np.float32) * 0.80 + 255 * 0.03)
    return _cache[key]


def _mask(w, h, r):
    """Anti-aliased rounded-rectangle mask."""
    key = ("mask", w, h, r)
    if key not in _cache:
        big = Image.new("L", (w * 3, h * 3), 0)
        ImageDraw.Draw(big).rounded_rectangle([0, 0, w * 3 - 1, h * 3 - 1], r * 3, fill=255)
        _cache[key] = big.resize((w, h), Image.LANCZOS)
    return _cache[key]


def _gloss(w, h, r, strength):
    """Light falling on the upper part of the pane, fading out before the middle."""
    key = ("gloss", w, h, r, strength)
    if key not in _cache:
        ramp = np.clip(1 - np.arange(h, dtype=np.float32) / max(1.0, h * 0.5), 0, 1) ** 1.6
        a = np.asarray(_mask(w, h, r), np.float32) / 255 * ramp[:, None] * strength    # strength = peak alpha, 0..255
        _cache[key] = Image.fromarray(a.astype(np.uint8), "L")
    return _cache[key]


def _rim(w, h, r):
    """One-pixel edge of the pane: bright at the top, faint at the bottom."""
    key = ("rim", w, h, r)
    if key not in _cache:
        outer = np.asarray(_mask(w, h, r), np.float32)
        inner = np.zeros((h, w), np.float32)
        if w > 4 and h > 4:
            inner[1:-1, 1:-1] = np.asarray(_mask(w - 2, h - 2, max(0, r - 1)), np.float32)
        ring = np.clip(outer - inner, 0, 255)
        ramp = 0.22 + 0.60 * np.clip(1 - np.arange(h, dtype=np.float32) / (h * 0.75), 0, 1)
        _cache[key] = Image.fromarray((ring * ramp[:, None]).astype(np.uint8), "L")
    return _cache[key]


def _shadow(w, h, r):
    key = ("shadow", w, h, r)
    if key not in _cache:
        big = Image.new("L", (w + 2 * SHADOW_PAD, h + 2 * SHADOW_PAD), 0)
        big.paste(_mask(w, h, r), (SHADOW_PAD, SHADOW_PAD))
        _cache[key] = big.filter(ImageFilter.GaussianBlur(4)).point(lambda v: int(v * 0.42))
    return _cache[key]


def canvas():
    """A fresh frame with the wallpaper on it."""
    return WALLPAPER.copy()


class GlassDraw(ImageDraw.ImageDraw):
    """ImageDraw that paints the theme's tiles and buttons as glass."""

    def __init__(self, im):
        super().__init__(im)
        self._img = im

    def sample(self, x, y):
        """Colour currently at a point, for shapes that need to blend with what is under them."""
        return self._img.getpixel((int(min(max(x, 0), W - 1)), int(min(max(y, 0), H - 1))))

    def rounded_rectangle(self, xy, radius=0, fill=None, outline=None, width=1, **kw):
        flat = [float(v) for pair in xy for v in (pair if isinstance(pair, (list, tuple)) else (pair,))]
        x0, y0, x1, y1 = (int(round(v)) for v in flat[:4])
        w, h = x1 - x0 + 1, y1 - y0 + 1
        fill_key = tuple(fill) if isinstance(fill, (list, tuple)) else fill
        if fill_key in _KINDS: layer, gloss = _LAYERS[_KINDS[fill_key]], (46 if fill_key == TILE else 70)
        elif fill_key in _TINTS: layer, gloss = _tint_layer(fill_key), 110
        elif fill is None and outline is not None: layer, gloss = None, 0          # outline-only pill
        else: layer, gloss = False, 0
        if layer is False or w < MIN_GLASS or h < MIN_GLASS:
            return super().rounded_rectangle(xy, radius, fill, outline, width, **kw)
        r = int(min(radius, w // 2, h // 2))
        mask = _mask(w, h, r)
        if layer is None:
            self._img.paste(_LAYERS["panel"].crop((x0, y0, x1 + 1, y1 + 1)), (x0, y0), mask.point(lambda v: v // 2))
        else:
            self._img.paste((0, 0, 0), (x0 - SHADOW_PAD, y0 - SHADOW_PAD + 3), _shadow(w, h, r))
            self._img.paste(layer.crop((x0, y0, x1 + 1, y1 + 1)), (x0, y0), mask)
            self._img.paste((255, 255, 255), (x0, y0), _gloss(w, h, r, gloss))
        self._img.paste((255, 255, 255), (x0, y0), _rim(w, h, r))
