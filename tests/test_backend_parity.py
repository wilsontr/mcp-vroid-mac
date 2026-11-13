"""The macOS backend must accept every call the shared code makes.

`actions.py`, `server.py` and `cli.py` are written once against the Linux
signatures, so a macOS function that drops a parameter only fails at runtime
(this is how `vroid_key` came to raise TypeError). These checks parse the
sources with `ast`, so they run on any platform without Quartz or Xlib.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

DRIVER = Path(__file__).resolve().parent.parent / "src" / "mcp_vroid" / "driver"
PAIRS = [("input.py", "input_mac.py"), ("capture.py", "capture_mac.py"),
         ("window.py", "window_mac.py")]


def _funcs(path: Path) -> dict[str, ast.arguments]:
    tree = ast.parse(path.read_text())
    return {n.name: n.args for n in tree.body
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}


def _params(args: ast.arguments) -> tuple[list[str], set[str], bool]:
    positional = [a.arg for a in args.posonlyargs + args.args]
    names = set(positional) | {a.arg for a in args.kwonlyargs}
    return positional, names, args.kwarg is not None


@pytest.mark.parametrize("linux,mac", PAIRS)
def test_mac_backend_accepts_linux_signatures(linux, mac):
    lin, mac_f = _funcs(DRIVER / linux), _funcs(DRIVER / mac)
    # Linux-only helpers that the shared code does not call.
    linux_only = {"hyprctl", "hyprctl_json", "dispatch", "x_focus_ok"}
    problems = []
    for name, largs in lin.items():
        if name in linux_only:
            continue
        if name not in mac_f:
            problems.append(f"{mac}: missing {name}()")
            continue
        lpos, lnames, _ = _params(largs)
        mpos, mnames, mkw = _params(mac_f[name])
        if mpos[: len(lpos)] != lpos:
            problems.append(f"{name}: positional {lpos} vs {mpos}")
        missing = lnames - mnames
        if missing and not mkw:
            problems.append(f"{name}: macOS lacks {sorted(missing)}")
    assert not problems, "\n".join(problems)


@pytest.mark.skipif(sys.platform != "darwin", reason="needs Quartz")
def test_mac_key_parsing():
    sys.path.insert(0, str(DRIVER.parent.parent))
    from mcp_vroid.driver import input_mac as I

    cmd, shift, ctrl = I._CMD, I._SHIFT, I._CTRL
    assert I._parse("s", ["ctrl"]) == (0x01, [cmd])
    assert I._parse("ctrl+shift+s", None) == (0x01, [cmd, shift])
    assert I._parse("S", None) == (0x01, [shift])
    assert I._parse("Return", None) == (0x24, [])
    assert I._parse("BackSpace", None) == (0x33, [])
    assert I._parse("Delete", None) == (0x75, [])
    assert I._parse("Control_L+c", None) == (0x08, [ctrl])
    assert I._parse("F5", None) == (0x60, [])
    with pytest.raises(ValueError):
        I._parse("hyper+s", None)
    with pytest.raises(ValueError):
        I._parse("NoSuchKey", None)
