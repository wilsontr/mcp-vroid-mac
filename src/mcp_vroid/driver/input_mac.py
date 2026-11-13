"""Pointer + keyboard injection through macOS Quartz Event Services.

Replaces the Wayland virtual pointer / XTEST half of the original driver and
keeps its call signatures (`key(name, mods=None, times=1)`, `hotkey(combo)`,
`click(..., space=, shot=)`, ...) so `actions.py`, `server.py` and `cli.py`
work against either backend unchanged.

* Mouse: `CGEventCreateMouseEvent` + `CGEventPost(kCGHIDEventTap, ...)`, so
  hover states and drags behave as they do for a human. Before a click, drag
  or scroll the target point is checked against the on-screen window stack:
  `screencapture -l` shows VRoid even when another window covers it, so this
  refuses rather than clicking into whatever is on top.
* Keyboard: modifiers are pressed and released as real keys around the
  shortcut (not just flagged on the event), and typed text carries both a
  US-layout keycode, where one exists, and the Unicode string.

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

# --- keycodes (US ANSI layout) ----------------------------------------------

_KEYCODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12,
    "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18,
    "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D, "]": 0x1E,
    "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23, "l": 0x25,
    "j": 0x26, "'": 0x27, "k": 0x28, ";": 0x29, "\\": 0x2A, ",": 0x2B,
    "/": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F, "`": 0x32, " ": 0x31,
    # named keys (lower-cased X keysym names plus common aliases)
    "return": 0x24, "enter": 0x24, "kp_enter": 0x4C, "tab": 0x30,
    "space": 0x31, "backspace": 0x33, "escape": 0x35, "esc": 0x35,
    "delete": 0x75, "forwarddelete": 0x75, "del": 0x75,  # X `Delete` = forward delete
    "help": 0x72, "insert": 0x72,
    "home": 0x73, "end": 0x77, "pageup": 0x74, "prior": 0x74, "page_up": 0x74,
    "pagedown": 0x79, "next": 0x79, "page_down": 0x79,
    "left": 0x7B, "arrowleft": 0x7B, "right": 0x7C, "arrowright": 0x7C,
    "down": 0x7D, "arrowdown": 0x7D, "up": 0x7E, "arrowup": 0x7E,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
}

# Shifted US characters -> their unshifted key.
_SHIFTED = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
    "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]",
    "|": "\\", ":": ";", '"': "'", "<": ",", ">": ".", "?": "/", "~": "`",
}

# modifier name -> (flag, keycode of the physical key we press)
_CMD = (Quartz.kCGEventFlagMaskCommand, 0x37)
_SHIFT = (Quartz.kCGEventFlagMaskShift, 0x38)
_ALT = (Quartz.kCGEventFlagMaskAlternate, 0x3A)
_CTRL = (Quartz.kCGEventFlagMaskControl, 0x3B)
_MODS = {
    "cmd": _CMD, "command": _CMD, "super": _CMD, "super_l": _CMD, "meta": _CMD,
    # Upstream flows say ctrl+s / ctrl+shift+s; VRoid's macOS shortcuts use ⌘.
    "ctrl": _CMD, "control": _CMD,
    # The real Control key, by its X keysym name.
    "control_l": _CTRL, "control_r": _CTRL,
    "shift": _SHIFT, "shift_l": _SHIFT, "shift_r": _SHIFT,
    "alt": _ALT, "option": _ALT, "opt": _ALT, "alt_l": _ALT, "alt_r": _ALT,
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


def _check_target(x: float, y: float) -> None:
    """Refuse to act at a screen point VRoid does not own on screen."""
    if not _SAFE:
        return
    blocker = W.occluder_at(x, y)
    if blocker is None:
        return
    who = blocker.get("owner")
    if who is None:
        raise RuntimeError(
            f"refusing to act at ({x:.0f}, {y:.0f}): no VRoid window is on "
            "screen at that point (outside the window, or the window moved). "
            "Take a fresh vroid_screenshot.")
    raise RuntimeError(
        f"refusing to act at ({x:.0f}, {y:.0f}): that point is covered by "
        f"{who!r} {blocker.get('title') or ''}".rstrip()
        + ". Move or close that window (or turn off its always-on-top), "
        "then retry.")


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


def _press(sx: float, sy: float, button: str, click_state: int = 1) -> None:
    down_t, up_t, btn = _button_events(button)
    for t in (down_t, up_t):
        ev = Quartz.CGEventCreateMouseEvent(None, t, (sx, sy), btn)
        Quartz.CGEventSetIntegerValueField(
            ev, Quartz.kCGMouseEventClickState, click_state)
        _post(ev)
        if t == down_t:
            time.sleep(0.05)


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
    _check_target(sx, sy)
    cx, cy = _cursor()
    _glide(cx, cy, sx, sy, moves)
    time.sleep(0.06)
    _press(sx, sy, BUTTONS.get(button, "left"))
    time.sleep(settle)


def double_click(x: float, y: float, button: str = "left", space: str = "window",
                 shot=None, settle: float = 0.35, moves: int = 3) -> None:
    """A real double-click: two presses at one point, click state 1 then 2.

    macOS recognises a double-click from the event's click-state field, not
    from timing, so two ordinary clicks are not enough.
    """
    _guard()
    sx, sy = _resolve(x, y, space, shot)
    _check_target(sx, sy)
    cx, cy = _cursor()
    _glide(cx, cy, sx, sy, moves)
    time.sleep(0.06)
    b = BUTTONS.get(button, "left")
    _press(sx, sy, b, click_state=1)
    time.sleep(0.06)
    _press(sx, sy, b, click_state=2)
    time.sleep(settle)


def drag(x1: float, y1: float, x2: float, y2: float, button: str = "left",
         space: str = "window", shot=None, steps: int = 24,
         settle: float = 0.4) -> None:
    """Press at (x1,y1), glide to (x2,y2), release. Used for sliders."""
    _guard()
    ax, ay = _resolve(x1, y1, space, shot)
    bx, by = _resolve(x2, y2, space, shot)
    _check_target(ax, ay)
    _check_target(bx, by)
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


def _scroll_target(x, y, space, shot) -> None:
    """Move to (x, y) if given; either way, the wheel lands under the cursor."""
    if x is not None and y is not None:
        sx, sy = _resolve(x, y, space, shot)
    else:
        sx, sy = _cursor()
    _check_target(sx, sy)
    if x is not None and y is not None:
        _move_to(sx, sy)
        time.sleep(0.2)


def scroll(ticks: int, x: float | None = None, y: float | None = None,
           space: str = "window", shot=None, settle: float = 0.3,
           backend: str = "quartz") -> None:
    """Wheel scroll. Negative = up/away, positive = down (same as the original)."""
    _guard()
    _scroll_target(x, y, space, shot)
    # CGEvent wheel: positive scrolls up, so invert to keep the original sign.
    ev = Quartz.CGEventCreateScrollWheelEvent(
        None, Quartz.kCGScrollEventUnitLine, 1, -int(ticks))
    _post(ev)
    time.sleep(settle)


def hscroll(ticks: int, x: float | None = None, y: float | None = None,
            space: str = "window", shot=None, settle: float = 0.3) -> None:
    """Horizontal wheel. Negative = left, positive = right."""
    _guard()
    _scroll_target(x, y, space, shot)
    ev = Quartz.CGEventCreateScrollWheelEvent(
        None, Quartz.kCGScrollEventUnitPixel, 2, 0, int(-ticks * 10))
    _post(ev)
    time.sleep(settle)


# --- keyboard ---------------------------------------------------------------

def _parse(name: str, mods: list[str] | None) -> tuple[int, list[tuple[int, int]]]:
    """'cmd+shift+s' (+ extra mods) -> (keycode, [(flag, modifier keycode)])."""
    raw = [p.strip() for p in name.split("+") if p.strip()] if name != "+" else ["+"]
    if not raw:
        raise ValueError("empty key combo")
    base = raw[-1]
    mod_names = [m.strip().lower() for m in (list(mods or []) + raw[:-1]) if m.strip()]
    chosen: list[tuple[int, int]] = []
    for m in mod_names:
        if m not in _MODS:
            raise ValueError(f"unknown modifier {m!r}")
        if _MODS[m] not in chosen:
            chosen.append(_MODS[m])
    need_shift = False
    if len(base) == 1:
        if base in _SHIFTED:
            base, need_shift = _SHIFTED[base], True
        elif base.isupper():
            need_shift = True
        code = _KEYCODES.get(base.lower())
    else:
        code = _KEYCODES.get(base.lower())
    if code is None:
        raise ValueError(f"unknown key {base!r}")
    if need_shift and _SHIFT not in chosen:
        chosen.append(_SHIFT)
    return code, chosen


def _tap(code: int, chosen: list[tuple[int, int]], text: str | None = None) -> None:
    """Hold the modifiers as real keys, tap `code`, release in reverse."""
    flags = 0
    for flag, mcode in chosen:
        flags |= flag
        ev = Quartz.CGEventCreateKeyboardEvent(None, mcode, True)
        Quartz.CGEventSetFlags(ev, flags)
        _post(ev)
        time.sleep(0.01)
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(ev, flags)
        if text is not None:
            Quartz.CGEventKeyboardSetUnicodeString(
                ev, len(text.encode("utf-16-le")) // 2, text)
        _post(ev)
        if down:
            time.sleep(0.03)
    for flag, mcode in reversed(chosen):
        flags &= ~flag
        ev = Quartz.CGEventCreateKeyboardEvent(None, mcode, False)
        Quartz.CGEventSetFlags(ev, flags)
        _post(ev)
        time.sleep(0.01)


def _type_char(ch: str) -> None:
    if ch == "\n":
        _tap(_KEYCODES["return"], [])
        return
    if ch == "\t":
        _tap(_KEYCODES["tab"], [])
        return
    base, shift = ch, False
    if ch in _SHIFTED:
        base, shift = _SHIFTED[ch], True
    elif len(ch) == 1 and ch.isascii() and ch.isupper():
        base, shift = ch.lower(), True
    code = _KEYCODES.get(base) if base.isascii() else None
    if code is None:
        # Non-US character: keycode 0 carrying the Unicode string. Cocoa text
        # fields use the string; apps that read only the keycode will not.
        _tap(0, [], text=ch)
    else:
        _tap(code, [_SHIFT] if shift else [], text=ch)


def type_text(text: str, delay_ms: float = 8.0) -> None:
    """Type a literal string into the focused widget.

    Focus is re-checked before every character so a mid-string app switch
    stops typing instead of spilling the rest into another application.
    """
    _guard()
    for i, ch in enumerate(text):
        if _SAFE and i and not W.is_vroid_focused():
            raise RuntimeError(
                f"focus left VRoid Studio after {i} of {len(text)} characters; "
                "stopped typing.")
        _type_char(ch)
        time.sleep(delay_ms / 1000.0)
    time.sleep(0.1)


def key(name: str, mods: list[str] | None = None, times: int = 1) -> None:
    """Press a key, optionally with modifiers.

    Same signature as the Linux backend: `key("s", mods=["ctrl"])`. `name`
    may also be a whole combo, e.g. 'Return', 'cmd+shift+g'.

    'ctrl'/'control' mean Command (⌘), because VRoid's macOS shortcuts use ⌘
    where the Windows build uses Ctrl; use 'Control_L' for the real Control
    key. 'Delete' is forward-delete (as in X); use 'BackSpace' for ⌫.
    """
    _guard()
    code, chosen = _parse(name, mods)
    for _ in range(max(1, int(times))):
        _tap(code, chosen)
        time.sleep(0.05)


def hotkey(combo: str, times: int = 1) -> None:
    """'ctrl+shift+s' -> modifier-held keypress."""
    key(combo, times=times)


def clear_field() -> None:
    """Select-all then delete in the focused text field."""
    key("a", mods=["cmd"])
    time.sleep(0.05)
    key("BackSpace")
    time.sleep(0.05)
