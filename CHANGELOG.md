# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [semantic versioning](https://semver.org/).

## [Unreleased] — macOS port (wilsontr/mcp-vroid-mac)

### Added

* macOS backend (`window_mac.py`, `capture_mac.py`, `input_mac.py`) behind
  `driver/backend.py`; the Linux backend is unchanged.
* `tests/test_backend_parity.py`: checks that the macOS backend accepts every
  call signature of the Linux one, plus key-name parsing on macOS.

### Fixed

* `vroid_key` (and the CLI `key` command) raised `TypeError` on macOS: the
  macOS `key()` now takes the Linux signature `key(name, mods=None, times=1)`.
* Double-click sends a real macOS double-click (click state 1 then 2) at the
  same point; the second click previously lost its coordinate space.
* Shortcuts hold their modifiers as real key presses; `S` implies Shift;
  `Delete` is forward-delete (`BackSpace` is ⌫); F3–F12 and `Control_L` (real
  Control) added.
* Clicks, drags and scrolls refuse when another window covers the target
  point, instead of landing in that window.
* Focus is read live through the Accessibility API and re-checked between
  typed characters.
* Minimised / off-Space windows no longer count as the VRoid window.
* `vroid_launch(restart=true)` force-quits if a polite quit stalls.
* The macOS save panel (a separate VRoid-owned "Save" window) is detected,
  captured by its window id, and driven by keyboard. The file name is typed
  without its extension, because the panel adds `.vroid`/`.vrm` itself (typing it
  produced `name.vroid.vroid`). A "Replace?" prompt is answered by clicking
  Replace, which is located by mirroring the alert's Cancel button. Verified
  live on VRoid 2.16.0.
* Save As works when a parameter text box still has focus: VRoid ignores the
  shortcut then, so it clicks an empty toolbar strip and retries.
* `whole_screen` captures the display VRoid is on, not always the main one.
* Capture numbering past 999 no longer wraps and overwrites old captures.

## [0.1.0] — 2026-08-24

First public release.

### Added

* **MCP server** (`mcp-vroid`, stdio) exposing 18 tools over VRoid Studio:
  * lifecycle — `vroid_launch`, `vroid_status`, `vroid_release`
  * seeing — `vroid_screenshot`, `vroid_find_text`, `vroid_find_button`,
    `vroid_current_screen`
  * raw input — `vroid_click`, `vroid_drag`, `vroid_scroll`, `vroid_type`,
    `vroid_key`
  * flows — `vroid_new_character`, `vroid_open_tab`, `vroid_set_slider`,
    `vroid_set_color`, `vroid_export_vrm`, `vroid_save_project`
* **Driver engine** (`mcp_vroid.driver`): `grim` capture, tesseract OCR and
  OpenCV colour matching for locating, `hyprctl` for window management, and
  input through a `zwlr_virtual_pointer_unstable_v1` helper (pointer) plus
  X11 XTEST (keyboard and wheel).
* **`native/vpointer`** — a small C client for the Wayland virtual-pointer
  protocol, built by `native/build.sh`. Moves the real compositor cursor and
  needs no `/dev/uinput` access.
* **Session-environment recovery** so the server works when an MCP client
  launches it with a sanitised environment.
* **Focus guard** — every acting tool refuses to run unless VRoid Studio is
  the focused window; the idle screensaver is dismissed rather than typed
  into.
* **`vroid-driver` CLI** for driving the same engine from a shell.
* `scripts/smoke_test.py` — starts the server, lists tools, calls the
  read-only ones; never sends input.
* Documentation: README, [`docs/ui-map.md`](docs/ui-map.md).

### Known limitations

Calibrated against VRoid Studio 2.14.0 (English) at 2560×1440 / scale 1.25 on
Hyprland. See the README's *Limitations and brittleness* section.

[0.1.0]: https://github.com/nhodges/mcp-vroid/releases/tag/v0.1.0
