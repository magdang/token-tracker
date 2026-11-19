"""Continuous Waybar JSON reporter; hover never starts provider requests."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from html import escape
from time import monotonic, sleep

from .core import Metric, Snapshot, fetch, keyring, load_accounts, timestamp


class Collector:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.pending = {}
        self.results = {}
        self.retry = {}
        self.keys = {}
        self.accounts = []

    def collect(self, account):
        if account['provider'] != 'openai-api':
            return fetch(account)
        identity = account['id']
        if identity not in self.keys:
            try:
                self.keys[identity] = keyring(identity)
            except Exception:
                self.keys[identity] = None
        if self.keys[identity] is None:
            return Snapshot(identity, 'unavailable', error='Keyring unavailable or key missing; run set-key, then reload Waybar.')
        return fetch(account, api_key=self.keys[identity])

    def tick(self, accounts):
        now = monotonic()
        for account in self.accounts:
            if account not in accounts:
                for state in (self.results, self.retry, self.keys):
                    state.pop(account["id"], None)
        self.accounts = [dict(a) for a in accounts]
        for identity, (account, future) in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[identity]
            if account not in accounts:
                continue
            try:
                result = future.result()
            except Exception:
                result = Snapshot(identity, 'unavailable', error='Provider refresh failed.')
            previous = self.results.get(identity)
            if result.error:
                if previous and previous.metrics:
                    result = replace(previous, source='stale', error=result.error)
                self.retry[identity] = now + 300
            else:
                self.retry[identity] = now
            self.results[identity] = result
        active = {a['id'] for a in accounts}
        for state in (self.results, self.retry, self.keys):
            for identity in set(state) - active:
                state.pop(identity, None)
        for account in accounts:
            identity = account['id']
            if identity not in self.pending and now >= self.retry.get(identity, 0):
                self.pending[identity] = (dict(account), self.pool.submit(self.collect, dict(account)))
        return {a['id']: self.results[a['id']] for a in accounts if a['id'] in self.results}


def markup(value):
    # Pango accepts XML characters only, even when markup delimiters are escaped.
    return escape("".join(c for c in value if c in "\t\n\r" or
                          0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or
                          0x10000 <= ord(c) <= 0x10FFFF))


def report(accounts, results, *, demo=False, error=None):
    lines = ['<b>AI usage' + (' · DEMO · sample data' if demo else '') + '</b>']
    if error:
        lines.append(markup(error))
    elif not accounts:
        lines.append('No accounts configured. Use token-tracker add to connect an account.')
    for account in accounts:
        lines.append('\n<b>' + markup(account['name']) + '</b>')
        result = results.get(account['id'])
        if result is None:
            lines.append('Checking…')
            continue
        lines.append(markup(result.source))
        for metric in result.metrics:
            value = f'{metric.used:g} / {metric.limit:g} {metric.unit}'
            lines.append(markup(f'{metric.label}: {value}'))
            if metric.resets_at:
                lines.append(markup(f'Resets: {metric.resets_at}'))
        if result.updated_at:
            lines.append(markup(f'Observed: {result.updated_at}'))
        if result.note:
            lines.append(markup(result.note))
        if result.error:
            lines.append(markup(result.error))
        if not result.metrics and not result.error:
            lines.append('No usage data available.')
    lines.append('\nUpdates every 5 seconds · failed providers retry after 5 minutes')
    return json.dumps({'text': 'AI DEMO' if demo else 'AI', 'tooltip': '\n'.join(lines),
                       'class': 'demo' if demo else 'usage'}, ensure_ascii=False)


def frame(collector, demo=False):
    if demo:
        accounts = [{'id': 'demo-personal', 'name': 'Personal · sample', 'provider': 'manual'},
                    {'id': 'demo-work', 'name': 'Work · sample', 'provider': 'manual'}]
        results = {a['id']: Snapshot(a['id'], 'DEMO', timestamp(),
                   [Metric('Session', used), Metric('Weekly', 35)], 'Sample data; no linked credentials.')
                   for a, used in zip(accounts, (72, 18))}
        return report(accounts, results, demo=True)
    try:
        accounts = load_accounts()
    except (ValueError, OSError, KeyError):
        return report([], {}, error='Cannot read account configuration. Check accounts.json, then wait for refresh.')
    return report(accounts, collector.tick(accounts))


def run(demo=False):
    collector = Collector()
    try:
        while True:
            print(frame(collector, demo), flush=True)
            sleep(5)
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    finally:
        collector.pool.shutdown(wait=False, cancel_futures=True)
