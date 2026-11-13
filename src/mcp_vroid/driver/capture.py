"""Screenshot the VRoid window with grim and hand back a PIL image.

Coordinates: Hyprland's layout is *logical* (2048x1152 here for a 2560x1440
panel at scale 1.25). grim renders at the output's native scale, so image
pixels are `scale` times the layout units. A Shot carries the mapping so
callers can hand OCR pixel coords straight back to input.click().
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import window as W
from .paths import CAPTURES


def output_scale() -> float:
    mons = W.hyprctl_json("monitors")
    return float(mons[0].get("scale", 1.0)) if mons else 1.0


_SEQ = re.compile(r"^(\d+)")


def next_capture_path(tag: str = "") -> Path:
    # Parse the whole leading number: slicing three digits wrapped "1000-..."
    # back to 100 and overwrote older captures.
    n = 0
    for p in CAPTURES.glob("[0-9]*.png"):
        m = _SEQ.match(p.name)
        if m:
            n = max(n, int(m.group(1)))
    name = f"{n + 1:03d}" + (f"-{tag}" if tag else "") + ".png"
    return CAPTURES / name


@dataclass
class Shot:
    image: Image.Image
    path: Path
    ox: int          # region origin x, layout coords
    oy: int
    scale: float     # image px per layout unit

    @property
    def size(self):
        return self.image.size

    def to_window(self, px: float, py: float) -> tuple[float, float]:
        """Image pixel -> window-relative layout coords."""
        return (px / self.scale, py / self.scale)

    def to_layout(self, px: float, py: float) -> tuple[float, float]:
        return (self.ox + px / self.scale, self.oy + py / self.scale)

    def crop(self, box) -> "Shot":
        l, t, r, b = box
        return Shot(self.image.crop(box), self.path,
                    int(self.ox + l / self.scale), int(self.oy + t / self.scale),
                    self.scale)


def grab_region(x: int, y: int, w: int, h: int, tag: str = "",
                path: Path | None = None) -> Shot:
    path = path or next_capture_path(tag)
    scale = output_scale()
    subprocess.run(
        ["grim", "-g", f"{x},{y} {w}x{h}", str(path)],
        check=True, capture_output=True,
    )
    img = Image.open(path).convert("RGB")
    # grim may clamp the region at the output edge; derive the real scale.
    if w:
        scale = img.width / w
    return Shot(img, path, x, y, scale)


def grab_window(win: W.Window | None = None, tag: str = "") -> Shot:
    win = win or W.find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    return grab_region(*win.geometry, tag=tag)


def grab_screen(tag: str = "") -> Shot:
    mon = W.hyprctl_json("monitors")[0]
    scale = float(mon.get("scale", 1.0))
    w = int(round(mon["width"] / scale))
    h = int(round(mon["height"] / scale))
    return grab_region(int(mon["x"]), int(mon["y"]), w, h, tag=tag)
