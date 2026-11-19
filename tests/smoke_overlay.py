"""Opt-in Hyprland integration test. Moves and restores the real pointer.

Run: ./tests/run-smoke.sh [--synthetic]
Captures only the demo panel to /tmp/opencode/token-tracker-hover.png.
Synthetic mode exercises GTK events and widget rendering without moving the cursor.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from token_tracker.ui import Gdk, GLib, Overlay  # noqa: E402

SYNTHETIC = "--synthetic" in sys.argv
if not SYNTHETIC and subprocess.run(
    ["pgrep", "-x", "hyprlock"], stdout=subprocess.DEVNULL
).returncode == 0:
    print("SKIP: hyprlock is active. Unlock your desktop before running the real-pointer smoke test.")
    sys.exit(77)


def hypr(*args):
    return subprocess.check_output(["hyprctl", *args], text=True)


def move(x, y):
    hypr("dispatch", f"hl.dsp.cursor.move({{ x = {int(x)}, y = {int(y)} }})")
    # Hyprland's cursor warp alone does not dispatch pointer motion to clients.
    subprocess.run(["/tmp/opencode/token-tracker-pointer"], check=True)


def layers():
    return [
        {**layer, "monitor": name}
        for name, monitor in json.loads(hypr("layers", "-j")).items()
        for level in monitor["levels"].values()
        for layer in level
        if layer.get("pid") == os.getpid()
    ]


def geometry(namespace):
    return next(layer for layer in layers() if layer["namespace"] == namespace)


def cross(window, entered, detail=Gdk.NotifyType.NONLINEAR):
    event = Gdk.Event.new(Gdk.EventType.ENTER_NOTIFY if entered else Gdk.EventType.LEAVE_NOTIFY)
    event.window = window.get_window()
    event.detail = detail
    window.emit("enter-notify-event" if entered else "leave-notify-event", event)


app = Overlay(demo=True)
app.set_application_id("io.github.magdang.TokenTracker.HoverTest")
original = json.loads(hypr("cursorpos", "-j"))
state = {}
errors = []


def startup():
    assert not app.window.get_visible(), "Panel must start collapsed"
    assert len(layers()) == 1, "Only launcher should be mapped"
    state["initial_check"] = app.last_checked
    button = geometry("token-tracker-button")
    if SYNTHETIC:
        cross(app.launcher, True)
    else:
        move(button["x"] + button["w"] / 2, button["y"] + button["h"] / 2)
    print("PASS: only the small launcher is mapped at startup")


def enter_panel():
    assert app.window.get_visible(), "Hover did not open the panel"
    panel = geometry("token-tracker-panel")
    state["panel"] = panel
    if SYNTHETIC:
        cross(app.launcher, False)
        cross(app.window, True)
    else:
        move(panel["x"] + panel["w"] / 2, panel["y"] + 24)
    print("PASS: hover opens panel")


def inspect_panel():
    assert app.window.get_visible(), "Panel closed while moving from launcher to panel"
    panel = geometry("token-tracker-panel")
    Path("/tmp/opencode").mkdir(exist_ok=True)
    if SYNTHETIC:
        import cairo
        widget = app.window.get_child()
        image = cairo.ImageSurface(cairo.FORMAT_ARGB32, widget.get_allocated_width(), widget.get_allocated_height())
        widget.draw(cairo.Context(image))
        image.write_to_png("/tmp/opencode/token-tracker-hover.png")
        cross(app.window, False, Gdk.NotifyType.INFERIOR)
    else:
        subprocess.run([
            "grim", "-g", f'{panel["x"]},{panel["y"]} {panel["w"]}x{panel["h"]}',
            "/tmp/opencode/token-tracker-hover.png",
        ], check=True)
        move(panel["x"] + panel["w"] / 2, panel["y"] + panel["h"] / 2)
    print("PASS: crossing the gap and entering panel keeps it open")


def leave_panel():
    assert app.window.get_visible(), "Panel closed while traversing account rows"
    panel = state["panel"]
    if SYNTHETIC:
        cross(app.window, False)
    else:
        move(panel["x"] - 100, panel["y"] + 100)
    print("PASS: moving between panel children keeps it open")


def check_closed():
    assert not app.window.get_visible(), "Panel did not close after pointer left"
    assert len(layers()) == 1, "Hidden panel is still mapped and could intercept input"
    print("PASS: moving outside closes panel and unmaps its input surface")


def check_refresh():
    assert not app.window.get_visible()
    assert app.last_checked != state["initial_check"], "No background five-second refresh"
    print("PASS: five-second refresh continues while panel is collapsed")
    app.quit()


steps = iter([
    (500, startup),
    (300, enter_panel),
    (300, inspect_panel),
    (300, leave_panel),
    (350, check_closed),
    (5500, check_refresh),
])


def next_step():
    delay, callback = next(steps)

    def execute_step():
        try:
            callback()
            if callback is not check_refresh:
                next_step()
        except Exception as error:
            errors.append(str(error))
            app.quit()
        return False

    GLib.timeout_add(delay, execute_step)


app.connect("activate", lambda *_: next_step())
try:
    app.run([])
finally:
    if not SYNTHETIC:
        move(original["x"], original["y"])
if errors:
    print("FAIL:", "; ".join(errors), file=sys.stderr)
    sys.exit(1)
print("Saved cropped demo panel: /tmp/opencode/token-tracker-hover.png")
