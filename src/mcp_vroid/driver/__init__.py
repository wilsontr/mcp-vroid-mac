"""GUI-automation driver for VRoid Studio.

The loop is: capture -> locate (tesseract OCR / cv2 colour matching) -> act
(pointer + keyboard) -> capture again.

The platform layer is selected in `backend.py`:

* macOS: `window_mac.py` (CGWindowList/NSRunningApplication),
  `capture_mac.py` (`screencapture`), `input_mac.py` (Quartz CGEvent).
* Linux: `window.py` (Hyprland), `capture.py` (`grim`), `input.py` (wlroots
  virtual pointer + XTEST), the upstream implementation.

`locate.py` and `actions.py` are shared by both.
"""
from .paths import CAPTURES, OUT  # noqa: F401
