"""Synthetic native-log fixtures for comparing disjoint policy runs; no model calls."""
import csv
import json
from pathlib import Path

import pytest
from src.banking_report import analyze_runs
from src.experiment_runner import build_experiment_plan, save_plan_csv
from src.run_experiments import append_json
from src.scope_policy import SEMANTIC_POLICY_VERSION

POLICIES=('full_approve','full_escalate','hybrid_llm','hybrid_llm_fixed')


def study(tmp_path):
    rows=build_experiment_plan(suite_name='banking',policies=list(POLICIES))
    rows=[r for r in rows if r['user_task_id']=='user_task_0' and
          (r['condition']=='clean' or r['injection_task_id']=='injection_task_0')]
    master=tmp_path/'master.csv';save_plan_csv(rows,master)
    roots=[]
    for policy in POLICIES:
        root=tmp_path/policy;root.mkdir();roots.append(root)
        selected=[r for r in rows if r['policy']==policy]
        save_plan_csv(selected,root/'manifest.csv')
        (root/'config.json').write_text(json.dumps(dict(mode='live',model='fixture-model',seed=0,
            source_fingerprints={'fixture':'hash'},episode_ids=[r['episode_id'] for r in selected])))
        for row in selected:
            folder=root/'episodes'/row['episode_id'];folder.mkdir(parents=True)
            (folder/'trajectory.json').write_text('{}')
            append_json(folder/'usage.jsonl',dict(record_type='api_attempt',component='agent',
                input_tokens=1,output_tokens=1,cost_usd=0))
            append_json(root/'results.jsonl',dict(row,status='ok',mode='live',error=None,
                utility=True,security=row['condition']=='clean',executed_calls=[],review_count=0,
                policy_version=SEMANTIC_POLICY_VERSION,assessment_mode='review_selection'))
    return roots,master


def test_four_policy_partitions_compare_without_copying_evidence(tmp_path,monkeypatch):
    roots,master=study(tmp_path)
    monkeypatch.setattr('src.banking_report.plot',lambda *args:None)
    report=analyze_runs(roots,tmp_path/'analysis',master_manifest=master)
    assert report['complete'] and report['comparison_ready']
    assert len(report['source_runs'])==4
    assert sum(g['planned'] for g in report['groups'])==48
    assert {g['policy'] for g in report['groups']}==set(POLICIES)
    assert not (tmp_path/'analysis/episodes').exists()


def test_master_manifest_exposes_unrun_policy_as_missing(tmp_path,monkeypatch):
    roots,master=study(tmp_path)
    monkeypatch.setattr('src.banking_report.plot',lambda *args:None)
    report=analyze_runs(roots[:3],tmp_path/'analysis',master_manifest=master)
    assert not report['complete']
    assert sum(g['missing'] for g in report['groups'])==12
    assert any(g['policy']=='hybrid_llm_fixed' and g['missing'] for g in report['groups'])


@pytest.mark.parametrize('field,value',[
    ('seed',1),('model','different-model'),('source_fingerprints',{'fixture':'changed-hash'}),
    ('episode_ids',[]),('mode','offline_test'),
])
def test_inconsistent_provenance_is_rejected(tmp_path,field,value):
    roots,master=study(tmp_path)
    config_path=roots[1]/'config.json';config=json.loads(config_path.read_text())
    config[field]=value;config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        analyze_runs(roots,tmp_path/'analysis',master_manifest=master)


def test_duplicate_selection_and_master_disagreement_rejected(tmp_path):
    import shutil
    roots,master=study(tmp_path)
    with pytest.raises(ValueError,match='distinct'):
        analyze_runs([roots[0],roots[0]],tmp_path/'analysis')
    copied=tmp_path/'duplicate';shutil.copytree(roots[0],copied)
    with pytest.raises(ValueError,match='Overlapping'):
        analyze_runs([roots[0],copied],tmp_path/'analysis')
    with master.open(encoding='utf-8-sig') as file:
        rows=list(csv.DictReader(file))
    rows[0]['repeat']='99'
    other=tmp_path/'wrong.csv';save_plan_csv(rows,other)
    with pytest.raises(ValueError,match='master manifest'):
        analyze_runs(roots,tmp_path/'analysis',master_manifest=other)


def test_provenance_error_identifies_runs_and_changed_source(tmp_path):
    roots,master=study(tmp_path)
    path=roots[2]/'config.json'
    config=json.loads(path.read_text())
    config['source_fingerprints']['prompts/reviewer.txt']='changed'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError) as error:
        analyze_runs(roots,tmp_path/'analysis',master_manifest=master)
    message=str(error.value)
    assert str(roots[2]) in message and str(roots[0]) in message
    assert 'source_fingerprints.prompts/reviewer.txt' in message
    assert 'do not edit frozen config.json' in message
    assert not (tmp_path/'analysis').exists()


def test_exploratory_config_override_records_differences(tmp_path,monkeypatch):
    roots,master=study(tmp_path)
    path=roots[2]/'config.json'
    config=json.loads(path.read_text())
    config['source_fingerprints']['fixture']='changed'
    path.write_text(json.dumps(config))
    original=path.read_bytes()
    monkeypatch.setattr('src.banking_report.plot',lambda *args:None)
    report=analyze_runs(roots,tmp_path/'analysis',master_manifest=master,allow_config_mismatch=True)
    assert report['complete'] and not report['comparison_ready']
    assert report['config_mismatches']==[dict(run_dir=str(roots[2]),reference_run_dir=str(roots[0]),
        differing_fields=['source_fingerprints.fixture'])]
    assert 'exploratory' in report['comparison_issues'][0]
    assert json.loads((tmp_path/'analysis/summary.json').read_text())['config_mismatches']==report['config_mismatches']
    assert path.read_bytes()==original
