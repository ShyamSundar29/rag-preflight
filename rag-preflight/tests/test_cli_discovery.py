"""Discoverable workflows and compatibility of legacy chunk file invocation."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from rag_preflight.cli import main, COMMANDS


class CLIDiscoveryTests(unittest.TestCase):
    def invoke(self, args):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                status = main(args)
            except SystemExit as exc:
                status = exc.code
        return status, out.getvalue(), err.getvalue()

    def test_top_help_lists_every_command(self):
        for args in (['--help'], ['-h']):
            status, out, err = self.invoke(args)
            self.assertEqual(status, 0, err)
            for command in COMMANDS:
                self.assertIn(command, out)
            self.assertIn('Legacy chunk audit', out)

    def test_workflow_help_is_reachable(self):
        for command in COMMANDS:
            status, out, err = self.invoke([command, '--help'])
            self.assertEqual(status, 0, err)
            self.assertIn('usage:', out)

    def test_unknown_command_has_actionable_error(self):
        status, out, err = self.invoke(['audit-index'])
        self.assertEqual(status, 2)
        self.assertIn('Unknown command', err)
        self.assertIn('existing-index', err)
        self.assertNotIn('No such file', err)

    def test_explicit_and_legacy_file_invocations_match(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chunks.json'
            path.write_text(json.dumps([{'text': 'Useful source text', 'metadata': {'source': 'a'}}]))
            self.assertEqual(self.invoke([str(path), '--json']),
                             self.invoke(['chunks', str(path), '--json']))
            bare = Path(directory) / 'extensionless'
            bare.write_text(path.read_text())
            self.assertEqual(self.invoke(['chunks', str(bare), '--json'])[0], 0)
            missing = Path(directory) / 'missing.json'
            self.assertIn('Input error:', self.invoke([str(missing)])[2])

    def test_no_arguments_fail_closed(self):
        status, out, err = self.invoke([])
        self.assertEqual(status, 2)
        self.assertEqual(out, '')
        self.assertIn('required', err)
        self.assertIn('--help', err)

    def test_console_no_arguments_and_help(self):
        import subprocess
        import sys
        for args, expected in (([], 2), (['--help'], 0)):
            result = subprocess.run([sys.executable, '-m', 'rag_preflight', *args],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stderr)
