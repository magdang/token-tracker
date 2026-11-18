"""GTK stays on the main thread; independent accounts refresh in a worker pool."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell  # noqa: E402

from .core import CONFIG, Metric, Snapshot, fetch, load_accounts, timestamp


CSS = b"""
window { background: transparent; color: #edf2fa; }
.panel { background: #141923; border: 1px solid #354055; border-radius: 18px; padding: 22px; }
.title { font-size: 23px; font-weight: bold; }
.subtitle { color: #98a7bc; font-size: 11px; }
.card { background: #1e2633; border-radius: 12px; padding: 16px; }
.account { font-size: 15px; font-weight: bold; }
.badge { color: #a5c7ff; font-size: 11px; }
.warning { color: #f1ba76; }
button { background: #29364a; color: #edf2fa; border: none; border-radius: 8px; padding: 7px 12px; }
button:hover { background: #3a4e6c; }
progressbar trough { background: #303d51; min-height: 7px; border: none; border-radius: 5px; }
progressbar progress { background: #8eb7fa; min-height: 7px; border: none; border-radius: 5px; }
.warning progressbar progress { background: #eab46d; }
"""


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_line_wrap(True)
    widget.set_max_width_chars(53)
    if style:
        widget.get_style_context().add_class(style)
    return widget


def observed_at(value):
    if not value:
        return "Not yet updated"
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if when.tzinfo is None:
            return "Timestamp needs a timezone"
        age = max(0, int((datetime.now(timezone.utc) - when).total_seconds() / 60))
        return f"Observed {age}m ago · {when.astimezone():%b %d, %H:%M}"
    except ValueError:
        return "Unknown observation time"


class Overlay(Gtk.Application):
    def __init__(self, demo=False, quit_after=None):
        super().__init__(
            application_id="io.github.magdang.TokenTracker" + (".Demo" if demo else ""),
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.demo = demo
        self.quit_after = quit_after
        self.window = None
        self.accounts = []
        self.results = {}
        self.pending = set()
        self.generation = 0
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.connect("activate", self.activate_overlay)
        self.connect("shutdown", lambda *_: self.pool.shutdown(wait=False, cancel_futures=True))

    def activate_overlay(self, *_):
        if self.window is not None:
            if self.window.get_visible():
                self.window.hide()
            else:
                self.window.show_all()
                self.refresh()
            return
        if not GtkLayerShell.is_supported():
            raise RuntimeError("This compositor does not support Wayland layer-shell")
        self.hold()
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title("Token Tracker")
        self.window.set_default_size(440, -1)
        self.window.set_resizable(False)
        self.window.set_app_paintable(True)
        visual = self.window.get_screen().get_rgba_visual()
        if visual:
            self.window.set_visual(visual)
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_namespace(self.window, "token-tracker")
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self.window, GtkLayerShell.Edge.TOP, 60)
        GtkLayerShell.set_margin(self.window, GtkLayerShell.Edge.RIGHT, 24)
        GtkLayerShell.set_exclusive_zone(self.window, 0)
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.ON_DEMAND)
        self.window.connect("key-press-event", self.key_pressed)
        self.window.connect("delete-event", self.hide_window)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        panel.get_style_context().add_class("panel")
        self.window.add(panel)
        panel.pack_start(label("Token Tracker", "title"), False, False, 0)
        panel.pack_start(label(
            "DEMO · Sample accounts, not real usage" if self.demo else "AI accounts · Local-first usage monitor",
            "subtitle",
        ), False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(560)
        self.cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroll.add(self.cards)
        panel.pack_start(scroll, True, True, 0)
        actions = Gtk.Box(spacing=8)
        for title, callback in (
            ("Refresh", lambda *_: self.refresh()),
            ("Close", lambda *_: self.window.hide()),
            ("Quit", lambda *_: self.quit()),
        ):
            button = Gtk.Button(label=title)
            button.connect("clicked", callback)
            actions.pack_start(button, True, True, 0)
        panel.pack_start(actions, False, False, 0)
        self.refresh()
        self.window.show_all()
        GLib.timeout_add_seconds(300, self.tick)
        if self.quit_after is not None:
            GLib.timeout_add_seconds(max(1, self.quit_after), self.stop)

    def stop(self):
        self.quit()
        return False

    def key_pressed(self, _window, event):
        if event.keyval == Gdk.KEY_Escape:
            self.window.hide()
            return True
        return False

    def hide_window(self, *_):
        self.window.hide()
        return True

    def tick(self):
        if self.window.get_visible():
            self.refresh()
        return True

    def refresh(self):
        if self.demo:
            self.accounts = [
                {"id": "demo-claude", "name": "Claude · Personal", "provider": "demo"},
                {"id": "demo-work", "name": "Claude · Work", "provider": "demo"},
                {"id": "demo-api", "name": "OpenAI API · Projects", "provider": "demo"},
            ]
            self.results = {
                "demo-claude": Snapshot("demo-claude", "DEMO", timestamp(), [
                    Metric("Session", 72), Metric("Weekly", 35)
                ], "Illustration only · not linked to Claude"),
                "demo-work": Snapshot("demo-work", "DEMO", timestamp(), [
                    Metric("Session", 18), Metric("Weekly", 61)
                ], "Separate account · sample data"),
                "demo-api": Snapshot("demo-api", "DEMO", timestamp(), [
                    Metric("Monthly budget", 12.4, 30, "USD")
                ], "Sample budget, not provider credit"),
            }
            self.render()
            return
        try:
            accounts = load_accounts()
        except (ValueError, OSError, KeyError):
            self.render("Cannot read account configuration. Check " + str(CONFIG))
            return
        # Do not overlap slow requests, including repeated manual refreshes.
        if self.pending:
            return
        self.accounts = accounts
        self.generation += 1
        generation = self.generation
        for account in accounts:
            identity = account["id"]
            self.pending.add(identity)
            future = self.pool.submit(fetch, account)
            future.add_done_callback(
                lambda done, identity=identity: GLib.idle_add(
                    self.received, generation, identity, done.result()
                )
            )
        self.render()

    def received(self, generation, identity, result):
        if generation == self.generation:
            self.pending.discard(identity)
            self.results[identity] = result
            self.render()
        return False

    def render(self, error=None):
        for child in self.cards.get_children():
            self.cards.remove(child)
        if error:
            self.cards.pack_start(label(error, "warning"), False, False, 0)
        elif not self.accounts:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            box.pack_start(label("No accounts connected", "account"), False, False, 0)
            box.pack_start(label(
                "Add an account from the terminal:\n"
                "./bin/token-tracker add codex-local \"Codex · Personal\"\n\n"
                "See README.md for API keys and other connections.", "subtitle"
            ), False, False, 0)
            self.cards.pack_start(box, False, False, 0)
        else:
            for account in self.accounts:
                self.cards.pack_start(self.card(account), False, False, 0)
        self.cards.show_all()

    def card(self, account):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        box.get_style_context().add_class("card")
        box.pack_start(label(account["name"], "account"), False, False, 0)
        result = self.results.get(account["id"])
        if not result:
            box.pack_start(label("Refreshing…", "subtitle"), False, False, 0)
            return box
        box.pack_start(label(
            result.source.upper() + (" · refreshing…" if account["id"] in self.pending else ""),
            "badge",
        ), False, False, 0)
        if result.error:
            box.pack_start(label(result.error, "warning"), False, False, 0)
        for metric in result.metrics:
            if metric.unit == "USD":
                text = f"${metric.used:,.2f} spent"
                if metric.limit > 0:
                    remaining = metric.limit - metric.used
                    text += f" / ${metric.limit:,.2f} · ${abs(remaining):,.2f} " + (
                        "left" if remaining >= 0 else "over budget"
                    )
            else:
                text = f"{metric.used:g}% used" if metric.limit == 100 else f"{metric.used:g} / {metric.limit:g}"
            box.pack_start(label(f"{metric.label} · {text}"), False, False, 0)
            if metric.limit > 0:
                bar = Gtk.ProgressBar()
                bar.set_fraction(max(0, min(1, metric.used / metric.limit)))
                box.pack_start(bar, False, False, 0)
                if metric.used / metric.limit >= 0.8:
                    box.get_style_context().add_class("warning")
            if metric.resets_at:
                try:
                    reset = datetime.fromisoformat(metric.resets_at.replace("Z", "+00:00"))
                    text = f"Reset reported for {reset.astimezone():%a %H:%M}"
                    if reset < datetime.now(timezone.utc):
                        text += " · snapshot needs refresh"
                except (ValueError, TypeError):
                    text = "Reset time unavailable"
                box.pack_start(label(text, "subtitle"), False, False, 0)
        if result.note:
            box.pack_start(label(result.note, "subtitle"), False, False, 0)
        box.pack_start(label(observed_at(result.updated_at), "subtitle"), False, False, 0)
        return box


def run(demo=False, quit_after=None):
    return Overlay(demo, quit_after).run([])
