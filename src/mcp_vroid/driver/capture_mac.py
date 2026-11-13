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

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import Quartz
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


def _display_for(win: "W.Window | None") -> int:
    """CGDirectDisplayID of the display holding the window's centre (else main)."""
    try:
        if win is not None:
            cx, cy = win.x + win.w / 2, win.y + win.h / 2
            err, ids, cnt = Quartz.CGGetDisplaysWithPoint((cx, cy), 8, None, None)
            if err == 0 and cnt:
                return int(ids[0])
        return int(Quartz.CGMainDisplayID())
    except Exception:
        return 0


def _display_bounds(did: int) -> tuple[int, int, int, int]:
    """(x, y, w, h) of a display in global points, top-left origin."""
    r = Quartz.CGDisplayBounds(did)
    return (int(r.origin.x), int(r.origin.y), int(r.size.width), int(r.size.height))


def output_scale() -> float:
    """Backing scale (pixels per point) of the display VRoid is on."""
    try:
        did = _display_for(W.find_window())
        mode = Quartz.CGDisplayCopyDisplayMode(did)
        pts = Quartz.CGDisplayModeGetWidth(mode)
        px = Quartz.CGDisplayModeGetPixelWidth(mode)
        return float(px) / float(pts) if pts else 1.0
    except Exception:
        return 1.0


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
    """Capture the whole display VRoid is on (the main display if unknown).

    Uses a region capture of that display's bounds, so the Shot maps image
    pixels back to global screen points even on a secondary display.
    """
    did = _display_for(W.find_window())
    try:
        x, y, w, h = _display_bounds(did)
    except Exception:
        x = y = w = h = 0
    if w and h:
        return grab_region(x, y, w, h, tag=tag or "screen")
    path = next_capture_path(tag or "screen")
    img, _ = _capture([SCREENCAPTURE, "-x", "-m", str(path)], path, 0)
    return Shot(img, path, 0, 0, 1.0)
