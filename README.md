# mcp-vroid-mac

Drive the **native macOS VRoid Studio** from any MCP client: screenshot the
window, locate widgets with OCR, and inject real pointer/keyboard events with
Quartz. No Wine, no plugins, no Linux.

This is a **downstream macOS port** of
[mcp-vroid](https://github.com/nhodges/mcp-vroid) by Nuri Hodges (MIT). The
VRoid-specific logic — OCR locating, the UI map, the parameter/colour/export
flows — is reused; the platform layer is selected behind
[`driver/backend.py`](src/mcp_vroid/driver/backend.py). The Linux/Hyprland
implementation is kept in-tree and documented in
[`README.upstream.md`](README.upstream.md).

| Piece | Upstream (Linux) | This port (macOS) |
| --- | --- | --- |
| window | `hyprctl` | `CGWindowListCopyWindowInfo` + `NSRunningApplication` |
| capture | `grim` | `screencapture -l <CGWindowID>` |
| input | wlroots virtual pointer + XTEST | Quartz `CGEvent` |
| keyboard | XTEST keysyms | `CGEventCreateKeyboardEvent` / Unicode events |
| OCR | tesseract | tesseract (unchanged) |
| workspaces | Hyprland workspace 9 | none (no-ops) |

## Requirements

- macOS with the native VRoid Studio app (`/Applications/VRoidStudio.app`,
  bundle id `net.pixiv.vroid.macosx`).
- Python 3.11+ and [uv](https://docs.astral.sh/uv/).
- `tesseract` (`brew install tesseract`).
- **Two macOS permissions** for whichever app hosts this MCP server (Terminal,
  iTerm, Claude Desktop, …):
  1. **Screen Recording** — System Settings → Privacy & Security →
     Screen & System Audio Recording.
  2. **Accessibility** — System Settings → Privacy & Security → Accessibility.
  Restart the host app after granting them. `vroid_status` reports both.

## Install

```bash
git clone <this directory> ~/mcp-vroid-mac
cd ~/mcp-vroid-mac
uv sync
```

Register it with Claude Code:

```bash
claude mcp add --scope user vroid-mac -- \
  uv run --directory /path/to/mcp-vroid-mac mcp-vroid-mac
```

Register it with **pi** (writes `~/.pi/agent/mcp.json`):

```bash
pi mcp add vroid -- uv run --directory /path/to/mcp-vroid-mac mcp-vroid-mac
pi mcp list        # expect: vroid: connected, 18 tools
```

Register it with **DSH** by adding an insert row to
`~/.dsh/profiles/<profile>/cordis.patch.yml` (the profile in use — `desktop`
for the desktop app, which also serves the web GUI):

```yaml
- insert:
    - id: mcp-vroid
      name: "@deepseek-ai/dsh-mcp-client"
      config:
        serverName: vroid
        transport: stdio
        command: /Users/you/.local/bin/uv
        args:
          - run
          - --directory
          - /path/to/mcp-vroid-mac
          - mcp-vroid-mac
        cwd: /path/to/mcp-vroid-mac
        env:
          HOME: /Users/you
          PATH: /Users/you/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
```

Validate without restarting: `dsh --profile desktop --dump-config | grep -A12 mcp-vroid`
(a raw `- id: …` row at top level would be an *override* and logs
"patch: entry … not found"; MCP servers are new rows, so they must be inside
`insert:`). DSH's HMR picks it up live and the tools appear as
`mcp__vroid__vroid_*`.

…or with any client that takes an `mcpServers` block:

```json
{
  "mcpServers": {
    "vroid": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-vroid-mac", "mcp-vroid-mac"]
    }
  }
}
```

Then call `vroid_status` first: it tells you whether VRoid is running, whether
it is focused, and whether both permissions are in place.

## Tools

The same tool set as the original server, 18 tools in four groups.

**Lifecycle** — `vroid_launch` (opens/brings the app forward), `vroid_status`
(window, focus, permissions, helpers), `vroid_release` (no-op on macOS).

**Seeing** — `vroid_screenshot`, `vroid_find_text`, `vroid_find_button`,
`vroid_current_screen`. Everything works in **image pixels of the window
capture**, so coordinates from `find_*` go straight into `click`.

**Acting (raw)** — `vroid_click`, `vroid_drag`, `vroid_scroll`, `vroid_type`,
`vroid_key`. `ctrl+…` shortcuts are translated to Command (⌘), because VRoid's
macOS shortcuts use ⌘.

**Acting (flows)** — `vroid_new_character`, `vroid_open_tab`,
`vroid_set_slider`, `vroid_set_color`, `vroid_export_vrm`,
`vroid_save_project`.

## How it works

```
screencapture -l <window> ──► PNG ──► tesseract / cv2 ──► (x,y) ──► CGEvent
      ▲                                                              │
      └────────────────────  screenshot again  ◄────────────────────┘
```

The loop is **see → locate → act → see again**:

1. `vroid_launch()` → `vroid_screenshot()` (the image goes to the model)
2. `vroid_find_text("Export")` / `vroid_find_button()` for coordinates
3. `vroid_click(x, y)` with coordinates from a **fresh** capture
4. `vroid_screenshot()` again to confirm what happened

Rules of thumb (inherited from the original, learned the hard way): read the
whole frame rather than a crop so modals are not missed; judge change by a UI
strip rather than the dithering 3D viewport; prefer typing exact values into
numeric boxes over dragging sliders; a grey “primary” button means a required
field is still empty.

## Calibration and caveats

The VRoid-specific anchors and OCR needles in `driver/actions.py` were
calibrated on **VRoid Studio 2.14.0**, English UI, at 2560×1440. The native
macOS app here is **2.16.0**, so some flows may need re-measuring:

- `vroid_new_character`, `vroid_open_tab`, `vroid_set_slider`,
  `vroid_set_color` use fractional anchors of the window, which survive
  resolution changes but not a UI reflow.
- `vroid_export_vrm` was written against Wine's file dialog. On macOS it now
  drives the native save panel (⌘⇧G → folder → filename → Return), but this
  path is the least tested part of the port.

The raw tools (`screenshot`, `find_text`, `find_button`, `click`, `type`,
`key`, `drag`, `scroll`) are the reliable foundation — the model can always
fall back to them, look at the screen, and drive the app step by step.

## Security

This server injects real mouse/keyboard events into your live desktop session
and takes screenshots of it. Run it attended, on a session you are watching.
`vroid_launch(restart=true)` quits VRoid Studio and loses unsaved work.
Captures are written unencrypted to
`~/Library/Application Support/mcp-vroid/captures` (override with
`MCP_VROID_CAPTURES`).

## How this relates to upstream

The platform layer sits behind `driver/backend.py`:

```
driver/backend.py      picks the platform modules
driver/window_mac.py   CGWindowList + NSRunningApplication
driver/capture_mac.py  screencapture
driver/input_mac.py    Quartz CGEvent
driver/window.py       upstream Linux: Hyprland
driver/capture.py      upstream Linux: grim
driver/input.py        upstream Linux: virtual pointer + XTEST
driver/actions.py      shared VRoid flows
driver/locate.py       shared OCR / colour matching
server.py              shared MCP tools
```

So the macOS diff is additive: `native/`, the Linux modules and
`README.upstream.md` stay as upstream shipped them, and the tool flows are
shared.

To pull upstream changes:

```bash
git remote add upstream https://github.com/nhodges/mcp-vroid
git fetch upstream
git merge upstream/main      # conflicts should be confined to actions/server
```

If upstream merges its Windows backend seam (PRs #1/#2, which also introduce
`driver/backend.py`), this port can be rebased onto that seam nearly as-is.

## Licence

MIT, same as the original. Upstream is Copyright (c) 2026 Nuri Hodges; see
[`LICENSE`](LICENSE). VRoid Studio is a product of pixiv Inc.; this project is
unaffiliated and simply drives the app's UI.
