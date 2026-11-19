"""Native GTK account manager. Only an explicit Add starts browser OAuth."""

import json
import signal
import threading

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from .chatgpt import AccountError, connect, disconnect
from .core import load_accounts


class Manager(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='io.github.magdang.TokenTracker.Accounts')
        self.window = None
        self.worker = None
        self.cancel = threading.Event()
        self.reviewed = threading.Event()
        self.accepted = False
        self.closed = False
        self.connect('activate', self.activate_manager)
        self.connect('shutdown', self.shutdown_manager)

    def activate_manager(self, *_):
        if self.window:
            self.window.present()
            return
        self.window = Gtk.ApplicationWindow(application=self, title='ChatGPT accounts')
        self.window.set_default_size(560, 520)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=18)
        self.window.add(box)
        box.pack_start(Gtk.Label(label='Verified ChatGPT subscription connections', xalign=0), False, False, 0)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.rows)
        box.pack_start(scroll, True, True, 0)
        self.name = self.entry(box, 'Account name (for example Account 1)')
        self.email = self.entry(box, 'Expected ChatGPT email')
        self.workspace = self.entry(box, 'Expected workspace name/ID (optional; review before linking)')
        self.add = Gtk.Button(label='Add ChatGPT account')
        self.add.connect('clicked', self.start_login)
        box.pack_start(self.add, False, False, 0)
        self.url = Gtk.LinkButton.new_with_label('https://auth.openai.com/', 'Sign-in URL will appear here')
        self.url.set_no_show_all(True)
        self.url_text = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.CHAR)
        self.url_scroll = Gtk.ScrolledWindow()
        self.url_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.url_scroll.set_min_content_height(80)
        self.url_scroll.add(self.url_text)
        self.url_scroll.set_no_show_all(True)
        box.pack_start(self.url_scroll, False, False, 0)
        box.pack_start(self.url, False, False, 0)
        self.status = Gtk.Label(xalign=0, selectable=True, wrap=True)
        self.status.set_max_width_chars(70)
        box.pack_start(self.status, False, False, 0)
        self.approve = Gtk.Button(label='Link this verified user and workspace')
        self.approve.connect('clicked', self.accept)
        self.approve.set_no_show_all(True)
        box.pack_start(self.approve, False, False, 0)
        self.cancel_button = Gtk.Button(label='Cancel sign-in')
        self.cancel_button.connect('clicked', self.cancel_login)
        self.cancel_button.set_sensitive(False)
        box.pack_start(self.cancel_button, False, False, 0)
        note = Gtk.Label(label='Coding quota only. ChatGPT website/model message limits unavailable.', xalign=0, wrap=True)
        box.pack_start(note, False, False, 0)
        self.refresh()
        self.timer = GLib.timeout_add_seconds(2, self.refresh)
        self.window.show_all()

    @staticmethod
    def entry(box, placeholder):
        entry = Gtk.Entry(placeholder_text=placeholder)
        entry.get_accessible().set_name(placeholder)
        box.pack_start(entry, False, False, 0)
        return entry

    def refresh(self):
        if self.closed:
            return False
        for child in self.rows.get_children():
            self.rows.remove(child)
        try:
            accounts = [a for a in load_accounts() if a['provider'] == 'chatgpt']
            for account in accounts:
                pin = account['verified']
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
                text = (f"{account['name']} · verified connection\n{pin['email']} · {pin['planType']}\n"
                        f"User: {pin['userId']}\nWorkspace: {pin['workspaceName'] or '(name unavailable)'} · {pin['accountId']}")
                label = Gtk.Label(label=text, xalign=0, selectable=True, wrap=True)
                label.set_max_width_chars(65)
                row.pack_start(label, False, False, 0)
                remove = Gtk.Button(label='Disconnect and delete managed credentials')
                remove.set_sensitive(not self.busy())
                remove.connect('clicked', lambda _, identity=account['id']: self.remove_account(identity))
                row.pack_start(remove, False, False, 0)
                self.rows.pack_start(row, False, False, 0)
            if not accounts:
                self.rows.pack_start(Gtk.Label(label='No verified connections yet.', xalign=0), False, False, 0)
        except (ValueError, OSError, KeyError):
            self.rows.pack_start(Gtk.Label(label='Cannot read account configuration.', xalign=0), False, False, 0)
        self.rows.show_all()
        return True

    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def post(self, function, *args):
        def apply():
            if not self.closed:
                function(*args)
            return False
        GLib.idle_add(apply)

    def show_url(self, url):
        def show():
            if self.cancel.is_set():
                return
            self.url.set_uri(url)
            self.url.set_label('Open sign-in in browser')
            self.url_text.get_buffer().set_text(url)
            self.url_scroll.show()
            self.url_text.show()
            self.url.show()
            self.status.set_text('Sign in as the expected account in your browser. Cancel stops this attempt.')
            try:
                Gio.AppInfo.launch_default_for_uri(url, None)
            except GLib.Error:
                self.status.set_text('Could not open browser. Use the visible sign-in URL, or cancel.')
        self.post(show)

    def confirm(self, pin):
        def review():
            if self.cancel.is_set():
                return
            self.status.set_text('Verify before linking:\n' + json.dumps(pin, indent=2, ensure_ascii=False))
            self.approve.show()
        self.post(review)
        while not self.reviewed.wait(.2):
            if self.cancel.is_set():
                return False
        return self.accepted and not self.cancel.is_set()

    def accept(self, *_):
        self.accepted = True
        self.reviewed.set()
        self.approve.hide()

    def cancel_login(self, *_):
        self.cancel.set()
        self.reviewed.set()
        self.status.set_text('Cancelling…')
        self.approve.hide()

    def start_login(self, *_):
        if self.busy():
            return
        name, email, workspace = (e.get_text().strip() for e in (self.name, self.email, self.workspace))
        self.cancel.clear()
        self.reviewed.clear()
        self.accepted = False
        def task():
            return connect(name, email, workspace, self.show_url, self.confirm, self.cancel)
        self.start_worker(task, 'Connected verified ChatGPT account. Quota refreshes automatically.')

    def remove_account(self, identity):
        if not self.busy():
            self.start_worker(lambda: disconnect(identity), 'Disconnected; managed credentials deleted.')

    def start_worker(self, task, success):
        self.add.set_sensitive(False)
        self.cancel_button.set_sensitive(True)
        self.status.set_text('Working…')
        def work():
            try:
                task()
                message = success
            except Exception as error:
                message = str(error) if isinstance(error, AccountError) else 'Account operation failed; check configuration and retry.'
            self.post(self.finished, message)
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.refresh()

    def finished(self, message):
        self.add.set_sensitive(True)
        self.cancel_button.set_sensitive(False)
        self.approve.hide()
        self.url.hide()
        self.url_scroll.hide()
        self.url_text.get_buffer().set_text('')
        self.status.set_text(message)
        self.refresh()

    def shutdown_manager(self, *_):
        self.closed = True
        self.cancel.set()
        self.reviewed.set()
        if hasattr(self, 'timer'):
            GLib.source_remove(self.timer)
        if self.worker:
            self.worker.join(timeout=25)


def run():
    app = Manager()
    source = GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: app.quit() or True)
    try:
        return app.run([])
    finally:
        GLib.source_remove(source)
