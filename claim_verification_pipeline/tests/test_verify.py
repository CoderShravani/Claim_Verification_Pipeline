import json
from unittest import mock
import urllib.error
import tempfile
import unittest
from pathlib import Path
import verify

class VerifierUnitTests(unittest.TestCase):
    def test_normalization_allows_whitespace_and_punctuation_variants(self):
        self.assertEqual(verify.norm('HbA1c −1.6%'), verify.norm('HbA1c -1.6%'))

    def test_quote_validation_requires_exact_normalized_substring(self):
        pages = [{'file':'study.pdf','page':2,'text':'HbA1c decreased by 1.6% at Week 30.'}]
        ok, page = verify.validate_quote({'evidence_span':'HbA1c decreased by 1.6% at Week 30.', 'evidence_file':'study.pdf', 'evidence_page':2}, pages)
        self.assertTrue(ok)
        self.assertEqual(page['page'], 2)
        ok, _ = verify.validate_quote({'evidence_span':'HbA1c decreased by 9.9% at Week 30.', 'evidence_file':'study.pdf', 'evidence_page':2}, pages)
        self.assertFalse(ok)
        ok, _ = verify.validate_quote({
            'evidence_span':'HbA1c decreased by 1.6% at Week 30.',
            'evidence_file':None, 'evidence_page':None
        }, pages)
        self.assertFalse(ok)

    def test_supported_is_downgraded_when_any_required_check_is_not_match(self):
        result = {
            'verdict': 'supported',
            'checks': {'figure':'match','population':'match','drug_indication':'match','actually_stated':'unclear'},
            'reason': 'Evidence is incomplete.'
        }
        verified = verify.enforce_supported_checks(result)
        self.assertEqual(verified['verdict'], 'cannot_verify')
        self.assertIn('not all four required checks', verified['reason'])

    def test_supported_is_preserved_when_all_four_checks_match(self):
        result = {
            'verdict': 'supported',
            'checks': {'figure':'match','population':'match','drug_indication':'match','actually_stated':'match'},
            'reason': 'All checks match.'
        }
        self.assertEqual(verify.enforce_supported_checks(result)['verdict'], 'supported')

    def test_model_result_rejects_missing_or_wrongly_typed_fields(self):
        valid = {
            'verdict':'supported',
            'checks': {'figure':'match','population':'match','drug_indication':'match','actually_stated':'match'},
            'evidence_file':'study.pdf', 'evidence_page':2,
            'evidence_span':'Exact source quote.', 'reason':'Matches source.',
            'source_numbers':[1.2, 3]
        }
        verify.validate_model_result(valid)
        bad = dict(valid)
        bad['evidence_page'] = True
        with self.assertRaises(ValueError):
            verify.validate_model_result(bad)
        bad = dict(valid)
        bad['unexpected'] = 'extra'
        with self.assertRaises(ValueError):
            verify.validate_model_result(bad)

    def test_network_error_becomes_fail_closed_result(self):
        claim = {'claim_id':'X','text':'Example claim','cited_paper':'study.pdf'}
        pages = [{'file':'study.pdf','page':1,'text':'Some relevant evidence with Example claim.'}]
        with mock.patch.object(verify, 'call_openai', side_effect=RuntimeError('LLM API connection failed (URLError)')):
            result = verify.verify_one(claim, pages, Path('/tmp/test_llm_log.jsonl'))
        self.assertEqual(result['verdict'], 'cannot_verify')
        self.assertIsNone(result['evidence_span'])

    def test_url_error_is_logged_and_raised_as_controlled_runtime_error(self):
        claim = {'claim_id':'X','text':'Example claim'}
        candidates = [{'file':'study.pdf','page':1,'text':'Evidence text'}]
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / 'llm_log.jsonl'
            with mock.patch.dict('os.environ', {'OPENAI_API_KEY':'test-key'}):
                with mock.patch.object(verify.urllib.request, 'urlopen',
                                       side_effect=urllib.error.URLError('offline')):
                    with self.assertRaisesRegex(RuntimeError, 'connection failed'):
                        verify.call_openai(claim, candidates, log_path)
            lines = log_path.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 1)
            logged = json.loads(lines[0])
            self.assertIn('network_error', logged['raw_response'])
            self.assertNotIn('test-key', json.dumps(logged))

    def test_unexpected_claim_failure_does_not_abort_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'papers').mkdir()
            (root / 'outputs').mkdir()
            (root / 'data' / 'claims.json').write_text(json.dumps([
                {'claim_id':'A','text':'first'},
                {'claim_id':'B','text':'second'}
            ]), encoding='utf-8')
            original_root = verify.ROOT
            try:
                with mock.patch.object(verify, 'load_pdfs', return_value=[]):
                    with mock.patch.object(verify, 'verify_one',
                        side_effect=[RuntimeError('unexpected'), {
                            'claim_id':'B','verdict':'cannot_verify','checks':{},
                            'evidence_file':None,'evidence_page':None,'evidence_span':None,
                            'computed':None,'reason':'test'
                        }]):
                        with mock.patch('sys.argv', ['verify.py', 'data/claims.json', '--root', str(root)]):
                            self.assertEqual(verify.main(), 0)
                output = json.loads((root / 'outputs' / 'predictions.json').read_text(encoding='utf-8'))
                self.assertEqual(len(output), 2)
                self.assertEqual(output[0]['verdict'], 'cannot_verify')
                self.assertEqual(output[1]['claim_id'], 'B')
            finally:
                verify.ROOT = original_root

    def test_numeric_audit_handles_twofold_claim_from_explicit_values(self):
        claim = '~2x greater HbA1c reduction vs basal insulin, reduction from baseline'
        evidence = 'Greater reductions compared with iGlar (−1.6%, −1.3%, respectively)'
        result = verify.python_numeric_audit(claim, evidence)
        self.assertIsNotNone(result)
        self.assertEqual(result['computed_ratio'], 1.23)
        self.assertFalse(result['matches_claim'])

    def test_fail_closed_schema(self):
        out = verify.fail_closed({'claim_id':'X'}, 'test')
        self.assertEqual(out['claim_id'], 'X')
        self.assertEqual(out['verdict'], 'cannot_verify')
        self.assertIsNone(out['evidence_span'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
