import json
import threading
import time
import unittest
from concurrent.futures import Future
from unittest.mock import patch
from xml.etree import ElementTree

from token_tracker.core import Metric, Snapshot
from token_tracker.waybar import Collector, frame, markup, report


class WaybarTests(unittest.TestCase):
    def setUp(self):
        self.accounts = [{'id': str(i), 'name': '<b>&"\' ' + str(i), 'provider': 'manual'} for i in range(2)]
        self.collector = Collector()

    def tearDown(self):
        self.collector.pool.shutdown(wait=True)

    def test_single_line_json_multi_account_and_markup(self):
        result = Snapshot('0', '<source>', 'now', [Metric('<Session>', 42)], '<note>', '<error>&"\'')
        raw = report(self.accounts, {'0': result})
        self.assertEqual(len(raw.splitlines()), 1)
        tooltip = json.loads(raw)['tooltip']
        parsed = ElementTree.fromstring('<root>' + tooltip + '</root>')
        text = ''.join(parsed.itertext())
        for part in (self.accounts[0]['name'], self.accounts[1]['name'], '<error>&"\'', '<Session>   58% left', 'Checking…'):
            self.assertIn(part, text)
        self.assertEqual(len(parsed.findall('.//b')), 4)

    def test_missing_and_demo(self):
        self.assertIn('No accounts configured', report([], {}))
        self.assertIn('No usage data', report(self.accounts[:1], {'0': Snapshot('0', 'manual')}))
        demo = json.loads(frame(self.collector, True))
        self.assertEqual(demo['text'], 'AI DEMO')
        self.assertIn('sample data', demo['tooltip'])
        self.assertIn('Work', demo['tooltip'])

    @patch('token_tracker.waybar.load_accounts', side_effect=ValueError('private config'))
    def test_malformed_config(self, load):
        value = frame(self.collector)
        self.assertIn('Cannot read account configuration', value)
        self.assertNotIn('private config', value)

    def test_slow_provider_does_not_block_or_overlap(self):
        release = threading.Event()
        def slow(account):
            release.wait(2)
            return Snapshot(account['id'], 'manual')
        try:
            with patch.object(self.collector, 'collect', side_effect=slow) as collect:
                start = time.monotonic()
                for _ in range(10):
                    self.collector.tick(self.accounts)
                self.assertLess(time.monotonic() - start, .5)
                self.assertEqual(len(self.collector.pending), 2)
                release.set()
                for _, future in self.collector.pending.values():
                    future.result(2)
                self.assertEqual(collect.call_count, 2)
        finally:
            release.set()

    def test_provider_failure_retains_stale_and_backs_off(self):
        account = self.accounts[0]
        self.collector.results['0'] = Snapshot('0', 'manual', metrics=[Metric('Session', 42)])
        future = Future()
        future.set_exception(RuntimeError('private provider body'))
        self.collector.pending['0'] = (account, future)
        result = self.collector.tick([account])['0']
        self.assertEqual(result.source, 'stale')
        self.assertEqual(result.metrics[0].used, 42)
        self.assertEqual(result.error, 'Provider refresh failed.')
        self.assertNotIn('0', self.collector.pending)

    @patch('token_tracker.waybar.keyring', side_effect=ValueError('locked'))
    def test_failed_keyring_is_not_reprompted(self, keyring):
        account = dict(self.accounts[0], provider='openai-api')
        for _ in range(3):
            self.assertIsNotNone(self.collector.collect(account).error)
        self.assertEqual(keyring.call_count, 1)

    @patch('token_tracker.waybar.fetch', return_value=Snapshot('0', 'reported'))
    @patch('token_tracker.waybar.keyring', return_value='test-only')
    def test_successful_keyring_cached(self, keyring, fetch):
        account = dict(self.accounts[0], provider='openai-api')
        for _ in range(3):
            self.collector.collect(account)
        self.assertEqual(keyring.call_count, 1)
        fetch.assert_called_with(account, api_key='test-only')

    def test_invalid_xml_characters_are_removed(self):
        self.assertEqual(markup("<&\x00\ud800\ufffe"), "&lt;&amp;")

    def test_changed_account_clears_cache_and_discards_inflight_result(self):
        old = self.accounts[0]
        changed = dict(old, name='Renamed')
        self.collector.accounts = [old]
        self.collector.results['0'] = Snapshot('0', 'old')
        future = Future()
        self.collector.pending['0'] = (old, future)
        self.assertEqual(self.collector.tick([changed]), {})
        future.set_result(Snapshot('0', 'old'))
        with patch.object(self.collector, 'collect', return_value=Snapshot('0', 'new')):
            self.assertEqual(self.collector.tick([changed]), {})
            self.assertEqual(self.collector.pending['0'][0], changed)

    def test_success_refreshes_on_next_tick_without_extra_delay(self):
        account = self.accounts[0]
        done = Future()
        done.set_result(Snapshot('0', 'manual'))
        self.collector.pending['0'] = (account, done)
        with patch.object(self.collector, 'collect', return_value=Snapshot('0', 'manual')):
            self.assertEqual(self.collector.tick([account])['0'].source, 'manual')
            self.assertIn('0', self.collector.pending)

    def test_switching_config_away_and_back_invalidates_pending_result(self):
        old = self.accounts[0]
        future = Future()
        self.collector.accounts = [old]
        self.collector.pending['0'] = (old, future)
        changed = dict(old, name='Changed')
        self.collector.tick([changed])
        self.collector.tick([old])
        future.set_result(Snapshot('0', 'superseded'))
        with patch.object(self.collector, 'collect', return_value=Snapshot('0', 'new')):
            self.assertEqual(self.collector.tick([old]), {})

    def test_four_worker_bound(self):
        release = threading.Event()
        entered = []
        def wait(account):
            entered.append(account['id'])
            release.wait(2)
            return Snapshot(account['id'], 'manual')
        accounts = [dict(self.accounts[0], id=str(n)) for n in range(8)]
        try:
            with patch.object(self.collector, 'collect', side_effect=wait):
                self.collector.tick(accounts)
                deadline = time.monotonic() + 1
                while len(entered) < 4 and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertEqual(len(entered), 4)
                self.assertEqual(len(self.collector.pending), 8)
                release.set()
                for _, future in self.collector.pending.values():
                    future.result(2)
        finally:
            release.set()
