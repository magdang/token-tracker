# Development and verification

Use the repository launcher for user-facing commands and Arch's system Python
for tests. No test below requires real credentials; mocked account tests use the
local `tests/fixtures/fake_codex.py`. Demo and mock tests do not perform live OAuth
or verify a live provider account.

## Core checks

The full unit suite imports the optional overlay modules, so it needs
`python-gobject`, `gtk3`, and `gtk-layer-shell` in addition to Python:

```sh
mkdir -p /tmp/opencode
export PYTHONPYCACHEPREFIX=/tmp/opencode/pycache
export TMPDIR=/tmp/opencode
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m compileall -q token_tracker
```

Expected result: the unit suite reports `OK`; `compileall` is quiet on success.
The cache/output locations keep generated files out of the repository.

The bounded continuous-stream smoke test needs no credentials, display, or GTK
layer-shell. It takes about ten seconds and expects three labelled frames at
five-second intervals:

```sh
./tests/run-smoke.sh --waybar-stream
```

The Pango renderer needs PyGObject/Pango and pycairo (Arch package:
`python-cairo`, if needed). It writes light and dark sample images for a
single-account and a dense multi-account fixture below `/tmp/opencode/`:

```sh
/usr/bin/python3 tests/render_waybar_demo.py
```

The account-manager smoke uses GTK on the current display and a fake Codex
server. It neither opens real OAuth nor reads credentials:

```sh
/usr/bin/python3 tests/smoke_accounts.py
```

## Optional desktop tests

Run these only in an unlocked, attended Hyprland session. Synthetic overlay
testing still queries Hyprland layer geometry but does not move the real pointer:

```sh
./tests/run-smoke.sh --synthetic
```

It needs the overlay dependencies plus pycairo and writes only the rendered demo
panel to `/tmp/opencode/token-tracker-hover.png`.

The real-pointer overlay test additionally needs `wayland-scanner`, a C compiler,
Wayland client headers, and `grim`:

```sh
./tests/run-smoke.sh
```

It builds a helper below `/tmp/opencode`, moves and restores the pointer, and
saves only the cropped demo panel at the same hover PNG path. It exits 77 when
`hyprlock` is already active.

The installed-Waybar smoke additionally needs the Atspi GI typelib and
`tesseract`, plus the real-pointer dependencies. Supply a crop wholly inside the
tooltip that is already configured in the running Waybar:

```sh
./tests/run-smoke.sh --waybar-desktop --tooltip-region 'x,y WxH'
```

It writes `/tmp/opencode/token-tracker-waybar-real-hover.png`; add `--demo` only
when the installed module itself is running `waybar --demo`, in which case the
filename contains `demo`. The test checks the running desktop integration, not
provider credentials or live quota correctness.

Before publishing documentation or examples, also inspect tracked paths for
private identities, raw secrets, developer-specific absolute paths, and generated
files. Preserve executable bits on `bin/token-tracker`, `tests/run-smoke.sh`, and
`tests/fixtures/fake_codex.py`.
