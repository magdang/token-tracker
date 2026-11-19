#!/usr/bin/python3
"""Executable account-only fixture; never network, OAuth, or real credentials."""
import json
import os
from pathlib import Path
import sys
import time

root = Path(os.environ['CODEX_HOME']).parent
assert Path.cwd() == root / 'work'
assert os.environ['HOME'] == str(root / 'home')
assert not any(k.startswith(('OPENAI_', 'AZURE_', 'ANTHROPIC_', 'CODEX_')) and k != 'CODEX_HOME' for k in os.environ)
assert 'NODE_OPTIONS' not in os.environ
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.170.0')
    sys.exit(0)
scenario = root / 'fixture.json'
def options():
    return json.loads(scenario.read_text()) if scenario.exists() else {}

def emit(value):
    print(json.dumps(value), flush=True)

initialized = False
ready = False
logged_in = not options().get('signed_out', False)
login_started = False
post_login_calls = {}
held = None
for line in sys.stdin:
    request = json.loads(line)
    method = request['method']
    with (root / 'rpc.jsonl').open('a') as log:
        log.write(json.dumps(request) + '\n')
    assert method in ('initialize', 'initialized', 'account/read', 'account/rateLimits/read',
                      'account/login/start', 'account/login/cancel', 'account/logout'), method
    if method == 'initialized':
        assert initialized
        ready = True
        continue
    if method != 'initialize':
        assert ready, 'account RPC before initialized'
    opts = options()
    mode = opts.get('mode')
    if login_started:
        post_login_calls[method] = post_login_calls.get(method, 0) + 1
        if (method == opts.get('post_login_delay_method')
                and post_login_calls[method] == opts.get('post_login_delay_nth', 1)):
            (root / 'blocked').write_text(method)
            time.sleep(30)
    if method == 'initialize':
        initialized = True
        if mode == 'malformed':
            print('not json: fixture-secret', flush=True)
            continue
        if mode == 'long':
            print('x' * 300000, flush=True)
            continue
        if mode == 'stderr':
            sys.stderr.write('fixture-secret' * 200000)
            sys.stderr.flush()
        if mode == 'timeout':
            continue
        result = {}
    elif method == 'account/read':
        account = {'type': 'chatgpt', 'email': opts.get('email', 'test@example.invalid'),
                   'planType': opts.get('plan', 'plus'), 'workspaceName': opts.get('workspace', 'Personal')}
        result = {'account': account if logged_in else None,
                  'userId': opts.get('userId', 'user-fixture') if logged_in else None,
                  'requiresOpenaiAuth': True}
        if mode == 'routing-mismatch':
            result['workspaceRouting'] = {'chatgptAccountId': 'other-workspace'}
        if mode == 'out-of-order':
            if held is None:
                held = (request['id'], result)
                continue
            emit({'id': request['id'], 'result': result})
            emit({'id': held[0], 'result': held[1]})
            held = None
            continue
    elif method == 'account/rateLimits/read':
        if opts.get('quota_delay'):
            time.sleep(opts['quota_delay'])
        if opts.get('quota_error'):
            emit({'id': request['id'], 'error': {'message': 'Bearer fixture-secret'}})
            continue
        result = {'accountId': opts.get('accountId', 'workspace-fixture'),
                  'rateLimits': {'primary': {'usedPercent': 0, 'windowDurationMins': 300},
                                 'planType': opts.get('plan', 'plus')}}
        if mode == 'buckets':
            result['rateLimitsByLimitId'] = {
                'codex': result['rateLimits'],
                'review': {'primary': {'usedPercent': 37, 'windowDurationMins': 10080, 'resetsAt': 1800000000},
                           'credits': {'balance': '12.5', 'unlimited': False, 'hasCredits': True}}}
        if mode == 'account-change':
            emit({'method': 'account/updated', 'params': {}})
    elif method == 'account/login/start':
        login_started = True
        assert request['params'] == {'type': 'chatgpt'}
        if mode == 'port':
            emit({'id': request['id'], 'error': {'message': 'port 1455 fixture-secret'}})
            continue
        result = {'type': 'chatgpt', 'loginId': 'login-fixture',
                  'authUrl': opts.get('url', 'https://auth.openai.com/authorize?state=fixture')}
        if mode not in ('cancel', 'no-completion'):
            emit({'method': 'account/login/completed', 'params': {'loginId': 'unrelated', 'success': False}})
            # Intentionally arrives before the login/start response.
            emit({'method': 'account/login/completed', 'params': {
                'loginId': 'login-fixture', 'success': mode != 'login-failure', 'error': 'fixture-secret'}})
            logged_in = mode != 'login-failure'
    elif method == 'account/login/cancel':
        result = {'status': 'canceled'}
    elif method == 'account/logout':
        logged_in = False
        result = {}
    emit({'id': request['id'], 'result': result})
