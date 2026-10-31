"""Run from repository root: python -m unittest discover -s examples/database_summary -v"""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('summary_example', Path(__file__).with_name('agent.py'))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class DatabaseSummaryTests(unittest.TestCase):
    def test_success_uses_both_callbacks_and_records_outcomes(self):
        report = agent.run_workflow()
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['callback_counts'], {'database': 1, 'llm': 1})
        self.assertTrue(all(a['outcome'] == {'status': 'succeeded', 'source': 'application'}
                            for a in report['trace']['actions']))
        self.assertIn('3 matching', report['summary'])

    def test_unapproved_destination_never_calls_llm(self):
        report = agent.run_workflow('blocked-transfer')
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['callback_counts'], {'database': 1, 'llm': 0})
        codes = {f['code'] for a in report['last_pre_dispatch_evaluation']['actions'] for f in a['findings']}
        self.assertTrue({'DESTINATION_BOUNDARY', 'TOOL_FIELD_NOT_ALLOWED', 'OUTSIDE_TASK_RESOURCES'} <= codes)
        self.assertNotIn('outcome', report['trace']['actions'][-1])

    def test_record_limit_never_queries_database(self):
        report = agent.run_workflow('record-limit')
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['callback_counts'], {'database': 0, 'llm': 0})

    def test_database_exception_stops_workflow_with_unknown_outcome(self):
        report = agent.run_workflow('database-failure')
        self.assertEqual(report['status'], 'execution_failed')
        self.assertEqual(report['callback_counts'], {'database': 1, 'llm': 0})
        self.assertEqual(len(report['trace']['actions']), 1)
        self.assertEqual(report['trace']['actions'][0]['outcome']['status'], 'unknown')

    def test_llm_exception_retains_unknown_and_does_not_retry(self):
        report = agent.run_workflow('llm-failure')
        self.assertEqual(report['status'], 'execution_failed')
        self.assertEqual(report['callback_counts'], {'database': 1, 'llm': 1})
        self.assertEqual(report['trace']['actions'][-1]['outcome']['status'], 'unknown')

    def test_no_matches_skips_llm(self):
        report = agent.run_workflow(term='does not exist')
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['callback_counts'], {'database': 1, 'llm': 0})

    def test_search_term_is_parameterized_and_not_sql(self):
        report = agent.run_workflow(term="' OR 1=1 --")
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['callback_counts']['llm'], 0)

    def test_evaluator_failure_prevents_every_callback(self):
        def unavailable(*args):
            raise RuntimeError('offline')
        report = agent.run_workflow(evaluator=unavailable)
        self.assertEqual(report['status'], 'evaluation_unavailable')
        self.assertEqual(report['callback_counts'], {'database': 0, 'llm': 0})


if __name__ == '__main__':
    unittest.main()
