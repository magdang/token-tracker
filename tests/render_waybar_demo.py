"""Render only labelled sample tooltip content, never capture the desktop."""
from pathlib import Path
import sys

import cairo
import gi

gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from token_tracker.waybar import frame

markup = json.loads(frame(None, demo=True))['tooltip']
assert 'DEMO · sample data' in markup
Pango.parse_markup(markup, -1, '\0')
surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
layout = PangoCairo.create_layout(cairo.Context(surface))
layout.set_font_description(Pango.FontDescription('Sans 14'))
layout.set_markup(markup, -1)
width, height = layout.get_pixel_size()
for suffix, background, foreground in [('', (236/255, 239/255, 243/255), (32/255, 38/255, 50/255)),
                                        ('-dark', (.1, .1, .1), (.94, .94, .94))]:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width + 32, height + 32)
    context = cairo.Context(surface)
    context.set_source_rgb(*background)
    context.paint()
    context.set_source_rgb(*foreground)
    context.move_to(16, 16)
    PangoCairo.update_layout(context, layout)
    PangoCairo.show_layout(context, layout)
    output = Path(f'/tmp/opencode/token-tracker-readable-demo{suffix}.png')
    output.parent.mkdir(parents=True, exist_ok=True)
    surface.write_to_png(str(output))
    print(f'PASS: native Pango DEMO tooltip rendered to {output} ({width + 32}×{height + 32})')
