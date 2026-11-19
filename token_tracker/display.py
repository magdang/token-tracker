"""Pure display formatting shared by native usage surfaces."""

from datetime import datetime, timezone
import math
import re
import unicodedata


def bounded(value, limit=240):
    text = ' '.join(''.join(c for c in str(value) if not unicodedata.category(c).startswith('C') or c in '\n\t\r').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def remaining(metric):
    if (not isinstance(metric.used, (int, float)) or not math.isfinite(metric.used) or metric.used < 0 or
            not isinstance(metric.limit, (int, float)) or not math.isfinite(metric.limit) or metric.limit <= 0):
        return None
    return max(0, min(1, 1 - metric.used / metric.limit))


def metric_value(metric):
    fraction = remaining(metric)
    if fraction is None:
        if metric.unit == 'credits':
            return f'{metric.used:g} credits · cap unknown'
        if metric.unit == 'USD':
            return f'${metric.used:,.2f} spent · no budget set'
        return 'Remaining unknown'
    if metric.unit == 'USD':
        return f'${max(0, metric.limit - metric.used):,.2f} left in budget'
    if metric.unit == '%':
        percent = fraction * 100
        # Keep tiny positive allowances distinct from exhausted and full quotas.
        if 0 < percent < .1:
            return '<0.1% left'
        if 99.9 < percent < 100:
            return '>99.9% left'
        return f'{round(percent, 1):g}% left'
    return f'{max(0, metric.limit - metric.used):g} {bounded(metric.unit, 24)} left'


def usage_detail(metric):
    if metric.unit == 'USD':
        text = f'${metric.used:,.2f} spent'
        if remaining(metric) is not None:
            text += f' of ${metric.limit:,.2f} budget'
            if metric.used > metric.limit:
                text += f' · ${metric.used - metric.limit:,.2f} over budget'
        return text
    if remaining(metric) is None and metric.unit == 'credits':
        return ''
    if remaining(metric) is None:
        return f'Used {metric.used:g} {bounded(metric.unit, 24)} · limit unknown'
    if metric.used >= metric.limit:
        return f'Used {metric.used:g} of {metric.limit:g} {bounded(metric.unit, 24)} · ' + ('limit exceeded' if metric.used > metric.limit else 'exhausted')
    return ''


def window_label(value):
    value = bounded(value, 128)
    match = re.fullmatch(r'(.*?) (primary|secondary) \((\d+) min\)', value)
    if not match:
        return bounded(value, 64)
    bucket, _, minutes = match.groups()
    minutes = int(minutes)
    if minutes % 1440 == 0:
        duration = f'{minutes // 1440}-day'
    elif minutes % 60 == 0:
        duration = f'{minutes // 60}-hour'
    else:
        duration = f'{minutes}-minute'
    return ('' if bucket == 'codex' else bounded(bucket, 32) + ' · ') + duration + ' window'


def duration(seconds):
    minutes = max(1, int(seconds // 60))
    days, hours = divmod(minutes // 60, 24)
    if days:
        return f'{days}d {hours}h'
    if hours:
        return f'{hours}h {minutes % 60}m'
    return f'{minutes}m'


def parse_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def observed_at(value, now=None):
    if not value:
        return 'Not yet updated'
    try:
        when = parse_time(value)
        if when.tzinfo is None:
            return 'Timestamp needs a timezone'
        seconds = ((now or datetime.now(timezone.utc)) - when).total_seconds()
        if seconds < 0:
            return 'Observation time is in the future'
        return 'Observed just now' if seconds < 60 else f'Observed {duration(seconds)} ago'
    except (ValueError, TypeError, AttributeError, OverflowError):
        return 'Unknown observation time'


def reset_text(value, now=None):
    try:
        reset = parse_time(value)
        if reset.tzinfo is None:
            return 'Reset time needs a timezone'
        seconds = (reset - (now or datetime.now(timezone.utc))).total_seconds()
        if seconds <= 0:
            return 'Reset passed · awaiting new snapshot'
        return f'Resets in {duration(math.ceil(seconds / 60) * 60)}'
    except (ValueError, TypeError, AttributeError, OverflowError):
        return 'Reset time unavailable'


def context_text(account, result, now=None):
    scope = {'chatgpt': 'Coding quota', 'codex-local': 'Local snapshot',
             'manual': 'Manual', 'openai-api': 'API costs · UTC month'}.get(account['provider'], '')
    if result.error or result.source == 'stale':
        scope = 'Stale · ' + scope if result.metrics else 'Unavailable · ' + scope
    return scope


def quota_notes(account, result):
    if account['provider'] != 'chatgpt':
        return ''
    pin = account.get('verified', {})
    identity = f"{pin.get('email')} · {pin.get('planType')} · workspace {pin.get('workspaceName') or pin.get('accountId')}"
    note = result.note.removeprefix(identity).strip()
    note = note.removeprefix('Coding quota only. ChatGPT website/model message limits unavailable.').strip()
    # Only provider quota details follow the verified identity in structured snapshots.
    return bounded(note) if result.note.startswith(identity) else ''
