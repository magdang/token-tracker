"""Continuous Waybar JSON reporter; hover never starts provider requests."""

import json
import signal
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from html import escape
from time import monotonic, sleep
from datetime import datetime, timedelta, timezone

from .core import Metric, Snapshot, fetch, keyring, load_accounts
from .display import (bounded, context_text, metric_value, quota_notes, remaining,
                      reset_text, usage_detail, window_label)


class Collector:
    def __init__(self):
        from .chatgpt import Sessions
        self.chatgpt = Sessions()
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.pending = {}
        self.results = {}
        self.retry = {}
        self.keys = {}
        self.accounts = []

    def close(self):
        self.chatgpt.close()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def collect(self, account):
        if account['provider'] == 'chatgpt':
            return self.chatgpt.fetch(account)
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
        self.chatgpt.reconcile(accounts)
        now = monotonic()
        for account in self.accounts:
            if account not in accounts:
                for state in (self.results, self.retry, self.keys):
                    state.pop(account["id"], None)
                if account["id"] in self.pending:
                    _, future = self.pending[account["id"]]
                    self.pending[account["id"]] = (None, future)
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
    return escape(bounded(value))


def report(accounts, results, *, demo=False, error=None, now=None):
    now = now or datetime.now(timezone.utc)
    compact = len(accounts) > 1 or sum(len(r.metrics) for r in results.values()) > 4
    font_size = (11 if compact else 12) * 1024
    lines = ['<b>AI usage' + (' · DEMO · sample data' if demo else '') + '</b>']
    if error:
        lines.append(markup(error))
    elif not accounts:
        lines.append('No accounts configured. Click AI to connect a ChatGPT account.')
    for account in accounts:
        lines.append('\n<b>' + markup(bounded(account['name'], 64)) + '</b>')
        result = results.get(account['id'])
        if result is None:
            lines.append('Checking…')
            continue
        lines.append(markup(context_text(account, result, now)))
        if result.error:
            lines.append('<b>' + markup(result.error) + '</b>')
        for metric in result.metrics:
            lines.append(('' if compact else '\n') + markup(window_label(metric.label)) + '   <span weight="bold">' + markup(metric_value(metric)) + '</span>')
            fraction = remaining(metric)
            if fraction is not None:
                filled = int(fraction * 20 + 1e-9)
                lines.append('<span font_family="monospace">' + '█' * filled + '<span alpha="40%">' + '░' * (20 - filled) + '</span></span>')
                if compact and metric.resets_at is not None:
                    lines[-1] += '  ' + markup(reset_text(metric.resets_at, now))
            detail = usage_detail(metric)
            if detail:
                lines.append(markup(detail))
            if metric.resets_at is not None and not (compact and fraction is not None):
                lines.append(markup(reset_text(metric.resets_at, now)))
        note = quota_notes(account, result)
        if note:
            lines.append(markup(note))
        if not result.metrics and not result.error:
            lines.append('No usage data available.')
    return json.dumps({'text': 'AI DEMO' if demo else 'AI', 'tooltip': f'<span font_family="sans-serif" size="{font_size}" weight="normal">' + '\n'.join(lines) + '</span>',
                       'class': 'demo' if demo else 'usage'}, ensure_ascii=False)


def frame(collector, demo=False):
    if demo:
        accounts = [{'id': 'demo-personal', 'name': 'Personal · sample', 'provider': 'chatgpt'},
                    {'id': 'demo-work', 'name': 'Work · sample', 'provider': 'openai-api'}]
        now = datetime.now(timezone.utc)
        results = {
            'demo-personal': Snapshot('demo-personal', 'DEMO', now.isoformat(), [
                Metric('codex primary (300 min)', 32, resets_at=(now + timedelta(hours=2, minutes=15)).isoformat()),
                Metric('codex secondary (10080 min)', 58, resets_at=(now + timedelta(days=3, hours=4)).isoformat())]),
            'demo-work': Snapshot('demo-work', 'DEMO', now.isoformat(), [Metric('Month to date', 12.4, 30, 'USD')]),
        }
        return report(accounts, results, demo=True)
    try:
        accounts = load_accounts()
    except (ValueError, OSError, KeyError):
        collector.chatgpt.reconcile([])
        return report([], {}, error='Cannot read account configuration. Check accounts.json, then wait for refresh.')
    return report(accounts, collector.tick(accounts))


def terminate(*_):
    raise SystemExit(0)


def run(demo=False):
    collector = Collector()
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        while True:
            print(frame(collector, demo), flush=True)
            sleep(5)
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    finally:
        collector.close()
        signal.signal(signal.SIGTERM, previous)
