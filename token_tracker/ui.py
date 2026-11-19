"""A persistent launcher and a hover-only usage panel. GTK stays on its main thread."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import signal
import subprocess
from datetime import datetime
from time import monotonic

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell  # noqa: E402

from .core import CONFIG, Metric, Snapshot, fetch, load_accounts, timestamp
from .interaction import HoverState
from .display import (bounded, context_text, metric_value, observed_at, remaining,
                      reset_text, usage_detail, window_label)


REFRESH_SECONDS = 5
CSS = b"""
window { background: transparent; color: #eeeeee; font-family: sans-serif; font-size: 14pt; }
.panel { background: #191919; border: 1px solid #454545; border-radius: 6px; padding: 16px; }
.title { font-size: 14pt; font-weight: 600; }
.muted { color: #b0b0b0; font-size: 13pt; }
.account { font-size: 14pt; font-weight: 600; }
.value { font-weight: bold; font-size: 16pt; font-feature-settings: "tnum"; }
.warning { color: #efbc7b; }
button { background: transparent; color: #bbbbbb; border: none; box-shadow: none;
         border-radius: 3px; padding: 2px 6px; min-height: 20px; min-width: 20px; }
button:hover { background: #303030; color: #ffffff; }
button:focus { outline: 1px solid #aaaaaa; }
button.launcher { background: #191919; border: 1px solid #555555; color: #eeeeee;
                  padding: 4px 8px; font-size: 13pt; font-weight: 600; border-radius: 4px; }
button.launcher:hover { background: #303030; border-color: #aaaaaa; }
separator { background: #363636; min-height: 1px; }
progressbar trough { background: #3b3b3b; min-height: 6px; border: none; border-radius: 0; }
progressbar progress { background: #dddddd; min-height: 6px; border: none; border-radius: 0; }
progressbar.warning progress { background: #efbc7b; }
"""


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_line_wrap(True)
    widget.set_max_width_chars(42)
    if style:
        widget.get_style_context().add_class(style)
    return widget


class Overlay(Gtk.Application):
    def __init__(self, demo=False, quit_after=None):
        super().__init__(
            application_id="io.github.magdang.TokenTracker" + (".Demo" if demo else ""),
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.demo = demo
        self.quit_after = quit_after
        self.window = None
        self.launcher = None
        self.accounts = []
        self.results = {}
        self.pending = {}
        self.failures = {}
        self.retry_after = {}
        self.closed = False
        self.config_error = None
        self.last_checked = None
        from .chatgpt import Sessions
        self.chatgpt = Sessions()
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.hover = HoverState(GLib.timeout_add, GLib.source_remove, self.open_panel, self.close_panel)
        self.connect("activate", self.activate_overlay)
        self.connect("shutdown", self.shutdown_overlay)

    def shutdown_overlay(self, *_):
        self.closed = True
        self.hover.cancel_close()
        self.chatgpt.close()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def surface(self, title, namespace, top, keyboard):
        window = Gtk.ApplicationWindow(application=self)
        window.set_title(title)
        window.set_resizable(False)
        window.set_app_paintable(True)
        visual = window.get_screen().get_rgba_visual()
        if visual:
            window.set_visual(visual)
        GtkLayerShell.init_for_window(window)
        # Let the compositor place the launcher on its current monitor.
        # The panel follows the launcher's actual output when first opened.
        GtkLayerShell.set_namespace(window, namespace)
        GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(window, GtkLayerShell.Edge.TOP, top)
        GtkLayerShell.set_margin(window, GtkLayerShell.Edge.RIGHT, 20)
        GtkLayerShell.set_exclusive_zone(window, 0)
        GtkLayerShell.set_keyboard_mode(window, keyboard)
        window.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        window.connect("enter-notify-event", self.crossing, namespace, True)
        window.connect("leave-notify-event", self.crossing, namespace, False)
        window.connect("key-press-event", self.key_pressed)
        window.connect("delete-event", lambda *_: self.hover.dismiss() or True)
        return window

    def activate_overlay(self, *_):
        if self.launcher is not None:
            if self.window.get_visible():
                self.hover.dismiss()
            else:
                self.open_panel()
            return
        if not GtkLayerShell.is_supported():
            raise RuntimeError("This compositor does not support Wayland layer-shell")
        self.hold()
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.launcher = self.surface(
            "Token Tracker Button", "token-tracker-button", 40, GtkLayerShell.KeyboardMode.NONE
        )
        button = Gtk.Button(label="AI")
        button.get_style_context().add_class("launcher")
        button.set_tooltip_text("AI usage · hover to open")
        button.get_accessible().set_name("AI usage")
        button.connect("clicked", lambda *_: self.open_panel())
        self.launcher.add(button)
        self.window = self.surface(
            "Token Tracker", "token-tracker-panel", 80, GtkLayerShell.KeyboardMode.ON_DEMAND
        )
        self.window.set_default_size(320, -1)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        panel.get_style_context().add_class("panel")
        self.window.add(panel)
        header = Gtk.Box(spacing=8)
        header.pack_start(label("Usage" + (" · demo" if self.demo else ""), "title"), True, True, 0)
        quit_button = Gtk.Button(label="Quit")
        quit_button.set_tooltip_text("Exit Token Tracker, including the floating button")
        quit_button.connect("clicked", lambda *_: self.quit())
        header.pack_end(quit_button, False, False, 0)
        accounts_button = Gtk.Button(label="Accounts")
        accounts_button.connect("clicked", lambda *_: subprocess.Popen([
            str(Path(__file__).resolve().parents[1] / "bin/token-tracker"), "accounts"
        ]))
        header.pack_end(accounts_button, False, False, 0)
        panel.pack_start(header, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(500)
        self.cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll.add(self.cards)
        panel.pack_start(scroll, True, True, 0)
        self.footer = label("Checking every 5s", "muted")
        panel.pack_start(self.footer, False, False, 0)
        self.refresh()
        # Only the button maps on startup. No invisible panel-sized input area.
        self.launcher.show_all()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self.tick)
        if self.quit_after is not None:
            GLib.timeout_add_seconds(max(1, self.quit_after), self.stop)

    def crossing(self, _window, event, surface, entered):
        # Child-window crossings must not close a panel containing controls.
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        if entered:
            self.hover.enter(surface)
        else:
            self.hover.leave(surface)
        return False

    def open_panel(self):
        if self.window is not None:
            if not self.window.get_visible() and self.launcher.get_window() is not None:
                monitor = Gdk.Display.get_default().get_monitor_at_window(self.launcher.get_window())
                GtkLayerShell.set_monitor(self.window, monitor)
            self.window.show_all()

    def close_panel(self):
        if self.window is not None:
            self.window.hide()

    def stop(self):
        self.quit()
        return False

    def key_pressed(self, _window, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hover.dismiss()
            return True
        return False

    def tick(self):
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
                ], "Sample data. Not linked to Claude."),
                "demo-work": Snapshot("demo-work", "DEMO", timestamp(), [
                    Metric("Session", 18), Metric("Weekly", 61)
                ], "Sample data. Separate account."),
                "demo-api": Snapshot("demo-api", "DEMO", timestamp(), [
                    Metric("Month to date", 12.4, 30, "USD")
                ], "Sample budget. Not provider credit."),
            }
            self.last_checked = datetime.now().strftime("%H:%M:%S")
            self.render()
            return
        try:
            accounts = load_accounts()
            self.config_error = None
        except (ValueError, OSError, KeyError):
            self.chatgpt.reconcile([])
            self.config_error = "Cannot read account configuration."
            self.render()
            return
        self.chatgpt.reconcile(accounts)
        for account in self.accounts:
            if account not in accounts:
                identity = account["id"]
                for state in (self.results, self.failures, self.retry_after):
                    state.pop(identity, None)
                if identity in self.pending:
                    # Keep the slot occupied until its old request finishes.
                    self.pending[identity] = None
        self.accounts = accounts
        for account in self.accounts:
            identity = account["id"]
            if identity in self.pending or monotonic() < self.retry_after.get(identity, 0):
                continue
            # A slow account does not prevent other accounts refreshing.
            self.pending[identity] = dict(account)
            future = self.pool.submit(self.chatgpt.fetch if account["provider"] == "chatgpt" else fetch, dict(account))
            future.add_done_callback(
                lambda done, account=dict(account): self.queue_result(account, done)
            )
        self.last_checked = datetime.now().strftime("%H:%M:%S")
        self.render()

    def queue_result(self, account, future):
        if not self.closed and not future.cancelled():
            GLib.idle_add(self.received, account, future.result())

    def received(self, account, result):
        if self.closed:
            return False
        identity = account["id"]
        requested = self.pending.pop(identity, None)
        # Discard work completed after removal or reconfiguration.
        if requested != account or account not in self.accounts:
            return False
        if result.error:
            failures = min(6, self.failures.get(identity, 0) + 1)
            self.failures[identity] = failures
            self.retry_after[identity] = monotonic() + min(300, 5 * 2 ** failures)
            previous = self.results.get(identity)
            if previous and previous.metrics:
                result = Snapshot(
                    identity, "stale", previous.updated_at, previous.metrics,
                    previous.note, result.error,
                )
        else:
            self.failures.pop(identity, None)
            self.retry_after.pop(identity, None)
        self.results[identity] = result
        self.render()
        return False

    def render(self):
        for child in self.cards.get_children():
            self.cards.remove(child)
        if self.config_error:
            message = label(self.config_error, "warning")
            message.set_tooltip_text(str(CONFIG))
            self.cards.pack_start(message, False, False, 0)
        elif not self.accounts:
            self.cards.pack_start(label("No accounts connected", "account"), False, False, 0)
            self.cards.pack_start(label(
                'Use Accounts above to link ChatGPT, or add other providers from the terminal.', "muted"
            ), False, False, 0)
        else:
            for index, account in enumerate(self.accounts):
                if index:
                    self.cards.pack_start(Gtk.Separator(), False, False, 0)
                self.cards.pack_start(self.card(account), False, False, 0)
        self.footer.set_text(
            ("Sample data · " if self.demo else "") +
            "Every 5s" + (f" · checked {self.last_checked}" if self.last_checked else "")
        )
        self.footer.set_tooltip_text(
            "Successful accounts refresh every 5 seconds, even while collapsed. "
            "Requests never overlap for the same account. Errors back off up to 5 minutes. "
            "Local snapshots and provider billing may be older than the last check."
        )
        self.cards.show_all()

    def card(self, account):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        box.pack_start(label(bounded(account["name"], 64), "account"), False, False, 0)
        result = self.results.get(account["id"])
        if not result:
            box.pack_start(label("Checking…", "muted"), False, False, 0)
            return box
        box.set_tooltip_text(
            f"{result.source} · {observed_at(result.updated_at)}\n{result.note}"
        )
        if result.error:
            box.pack_start(label(bounded(result.error), "warning"), False, False, 0)
        for metric in result.metrics:
            row = Gtk.Box(spacing=12)
            row.pack_start(label(window_label(metric.label), "muted"), True, True, 0)
            row.pack_end(label(metric_value(metric), "value"), False, False, 0)
            box.pack_start(row, False, False, 0)
            fraction = remaining(metric)
            if fraction is not None:
                bar = Gtk.ProgressBar()
                bar.set_fraction(fraction)
                if fraction <= 0.2:
                    bar.get_style_context().add_class("warning")
                box.pack_start(bar, False, False, 0)
            detail = usage_detail(metric)
            if detail:
                box.pack_start(label(detail, "muted"), False, False, 0)
            if metric.resets_at is not None:
                box.pack_start(label(reset_text(metric.resets_at), "muted"), False, False, 0)
        if not result.metrics and not result.error:
            box.pack_start(label(
                "Manual · no usage entered" if result.source == "manual" else "Usage unavailable",
                "muted",
            ), False, False, 0)
        box.pack_start(label(context_text(account, result), "muted"), False, False, 0)
        return box


def run(demo=False, quit_after=None):
    app = Overlay(demo, quit_after)
    source = GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: app.quit() or True)
    try:
        return app.run([])
    finally:
        GLib.source_remove(source)
