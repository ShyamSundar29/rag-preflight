"""Acceptance checks for generated messy real-format documents."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / 'scripts' / 'messy_document_acceptance.py'


class MessyDocumentAcceptanceTests(unittest.TestCase):
    def test_generated_real_format_acceptance(self):
        try:
            import docx  # noqa: F401
            import pptx  # noqa: F401
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest('rag-preflight[pdf,office] is unavailable')
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'acceptance.json'
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), '--output', str(output)],
                check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, '')
            payload = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(payload['fixture_kind'], 'generated_synthetic_edge_cases')
        self.assertEqual(payload['outcome'], 'incomplete')
        self.assertEqual(payload['metrics']['files_discovered'], 10)
        self.assertEqual(payload['metrics']['files_audited'], 6)
        self.assertEqual(payload['metrics']['unsupported_files'], 1)
        self.assertEqual(payload['metrics']['likely_image_only_units'], 1)
        self.assertEqual(payload['metrics']['missing_expected_files'], 1)
        self.assertEqual(payload['read_failure_reasons'],
                         ['empty_file', 'encrypted_pdf', 'invalid_pdf', 'invalid_utf8'])
        codes = {group['code'] for group in payload['finding_groups']}
        self.assertTrue({'source_read_failed', 'likely_image_only_page',
                         'missing_expected_source'}.issubset(codes))
        self.assertTrue(all(payload['expected_observations'].values()))
        self.assertTrue(any('not evidence from an external production corpus' in item
                            for item in payload['limitations']))
