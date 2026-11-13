"""Find / launch / focus the VRoid Studio window on macOS.

Replaces the Hyprland/`hyprctl` half of the original driver. A `Window` here
carries the same fields the rest of the driver expects: geometry in *screen
points* (top-left origin, the coordinate space CGEvent uses), plus the
CGWindowID used by `screencapture -l`.

There are no workspaces on macOS, so the workspace helpers are no-ops kept for
API compatibility with `server.py` / `actions.py`.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

import Quartz
from AppKit import (
    NSApplicationActivateIgnoringOtherApps,
    NSRunningApplication,
    NSWorkspace,
)

BUNDLE_ID = "net.pixiv.vroid.macosx"
OWNER_NAMES = ("VRoid Studio", "VRoidStudio")
APP_PATH = "/Applications/VRoidStudio.app"
MIN_SIZE = 200
WORKSPACE = 0


@dataclass
class Window:
    address: str            # CGWindowID, as a string (kept for API parity)
    cls: str                # owner application name
    title: str
    x: int
    y: int
    w: int
    h: int
    workspace: int = WORKSPACE
    focused: bool = False
    fullscreen: bool = False
    pid: int = 0

    @property
    def geometry(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) in screen points, top-left origin."""
        return (self.x, self.y, self.w, self.h)

    @property
    def window_id(self) -> int:
        return int(self.address)

    def to_layout(self, x: float, y: float) -> tuple[float, float]:
        """Window-relative point -> global screen point."""
        return (self.x + x, self.y + y)


def _frontmost():
    try:
        return NSWorkspace.sharedWorkspace().frontmostApplication()
    except Exception:
        return None


def is_vroid_focused() -> bool:
    app = _frontmost()
    if app is None:
        return False
    try:
        if (app.bundleIdentifier() or "") == BUNDLE_ID:
            return True
        return (app.localizedName() or "") in OWNER_NAMES
    except Exception:
        return False


def assert_vroid_focused() -> None:
    if not is_vroid_focused():
        app = _frontmost()
        name = app.localizedName() if app is not None else None
        raise RuntimeError(
            "refusing to act: the focused application is not VRoid Studio "
            f"(frontmost={name!r}). Call vroid_launch, then retry."
        )


def _windows() -> list[dict]:
    return list(
        Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID
        )
        or []
    )


def find_window() -> Window | None:
    """Return the largest VRoid Studio window, or None."""
    best: Window | None = None
    for w in _windows():
        owner = str(w.get("kCGWindowOwnerName") or "")
        if owner not in OWNER_NAMES:
            continue
        if int(w.get("kCGWindowLayer") or 0) != 0:
            continue
        b = w.get("kCGWindowBounds") or {}
        ww, hh = int(b.get("Width", 0)), int(b.get("Height", 0))
        if ww < MIN_SIZE or hh < MIN_SIZE:
            continue
        cand = Window(
            address=str(w.get("kCGWindowNumber")),
            cls=owner,
            title=str(w.get("kCGWindowName") or ""),
            x=int(b.get("X", 0)),
            y=int(b.get("Y", 0)),
            w=ww,
            h=hh,
            focused=is_vroid_focused(),
            pid=int(w.get("kCGWindowOwnerPID") or 0),
        )
        if best is None or cand.w * cand.h > best.w * best.h:
            best = cand
    return best


def launch() -> None:
    """Open VRoid Studio by bundle id, falling back to its name/path."""
    for cmd in (
        ["open", "-b", BUNDLE_ID],
        ["open", "-a", "VRoid Studio"],
        ["open", APP_PATH],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        except Exception:
            continue
        if r.returncode == 0:
            return
    raise RuntimeError(
        "could not launch VRoid Studio with `open`; is /Applications/VRoidStudio.app installed?"
    )


def wait_for_window(timeout: float = 180.0, poll: float = 1.0) -> Window:
    deadline = time.time() + timeout
    while time.time() < deadline:
        w = find_window()
        if w is not None and w.w > MIN_SIZE and w.h > MIN_SIZE:
            return w
        time.sleep(poll)
    raise TimeoutError(f"VRoid Studio window did not appear within {timeout}s")


def launch_and_wait(timeout: float = 240.0) -> Window:
    w = find_window()
    if w is not None:
        return w
    launch()
    return wait_for_window(timeout)


def focus(win: Window | None = None) -> Window:
    win = win or find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(win.pid)
    if app is not None:
        try:
            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        except Exception:
            pass
        time.sleep(0.35)
    if not is_vroid_focused():
        subprocess.run(
            ["osascript", "-e", f'tell application id "{BUNDLE_ID}" to activate'],
            capture_output=True,
        )
        time.sleep(0.35)
    return find_window() or win


def fullscreen(win: Window | None = None) -> Window:
    """No native fullscreen: VRoid's window is already a stable size.

    Kept for API parity with the original driver so callers can keep calling
    `W.fullscreen(win)`.
    """
    return focus(win)


def prepare(timeout: float = 240.0) -> tuple[Window, int]:
    """Launch/focus VRoid and return (window, previous_workspace)."""
    win = launch_and_wait(timeout)
    win = focus(win)
    assert_vroid_focused()
    return win, WORKSPACE


# --- workspace / desktop helpers (no-ops on macOS) --------------------------

def active_workspace() -> int:
    return WORKSPACE


def park(win: Window, workspace: int = WORKSPACE) -> None:
    return None


def enter(workspace: int = WORKSPACE) -> int:
    return WORKSPACE


def leave(prev: int) -> None:
    return None


def dismiss_screensaver() -> bool:
    return False


def notify(msg: str, ms: int = 3000, color: str = "rgb(88aaff)") -> None:
    return None
