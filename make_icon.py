"""Generate icon.png for the Cherkasy Outage HA integration.

Visual concept: electricity pylon silhouette with a bold red diagonal slash,
on a dark navy background — instantly reads as "power outage".
"""

import math

from PIL import Image, ImageDraw

SIZE = 256
OUT = "custom_components/cherkasy_outage/brand/icon.png"

# ── Palette ───────────────────────────────────────────────────────────────────
BG = (18, 30, 54)  # dark navy
PYLON_BODY = (180, 200, 230)  # cool steel blue-grey
WIRE_COL = (140, 165, 200)  # slightly dimmer wires
SLASH_COL = (220, 40, 40)  # bold red slash

img = Image.new("RGBA", (SIZE, SIZE), BG)
d = ImageDraw.Draw(img)


# ── Helper ────────────────────────────────────────────────────────────────────
def line(x0, y0, x1, y1, col=PYLON_BODY, w=4):
    d.line([(x0, y0), (x1, y1)], fill=col, width=w)


def poly(pts, col=PYLON_BODY):
    d.polygon(pts, fill=col)


# ── Pylon geometry ────────────────────────────────────────────────────────────
cx = SIZE // 2  # 128

# Crossarm Y positions — spread out to fill more of the height
arm1_y = 52  # top arm
arm2_y = 108  # mid arm
arm3_y = 152  # lower arm

# Arm half-widths
arm1_hw = 72
arm2_hw = 54
arm3_hw = 40

# Tower leg spread at base
base_y = 220
base_hw = 36
neck_y = 172

# ── Main tower legs ───────────────────────────────────────────────────────────
top_y = 38
top_hw = 8  # narrow top

line(cx - top_hw, top_y, cx - base_hw, base_y, w=5)
line(cx + top_hw, top_y, cx + base_hw, base_y, w=5)

# ── Horizontal crossarms ──────────────────────────────────────────────────────
for ay, hw in [(arm1_y, arm1_hw), (arm2_y, arm2_hw), (arm3_y, arm3_hw)]:
    line(cx - hw, ay, cx + hw, ay, w=5)
    # short vertical insulator stubs
    line(cx - hw, ay, cx - hw, ay + 8, w=4)
    line(cx + hw, ay, cx + hw, ay + 8, w=4)
    # centre kingpin
    line(cx, ay - 6, cx, ay + 6, w=4)

# ── Diagonal bracing between arms ────────────────────────────────────────────
# between arm1 and arm2
line(cx - arm1_hw, arm1_y, cx - arm2_hw, arm2_y, w=3)
line(cx + arm1_hw, arm1_y, cx + arm2_hw, arm2_y, w=3)
# inner X bracing
line(cx - arm2_hw, arm1_y, cx - arm1_hw + 20, arm2_y, w=3)
line(cx + arm2_hw, arm1_y, cx + arm1_hw - 20, arm2_y, w=3)

# between arm2 and arm3
line(cx - arm2_hw, arm2_y, cx - arm3_hw, arm3_y, w=3)
line(cx + arm2_hw, arm2_y, cx + arm3_hw, arm3_y, w=3)
line(cx - arm3_hw, arm2_y, cx - arm2_hw + 14, arm3_y, w=3)
line(cx + arm3_hw, arm2_y, cx + arm2_hw - 14, arm3_y, w=3)

# between arm3 and base struts
line(cx - arm3_hw, arm3_y, cx - base_hw, neck_y, w=3)
line(cx + arm3_hw, arm3_y, cx + base_hw, neck_y, w=3)
line(cx - base_hw, arm3_y, cx - arm3_hw + 12, neck_y, w=3)
line(cx + base_hw, arm3_y, cx + arm3_hw - 12, neck_y, w=3)

# ── Base spreader feet ────────────────────────────────────────────────────────
foot_w = 14
line(cx - base_hw, base_y, cx - base_hw - foot_w, base_y, w=5)
line(cx + base_hw, base_y, cx + base_hw + foot_w, base_y, w=5)
line(cx - base_hw - 2, base_y, cx - base_hw - 2, base_y + 6, w=5)
line(cx + base_hw + 2, base_y, cx + base_hw + 2, base_y + 6, w=5)


# ── Drooping power lines (catenary-like with short polylines) ─────────────────
def catenary(x0, x1, y_attach, sag, steps=14, col=WIRE_COL, w=2):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        xp = x0 + (x1 - x0) * t
        # parabolic sag
        yp = y_attach + sag * 4 * t * (1 - t)
        pts.append((xp, yp))
    d.line(pts, fill=col, width=w)


# wires leave from arm-tip insulators, droop offscreen left/right
for ay, hw in [(arm1_y + 8, arm1_hw), (arm2_y + 8, arm2_hw)]:
    # left wire droops down-left
    catenary(cx - hw, cx - hw - 60, ay, 18)
    # right wire droops down-right
    catenary(cx + hw, cx + hw + 60, ay, 18)

# ── Red slash (NO POWER) ──────────────────────────────────────────────────────
slash_w = 18
margin = 26
# bold diagonal from top-right to bottom-left (like a "prohibited" slash)
x0, y0 = SIZE - margin, margin
x1, y1 = margin, SIZE - margin

# draw thick line with round caps via multiple offset lines
for offset in range(-slash_w // 2, slash_w // 2 + 1, 2):
    dx = offset * math.cos(math.radians(45))
    dy = -offset * math.sin(math.radians(45))
    d.line([(x0 + dx, y0 + dy), (x1 + dx, y1 + dy)], fill=SLASH_COL, width=3)

# ── Save ──────────────────────────────────────────────────────────────────────
img.save(OUT, "PNG")
print(f"Saved {OUT}  ({SIZE}×{SIZE})")
