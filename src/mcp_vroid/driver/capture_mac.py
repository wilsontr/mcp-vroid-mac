"""Screenshot the VRoid window with macOS `screencapture`.

Mirrors the original grim-based module: a `Shot` carries the image plus the
mapping back to screen points, so OCR pixel coordinates can be handed straight
to `input.click(..., space="image", shot=shot)`.

Points vs pixels: macOS screen coordinates (CGWindowList bounds, CGEvent
positions, `screencapture -R`) are in *points*. On a Retina display the PNG is
2x, so `Shot.scale` is computed from `image.width / region.width` and callers
stay in image pixels until `to_layout()` converts.

Window capture uses `screencapture -l <CGWindowID>`, which captures the window
even when other windows overlap it. It needs the Screen Recording permission
for the process that hosts this server.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import window_mac as W
from .paths import CAPTURES

SCREENCAPTURE = shutil.which("screencapture") or "/usr/sbin/screencapture"
PERMISSION_HINT = (
    "Screen capture failed. Grant this process (your terminal / MCP client) "
    "Screen Recording in System Settings > Privacy & Security > Screen & "
    "System Audio Recording, then restart it. macOS returns a blank or "
    "missing image when the permission is missing."
)


def screen_recording_ok() -> bool:
    """Best-effort Screen Recording permission check."""
    try:
        import Quartz

        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        return True  # unknown; let the actual capture report failure


def _screen_scale() -> float:
    try:
        from AppKit import NSScreen

        s = NSScreen.mainScreen()
        return float(s.backingScaleFactor()) if s is not None else 1.0
    except Exception:
        return 1.0


def output_scale() -> float:
    return _screen_scale()


def next_capture_path(tag: str = "") -> Path:
    n = 0
    for p in CAPTURES.glob("[0-9][0-9][0-9]*.png"):
        try:
            n = max(n, int(p.name[:3]))
        except ValueError:
            pass
    name = f"{n + 1:03d}" + (f"-{tag}" if tag else "") + ".png"
    return CAPTURES / name


@dataclass
class Shot:
    image: Image.Image
    path: Path
    ox: int          # region origin x, screen points
    oy: int
    scale: float     # image px per screen point

    @property
    def size(self):
        return self.image.size

    def to_window(self, px: float, py: float) -> tuple[float, float]:
        """Image pixel -> window-relative point."""
        return (px / self.scale, py / self.scale)

    def to_layout(self, px: float, py: float) -> tuple[float, float]:
        """Image pixel -> global screen point."""
        return (self.ox + px / self.scale, self.oy + py / self.scale)

    def crop(self, box) -> "Shot":
        l, t, r, b = box
        return Shot(
            self.image.crop(box),
            self.path,
            int(self.ox + l / self.scale),
            int(self.oy + t / self.scale),
            self.scale,
        )


def _capture(args: list[str], path: Path, width: int):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0 or not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"{PERMISSION_HINT}\n(screencapture: {r.stderr.strip()})")
    img = Image.open(path).convert("RGB")
    scale = (img.width / width) if width else 1.0
    return img, scale


def grab_region(x: int, y: int, w: int, h: int, tag: str = "",
                path: Path | None = None) -> Shot:
    path = path or next_capture_path(tag)
    img, scale = _capture(
        [SCREENCAPTURE, "-x", "-R", f"{int(x)},{int(y)},{int(w)},{int(h)}", str(path)],
        path, int(w),
    )
    return Shot(img, path, int(x), int(y), scale)


def grab_window(win: W.Window | None = None, tag: str = "") -> Shot:
    win = win or W.find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    path = next_capture_path(tag)
    img, scale = _capture(
        [SCREENCAPTURE, "-x", "-o", "-l", str(win.window_id), str(path)],
        path, win.w,
    )
    return Shot(img, path, win.x, win.y, scale)


def grab_screen(tag: str = "") -> Shot:
    path = next_capture_path(tag or "screen")
    pt_width = 0
    try:
        from AppKit import NSScreen

        screen = NSScreen.mainScreen()
        if screen is not None:
            pt_width = int(screen.frame().size.width)
    except Exception:
        pass
    img, scale = _capture([SCREENCAPTURE, "-x", str(path)], path, pt_width)
    return Shot(img, path, 0, 0, scale)
