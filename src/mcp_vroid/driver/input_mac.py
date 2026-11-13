"""Pointer + keyboard injection through macOS Quartz Event Services.

Replaces the Wayland virtual pointer / XTEST half of the original driver.

* Mouse: `CGEventCreateMouseEvent` + `CGEventPost(kCGHIDEventTap, ...)`, so
  hover states and drags behave as they do for a human.
* Keyboard: `CGEventCreateKeyboardEvent` with either a keycode (for shortcuts)
  or a Unicode string (for typing arbitrary text).

Coordinates are global screen points (top-left origin), the same space as
`CGWindowList` bounds, so window-relative coordinates map with a simple
translation.

Both halves need the **Accessibility** permission for the process that hosts
this server; without it macOS silently drops the events.
"""
from __future__ import annotations

import time

import ApplicationServices as AS
import Quartz

from . import window_mac as W

BUTTONS = {
    "left": "left", "right": "right", "middle": "middle",
    1: "left", 2: "middle", 3: "right",
}

_SAFE = True  # module-level guard: verify VRoid focus before every action

# --- keycodes (US layout; shortcuts only) -----------------------------------

_KEYCODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12,
    "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18,
    "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D, "]": 0x1E,
    "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23, "return": 0x24,
    "enter": 0x24, "l": 0x25, "j": 0x26, "'": 0x27, "k": 0x28, ";": 0x29,
    "\\": 0x2A, ",": 0x2B, "/": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F,
    "tab": 0x30, "space": 0x31, "`": 0x32, "delete": 0x33, "backspace": 0x33,
    "escape": 0x35, "esc": 0x35, "cmd": 0x37, "command": 0x37, "shift": 0x38,
    "capslock": 0x39, "alt": 0x3A, "option": 0x3A, "opt": 0x3A,
    "ctrl": 0x3B, "control": 0x3B, "arrowleft": 0x7B, "left": 0x7B,
    "arrowright": 0x7C, "right": 0x7C, "arrowdown": 0x7D, "down": 0x7D,
    "arrowup": 0x7E, "up": 0x7E, "home": 0x73, "end": 0x77,
    "pageup": 0x74, "pagedown": 0x79, "f1": 0x7A, "f2": 0x78,
}

_MOD_FLAGS = {
    "cmd": Quartz.kCGEventFlagMaskCommand,
    "command": Quartz.kCGEventFlagMaskCommand,
    "ctrl": Quartz.kCGEventFlagMaskCommand,      # VRoid's macOS shortcuts are ⌘
    "control": Quartz.kCGEventFlagMaskCommand,
    "shift": Quartz.kCGEventFlagMaskShift,
    "alt": Quartz.kCGEventFlagMaskAlternate,
    "option": Quartz.kCGEventFlagMaskAlternate,
    "opt": Quartz.kCGEventFlagMaskAlternate,
}

PERMISSION_HINT = (
    "Accessibility permission is required to move the mouse and type. Grant it "
    "to this process (your terminal / MCP client) in System Settings > Privacy "
    "& Security > Accessibility, then restart it."
)


def accessibility_ok() -> bool:
    try:
        return bool(AS.AXIsProcessTrusted())
    except Exception:
        return False


def set_safety(on: bool) -> None:
    global _SAFE
    _SAFE = on


def _guard() -> None:
    if not accessibility_ok():
        raise RuntimeError(PERMISSION_HINT)
    if not _SAFE:
        return
    if not W.is_vroid_focused():
        W.focus()
    W.assert_vroid_focused()


# --- geometry ---------------------------------------------------------------

def _cursor() -> tuple[float, float]:
    try:
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return float(loc.x), float(loc.y)
    except Exception:
        return 0.0, 0.0


def _resolve(x: float, y: float, space: str, shot=None) -> tuple[float, float]:
    if space == "layout":
        return x, y
    if space == "image":
        if shot is None:
            raise ValueError("space='image' needs shot=")
        return shot.to_layout(x, y)
    win = W.find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    return win.to_layout(x, y)


def _post(ev) -> None:
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _move_to(x: float, y: float) -> None:
    _post(Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventMouseMoved, (x, y), Quartz.kCGMouseButtonLeft))


def _glide(cx: float, cy: float, tx: float, ty: float, steps: int = 3,
           pause: float = 0.012) -> None:
    for i in range(1, steps + 1):
        t = i / steps
        _move_to(cx + (tx - cx) * t, cy + (ty - cy) * t)
        time.sleep(pause)


def _button_events(button: str):
    if button == "right":
        return Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight
    if button == "middle":
        return Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp, Quartz.kCGMouseButtonCenter
    return Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft


# --- pointer ----------------------------------------------------------------

def move(x: float, y: float, space: str = "window", shot=None) -> None:
    _guard()
    sx, sy = _resolve(x, y, space, shot)
    _move_to(sx, sy)


def click(x: float, y: float, button: str = "left", space: str = "window",
          shot=None, settle: float = 0.35, moves: int = 3) -> None:
    """Move (in a few steps, so hover states fire) then click."""
    _guard()
    sx, sy = _resolve(x, y, space, shot)
    cx, cy = _cursor()
    _glide(cx, cy, sx, sy, moves)
    time.sleep(0.06)
    b = BUTTONS.get(button, "left")
    down_t, up_t, btn = _button_events(b)
    _post(Quartz.CGEventCreateMouseEvent(None, down_t, (sx, sy), btn))
    time.sleep(0.05)
    _post(Quartz.CGEventCreateMouseEvent(None, up_t, (sx, sy), btn))
    time.sleep(settle)


def double_click(x: float, y: float, **kw) -> None:
    click(x, y, **kw)
    time.sleep(0.05)
    click(x, y, settle=kw.get("settle", 0.35))


def drag(x1: float, y1: float, x2: float, y2: float, button: str = "left",
         space: str = "window", shot=None, steps: int = 24,
         settle: float = 0.4) -> None:
    """Press at (x1,y1), glide to (x2,y2), release. Used for sliders."""
    _guard()
    ax, ay = _resolve(x1, y1, space, shot)
    bx, by = _resolve(x2, y2, space, shot)
    b = BUTTONS.get(button, "left")
    down_t, up_t, btn = _button_events(b)
    drag_t = Quartz.kCGEventLeftMouseDragged
    if b == "right":
        drag_t = Quartz.kCGEventRightMouseDragged
    elif b == "middle":
        drag_t = Quartz.kCGEventOtherMouseDragged
    _move_to(ax, ay)
    time.sleep(0.12)
    _post(Quartz.CGEventCreateMouseEvent(None, down_t, (ax, ay), btn))
    time.sleep(0.12)
    for i in range(1, steps + 1):
        t = i / steps
        _post(Quartz.CGEventCreateMouseEvent(
            None, drag_t, (ax + (bx - ax) * t, ay + (by - ay) * t), btn))
        time.sleep(0.016)
    time.sleep(0.15)
    _post(Quartz.CGEventCreateMouseEvent(None, up_t, (bx, by), btn))
    time.sleep(settle)


def scroll(ticks: int, x: float | None = None, y: float | None = None,
           space: str = "window", shot=None, settle: float = 0.3,
           backend: str = "quartz") -> None:
    """Wheel scroll. Negative = up/away, positive = down (same as the original)."""
    _guard()
    if x is not None and y is not None:
        move(x, y, space, shot)
        time.sleep(0.2)
    # CGEvent wheel: positive scrolls up, so invert to keep the original sign.
    value = -int(ticks)
    ev = Quartz.CGEventCreateScrollWheelEvent(
        None, Quartz.kCGScrollEventUnitLine, 1, value)
    _post(ev)
    time.sleep(settle)


# --- keyboard ---------------------------------------------------------------

def _type_char(ch: str) -> None:
    ok = False
    try:
        down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
        Quartz.CGEventKeyboardSetUnicodeString(down, len(ch), ch)
        _post(down)
        up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
        Quartz.CGEventKeyboardSetUnicodeString(up, len(ch), ch)
        _post(up)
        ok = True
    except Exception:
        ok = False
    if not ok:
        code = _KEYCODES.get(ch.lower())
        if code is None:
            raise RuntimeError(f"cannot type character {ch!r}")
        _keycode(code, shift=ch.isupper())


def _keycode(code: int, shift: bool = False) -> None:
    flags = Quartz.kCGEventFlagMaskShift if shift else 0
    down = Quartz.CGEventCreateKeyboardEvent(None, code, True)
    up = Quartz.CGEventCreateKeyboardEvent(None, code, False)
    if flags:
        Quartz.CGEventSetFlags(down, flags)
        Quartz.CGEventSetFlags(up, flags)
    _post(down)
    time.sleep(0.02)
    _post(up)


def type_text(text: str, clear_first: bool = False,
              delay_ms: float = 8.0) -> None:
    _guard()
    if clear_first:
        key("cmd+a")
        time.sleep(0.1)
    for ch in text:
        _type_char(ch)
        time.sleep(delay_ms / 1000.0)
    time.sleep(0.1)


def clear_field() -> None:
    """Select-all then delete in the focused text field."""
    _guard()
    key("cmd+a")
    time.sleep(0.05)
    _keycode(_KEYCODES["backspace"])
    time.sleep(0.05)


def hotkey(combo: str, times: int = 1) -> None:
    key(combo, times)


def hscroll(ticks: int, x: float | None = None, y: float | None = None,
            space: str = "window", shot=None, settle: float = 0.3) -> None:
    """Horizontal wheel. Negative = left, positive = right."""
    _guard()
    if x is not None and y is not None:
        move(x, y, space, shot)
        time.sleep(0.2)
    value = int(-ticks * 10)
    ev = Quartz.CGEventCreateScrollWheelEvent(
        None, Quartz.kCGScrollEventUnitPixel, 2, 0, value)
    _post(ev)
    time.sleep(settle)


def key(combo: str, times: int = 1) -> None:
    """Press a shortcut, e.g. 'Return', 'Escape', 'cmd+s', 'shift+cmd+s'.

    'ctrl+…' is translated to Command, because VRoid's macOS shortcuts use ⌘.
    """
    _guard()
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty key combo")
    name = parts[-1]
    mods = parts[:-1]
    shift = "shift" in mods or (len(name) == 1 and name.isupper())
    if len(name) == 1:
        code = _KEYCODES.get(name.lower())
        if code is None:
            raise ValueError(f"unknown key {name!r}")
    else:
        code = _KEYCODES.get(name)
        if code is None:
            raise ValueError(f"unknown key {name!r}")
    flags = Quartz.kCGEventFlagMaskShift if shift else 0
    for m in mods:
        flags |= _MOD_FLAGS.get(m, 0)
    for _ in range(max(1, int(times))):
        down = Quartz.CGEventCreateKeyboardEvent(None, code, True)
        up = Quartz.CGEventCreateKeyboardEvent(None, code, False)
        if flags:
            Quartz.CGEventSetFlags(down, flags)
            Quartz.CGEventSetFlags(up, flags)
        _post(down)
        time.sleep(0.03)
        _post(up)
        time.sleep(0.05)
