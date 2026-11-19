"""Desktop discovery uses temporary executables, never real accounts."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from token_tracker import chatgpt

FIXTURE = Path(__file__).parent / 'fixtures/fake_codex.py'


class ExecutableTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        for patcher in (patch.dict(os.environ, {'HOME': str(self.home), 'PATH': ''}, clear=True),
                        patch.object(chatgpt, 'STATE', self.home / 'state')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def executable(self, name, text='#!/bin/sh\nexit 0\n'):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o700)
        return path

    def test_path_precedence_and_known_user_installs(self):
        npm = self.executable('.npm-global/bin/codex')
        local = self.executable('.local/bin/codex')
        ordinary = self.executable('bin/codex')
        with patch.dict(os.environ, PATH=str(ordinary.parent)):
            self.assertEqual(chatgpt.resolve_codex()[0], [str(ordinary)])
        self.assertEqual(chatgpt.resolve_codex()[0], [str(npm)])
        npm.unlink()
        self.assertEqual(chatgpt.resolve_codex()[0], [str(local)])

    def test_explicit_argument_and_environment_override(self):
        explicit = self.executable('custom/codex')
        with patch.dict(os.environ, TOKEN_TRACKER_CODEX='/missing'):
            self.assertEqual(chatgpt.resolve_codex(explicit)[0], [str(explicit)])
            with self.assertRaisesRegex(chatgpt.AccountError, 'accessible absolute'):
                chatgpt.resolve_codex()
        with patch.dict(os.environ, TOKEN_TRACKER_CODEX=str(explicit)):
            self.assertEqual(chatgpt.resolve_codex()[0], [str(explicit)])
        server = chatgpt.Server('1' * 32, executable=FIXTURE.resolve())
        self.addCleanup(server.close)
        self.assertIn('account', server.call('account/read'))

    def test_missing_invalid_inaccessible_and_malformed(self):
        with self.assertRaisesRegex(chatgpt.AccountError, 'not found'):
            chatgpt.resolve_codex()
        invalid = self.executable('.npm-global/bin/codex')
        invalid.chmod(0o600)
        with self.assertRaisesRegex(chatgpt.AccountError, 'accessible absolute'):
            chatgpt.resolve_codex()
        for value in ('relative/codex', '', '/bad\x00path', str(self.home)):
            with self.subTest(value=repr(value)), self.assertRaises(chatgpt.AccountError):
                chatgpt.resolve_codex(value)
        invalid.chmod(0o700)
        invalid.write_text('not an executable format')
        with self.assertRaisesRegex(chatgpt.AccountError, 'could not start'):
            chatgpt.Server('1' * 32)

    def test_never_search_cwd_empty_or_relative_path(self):
        self.executable('codex', '#!/bin/sh\ntouch SHOULD_NOT_RUN\n')
        with patch.object(Path, 'cwd', return_value=self.home):
            for value in ('', ':', '.:bin', ':' + str(self.home) + ':'):
                with patch.dict(os.environ, PATH=value):
                    with self.assertRaisesRegex(chatgpt.AccountError, 'not found'):
                        chatgpt.resolve_codex()
        self.assertFalse((self.home / 'SHOULD_NOT_RUN').exists())

    def test_npm_launcher_gets_absolute_node_with_empty_path(self):
        launcher = self.executable('.npm-global/bin/codex', '#!/usr/bin/env node\nunused fixture\n')
        # Fixture interpreter proves the resolved Node command is actually invoked.
        node = self.executable('.npm-global/bin/node',
                               '#!/usr/bin/python3\nimport os, sys\n'
                               'assert sys.argv[1].endswith("/codex")\n'
                               f'os.execv({str(FIXTURE.resolve())!r}, ["codex", *sys.argv[2:]])\n')
        command, path = chatgpt.resolve_codex()
        self.assertEqual(command, [str(node), str(launcher)])
        self.assertEqual(path, '')
        server = chatgpt.Server('1' * 32)
        self.addCleanup(server.close)
        self.assertIn('account', server.call('account/read'))
        with patch.object(chatgpt, 'executable_file', side_effect=lambda p: str(p) == str(launcher)):
            with self.assertRaisesRegex(chatgpt.AccountError, 'Node.js is unavailable'):
                chatgpt.resolve_codex()

    def test_startup_failures_are_safe_and_distinct(self):
        for body, message in [('echo secret >&2; exit 1', 'failed to start'),
                              ('echo codex-cli 0.1.0', 'Unsupported'),
                              ('exec sleep 2', 'timed out')]:
            executable = self.executable('custom/codex', '#!/bin/sh\n' + body + '\n')
            with patch.dict(os.environ, PATH='/usr/bin:/bin'):
                with self.assertRaisesRegex(chatgpt.AccountError, message) as caught:
                    chatgpt.Server('1' * 32, executable=executable, timeout=.05)
            self.assertNotIn('secret', str(caught.exception))
        with patch.object(chatgpt.subprocess, 'run', side_effect=PermissionError('secret')):
            with self.assertRaisesRegex(chatgpt.AccountError, 'could not start'):
                chatgpt.check_codex(['/not-used'], {}, self.home, 1)
        with patch.object(chatgpt, 'check_codex'), patch.object(chatgpt.subprocess, 'Popen', side_effect=PermissionError('secret')):
            with self.assertRaisesRegex(chatgpt.AccountError, 'app-server could not start'):
                chatgpt.Server('1' * 32, executable=executable)
