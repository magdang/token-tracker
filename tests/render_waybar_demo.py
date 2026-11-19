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
from datetime import datetime, timezone
from token_tracker.core import Metric, Snapshot
from token_tracker.waybar import report

now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
for count in (1, 3):
    accounts = [{'id': str(i), 'name': f'Account {i + 1} · sample', 'provider': 'chatgpt'}
                for i in range(count)]
    results = {a['id']: Snapshot(a['id'], 'DEMO', now.isoformat(), [
        Metric('codex primary (300 min)', 32, resets_at='2026-11-19T14:15:00Z'),
        Metric('codex secondary (10080 min)', 58, resets_at='2026-11-22T16:00:00Z')])
               for a in accounts}
    markup = json.loads(report(accounts, results, demo=True, now=now))['tooltip']
    assert 'DEMO · sample data' in markup and 'Observed' not in markup
    Pango.parse_markup(markup, -1, '\0')
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
    layout = PangoCairo.create_layout(cairo.Context(surface))
    layout.set_font_description(Pango.FontDescription('Sans 11'))
    layout.set_markup(markup, -1)
    width, height = layout.get_pixel_size()
    assert height + 32 < 600, 'Sample tooltip should fit comfortably on screen'
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
        output = Path(f'/tmp/opencode/token-tracker-readable-demo-{count}{suffix}.png')
        output.parent.mkdir(parents=True, exist_ok=True)
        surface.write_to_png(str(output))
        print(f'PASS: native Pango DEMO tooltip rendered to {output} ({width + 32}×{height + 32})')
