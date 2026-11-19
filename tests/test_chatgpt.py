import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from token_tracker import chatgpt
from token_tracker.core import load_accounts, save_accounts, validate
from token_tracker.__main__ import main

FIXTURE = str(Path(__file__).parent / 'fixtures/fake_codex.py')


class ChatGPTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'
        self.config = Path(self.temp.name) / 'config/accounts.json'
        self.identity = '1' * 32
        self.patchers = [patch.object(chatgpt, 'STATE', self.state),
                         patch.object(chatgpt.shutil, 'which', return_value=FIXTURE),
                         patch.object(chatgpt, 'load_accounts', side_effect=lambda: load_accounts(self.config)),
                         patch.object(chatgpt, 'save_accounts', side_effect=lambda a: save_accounts(a, self.config))]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def scenario(self, identity=None, **options):
        root = chatgpt.home_for(identity or self.identity)
        root.mkdir(parents=True, exist_ok=True)
        (root / 'fixture.json').write_text(json.dumps(options))
        return root

    def server(self, **opts):
        self.scenario(**opts)
        server = chatgpt.Server(self.identity, timeout=.5)
        self.addCleanup(server.close)
        return server

    def account(self, identity=None, **opts):
        identity = identity or self.identity
        self.scenario(identity, **opts)
        server = chatgpt.Server(identity, timeout=.5)
        try:
            pin, _ = chatgpt.verified(server)
        finally:
            server.close()
        return {'id': identity, 'provider': 'chatgpt', 'name': 'Test', 'verified': pin}

    def test_handshake_allowlist_isolation_and_permissions(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-secret', 'CODEX_HOME': '/not-used',
                                     'OPENAI_BASE_URL': 'https://invalid.invalid', 'NODE_OPTIONS': 'secret'}):
            server = self.server()
        pin, _ = chatgpt.verified(server)
        self.assertEqual(pin['userId'], 'user-fixture')
        calls = [json.loads(line)['method'] for line in (server.root / 'rpc.jsonl').read_text().splitlines()]
        self.assertEqual(calls[:3], ['initialize', 'initialized', 'account/read'])
        with self.assertRaisesRegex(chatgpt.AccountError, 'Only account'):
            server.call('turn/start')
        server.close()
        for directory, dirs, files in os.walk(server.root):
            self.assertEqual(stat.S_IMODE(Path(directory).stat().st_mode), 0o700)
            for name in files:
                self.assertEqual(stat.S_IMODE((Path(directory) / name).stat().st_mode), 0o600)
        self.assertIsNotNone(server.process.poll())

    def test_out_of_order_responses(self):
        server = self.server(mode='out-of-order')
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(server.call, 'account/read') for _ in range(2)]
            self.assertTrue(all(f.result()['userId'] == 'user-fixture' for f in futures))

    def test_bounded_malformed_timeout_and_stderr(self):
        for mode, message in [('malformed', 'malformed JSON'), ('long', 'output limit'), ('timeout', 'timed out')]:
            with self.subTest(mode=mode):
                self.scenario(mode=mode)
                with self.assertRaisesRegex(chatgpt.AccountError, message) as caught:
                    chatgpt.Server(self.identity, timeout=.15)
                self.assertNotIn('fixture-secret', str(caught.exception))
        server = self.server(mode='stderr')
        self.assertIsNotNone(server.call('account/read')['account'])

    def test_multiple_buckets_unknown_zero_and_credits(self):
        server = self.server(mode='buckets')
        pin, limits = chatgpt.verified(server)
        result = chatgpt.snapshot({'id': self.identity, 'verified': pin}, limits)
        self.assertEqual([m.used for m in result.metrics], [0, 37])
        self.assertIn('300 min', result.metrics[0].label)
        self.assertIn('10080 min', result.metrics[1].label)
        self.assertIn('secondary: unknown', result.note)
        self.assertIn('12.5 (not USD)', result.note)
        self.assertIn('website/model message limits unavailable', result.note)
        self.assertTrue(all(m.unit != 'USD' for m in result.metrics))

    def test_three_homes_persistent_children_and_wrong_identity(self):
        accounts = [self.account(str(n)*32, userId=f'user-{n}', accountId=f'workspace-{n}',
                                 email=f'test{n}@example.invalid') for n in (1, 2, 3)]
        sessions = chatgpt.Sessions()
        self.addCleanup(sessions.close)
        sessions.reconcile(accounts)
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertTrue(all(not r.error for r in pool.map(sessions.fetch, accounts)))
        pids = {key: value[1].process.pid for key, value in sessions.servers.items()}
        for account in accounts:
            self.assertFalse(sessions.fetch(account).error)
        self.assertEqual(pids, {key: value[1].process.pid for key, value in sessions.servers.items()})
        self.assertEqual(len({s.root for _, s in sessions.servers.values()}), 3)
        self.scenario(userId='wrong-user', accountId='workspace-1', email='test1@example.invalid')
        bad = sessions.fetch(accounts[0])
        self.assertIn('changed', bad.error)
        self.assertFalse(bad.metrics)
        self.assertNotIn(self.identity, sessions.servers)

    def test_missing_pins_wrong_workspace_and_routing(self):
        account = self.account()
        sessions = chatgpt.Sessions()
        self.addCleanup(sessions.close)
        sessions.reconcile([account])
        for opts in ({'accountId': 'wrong'}, {'accountId': None}, {'userId': None},
                     {'email': None}, {'workspace': None}, {'mode': 'routing-mismatch'},
                     {'mode': 'account-change'}, {'signed_out': True}):
            with self.subTest(opts=opts):
                self.scenario(**opts)
                result = sessions.fetch(account)
                self.assertIsNotNone(result.error)
                self.assertFalse(result.metrics)
        with self.assertRaises(ValueError):
            validate([{**account, 'verified': {}}])

    def test_duplicate_user_or_workspace_rejected(self):
        a = self.account()
        for other in ({**a['verified'], 'accountId': 'different'}, {**a['verified'], 'userId': 'different'}):
            with self.assertRaisesRegex(chatgpt.AccountError, 'Duplicate'):
                validate([a, {**a, 'id': '2'*32, 'verified': other}])

    def login(self, **kwargs):
        identity = 'a' * 32
        self.scenario(identity, signed_out=True, **kwargs.pop('scenario', {}))
        with patch.object(chatgpt.uuid, 'uuid4') as new_id:
            new_id.return_value.hex = identity
            return chatgpt.connect('Account 1', kwargs.pop('email', 'test@example.invalid'),
                                   kwargs.pop('workspace', ''), kwargs.pop('show_url', Mock()),
                                   kwargs.pop('confirm', Mock(return_value=True)), **kwargs)

    def test_login_and_disconnect(self):
        shown, confirm = Mock(), Mock(return_value=True)
        account = self.login(show_url=shown, confirm=confirm)
        shown.assert_called_once()
        confirm.assert_called_once()
        self.assertEqual(load_accounts(self.config)[0], account)
        chatgpt.disconnect(account['id'])
        self.assertEqual(load_accounts(self.config), [])
        self.assertFalse(chatgpt.home_for(account['id']).exists())

    def test_login_wrong_identity_workspace_failure_cancel_and_url(self):
        for kwargs, expected in [({'email': 'other@example.invalid'}, 'Wrong ChatGPT email'),
                                 ({'workspace': 'Wrong'}, 'Wrong ChatGPT workspace'),
                                 ({'scenario': {'mode': 'login-failure'}}, 'sign-in failed'),
                                 ({'scenario': {'mode': 'port'}}, 'port 1455'),
                                 ({'scenario': {'accountId': None}}, 'Exact attribution'),
                                 ({'scenario': {'url': 'https://evil.invalid/'}}, 'unexpected sign-in URL'),
                                 ({'confirm': Mock(return_value=False)}, 'cancelled')]:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(chatgpt.AccountError, expected) as caught:
                    self.login(**kwargs)
                self.assertNotIn('fixture-secret', str(caught.exception))
                self.assertFalse(chatgpt.home_for('a'*32).exists())
                self.assertEqual(load_accounts(self.config), [])
        cancel = threading.Event()
        with self.assertRaisesRegex(chatgpt.AccountError, 'cancelled'):
            self.login(scenario={'mode': 'cancel'}, show_url=lambda _: cancel.set(), cancel=cancel)

    def test_duplicate_login_is_not_saved(self):
        existing = self.account()
        save_accounts([existing], self.config)
        with self.assertRaisesRegex(chatgpt.AccountError, 'Duplicate'):
            self.login()
        self.assertEqual(load_accounts(self.config), [existing])
        self.assertFalse(chatgpt.home_for('a'*32).exists())

    def test_disconnect_waits_for_reader_before_deleting_home(self):
        account = self.account()
        save_accounts([account], self.config)
        sessions = chatgpt.Sessions()
        self.addCleanup(sessions.close)
        sessions.reconcile([account])
        self.assertFalse(sessions.fetch(account).error)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(chatgpt.disconnect, self.identity)
            deadline = time.monotonic() + 2
            while load_accounts(self.config) and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertFalse(load_accounts(self.config))
            self.assertTrue(chatgpt.home_for(self.identity).exists())
            sessions.reconcile([])
            future.result(3)
        self.assertFalse(chatgpt.home_for(self.identity).exists())

    def test_only_valid_official_browser_urls(self):
        for value in (None, 123, 'https://auth.openai.com:bad/', 'https://auth.openai.com:8080/',
                      'https://auth.openai.com/\nunsafe', 'https://auth.openai.com/#access_token=fixture',
                      'https://user:password@auth.openai.com/', 'http://auth.openai.com/'):
            self.assertFalse(chatgpt.valid_auth_url(value))
        self.assertTrue(chatgpt.valid_auth_url('https://auth.openai.com/authorize?state=fixture'))

    def test_login_lock(self):
        with chatgpt.login_lock():
            with self.assertRaisesRegex(chatgpt.AccountError, 'Another tracker'):
                with chatgpt.login_lock():
                    self.fail('concurrent login allowed')

    def test_login_completion_timeout_and_close(self):
        server = self.server()
        with self.assertRaisesRegex(chatgpt.AccountError, 'timed out'):
            server.completion('absent', threading.Event(), timeout=.01)
        server.close()
        with self.assertRaises(chatgpt.AccountError):
            server.call('account/read')

    def test_reload_drops_children_and_discards_inflight(self):
        account = self.account(quota_delay=.15)
        sessions = chatgpt.Sessions()
        self.addCleanup(sessions.close)
        sessions.reconcile([account])
        self.assertFalse(sessions.fetch(account).error)
        server = sessions.servers[self.identity][1]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(sessions.fetch, account)
            time.sleep(.03)
            sessions.reconcile([])
            self.assertIsNotNone(future.result().error)
        self.assertIsNotNone(server.process.poll())
        self.assertFalse(sessions.servers)

    def test_secrets_redacted(self):
        account = self.account(quota_error=False)
        self.scenario(quota_error=True)
        sessions = chatgpt.Sessions()
        self.addCleanup(sessions.close)
        sessions.reconcile([account])
        result = sessions.fetch(account)
        self.assertTrue(result.error)
        self.assertNotIn('fixture-secret', json.dumps(result.to_dict()))

    def test_cli_connect_and_gui_entrypoint(self):
        with patch('sys.argv', ['token-tracker', 'connect', 'chatgpt', 'Account 1', '--email', 'a@example.invalid', '--workspace', 'Personal']), patch.object(chatgpt, 'connect', return_value={'id': 'test'}) as connect, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
            self.assertEqual(connect.call_args.args[:3], ('Account 1', 'a@example.invalid', 'Personal'))
        with patch('sys.argv', ['token-tracker', 'accounts']), patch('token_tracker.accounts.run', return_value=0) as run:
            self.assertEqual(main(), 0)
            run.assert_called_once()

    def test_collector_chatgpt_backoff_stale_and_reload(self):
        from token_tracker.waybar import Collector
        account = self.account()
        collector = Collector()
        self.addCleanup(collector.close)
        collector.tick([account])
        collector.pending[self.identity][1].result(2)
        result = collector.tick([account])[self.identity]
        self.assertFalse(result.error)
        # Finish the already-scheduled successful refresh before failing the next.
        collector.pending[self.identity][1].result(2)
        self.scenario(quota_error=True)
        collector.tick([account])
        collector.pending[self.identity][1].result(2)
        result = collector.tick([account])[self.identity]
        self.assertEqual(result.source, 'stale')
        self.assertTrue(result.error)
        self.assertEqual(result.updated_at, collector.results[self.identity].updated_at)
        self.assertNotIn(self.identity, collector.pending)
        self.assertGreater(collector.retry[self.identity], time.monotonic() + 290)
        changed = {**account, 'name': 'Renamed'}
        self.scenario()
        self.assertEqual(collector.tick([changed]), {})
        self.assertIn(self.identity, collector.pending)
        collector.pending[self.identity][1].result(2)
        collector.tick([])
        self.assertFalse(collector.results)

    def test_bad_managed_id_and_symlink(self):
        with self.assertRaises(chatgpt.AccountError):
            chatgpt.home_for('../../.codex')
        target = Path(self.temp.name) / 'other'
        target.mkdir()
        root = self.scenario()
        (root / 'credentials-link').symlink_to(target)
        with self.assertRaises(chatgpt.AccountError):
            chatgpt.Server(self.identity)
        self.assertTrue(target.exists())


if __name__ == '__main__':
    unittest.main()
