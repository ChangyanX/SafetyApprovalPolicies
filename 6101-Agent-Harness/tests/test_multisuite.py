"""Offline semantic coverage and multi-domain experiment-plan invariants."""
from collections import Counter
import hashlib
import inspect
from pathlib import Path
import tempfile
import unittest

from agentdojo.task_suite.load_suites import get_suites
from src.experiment_runner import build_experiment_plan, main, save_plan_csv
from src.risk_based_policy import RiskBasedPolicy
from src.tool_risk import load_tool_risk_metadata, risk_for
from src.types import GateInput, Decision

CATALOG = Path(__file__).resolve().parents[1] / 'src/tool_risk_metadata.yaml'


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_tool_risk_metadata(CATALOG)

    def test_registered_tool_coverage_and_source_signatures(self):
        total = 0
        for name, suite in get_suites('v1.2.2').items():
            self.assertEqual(set(self.catalog.suites[name]), {t.name for t in suite.tools})
            for tool in suite.tools:
                meta = risk_for(self.catalog, tool.name, name)
                self.assertEqual(meta['parameters'], list(tool.parameters.model_json_schema()['properties']))
                self.assertEqual(meta['source_sha256'], hashlib.sha256(inspect.getsource(tool.run).encode()).hexdigest())
                self.assertIn('operation', meta['scope_checks'])
                self.assertIn('provenance', meta['scope_checks'])
                total += 1
        self.assertEqual(total, 74)

    def test_namespace_isolation_and_ambiguous_fallback(self):
        self.assertNotIn('source', risk_for(self.catalog, 'get_balance', 'workspace'))
        self.assertEqual(risk_for(self.catalog, 'get_balance', 'workspace')['default_decision'], 'ESCALATE')
        self.assertNotIn('source', risk_for(self.catalog, 'send_email'))
        self.assertIn('source', risk_for(self.catalog, 'send_email', 'travel'))
        with self.assertRaises(ValueError):
            risk_for(self.catalog, 'get_balance', 'invalid_suite')

    def test_nonobvious_semantics(self):
        self.assertEqual(risk_for(self.catalog, 'post_webpage', 'slack')['action_family'], 'publication')
        self.assertIn('simulated web_requests', risk_for(self.catalog, 'get_webpage', 'slack')['semantic_notes'])
        self.assertEqual(risk_for(self.catalog, 'reserve_hotel', 'travel')['implicit_data_fields'], ['user.Phone Number'])

    def test_legacy_yaml(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.yaml'
            path.write_text('defaults:\n  risk: medium\n  default_decision: ESCALATE\ntools:\n  lookup:\n    risk: low\n    default_decision: AUTO_APPROVE\n')
            md = load_tool_risk_metadata(path)
            self.assertEqual(risk_for(md, 'lookup')['default_decision'], 'AUTO_APPROVE')
            self.assertEqual(risk_for(md, 'missing')['default_decision'], 'ESCALATE')

    def test_risk_policy_uses_suite_and_explicit_escalation(self):
        for suite, tool in [('workspace', 'send_email'), ('travel', 'reserve_hotel'),
                            ('banking', 'get_balance'), ('slack', 'send_direct_message')]:
            gi = GateInput(tool_name=tool, args={}, tool_metadata={}, trajectory=[],
                           user_task_text='test', k_remaining=1, suite_name=suite)
            expected = Decision.AUTO_APPROVE if tool == 'get_balance' else Decision.ESCALATE
            self.assertEqual(RiskBasedPolicy(self.catalog).decide(gi).decision, expected)
        policy = RiskBasedPolicy({'__default__': {}, 'lookup': {'risk': 'low', 'default_decision': 'ESCALATE'}})
        self.assertEqual(policy.decide(gi.model_copy(update={'tool_name': 'lookup', 'suite_name': None})).decision, Decision.ESCALATE)
        with self.assertRaises(ValueError):
            RiskBasedPolicy(load_tool_risk_metadata(CATALOG, 'travel')).decide(gi)


class PlannerTests(unittest.TestCase):
    def test_all_suites_and_condition_identities(self):
        plan = build_experiment_plan()
        self.assertEqual(len(plan), 12552)
        self.assertEqual(Counter(r['suite'] for r in plan),
                         {'workspace': 7200, 'travel': 1920, 'banking': 1920, 'slack': 1512})
        self.assertEqual(len({r['episode_id'] for r in plan}), len(plan))
        for r in plan:
            self.assertEqual(r['status'], 'pending')
            if r['condition'] == 'clean':
                self.assertEqual((r['attack'], r['injection_task_id']), ('', ''))
            else:
                self.assertEqual(r['attack'], 'direct')
                self.assertTrue(r['injection_task_id'])

    def test_old_single_suite_argument_and_repetitions(self):
        kw = dict(suite_name='banking', policies=['full_approve'], k_values=[0], repeats=2, include_attacked=False)
        plan = build_experiment_plan(**kw)
        self.assertEqual(len(plan), 32)
        self.assertEqual({r['repeat'] for r in plan}, {0, 1})
        self.assertEqual(plan, build_experiment_plan(**kw))

    def test_attack_and_policy_pairing(self):
        plan = build_experiment_plan(suite_names=['slack'], policies=['full_approve', 'full_escalate'],
                                     k_values=[1], attack_methods=['direct', 'ignore_previous'], include_clean=False)
        self.assertEqual(len(plan), 21 * 5 * 2 * 2)
        pairs = Counter((r['user_task_id'], r['injection_task_id'], r['attack'], r['repeat'], r['k']) for r in plan)
        self.assertEqual(set(pairs.values()), {2})

    def test_invalid_configuration(self):
        for kw in [dict(suite_names=[]), dict(suite_name='banking', suite_names=['slack']),
                   dict(suite_names=['missing']), dict(k_values=[-1]), dict(k_values=[True]),
                   dict(k_values=[1, 1]), dict(repeats=0), dict(policies=['hybrid_not_implemented']),
                   dict(attack_methods=['manual']), dict(attack_methods=['dos']),
                   dict(include_clean=False, include_attacked=False)]:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                build_experiment_plan(**kw)

    def test_overwrite_protection(self):
        plan = build_experiment_plan(suite_name='slack', policies=['full_approve'], k_values=[0], include_attacked=False)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.csv'
            path.write_text('existing results')
            with self.assertRaises(FileExistsError):
                save_plan_csv(plan, path)
            self.assertEqual(path.read_text(), 'existing results')
            save_plan_csv(plan, path, overwrite=True)
            self.assertIn('episode_id', path.read_text(encoding='utf-8-sig'))

    def test_cli_is_offline_and_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.csv'
            main(['--suite', 'slack', '--policy', 'full_approve', '--k', '0', '--clean-only', '--output', str(path)])
            self.assertEqual(len(path.read_text(encoding='utf-8-sig').splitlines()), 22)
