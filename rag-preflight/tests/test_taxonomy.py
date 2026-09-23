"""Keep finding documentation synchronized with emitted source codes."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def emitted_codes(source: str) -> set[str]:
    tree = ast.parse(source)
    builders = {n.targets[0].id for n in ast.walk(tree)
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                and n.value.func.id == 'EvidenceBuilder'}
    def values(expr):
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return {expr.value}
        if isinstance(expr, ast.IfExp):
            return values(expr.body) | values(expr.orelse)
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == 'code':
            # Current compatibility adapter emits page aliases and unit codes.
            base = values(expr.args[0])
            return base | {c.replace('pages', 'units').replace('page', 'unit') for c in base}
        raise ValueError(f'Unsupported finding-code expression: {ast.dump(expr)}')
    found = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        constructor = isinstance(n.func, ast.Name) and n.func.id in ('Finding', 'Issue')
        emitter = isinstance(n.func, ast.Name) and n.func.id == 'add'
        builder = (isinstance(n.func, ast.Attribute) and n.func.attr == 'add'
                   and isinstance(n.func.value, ast.Name) and n.func.value.id in builders)
        if not (constructor or emitter or builder):
            continue
        expr = n.args[0] if n.args else next(k.value for k in n.keywords if k.arg == 'code')
        # Existing constructors forward codes from helper arguments or audited
        # issues. New expressions in emission sites must be handled explicitly.
        if constructor and (isinstance(expr, ast.Name) and expr.id == 'code'
                            or isinstance(expr, ast.Attribute) and ast.dump(expr) == ast.dump(ast.parse('issue.code', mode='eval').body)):
            continue
        found.update(values(expr))
    return found


class TaxonomyTests(unittest.TestCase):
    def test_all_emitted_codes_have_table_entries(self):
        codes = set().union(*(emitted_codes(p.read_text()) for p in (ROOT/'src/rag_preflight').glob('*.py')))
        documented = set(re.findall(r'^\|\s*([a-z][a-z0-9_]*)\s*\|', (ROOT/'docs/failures.md').read_text(), re.M))
        self.assertTrue(codes)
        self.assertFalse(codes-documented, f'Undocumented finding codes: {sorted(codes-documented)}')

    def test_new_code_and_aliases_are_detected(self):
        codes = emitted_codes("add('new_code', 'message'); add(code('missing_chunk_pages'), 'message')")
        self.assertEqual(codes, {'new_code', 'missing_chunk_pages', 'missing_chunk_units'})
        self.assertEqual(emitted_codes("builder = EvidenceBuilder(5); builder.add('other_code')"), {'other_code'})
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            emitted_codes('add(dynamically_built_code, "message")')
