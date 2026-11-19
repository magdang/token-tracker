"""Native GTK manager smoke test. Mocked login only; no OAuth or pointer motion."""
import json
import os
import signal
import sys
import tempfile
from pathlib import Path
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from token_tracker.accounts import Manager, GLib  # noqa: E402
from token_tracker.chatgpt import AccountError  # noqa: E402
from token_tracker import accounts as manager, chatgpt  # noqa: E402


def cleanup_smoke(action, method):
    """Interrupt a real fixture RPC after login completion, with GTK still running."""
    app = Manager()
    app.set_application_id('io.github.magdang.TokenTracker.AccountsCleanupSmoke')
    children, errors = [], []
    server_type = chatgpt.Server
    started = time.monotonic()
    interrupted = False
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / 'chatgpt' / ('a' * 32)
        root.mkdir(parents=True)
        (root / 'fixture.json').write_text(json.dumps({
            'signed_out': True, 'post_login_delay_method': method}))

        def server(*args, **kwargs):
            child = server_type(*args, **kwargs)
            children.append(child)
            return child

        def check():
            nonlocal interrupted
            try:
                assert time.monotonic() - started < 8, 'Cleanup smoke timed out'
                if not app.worker:
                    app.name.set_text('Account 1')
                    app.email.set_text('test@example.invalid')
                    app.add.clicked()
                    assert not app.worker.daemon
                elif not interrupted and (root / 'blocked').exists():
                    interrupted = True
                    if action == 'cancel':
                        app.cancel_button.clicked()
                    elif action == 'close':
                        app.window.close()
                    else:
                        os.kill(os.getpid(), signal.SIGTERM)
                elif interrupted and action == 'cancel' and not app.busy():
                    assert 'cancelled' in app.status.get_text()
                    app.quit()
            except Exception as error:
                errors.append(str(error))
                app.quit()
                return False
            return True

        with patch.object(chatgpt, 'STATE', Path(directory)), \
             patch.object(chatgpt.shutil, 'which', return_value=str(Path(__file__).parent.resolve() / 'fixtures/fake_codex.py')), \
             patch.object(chatgpt.uuid, 'uuid4') as identity, \
             patch.object(chatgpt, 'Server', side_effect=server), \
             patch.object(chatgpt, 'load_accounts', return_value=[]), \
             patch.object(chatgpt, 'save_accounts') as save, \
             patch.object(manager, 'load_accounts', return_value=[]), \
             patch.object(manager, 'Manager', return_value=app), \
             patch.object(manager.Gio.AppInfo, 'launch_default_for_uri'):
            identity.return_value.hex = 'a' * 32
            timer = GLib.timeout_add(25, check)
            try:
                manager.run()
            finally:
                GLib.source_remove(timer)
            save.assert_not_called()
        assert not errors, errors
        assert time.monotonic() - started < 8, 'Shutdown did not interrupt the slow RPC'
        assert interrupted and not app.busy()
        assert len(children) == 1 and children[0].process.poll() is not None
        assert children[0].lease is None and not root.exists()
        print(f'PASS: manager {action} during slow post-login {method} reaps child and deletes uncommitted home')


if len(sys.argv) == 3:
    assert sys.argv[1] in ('cancel', 'close', 'sigterm')
    assert sys.argv[2] in ('account/read', 'account/rateLimits/read')
    cleanup_smoke(*sys.argv[1:])
    sys.exit(0)

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
