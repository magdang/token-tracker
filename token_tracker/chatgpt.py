"""Account-only Codex 0.170.0 client. Codex alone owns credentials and refresh."""

import atexit
from collections import deque
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from time import monotonic, sleep
from urllib.parse import urlsplit
import uuid

from .core import Metric, Snapshot, load_accounts, save_accounts, timestamp

STATE = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'token-tracker'
MAX_LINE = 256 * 1024
METHODS = frozenset(('initialize', 'account/read', 'account/login/start',
                     'account/login/cancel', 'account/logout', 'account/rateLimits/read'))
CONFIG_TEXT = '''sandbox_mode = "read-only"
approval_policy = "never"
cli_auth_credentials_store = "file"
forced_login_method = "chatgpt"
project_doc_max_bytes = 0
check_for_update_on_startup = false
mcp_servers = {}
[features]
plugins = false
plugin_hooks = false
codex_hooks = false
hooks = false
plugin_discovery_prefetch = false
recommended_plugins = false
apps = false
[cloud.skills]
enabled = false
[orchestrator.mcp]
enabled = false
'''


class AccountError(ValueError):
    """Only fixed, safe messages cross the transport boundary."""


def executable_file(value):
    path = Path(value)
    return (path.is_absolute() and not any(ord(c) < 32 for c in str(path))
            and path.is_file() and os.access(path, os.X_OK))


def resolve_codex(executable=None):
    """Resolve using the real home, before creating the isolated child environment."""
    directories = [p for p in os.environ.get('PATH', os.defpath).split(os.pathsep)
                   if p and Path(p).is_absolute() and Path(p).resolve() != Path.cwd()]
    search_path = os.pathsep.join(directories)
    override = executable if executable is not None else os.environ.get('TOKEN_TRACKER_CODEX')
    if override is not None:
        candidates = [os.fspath(override)]
    else:
        candidates = [str(Path(p) / 'codex') for p in directories]
        candidates += [str(Path.home() / p / 'codex') for p in ('.npm-global/bin', '.local/bin')]
    invalid = False
    for candidate in candidates:
        try:
            if override is None and Path(candidate).parent.resolve() == Path.cwd():
                continue
            if not executable_file(candidate):
                invalid |= Path(candidate).exists() or override is not None
                continue
            with open(candidate, 'rb') as stream:
                header = stream.readline(128).rstrip()
            command = [candidate]
            if header == b'#!/usr/bin/env node':
                node = next((str(Path(p) / 'node') for p in directories +
                             [str(Path(candidate).parent), '/usr/local/bin', '/usr/bin', '/bin']
                             if executable_file(Path(p) / 'node')), None)
                if node is None:
                    raise AccountError('Codex CLI was found, but Node.js is unavailable. Make its node executable available to the desktop session.')
                command = [node, candidate]
            return command, search_path
        except OSError:
            invalid = True
    if invalid:
        raise AccountError('Codex CLI was found or explicitly configured, but is not an accessible absolute executable. Check permissions or TOKEN_TRACKER_CODEX.')
    raise AccountError('Codex CLI was not found. Set TOKEN_TRACKER_CODEX to its absolute path, or install @openai/codex (tested with 0.170.0).')


def check_codex(command, env, cwd, timeout):
    try:
        result = subprocess.run([*command, '--version'], env=env, cwd=cwd,
                                capture_output=True, timeout=timeout, check=False, umask=0o077)
    except OSError:
        raise AccountError('Codex CLI was found but could not start. Check its executable and interpreter permissions.') from None
    except subprocess.TimeoutExpired:
        raise AccountError('Codex CLI version check timed out; check the configured executable.') from None
    if result.returncode:
        raise AccountError('Codex CLI was found but failed to start. Check its runtime installation; no account changes are needed.')
    if result.stdout.strip() != b'codex-cli 0.170.0':
        raise AccountError('Unsupported Codex CLI version or invalid executable. This account integration requires 0.170.0; set TOKEN_TRACKER_CODEX to a compatible executable.')


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise AccountError('Managed state must not contain symbolic links.')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def home_for(identity):
    if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{32}', identity):
        raise AccountError('Invalid managed ChatGPT connection ID; reconnect this account.')
    return STATE / 'chatgpt' / identity


def secure_tree(root):
    # Adjust metadata only; never open Codex credential files.
    for directory, dirs, files in os.walk(root, followlinks=False):
        private_dir(directory)
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink():
                relative = path.relative_to(root).parts
                # Codex creates executable aliases here on startup. Never chmod
                # their targets or allow linked directories/credential files.
                if (len(relative) == 5 and relative[:3] == ('codex', 'tmp', 'arg0-linux')
                        and relative[3].startswith('codex-arg0')
                        and name in ('applypatch', 'apply_patch', 'codex-linux-sandbox')
                        and name in files and path.is_file()):
                    continue
                raise AccountError('Managed state must not contain symbolic links.')
            path.chmod(0o700 if path.is_dir() else 0o600)


class Server:
    def __init__(self, identity, executable=None, timeout=15, cancel=None):
        self.timeout = timeout
        self.cancel = cancel
        self.condition = threading.Condition()
        self.write_lock = threading.Lock()
        self.operation = threading.Lock()
        self.waiters = {}
        self.notifications = deque(maxlen=32)
        self.serial = 0
        self.epoch = 0
        self.failure = None
        self.closed = False
        self.close_lock = threading.Lock()
        self.lease = None
        self.process = None
        command, search_path = resolve_codex(executable)
        private_dir(STATE)
        private_dir(STATE / 'chatgpt')
        self.root = private_dir(home_for(identity))
        for name in ('codex', 'home', 'work', 'config', 'data', 'cache'):
            private_dir(self.root / name)
        secure_tree(self.root)
        try:
            self.lease = os.open(self.root / 'connection.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            fcntl.flock(self.lease, fcntl.LOCK_SH)
            config = self.root / 'codex/config.toml'
            # This is exclusively app-owned config, never the user's Codex config.
            fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(CONFIG_TEXT)
                stream.write('\n[projects.' + json.dumps(str(self.root / 'work')) + ']\ntrust_level = "trusted"\n')
            env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'TZ', 'SSL_CERT_FILE', 'SSL_CERT_DIR')
                   if k in os.environ}
            env.update(HOME=str(self.root / 'home'), CODEX_HOME=str(self.root / 'codex'),
                       PATH=search_path,
                       XDG_CONFIG_HOME=str(self.root / 'config'), XDG_DATA_HOME=str(self.root / 'data'),
                       XDG_CACHE_HOME=str(self.root / 'cache'))
            check_codex(command, env, self.root / 'work', timeout)
            try:
                self.process = subprocess.Popen(
                    [*command, 'app-server', '--strict-config', '--listen', 'stdio://'],
                    cwd=self.root / 'work', env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, umask=0o077,
                )
            except OSError:
                raise AccountError('Codex CLI was found but app-server could not start. Check executable and interpreter permissions.') from None
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            self.call('initialize', {'clientInfo': {'name': 'token_tracker', 'version': '0.2'},
                                     'capabilities': {'experimentalApi': False}})
            self._send({'method': 'initialized'})
        except BaseException:
            self.close()
            raise

    def _fail(self, message):
        with self.condition:
            self.failure = message
            self.condition.notify_all()

    def _read(self):
        try:
            ignored = 0
            while True:
                line = self.process.stdout.readline(MAX_LINE + 1)
                if not line:
                    raise AccountError('Codex app-server stopped; check the CLI runtime and retry. No account changes are needed.')
                if len(line) > MAX_LINE or not line.endswith(b'\n'):
                    raise AccountError('Codex app-server exceeded its output limit.')
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    raise AccountError('Codex app-server returned malformed JSON.') from None
                if not isinstance(message, dict):
                    raise AccountError('Codex app-server returned an invalid response.')
                with self.condition:
                    identity = message.get('id')
                    if isinstance(identity, int) and identity in self.waiters:
                        self.waiters[identity] = message
                        ignored = 0
                    elif message.get('method') == 'account/login/completed':
                        if len(self.notifications) == self.notifications.maxlen:
                            raise AccountError('Too many Codex login notifications.')
                        self.notifications.append(message.get('params', {}))
                    elif message.get('method') == 'account/updated':
                        self.epoch += 1
                    else:
                        ignored += 1
                        if ignored > 128:
                            raise AccountError('Codex app-server exceeded its notification limit.')
                    self.condition.notify_all()
        except Exception as error:
            self._fail(str(error) if isinstance(error, AccountError) else 'Codex app-server transport failed.')

    def _send(self, message):
        try:
            with self.write_lock:
                self.process.stdin.write((json.dumps(message) + '\n').encode())
                self.process.stdin.flush()
        except (OSError, ValueError):
            raise AccountError('Codex app-server transport closed.') from None

    def call(self, method, params=None, timeout=None):
        if method not in METHODS:
            raise AccountError('Only account RPCs are permitted.')
        with self.condition:
            if self.cancel is not None and self.cancel.is_set():
                raise AccountError('Sign-in cancelled.')
            if self.closed or self.failure:
                raise AccountError(self.failure or 'Codex app-server is closed.')
            if len(self.waiters) >= 4:
                raise AccountError('Too many pending account requests.')
            self.serial += 1
            identity = self.serial
            self.waiters[identity] = None
        try:
            self._send({'id': identity, 'method': method, 'params': params or {}})
            deadline = monotonic() + (self.timeout if timeout is None else timeout)
            with self.condition:
                while True:
                    if self.cancel is not None and self.cancel.is_set():
                        raise AccountError('Sign-in cancelled.')
                    if self.failure or self.closed:
                        raise AccountError(self.failure or 'Codex app-server is closed.')
                    if self.waiters[identity] is not None:
                        break
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise AccountError('Codex account request timed out; retry later.')
                    self.condition.wait(min(.2, remaining))
                response = self.waiters[identity]
            if 'error' in response:
                # Remote errors may contain tokens/URLs. Never expose their text.
                if method == 'account/login/start':
                    raise AccountError('Sign-in could not start. Callback port 1455 may be in use by another Codex app; close its login window and retry. No process was killed.')
                raise AccountError('Codex account request failed; check sign-in and retry.')
            result = response.get('result')
            if not isinstance(result, dict):
                raise AccountError('Codex app-server returned an invalid account result.')
            return result
        finally:
            with self.condition:
                self.waiters.pop(identity, None)

    def completion(self, login_id, cancel, timeout=300):
        deadline = monotonic() + timeout
        with self.condition:
            while True:
                if cancel.is_set():
                    raise AccountError('Sign-in cancelled.')
                for event in list(self.notifications):
                    if isinstance(event, dict) and event.get('loginId') == login_id:
                        self.notifications.remove(event)
                        if event.get('success') is not True:
                            raise AccountError('ChatGPT sign-in failed. Please retry.')
                        return
                if self.failure or self.closed:
                    raise AccountError(self.failure or 'Codex app-server closed during sign-in.')
                if monotonic() >= deadline:
                    raise AccountError('ChatGPT sign-in timed out; please retry.')
                self.condition.wait(min(.2, max(0, deadline - monotonic())))

    def close(self):
        with self.close_lock:
            if not self.closed:
                self._close()

    def _close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        if self.process is not None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=1)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=1)
            if hasattr(self, 'reader') and self.reader is not threading.current_thread():
                self.reader.join(timeout=1)
            self.process.stdout.close()
        try:
            if hasattr(self, 'root') and self.root.exists():
                secure_tree(self.root)
        finally:
            if self.lease is not None:
                os.close(self.lease)
                self.lease = None


def nonempty(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 512 and all(ord(c) >= 32 for c in value)


def verified(server):
    first = server.call('account/read', {'refreshToken': False})
    epoch = server.epoch
    limits = server.call('account/rateLimits/read')
    last = server.call('account/read', {'refreshToken': False})
    if first != last or epoch != server.epoch:
        raise AccountError('Account changed during refresh; discarded response. Retry.')
    account = first.get('account')
    if not isinstance(account, dict) or account.get('type') != 'chatgpt':
        raise AccountError('No ChatGPT sign-in in this connection. Reconnect this account.')
    pin = {key: account.get(key) for key in ('email', 'planType', 'workspaceName')}
    pin.update(userId=first.get('userId'), accountId=limits.get('accountId'))
    if any(not nonempty(pin[key]) for key in ('email', 'planType', 'userId', 'accountId')) or pin['planType'] == 'unknown':
        raise AccountError('Exact attribution unavailable: Codex must expose email, plan, userId and quota accountId. Connection rejected; no ambient fallback.')
    if pin['workspaceName'] is not None and not nonempty(pin['workspaceName']):
        raise AccountError('Workspace metadata is invalid; reconnect this account.')
    routing = first.get('workspaceRouting')
    if routing is not None and (not isinstance(routing, dict) or routing.get('chatgptAccountId') != pin['accountId']):
        raise AccountError('Workspace and quota account IDs do not match; response rejected.')
    return pin, limits


def validate_pin(pin):
    if not isinstance(pin, dict) or set(pin) != {'email', 'planType', 'workspaceName', 'userId', 'accountId'}:
        raise AccountError('Missing verified identity; reconnect this account.')
    if any(not nonempty(pin[k]) for k in ('email', 'planType', 'userId', 'accountId')) or pin['planType'] == 'unknown':
        raise AccountError('Missing verified identity fields; reconnect this account.')
    if pin['workspaceName'] is not None and not nonempty(pin['workspaceName']):
        raise AccountError('Missing verified workspace; reconnect this account.')


def duplicate(pin, accounts, identity=None):
    for account in accounts:
        other = account.get('verified', {})
        if account.get('provider') == 'chatgpt' and account['id'] != identity and (
            other.get('userId') == pin['userId'] or other.get('accountId') == pin['accountId']
        ):
            raise AccountError('Duplicate ChatGPT user or workspace already connected. Quota would overlap; use the existing connection.')


def snapshot(account, limits):
    metrics, notes = [], ['Coding quota only. ChatGPT website/model message limits unavailable.']
    buckets = limits.get('rateLimitsByLimitId')
    if buckets is None:
        buckets = {'codex': limits.get('rateLimits')}
    if not isinstance(buckets, dict):
        raise AccountError('Invalid quota buckets from Codex.')
    for key, bucket in buckets.items():
        if not isinstance(bucket, dict):
            raise AccountError('Invalid quota bucket from Codex.')
        plan = bucket.get('planType')
        if plan is not None and plan != account['verified']['planType']:
            raise AccountError('Quota plan does not match the verified account.')
        name = bucket.get('limitName') or key
        if not nonempty(name):
            raise AccountError('Invalid quota bucket name.')
        for slot in ('primary', 'secondary'):
            window = bucket.get(slot)
            if window is None:
                notes.append(f'{name} {slot}: unknown.')
                continue
            used = window.get('usedPercent')
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) or used < 0:
                raise AccountError('Invalid quota percentage from Codex.')
            duration = window.get('windowDurationMins')
            if duration is not None and (type(duration) is not int or duration <= 0):
                raise AccountError('Invalid quota duration from Codex.')
            label = f'{name} {slot}' + (f' ({duration} min)' if duration is not None else ' (duration unknown)')
            reset = window.get('resetsAt')
            if reset is not None and type(reset) is not int:
                raise AccountError('Invalid quota reset from Codex.')
            from datetime import datetime, timezone
            metrics.append(Metric(label, used, resets_at=datetime.fromtimestamp(reset, timezone.utc).isoformat() if reset is not None else None))
        credits = bucket.get('credits')
        if credits is not None:
            if not isinstance(credits, dict):
                raise AccountError('Invalid credit information from Codex.')
            if credits.get('unlimited') is True:
                balance = 'unlimited'
            elif credits.get('balance') is not None:
                balance = str(credits['balance'])
                from decimal import Decimal, InvalidOperation
                try:
                    if not Decimal(balance).is_finite() or Decimal(balance) < 0:
                        raise InvalidOperation
                except InvalidOperation:
                    raise AccountError('Invalid credit balance from Codex.') from None
            else:
                balance = 'unknown'
            notes.append(f'{name} credits: {balance} (not USD).')
    pin = account['verified']
    notes.insert(0, f"{pin['email']} · {pin['planType']} · workspace {pin['workspaceName'] or pin['accountId']}")
    return Snapshot(account['id'], 'live · verified ChatGPT', timestamp(), metrics, ' '.join(notes))


class Sessions:
    """One persistent child per configured identity, bounded by the collector's pool."""
    def __init__(self):
        self.lock = threading.Lock()
        self.accounts = []
        self.servers = {}
        self.retired = set()
        self.closed = False
        atexit.register(self.close)

    def reconcile(self, accounts):
        with self.lock:
            self.accounts = [dict(a) for a in accounts if a['provider'] == 'chatgpt']
            obsolete = [self.servers.pop(k)[1] for k, (a, _) in list(self.servers.items()) if a not in self.accounts]
            for server in obsolete:
                # Keep ownership until reaped, without stalling five-second ticks.
                self.retired.add(server)
                server._fail('Connection removed or reconfigured; response discarded.')
                threading.Thread(target=self.retire, args=(server,), daemon=False).start()

    def retire(self, server):
        try:
            server.close()
        finally:
            with self.lock:
                self.retired.discard(server)

    def fetch(self, account):
        server = None
        try:
            validate_pin(account.get('verified'))
            with self.lock:
                if self.closed or account not in self.accounts:
                    raise AccountError('Connection removed or reconfigured; response discarded.')
                duplicate(account['verified'], self.accounts, account['id'])
                entry = self.servers.get(account['id'])
            if entry is None:
                server = Server(account['id'])
                with self.lock:
                    if self.closed or account not in self.accounts:
                        raise AccountError('Connection removed or reconfigured; response discarded.')
                    self.servers[account['id']] = (dict(account), server)
            else:
                server = entry[1]
            with server.operation:
                pin, limits = verified(server)
                if pin != account['verified']:
                    raise AccountError('Verified account/workspace changed or fields disappeared. Reconnect; quota rejected.')
                with self.lock:
                    if self.closed or account not in self.accounts:
                        raise AccountError('Connection removed or reconfigured; response discarded.')
                return snapshot(account, limits)
        except Exception as error:
            if server:
                server.close()
                with self.lock:
                    if self.servers.get(account['id'], (None, None))[1] is server:
                        self.servers.pop(account['id'])
            message = str(error) if isinstance(error, AccountError) else 'ChatGPT refresh failed; retry or reconnect.'
            return Snapshot(account['id'], 'unavailable', error=message)

    def close(self):
        with self.lock:
            self.closed = True
            servers = [s for _, s in self.servers.values()] + list(self.retired)
            self.servers.clear()
        for server in servers:
            server.close()
        atexit.unregister(self.close)


@contextmanager
def login_lock():
    private_dir(STATE)
    fd = os.open(STATE / 'login.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AccountError('Another tracker sign-in is running; finish or cancel it first.') from None
        yield
    finally:
        os.close(fd)


def valid_auth_url(value):
    if not isinstance(value, str) or len(value) > 16384 or any(ord(c) < 33 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and parsed.hostname == 'auth.openai.com'
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and not parsed.fragment)
    except ValueError:
        return False


def connect(name, email, workspace, show_url, confirm, cancel=None):
    """Only called by an explicit CLI/GUI action; never by a provider refresh."""
    if not nonempty(name) or not nonempty(email) or '@' not in email:
        raise AccountError('Enter an account name and expected ChatGPT email.')
    cancel = cancel or threading.Event()
    identity = uuid.uuid4().hex
    server, login_id, saved = None, None, False
    with login_lock():
        try:
            server = Server(identity, cancel=cancel)
            if server.call('account/read', {'refreshToken': False}).get('account') is not None:
                raise AccountError('New isolated home unexpectedly has an account; sign-in rejected.')
            if cancel.is_set():
                raise AccountError('Sign-in cancelled.')
            login = server.call('account/login/start', {'type': 'chatgpt'})
            login_id, url = login.get('loginId'), login.get('authUrl')
            if login.get('type') != 'chatgpt' or not nonempty(login_id) or not valid_auth_url(url):
                raise AccountError('Codex returned an unexpected sign-in URL; login rejected.')
            if cancel.is_set():
                raise AccountError('Sign-in cancelled.')
            show_url(url)
            server.completion(login_id, cancel)
            pin, _ = verified(server)
            if pin['email'].casefold() != email.strip().casefold():
                raise AccountError('Wrong ChatGPT email signed in; connection rejected.')
            if workspace and workspace not in (pin['workspaceName'], pin['accountId']):
                raise AccountError('Wrong ChatGPT workspace signed in; connection rejected.')
            duplicate(pin, load_accounts())
            if cancel.is_set() or not confirm(pin):
                raise AccountError('Sign-in cancelled; connection not saved.')
            # Re-read after confirmation: a queued notification is never identity proof.
            latest, _ = verified(server)
            if latest != pin or cancel.is_set():
                raise AccountError('Account changed before saving; connection rejected.')
            accounts = load_accounts()
            duplicate(pin, accounts)
            account = {'id': identity, 'provider': 'chatgpt', 'name': name, 'verified': pin}
            accounts.append(account)
            save_accounts(accounts)
            saved = True
            return account
        finally:
            if server:
                if not saved:
                    try:
                        if login_id:
                            server.call('account/login/cancel', {'loginId': login_id}, timeout=2)
                        server.call('account/logout', timeout=2)
                    except AccountError:
                        pass
                server.close()
            if not saved and home_for(identity).exists():
                shutil.rmtree(home_for(identity))


def disconnect(identity):
    """Remove config first, then only this app-owned home; never touch ~/.codex."""
    home = home_for(identity)
    with login_lock():
        accounts = load_accounts()
        if not any(a['id'] == identity and a['provider'] == 'chatgpt' for a in accounts):
            raise AccountError('Unknown ChatGPT connection.')
        save_accounts([a for a in accounts if a['id'] != identity])
        if home.exists():
            fd = os.open(home / 'connection.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                deadline = monotonic() + 20
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if monotonic() >= deadline:
                            raise AccountError('Connection removed. Managed credentials retained while a tracker reader is running; close tracker readers and retry cleanup from the managed state directory.') from None
                        sleep(.1)
                shutil.rmtree(home)
            finally:
                os.close(fd)
