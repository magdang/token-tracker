from datetime import datetime, timezone
import json
import unittest
from xml.etree import ElementTree

from token_tracker.core import Metric, Snapshot
from token_tracker.display import (bounded, context_text, metric_value, observed_at,
                                   quota_notes, remaining, reset_text, usage_detail, window_label)
from token_tracker.waybar import report

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


class DisplayTests(unittest.TestCase):
    def tooltip(self, metrics):
        raw = json.loads(report([{'id': 'one', 'name': 'Sample', 'provider': 'manual'}],
                               {'one': Snapshot('one', 'manual', NOW.isoformat(), metrics)}, now=NOW))['tooltip']
        ElementTree.fromstring('<root>' + raw + '</root>')
        return raw

    def test_remaining_and_constant_bar_width(self):
        for used, left, filled in [(0, '100%', 20), (100, '0%', 0), (32, '68%', 13), (125, '0%', 0)]:
            with self.subTest(used=used):
                metric = Metric('Quota', used)
                self.assertEqual(metric_value(metric), left + ' left')
                raw = self.tooltip([metric])
                self.assertEqual(raw.count('█'), filled)
                self.assertEqual(raw.count('░'), 20 - filled)
        self.assertIn('125', usage_detail(Metric('Quota', 125)))
        self.assertIn('exceeded', self.tooltip([Metric('Quota', 125)]))
        self.assertIn('exhausted', self.tooltip([Metric('Quota', 100)]))

    def test_denominator_and_small_remainders(self):
        self.assertEqual(metric_value(Metric('Quota', 1, 4)), '75% left')
        self.assertEqual(metric_value(Metric('Quota', 99.999)), '<0.1% left')
        self.assertEqual(metric_value(Metric('Quota', .001)), '>99.9% left')
        self.assertEqual(remaining(Metric('Quota', 1, 4)), .75)

    def test_unknown_limits_have_no_bars(self):
        for cap in (0, None, -1, float('nan'), float('inf')):
            with self.subTest(cap=cap):
                metric = Metric('Quota', 42, cap)
                self.assertIsNone(remaining(metric))
                raw = self.tooltip([metric])
                self.assertIn('Remaining unknown', raw)
                self.assertNotIn('█', raw)
                self.assertNotIn('░', raw)
                self.assertNotIn('100% left', raw)
        self.assertIsNone(remaining(Metric('Quota', float('nan'))))
        self.assertIsNone(remaining(Metric('Quota', -1)))

    def test_budget_is_not_provider_balance(self):
        metric = Metric('Budget', 12.4, 30, 'USD')
        self.assertEqual(metric_value(metric), '$17.60 left in budget')
        self.assertIn('$12.40 spent of $30.00 budget', usage_detail(metric))
        over = Metric('Budget', 32, 30, 'USD')
        self.assertEqual(metric_value(over), '$0.00 left in budget')
        self.assertIn('$2.00 over budget', usage_detail(over))
        raw = self.tooltip([Metric('Costs', 12.4, 0, 'USD')])
        self.assertIn('no budget set', raw)
        self.assertNotIn('█', raw)

    def test_unbounded_credits(self):
        raw = self.tooltip([Metric('Balance', 12.5, 0, 'credits')])
        self.assertIn('12.5 credits · cap unknown', raw)
        for absent in ('$', '% left', '█', 'Used 12.5'):
            self.assertNotIn(absent, raw)
        account = {'provider': 'chatgpt', 'verified': {'email': 'private@example.test', 'planType': 'plus', 'accountId': 'private-id'}}
        result = Snapshot('one', 'live', note='private@example.test · plus · workspace private-id Coding quota only. ChatGPT website/model message limits unavailable. codex secondary: unknown. codex credits: 12.5 (not USD).')
        note = quota_notes(account, result)
        self.assertEqual(note, 'codex secondary: unknown. codex credits: 12.5 (not USD).')
        raw = json.loads(report([dict(account, id='one', name='Alias')], {'one': result}, now=NOW))['tooltip']
        self.assertIn('secondary: unknown', raw)
        self.assertNotIn('private', raw)
        self.assertNotIn('█', raw)

    def test_reported_window_durations(self):
        for minutes, expected in [(300, '5-hour'), (10080, '7-day'), (90, '90-minute')]:
            self.assertEqual(window_label(f'codex primary ({minutes} min)'), expected + ' window')
        self.assertEqual(window_label('Review secondary (60 min)'), 'Review · 1-hour window')
        self.assertIn('duration unknown', window_label('codex primary (duration unknown)'))
        self.assertEqual(window_label('Custom window'), 'Custom window')

    def test_reset_dates_and_timezones(self):
        self.assertEqual(reset_text('2026-11-19T17:15:00+03:00', NOW), 'Resets in 2h 15m')
        self.assertEqual(reset_text('2026-11-22T16:00:00Z', NOW), 'Resets in 3d 4h')
        self.assertEqual(reset_text('2026-11-19T12:00:01Z', NOW), 'Resets in 1m')
        for value in ('2026-11-19T11:59:59Z', NOW.isoformat()):
            self.assertEqual(reset_text(value, NOW), 'Reset passed · awaiting new snapshot')
        self.assertEqual(reset_text('2026-11-19T15:00:00', NOW), 'Reset time needs a timezone')
        for value in ('bad', 42, None):
            self.assertEqual(reset_text(value, NOW), 'Reset time unavailable')

    def test_freshness_and_failed_live_query(self):
        self.assertEqual(observed_at(NOW.isoformat(), NOW), 'Observed just now')
        self.assertEqual(observed_at('2026-11-19T10:45:00Z', NOW), 'Observed 1h 15m ago')
        self.assertIn('future', observed_at('2026-11-20T12:00:00Z', NOW))
        account = {'provider': 'chatgpt', 'id': 'one', 'name': 'Alias'}
        result = Snapshot('one', 'live', '2026-11-18T12:00:00Z', [Metric('Quota', 42)], error='Sign-in failed <retry>')
        raw = json.loads(report([account], {'one': result}, now=NOW))['tooltip']
        for expected in ('Stale', 'Observed 1d 0h ago', 'Sign-in failed &lt;retry&gt;', 'Coding quota'):
            self.assertIn(expected, raw)
        for provider, scope in [('manual', 'Manual'), ('codex-local', 'Local snapshot')]:
            self.assertIn(scope, context_text(dict(account, provider=provider), result, NOW))

    def test_hostile_content_is_escaped_and_bounded(self):
        evil = '<span size="999999">&\x00\ud800\ufffe\u202e\n' + 'a' * 10000
        account = {'provider': 'manual', 'id': 'not-visible', 'name': evil}
        result = Snapshot('one', evil, metrics=[Metric(evil, 42, unit=evil)], error=evil, note=evil)
        raw = json.loads(report([account], {'not-visible': result}, now=NOW))['tooltip']
        ElementTree.fromstring('<root>' + raw + '</root>')
        self.assertNotIn('<span size="999999">', raw)
        self.assertNotIn('not-visible', raw)
        self.assertNotIn('\u202e', raw)
        self.assertIn('&lt;span', raw)
        self.assertLess(len(raw), 2000)
        self.assertEqual(len(bounded('a' * 10000)), 240)
        self.assertLessEqual(len(window_label('codex primary (' + '9' * 10000 + ' min)')), 64)
