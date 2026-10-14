"""Shared fonts and colours for the CTRL-00 panel screens."""
from PIL import ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf"
def font(size, bold=False): return ImageFont.truetype(FONT % ("-Bold" if bold else ""), size)
F_TITLE, F_CLOCK, F_NAME, F_TEMP, F_PILL = font(19, True), font(19), font(14, True), font(30, True), font(12, True)
F_BTN, F_SUB, F_HUGE, F_LINE = font(26, True), font(14), font(54, True), font(19)
F_COND = font(16, True)
F_KEY, F_SMALL, F_ICON = font(22, True), font(12), font(24)

BG, TILE, TILE_HI = (11, 13, 18), (24, 28, 38), (38, 44, 58)
TEXT, MUTED = (240, 243, 250), (166, 176, 198)
AMBER, CYAN, ORANGE, RED, GREEN = (255, 176, 32), (64, 196, 255), (255, 106, 0), (255, 84, 84), (64, 214, 128)
