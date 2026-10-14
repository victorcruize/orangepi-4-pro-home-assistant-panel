"""Builds the panel's media files: intro.rgb565 (from the logo sketch video) and saver.rgb565 (pulsing logo).

Both are sequences of raw 480x320 big-endian RGB565 frames, ready to be pushed to the LCD without decoding.
Usage: python3 make_media.py            (run inside ~/lcd35, needs ffmpeg, Pillow and numpy)
"""
import math, os, subprocess
import numpy as np
from PIL import Image, ImageFilter

W, H = 480, 320
MEDIA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
INTRO_FPS, SAVER_FPS, SAVER_PERIOD_S = 10, 8, 4
LOGO_PX, GLOW = 196, (196, 212, 255)
BG_CENTER, BG_EDGE = (44, 56, 118), (10, 13, 30)

rng = np.random.default_rng(7)
NOISE = rng.uniform(-0.5, 0.5, (H, W, 1)).astype(np.float32)      # fixed pattern: dithers gradients without shimmer


def to_rgb565(a):
    """a: float32 HxWx3 in 0..255 -> big-endian RGB565 bytes, with noise dithering against banding."""
    r = np.clip(a[..., 0] + NOISE[..., 0] * 8, 0, 255).astype(np.uint16) >> 3
    g = np.clip(a[..., 1] + NOISE[..., 0] * 4, 0, 255).astype(np.uint16) >> 2
    b = np.clip(a[..., 2] + NOISE[..., 0] * 8, 0, 255).astype(np.uint16) >> 3
    return ((r << 11) | (g << 5) | b).astype(">u2").tobytes()


def build_intro():
    """Video is square: scale to the panel width and crop the centre band, so the logo fills the screen."""
    out = os.path.join(MEDIA, "intro.rgb565")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(MEDIA, "logo-sketch.mp4"),
                    "-vf", f"fps={INTRO_FPS},scale={W}:{W}:flags=lanczos,crop={W}:{H}", "-sws_dither", "bayer",
                    "-f", "rawvideo", "-pix_fmt", "rgb565be", out], check=True)
    return os.path.getsize(out) // (W * H * 2)


def build_saver():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dist = np.clip(np.hypot((xx - W / 2) / (W * 0.62), (yy - H / 2) / (H * 0.78)), 0, 1)[..., None]
    bg = np.array(BG_CENTER, np.float32) * (1 - dist) ** 1.6 + np.array(BG_EDGE, np.float32) * (1 - (1 - dist) ** 1.6)
    logo_src = Image.open(os.path.join(MEDIA, "logo.png")).convert("RGBA")
    frames = SAVER_FPS * SAVER_PERIOD_S
    with open(os.path.join(MEDIA, "saver.rgb565"), "wb") as f:
        for k in range(frames):
            breath = 0.5 - 0.5 * math.cos(2 * math.pi * k / frames)          # 0..1..0, eased
            size = int(round(LOGO_PX * (1 + 0.025 * breath)))
            logo = logo_src.resize((size, size), Image.LANCZOS)
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            layer.paste(logo, ((W - size) // 2, (H - size) // 2))
            rgba = np.asarray(layer, np.float32)
            alpha = rgba[..., 3:4] / 255
            halo = np.asarray(layer.getchannel("A").filter(ImageFilter.GaussianBlur(14 + 10 * breath)), np.float32)[..., None] / 255
            halo = np.clip(halo * (0.55 + 0.75 * breath), 0, 1)
            img = bg + (np.array(GLOW, np.float32) - bg) * halo                   # glow behind the disc
            img = img * (1 - alpha) + rgba[..., :3] * alpha                       # logo on top
            f.write(to_rgb565(img))
    return frames


if __name__ == "__main__":
    print("intro frames:", build_intro())
    print("saver frames:", build_saver())
