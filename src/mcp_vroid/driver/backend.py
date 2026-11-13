"""Platform backend selection.

`actions`, `server` and `cli` import the desktop layer from here, so the VRoid
flows are written once against a platform-neutral surface:

    from .backend import window as W, capture as C, input as I

Two implementations ship:

* Linux (upstream): Hyprland/`hyprctl` window management, `grim` capture, a
  wlroots virtual pointer plus XTEST input — `window.py`, `capture.py`,
  `input.py`.
* macOS (this port): `CGWindowList`/`NSRunningApplication`, `screencapture`,
  Quartz `CGEvent` — `window_mac.py`, `capture_mac.py`, `input_mac.py`.

Adding a platform means adding one branch here and three modules; the flows,
OCR locating and the MCP server stay untouched.
"""
from __future__ import annotations

import sys

if sys.platform == "darwin":
    from . import capture_mac as capture
    from . import input_mac as input
    from . import window_mac as window
else:
    from . import capture
    from . import input
    from . import window

__all__ = ["capture", "input", "window"]
