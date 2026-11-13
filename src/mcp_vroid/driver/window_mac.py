"""Find / launch / focus the VRoid Studio window on macOS.

Replaces the Hyprland/`hyprctl` half of the original driver. A `Window` here
carries the same fields the rest of the driver expects: geometry in *screen
points* (top-left origin, the coordinate space CGEvent uses), plus the
CGWindowID used by `screencapture -l`.

There are no workspaces on macOS, so the workspace helpers are no-ops kept for
API compatibility with `server.py` / `actions.py`.

VRoid Studio for macOS is sandboxed. Its save panel shows up as a separate
VRoid-owned window titled "Save" (contents rendered by the "Open and Save
Panel Service" process). Windows of either owner count as VRoid's for focus
and occlusion checks; see `panel_window()` for finding the panel.
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
# Out-of-process NSSavePanel/NSOpenPanel host used by sandboxed apps.
PANEL_OWNERS = ("Open and Save Panel Service",)
APP_PATH = "/Applications/VRoidStudio.app"
MIN_SIZE = 200
WORKSPACE = 0

FOCUS_HINT = (
    "Could not bring VRoid Studio to the front. Click its window once by hand, "
    "or allow the app hosting this server to control VRoid Studio in System "
    "Settings > Privacy & Security > Automation (used by the osascript "
    "fallback), then retry."
)


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


# --- running app / focus ----------------------------------------------------

def running_app():
    """The running VRoid Studio NSRunningApplication, or None."""
    try:
        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
        return apps[0] if apps else None
    except Exception:
        return None


def _frontmost_pid() -> int | None:
    """PID of the app that currently has keyboard focus.

    Asks the Accessibility API first: it is answered live by the WindowServer,
    whereas `NSWorkspace.frontmostApplication` is only refreshed by
    notifications on the main run loop and can be stale in a server process
    that never runs one.
    """
    try:
        import ApplicationServices as AS

        if AS.AXIsProcessTrusted():
            sys_el = AS.AXUIElementCreateSystemWide()
            err, app = AS.AXUIElementCopyAttributeValue(
                sys_el, "AXFocusedApplication", None)
            if err == 0 and app is not None:
                err, pid = AS.AXUIElementGetPid(app, None)
                if err == 0 and pid:
                    return int(pid)
    except Exception:
        pass
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app is not None else None
    except Exception:
        return None


def _app_name(pid: int | None) -> str | None:
    if not pid:
        return None
    try:
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        return str(app.localizedName()) if app is not None else None
    except Exception:
        return None


def _is_vroid_pid(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        if (app.bundleIdentifier() or "") == BUNDLE_ID:
            return True
        return (app.localizedName() or "") in OWNER_NAMES + PANEL_OWNERS
    except Exception:
        return False


def is_vroid_focused() -> bool:
    return _is_vroid_pid(_frontmost_pid())


def assert_vroid_focused() -> None:
    pid = _frontmost_pid()
    if not _is_vroid_pid(pid):
        raise RuntimeError(
            "refusing to act: the focused application is not VRoid Studio "
            f"(frontmost={_app_name(pid)!r}). Call vroid_launch, then retry."
        )


# --- window list ------------------------------------------------------------

def _windows(onscreen_only: bool = True) -> list[dict]:
    opts = (Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements) if onscreen_only \
        else Quartz.kCGWindowListOptionAll
    return list(Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or [])


def _bounds(w: dict) -> tuple[int, int, int, int]:
    b = w.get("kCGWindowBounds") or {}
    return (int(b.get("X", 0)), int(b.get("Y", 0)),
            int(b.get("Width", 0)), int(b.get("Height", 0)))


def find_window() -> Window | None:
    """Return the largest on-screen VRoid Studio window, or None.

    Minimised windows and windows on another Space are ignored: they cannot be
    captured or clicked, so treating them as "the window" only produces
    garbage screenshots and misdirected input.
    """
    best: Window | None = None
    focused = None
    for w in _windows(onscreen_only=True):
        owner = str(w.get("kCGWindowOwnerName") or "")
        if owner not in OWNER_NAMES:
            continue
        if int(w.get("kCGWindowLayer") or 0) != 0:
            continue
        x, y, ww, hh = _bounds(w)
        if ww < MIN_SIZE or hh < MIN_SIZE:
            continue
        if focused is None:
            focused = is_vroid_focused()
        cand = Window(
            address=str(w.get("kCGWindowNumber")),
            cls=owner,
            title=str(w.get("kCGWindowName") or ""),
            x=x, y=y, w=ww, h=hh,
            focused=focused,
            pid=int(w.get("kCGWindowOwnerPID") or 0),
        )
        if best is None or cand.w * cand.h > best.w * best.h:
            best = cand
    return best


def panel_window() -> dict | None:
    """The visible save/open panel, if one is up.

    In VRoid 2.16 the panel is a separate VRoid-owned window titled "Save"
    (its contents are rendered by the panel service, but the window belongs
    to VRoid). Match any visible VRoid or panel-service window other than the
    main editor window. Returns {"x","y","w","h","owner","id","title"} in
    screen points, or None.
    """
    main = find_window()
    main_id = main.window_id if main is not None else None
    best = None
    for w in _windows(onscreen_only=True):
        owner = str(w.get("kCGWindowOwnerName") or "")
        if owner not in OWNER_NAMES + PANEL_OWNERS:
            continue
        if w.get("kCGWindowNumber") == main_id:
            continue
        if int(w.get("kCGWindowLayer") or 0) != 0:
            continue
        if float(w.get("kCGWindowAlpha") or 0) <= 0:
            continue
        x, y, ww, hh = _bounds(w)
        if ww < MIN_SIZE or hh < 100:
            continue
        if best is None or ww * hh > best["w"] * best["h"]:
            best = {"x": x, "y": y, "w": ww, "h": hh, "owner": owner,
                    "title": str(w.get("kCGWindowName") or ""),
                    "id": w.get("kCGWindowNumber")}
    return best


def occluder_at(x: float, y: float) -> dict | None:
    """What would actually receive a click at screen point (x, y).

    Returns None when the topmost window there belongs to VRoid (or its save
    panel service), else {"owner", "title", "layer"} of the window in the way.
    `screencapture -l` shows VRoid even when something covers it, so without
    this check a click "on" a visible widget can land in another app.
    """
    for w in _windows(onscreen_only=True):           # front-to-back order
        if int(w.get("kCGWindowLayer") or 0) < 0:
            continue
        if float(w.get("kCGWindowAlpha") or 0) <= 0:
            continue
        owner = str(w.get("kCGWindowOwnerName") or "")
        if owner == "Window Server":
            continue
        wx, wy, ww, hh = _bounds(w)
        if not (wx <= x < wx + ww and wy <= y < wy + hh):
            continue
        if owner in OWNER_NAMES + PANEL_OWNERS:
            return None
        return {"owner": owner, "title": str(w.get("kCGWindowName") or ""),
                "layer": int(w.get("kCGWindowLayer") or 0)}
    return {"owner": None, "title": "", "layer": None}  # nothing of VRoid's there


# --- lifecycle --------------------------------------------------------------

def launch() -> None:
    """Open (or re-open/unhide) VRoid Studio by bundle id, falling back to its path."""
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
        if w is not None:
            return w
        time.sleep(poll)
    if running_app() is not None:
        raise TimeoutError(
            f"VRoid Studio is running but has no visible window after {timeout}s "
            "(minimised, hidden, or on another Space?). Bring it to the "
            "current desktop and retry.")
    raise TimeoutError(f"VRoid Studio window did not appear within {timeout}s")


def launch_and_wait(timeout: float = 240.0) -> Window:
    w = find_window()
    if w is not None:
        return w
    launch()            # also un-hides / re-opens a running but hidden app
    return wait_for_window(timeout)


def quit_app(timeout: float = 15.0, force: bool = True) -> bool:
    """Quit VRoid Studio; force-terminate if it is still up after `timeout`.

    A polite quit can stall on an unsaved-changes prompt, so `force=True`
    matches the upstream `pkill` behaviour (unsaved work is lost). Returns
    True once the app is gone.
    """
    app = running_app()
    if app is None:
        return True
    try:
        app.terminate()
    except Exception:
        pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if running_app() is None:
            return True
        time.sleep(0.5)
    if force:
        app = running_app()
        if app is not None:
            try:
                app.forceTerminate()
            except Exception:
                pass
        deadline = time.time() + 10
        while time.time() < deadline:
            if running_app() is None:
                return True
            time.sleep(0.5)
    return running_app() is None


def focus(win: Window | None = None) -> Window:
    win = win or find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(win.pid)
    if app is not None:
        try:
            app.unhide()
            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        except Exception:
            pass
        time.sleep(0.35)
    if not is_vroid_focused():
        # macOS 14+ cooperative activation can ignore the request above from a
        # background process; AppleScript still works but needs Automation.
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
    if not is_vroid_focused():
        raise RuntimeError(FOCUS_HINT)
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
