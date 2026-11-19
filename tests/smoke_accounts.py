"""Native GTK manager smoke test. Mocked login only; no OAuth or pointer motion."""
import sys
from pathlib import Path
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from token_tracker.accounts import Manager, GLib  # noqa: E402
from token_tracker.chatgpt import AccountError  # noqa: E402

pin = {'email': 'test@example.invalid', 'planType': 'plus', 'userId': 'fixture-user',
       'accountId': 'fixture-workspace', 'workspaceName': 'Personal'}
accounts = [{'id': str(n)*32, 'provider': 'chatgpt', 'name': f'Account {n}',
             'verified': {**pin, 'userId': f'fixture-user-{n}', 'accountId': f'fixture-workspace-{n}'}}
            for n in (1, 2, 3)]
app = Manager()
app.set_application_id('io.github.magdang.TokenTracker.AccountsSmoke')
errors = []
stage = 0
started = time.monotonic()


def fake_connect(name, email, workspace, show_url, confirm, cancel):
    show_url('https://auth.openai.com/authorize?state=fixture&challenge=' + 'a' * 900)
    if not confirm(pin):
        raise AccountError('Sign-in cancelled; connection not saved.')
    return accounts[0]


def check():
    global stage
    try:
        assert time.monotonic() - started < 8, 'Manager smoke timed out'
        if stage == 0:
            assert len(app.rows.get_children()) == 3
            app.name.set_text('Account 1')
            app.email.set_text('test@example.invalid')
            app.add.clicked()
            stage = 1
        elif stage in (1, 4) and app.approve.get_visible():
            assert app.window.get_preferred_width().minimum_width < 700, 'Sign-in URL forces an oversized window'
            assert app.url.get_visible()
            buffer = app.url_text.get_buffer()
            assert buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).startswith('https://auth.openai.com/')
            assert 'fixture-workspace' in app.status.get_text()
            assert not app.add.get_sensitive()
            if stage == 1:
                app.approve.clicked()
                stage = 2
            else:
                app.cancel_button.clicked()
                stage = 5
        elif stage == 2 and not app.busy() and app.add.get_sensitive():
            assert 'Connected verified' in app.status.get_text()
            assert not app.url.get_visible()
            app.add.clicked()
            stage = 4
        elif stage == 5 and not app.busy() and app.add.get_sensitive():
            assert 'cancelled' in app.status.get_text()
            assert not app.url.get_visible()
            print('PASS: native manager lists three accounts, shows URL and verified identity, links and cancels mocked login')
            app.quit()
            return False
    except Exception as error:
        errors.append(str(error))
        app.quit()
        return False
    return True


with patch('token_tracker.accounts.load_accounts', return_value=accounts), \
     patch('token_tracker.accounts.connect', side_effect=fake_connect), \
     patch('token_tracker.accounts.Gio.AppInfo.launch_default_for_uri'):
    GLib.timeout_add(50, check)
    app.run([])
if errors:
    raise AssertionError('; '.join(errors))
assert stage == 5
