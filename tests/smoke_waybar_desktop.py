"""Opt-in test of the installed bar, with a caller-supplied tooltip-only crop.

Run via run-smoke.sh --waybar-desktop --tooltip-region 'x,y WxH' [--demo].
Requires Atspi, grim, tesseract and the compiled virtual-pointer helper.
Never unlocks the session; moves and restores the pointer. The crop must fit
inside the visible tooltip, so no desktop content is saved.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

import gi

gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

parser = argparse.ArgumentParser()
parser.add_argument('--tooltip-region', required=True)
parser.add_argument('--demo', action='store_true')
args = parser.parse_args()


def unlocked():
    if subprocess.run(['pgrep', '-x', 'hyprlock'], stdout=subprocess.DEVNULL).returncode == 0:
        raise SystemExit('SKIP: hyprlock is active')


def move(x, y):
    unlocked()
    current = json.loads(subprocess.check_output(['hyprctl', 'cursorpos', '-j']))
    return subprocess.Popen(['/tmp/opencode/token-tracker-pointer',
                             str(int(x) - current['x']), str(int(y) - current['y']), '30'])


def find(a):
    if a.get_role_name() == 'label' and a.get_name() == ('AI DEMO' if args.demo else 'AI'):
        return a.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
    for i in range(a.get_child_count()):
        found = find(a.get_child_at_index(i))
        if found is not None:
            return found


unlocked()
original = json.loads(subprocess.check_output(['hyprctl', 'cursorpos', '-j']))
rect = None
for app in Atspi.get_desktop(0):
    if 'waybar' in app.get_name():
        rect = find(app)
        if rect is not None:
            break
assert rect is not None, 'Installed Waybar AI module not found'
helpers = []
try:
    helpers.append(move(rect.x, rect.y + 200))
    time.sleep(.3)
    helpers[-1].terminate()
    helpers[-1].wait(timeout=3)
    helpers.append(move(rect.x + rect.width / 2, rect.y + rect.height / 2))
    time.sleep(2)
    actual = json.loads(subprocess.check_output(["hyprctl", "cursorpos", "-j"]))
    assert rect.x <= actual["x"] < rect.x + rect.width and rect.y <= actual["y"] < rect.y + rect.height, "Pointer moved during test"
    unlocked()
    path = Path('/tmp/opencode/token-tracker-waybar-' + ('demo' if args.demo else 'real') + '-hover.png')
    subprocess.run(['grim', '-g', args.tooltip_region, str(path)], check=True)
    text = subprocess.check_output(['tesseract', str(path), 'stdout'], stderr=subprocess.DEVNULL, text=True)
    if 'usage' not in text.lower():
        path.unlink(missing_ok=True)
        raise AssertionError('Tooltip did not open on hover')
    if args.demo:
        assert 'DEMO' in text and 'sample' in text and 'Personal' in text and 'Work' in text
    # Compare only a two-pixel strip of the tooltip border after leaving. No
    # readable desktop region is captured when the tooltip has closed.
    xy, size = args.tooltip_region.split()
    width = size.split('x')[0]
    stripe = xy + ' ' + width + 'x2'
    before = subprocess.check_output(['grim', '-g', stripe, '-'])
    helpers.append(move(rect.x, rect.y + 200))
    time.sleep(.7)
    unlocked()
    after = subprocess.check_output(['grim', '-g', stripe, '-'])
    assert before != after, 'Tooltip border remained after pointer left'
    print('PASS: native Waybar hover opens; pointer leave closes; crop:', path)
finally:
    if subprocess.run(['pgrep', '-x', 'hyprlock'], stdout=subprocess.DEVNULL).returncode != 0:
        helpers.append(move(original['x'], original['y']))
    for helper in helpers:
        helper.terminate()
        helper.wait(timeout=3)
