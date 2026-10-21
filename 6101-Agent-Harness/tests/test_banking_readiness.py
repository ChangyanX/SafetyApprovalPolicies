"""Regression coverage for banking manifests, role wiring and native reporting."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest

from src.banking_report import analyze
from src.experiment_runner import build_experiment_plan, main as plan_main, save_plan_csv
from src.gated_smoke import ScriptedAgent, ScriptedReviewer
from src.policy import make_policy
from src.run_experiments import append_json, execute_episode, main, source_fingerprints


def test_banking_cli_defaults_include_original_policy_and_task_filter(tmp_path):
    path=tmp_path/'plan.csv'
    plan_main(['--output',str(path),'--task','user_task_0','--injection-task','injection_task_0'])
    with path.open(encoding='utf-8-sig') as file:
        rows=list(csv.DictReader(file))
    assert len(rows)==32
    assert {r['suite'] for r in rows}=={'banking'}
    assert {r['policy'] for r in rows}=={'full_approve','full_escalate','hybrid_llm','hybrid_llm_fixed'}
    assert {r['condition'] for r in rows}=={'clean','attacked'}
    with patch('src.run_experiments.OpenAI') as client:
        assert main(['--manifest',str(path),'--output-dir',str(tmp_path/'unused'),'--all','--validate-only'])==0
        client.assert_not_called()
    assert not (tmp_path/'unused').exists()


def test_live_policy_requires_assessor_and_fingerprints_include_prompts():
    with pytest.raises(ValueError,match='explicit live assessor'):
        make_policy('hybrid_llm')
    assert 'src/prompts/r3_assessor.txt' in source_fingerprints()


def test_runner_really_calls_r4_and_records_policy_usage(tmp_path):
    client=Mock()
    requests=[]
    def complete(**kwargs):
        assert kwargs['reasoning_effort']=='none' and kwargs['extra_body']=={'think':False}
        req=json.loads(kwargs['messages'][1]['content']);requests.append(req)
        response={k:req[k] for k in ('schema_version','episode_id','call_id','proposal_hash')}
        response.update(status='ok',checks=[],error=None)
        return NS(choices=[NS(finish_reason='stop',message=NS(content=json.dumps(response),refusal=None))],
                  usage=NS(prompt_tokens=40,completion_tokens=10,total_tokens=50))
    client.chat.completions.create.side_effect=complete
    row=build_experiment_plan(suite_name='banking',policies=['hybrid_llm'],k_values=[1],include_attacked=False)[0]
    out=tmp_path/'episode'
    result=execute_episode(row,out,client=client,agent=ScriptedAgent('banking'),reviewer=ScriptedReviewer())
    assert result['status']=='ok',result['error']
    assert requests
    assert (out/'assessor.jsonl').exists()
    assert sum(u['input_tokens'] for u in result['usage'] if u['component']=='policy')==40*len(requests)
    assert all('injection_task_id' not in r for r in requests)
    assert make_policy('hybrid_llm_fixed',policy_options={'assessor':object()}).name=='hybrid_llm_fixed'


def dataset(tmp_path):
    run=tmp_path/'run';(run/'episodes').mkdir(parents=True)
    rows=build_experiment_plan(suite_name='banking',policies=['full_escalate'],k_values=[1])
    rows=[r for r in rows if r['user_task_id']=='user_task_0' and
          (r['condition']=='clean' or r['injection_task_id']=='injection_task_0')]
    save_plan_csv(rows,run/'manifest.csv')
    for row in rows:
        folder=run/'episodes'/row['episode_id'];folder.mkdir()
        append_json(run/'results.jsonl',dict(row,status='ok',mode='live',utility=True,
            security=True,review_count=1,executed_calls=[],error=None))
        (folder/'trajectory.json').write_text('{}')
        append_json(folder/'audit.jsonl',dict(kind='review_started',call_id='c1',tool='send_money'))
        append_json(folder/'audit.jsonl',dict(kind='review_result',call_id='c1',approved=True))
        append_json(folder/'usage.jsonl',dict(record_type='api_attempt',component='reviewer',
            input_tokens=10,output_tokens=5,cost_usd=0))
        append_json(folder/'usage.jsonl',dict(record_type='consultation_summary',component='reviewer',
            input_tokens=10,output_tokens=5,cost_usd=0))
    return run


def test_native_report_separates_conditions_costs_and_hitl(tmp_path):
    run=dataset(tmp_path)
    with patch('src.banking_report.plot'):
        report=analyze(run,tmp_path/'analysis')
    assert report['complete']
    assert not report['comparison_ready']  # a single-policy diagnostic is not a full comparison
    assert report['comparison_issues']
    groups={g['condition']:g for g in report['groups']}
    assert groups['clean']['valid_only_rate']==1
    assert groups['clean']['attack_success_valid_only'] is None
    assert groups['attacked']['valid_only_rate']==0
    assert groups['attacked']['hitl_successful_cohort_total']==0
    assert groups['attacked']['hitl_utility_successful_cohort_total']==1
    with (tmp_path/'analysis/component_costs.csv').open() as file:
        costs=list(csv.DictReader(file))
    assert sum(int(r['input_tokens']) for r in costs)==20  # no double counting summaries
    assert sum(int(r['api_attempts']) for r in costs)==2
    with pytest.raises(ValueError,match='outside'):
        analyze(run,run/'analysis')


def test_report_tracks_missing_errors_and_rejects_fixture_results(tmp_path):
    run=dataset(tmp_path)
    results=[json.loads(line) for line in (run/'results.jsonl').read_text().splitlines()]
    results[0].update(status='error',error='timeout',utility=None,security=None)
    (run/'results.jsonl').write_text(json.dumps(results[0])+'\n')
    with patch('src.banking_report.plot'):
        report=analyze(run,tmp_path/'analysis')
    assert not report['complete']
    assert sum(g['errors'] for g in report['groups'])==1
    assert sum(g['missing'] for g in report['groups'])==1
    results[0]['mode']='offline_test'
    (run/'results.jsonl').write_text(json.dumps(results[0])+'\n')
    with pytest.raises(ValueError,match='fixtures'):
        analyze(run,tmp_path/'analysis')


def test_runner_does_not_hide_reviewer_usage_audit_failure(tmp_path):
    reviewer=ScriptedReviewer()
    reviewer.usage_callback_errors=1
    row=build_experiment_plan(suite_name='banking',policies=['full_escalate'],k_values=[1],include_attacked=False)[0]
    result=execute_episode(row,tmp_path/'episode',agent=ScriptedAgent('banking'),reviewer=reviewer)
    assert result['status']=='error'
    assert result['utility'] is None and result['security'] is None
    assert 'audit callback' in result['error']
