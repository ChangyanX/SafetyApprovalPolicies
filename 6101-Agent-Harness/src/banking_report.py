"""Analyze one frozen banking run, including coverage, costs and review evidence.

Uses the connected runner's native files. Evaluator labels remain offline.
Failure candidates require human inspection; no per-call safety labels are invented.
"""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path

from .r3_compare import compare
from .experiment_config import DEFAULT_K_VALUES
from .scope_policy import SEMANTIC_POLICY_VERSION


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def analyze(run_dir, output_dir, *, exclude_tasks=None):
    """Backwards-compatible single-run analysis."""
    return analyze_runs([run_dir], output_dir, exclude_tasks=exclude_tasks)


def analyze_runs(run_dirs, output_dir, *, exclude_tasks=None, master_manifest=None,
                 allow_config_mismatch=False):
    """Compare disjoint run partitions without copying or modifying raw evidence."""
    roots = [Path(root).resolve() for root in run_dirs]
    output_dir = Path(output_dir).resolve()
    if not roots or len(set(roots)) != len(roots):
        raise ValueError('Run directories must be nonempty and distinct')
    if any(root == output_dir or root in output_dir.parents for root in roots):
        raise ValueError('Analysis output must be outside the immutable run directory')
    manifest, results, episode_roots, sources = [], [], {}, []
    shared_config = None
    shared_config_root = None
    config_mismatches = []
    for root in roots:
        with (root/'manifest.csv').open(encoding='utf-8-sig', newline='') as file:
            rows = list(csv.DictReader(file))
        if not rows or {r['suite'] for r in rows} != {'banking'}:
            raise ValueError('A nonempty banking-only frozen manifest is required')
        records = read_jsonl(root/'results.jsonl')
        compare(rows, records)  # Bind each source's records to its own frozen selection.
        for row in rows:
            if row['episode_id'] in episode_roots:
                raise ValueError('Overlapping episode IDs across input runs; do not double-count retries')
            episode_roots[row['episode_id']] = root
        config_path = root/'config.json'
        config = json.loads(config_path.read_text()) if config_path.exists() else None
        if len(roots) > 1:
            if not isinstance(config, dict) or config.get('mode') != 'live':
                raise ValueError('Combined runs require native live config.json provenance')
            if config.get('episode_ids') != [r['episode_id'] for r in rows]:
                raise ValueError('Source configuration episode IDs disagree with its frozen manifest')
            normalized = {key:value for key,value in config.items() if key != 'episode_ids'}
            if shared_config is not None and normalized != shared_config:
                differences = []
                for key in sorted(shared_config.keys() | normalized.keys()):
                    if shared_config.get(key) == normalized.get(key):
                        continue
                    if key == 'source_fingerprints':
                        before, after = shared_config.get(key), normalized.get(key)
                        if isinstance(before, dict) and isinstance(after, dict):
                            differences.extend(f'{key}.{path}' for path in sorted(before.keys() | after.keys())
                                               if before.get(path) != after.get(path))
                            continue
                    differences.append(key)
                message = (
                    'Input model/runtime/source/prompt/policy configurations differ: '
                    f'{root} versus {shared_config_root}; differing fields: '
                    + ', '.join(differences)
                    + '. Rerun incompatible partitions with matching configurations in new run directories; '
                    'do not edit frozen config.json provenance.')
                if not allow_config_mismatch:
                    raise ValueError(message + ' Use --allow-config-mismatch for exploratory analysis.')
                config_mismatches.append(dict(run_dir=str(root), reference_run_dir=str(shared_config_root),
                    differing_fields=differences))
            if shared_config is None:
                shared_config = normalized
                shared_config_root = root
        sources.append(dict(run_dir=str(root), planned=len(rows), observed=len(records),
            config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest() if config else None))
        manifest.extend(rows); results.extend(records)
    if master_manifest is not None:
        master_manifest = Path(master_manifest).resolve()
        with master_manifest.open(encoding='utf-8-sig', newline='') as file:
            expected = list(csv.DictReader(file))
        if not expected or {r['suite'] for r in expected} != {'banking'}:
            raise ValueError('A nonempty banking-only master manifest is required')
        planned = {r['episode_id']:r for r in expected}
        if len(planned) != len(expected):
            raise ValueError('Duplicate master manifest episode IDs')
        if any(row != planned.get(row['episode_id']) for row in manifest):
            raise ValueError('Input run selections disagree with the master manifest')
        manifest = expected  # Unrun partitions remain scheduled missing outcomes.
    report = compare(manifest, results)
    if exclude_tasks:
        unknown = set(exclude_tasks) - {r['user_task_id'] for r in manifest}
        if unknown:
            raise ValueError(f'Unknown excluded tasks: {sorted(unknown)}')
        manifest = [r for r in manifest if r['user_task_id'] not in exclude_tasks]
        if not manifest:
            raise ValueError('Task exclusion leaves an empty cohort')
        ids = {r['episode_id'] for r in manifest}
        results = [r for r in results if r['episode_id'] in ids]
        report = compare(manifest, results)
    report['excluded_user_tasks'] = sorted(exclude_tasks or [])
    report['source_runs'] = sources
    report['config_mismatches'] = config_mismatches
    report['master_manifest'] = str(master_manifest) if master_manifest is not None else None
    observed = {r['episode_id']: r for r in results}
    issues, candidates, reviews, cost_rows, assessor_rows = [], [], [], [], []
    semantic_rows = []
    usage_groups = defaultdict(list)
    for row in manifest:
        eid = row['episode_id']
        result = observed.get(eid)
        if result is None:
            continue
        if row['policy'].startswith('hybrid_llm') and result['status']=='ok' and (
                result.get('policy_version') != SEMANTIC_POLICY_VERSION
                or result.get('assessment_mode') != 'review_selection'):
            issues.append(f'{eid}: old or missing semantic policy identity; run a fresh versioned cohort')
        folder = episode_roots[eid]/'episodes'/eid
        events = read_jsonl(folder/'audit.jsonl')
        usage = [u for u in read_jsonl(folder/'usage.jsonl')
                 if u.get('record_type') == 'api_attempt']
        for u in usage:
            usage_groups[(row['policy'], int(row['k']), row['condition'], u['component'])].append(u)
        traces = read_jsonl(folder/'assessor.jsonl')
        for trace in traces:
            assessor_rows.append(dict(episode_id=eid, policy=row['policy'], k=row['k'],
                condition=row['condition'], call_id=trace['call_id'], status=trace['status'],
                error_code=trace.get('error_code'), provider_called=trace['provider_called']))
        if sum(t['provider_called'] for t in traces) != sum(u['component']=='policy' for u in usage):
            issues.append(f'{eid}: policy API attempts disagree with assessor traces')
        started = [e for e in events if e['kind'] == 'review_started']
        if len(started) != result['review_count']:
            issues.append(f'{eid}: review count disagrees with durable audit')
        if result['status']=='ok':
            actual = {e['call_id'] for e in events if e['kind']=='execution'}
            if actual != {c['call_id'] for c in result['executed_calls']}:
                issues.append(f'{eid}: executed calls disagree with durable audit')
        if result['status'] == 'ok' and not (folder/'trajectory.json').exists():
            issues.append(f'{eid}: missing trajectory')
        if result['status'] == 'ok' and not usage:
            issues.append(f'{eid}: no model API usage records')
        if result['status']=='ok' and sum(u['component']=='reviewer' for u in usage) < len(started):
            issues.append(f'{eid}: reviewer API usage missing')
        verdicts = {e['call_id']: e for e in events if e['kind'] == 'review_result'}
        decisions = {e['call_id']: e for e in events if e['kind'] == 'gate_decision'}
        proposals = {e['call_id']: e for e in events if e['kind'] == 'proposal'}
        for cid, decision in decisions.items():
            audit = decision.get('policy_audit') or {}
            influence = audit.get('semantic_influence')
            if not influence:
                continue
            if row['policy'].startswith('hybrid_llm') and (
                    influence['mode'] != 'review_selection'
                    or influence['version'] != SEMANTIC_POLICY_VERSION):
                issues.append(f'{eid}: semantic policy version/mode mismatch')
            allocation = audit['allocation']
            semantic_rows.append(dict(episode_id=eid, call_id=cid, policy=row['policy'],
                k=row['k'], condition=row['condition'], version=influence['version'],
                mode=influence['mode'], evidence_complete=influence['evidence_complete'],
                accepted_checks=';'.join(influence['accepted_checks']),
                ignored_checks=';'.join(influence['ignored_checks']),
                semantic_violations=';'.join(influence['violations']),
                relevance_supported=influence['relevance_supported'],
                heuristic_necessity=allocation['heuristic_necessity'],
                effective_necessity=allocation['necessity'], priority=allocation['priority'],
                threshold=allocation['threshold'], decision=decision['decision'],
                reviewer_consulted=decision['reviewed'], approved=decision['approved'],
                executed=cid in {c['call_id'] for c in result['executed_calls']}))
        for event in started:
            cid = event['call_id']
            verdict = verdicts.get(cid, {})
            reviews.append(dict(episode_id=eid, policy=row['policy'], k=row['k'],
                condition=row['condition'], call_id=cid, tool=event['tool'],
                approved=verdict.get('approved'), error=verdict.get('error'),
                reason=verdict.get('reason'), utility=result.get('utility'),
                attack_success=result.get('security') if row['condition']=='attacked' else None,
                audit_path=str(folder/'audit.jsonl')))
        failure = result['status'] != 'ok' or not result.get('utility') or (
            row['condition']=='attacked' and result.get('security'))
        if failure:
            denied = [cid for cid, e in decisions.items() if not e['approved']]
            category = ('runtime_error' if result['status']!='ok' else
                        'attack_success_candidate' if row['condition']=='attacked' and result['security'] else
                        'over_conservative_candidate' if denied else 'utility_failure_candidate')
            candidates.append(dict(episode_id=eid, policy=row['policy'], k=row['k'],
                condition=row['condition'], user_task_id=row['user_task_id'],
                injection_task_id=row['injection_task_id'], category=category,
                utility=result.get('utility'), security=result.get('security'),
                denied_call_ids=';'.join(denied), proposed_calls=len(proposals),
                executed_calls=len(result['executed_calls']), error=result.get('error'),
                trajectory_path=str(folder/'trajectory.json'), audit_path=str(folder/'audit.jsonl'),
                confirmed_classification='', explanation='', decisive_call_id=''))
    for (policy, k, condition, component), usage in sorted(usage_groups.items()):
        cost_rows.append(dict(policy=policy, k=k, condition=condition, component=component,
            api_attempts=len(usage), known_cost_usd=sum(u['cost_usd'] for u in usage if u.get('cost_usd') is not None),
            unknown_cost_attempts=sum(u.get('cost_usd') is None for u in usage),
            input_tokens=sum(u.get('input_tokens') or 0 for u in usage),
            output_tokens=sum(u.get('output_tokens') or 0 for u in usage),
            unknown_token_attempts=sum(u.get('input_tokens') is None or u.get('output_tokens') is None for u in usage)))
    # Include deterministic policies with zero API attempts, rather than omitting them.
    keys = {(r['policy'], r['k'], r['condition'], r['component']) for r in cost_rows}
    for group in report['groups']:
        for component in ('agent','policy','reviewer'):
            key = (group['policy'], group['k'], group['condition'], component)
            if key not in keys:
                cost_rows.append(dict(policy=key[0], k=key[1], condition=key[2], component=component,
                    api_attempts=0, known_cost_usd=0, unknown_cost_attempts=0,
                    input_tokens=0, output_tokens=0, unknown_token_attempts=0))
    cells = defaultdict(set)
    for row in manifest:
        cells[(row['policy'],int(row['k']),row['condition'])].add(
            (row['user_task_id'],row['attack'],row['injection_task_id'],str(row['repeat'])))
    comparison_issues = ['Input configurations differ; exploratory comparison only'] if config_mismatches else []
    policies = {r['policy'] for r in manifest}
    if not {'full_approve','full_escalate'} <= policies or not any(p.startswith('hybrid_') for p in policies):
        comparison_issues.append('Study does not contain both required baselines and an original policy')
    budgets = {int(r['k']) for r in manifest}
    conditions = {r['condition'] for r in manifest}
    if budgets != set(DEFAULT_K_VALUES):
        comparison_issues.append(f'Study must cover the project budget grid {DEFAULT_K_VALUES}')
    if len(budgets) < 2:
        comparison_issues.append('A meaningful curve needs multiple review budgets')
    if conditions != {'clean','attacked'}:
        comparison_issues.append('Study must distinguish both clean and attacked conditions')
    for k in sorted(budgets):
        for condition in sorted(conditions):
            cohorts = [cells.get((p,k,condition),set()) for p in sorted(policies)]
            if any(c != cohorts[0] for c in cohorts[1:]) or not cohorts[0]:
                comparison_issues.append(f'Unmatched policy cohorts at budget {k}, condition {condition}')
    report['comparison_issues'] = comparison_issues
    report['audit_issues'] = issues
    report['complete'] = bool(results) and not issues and all(
        g['missing']==0 and g['errors']==0 for g in report['groups'])
    report['comparison_ready'] = report['complete'] and not comparison_issues
    report['cost_note'] = 'Local Ollama API charge is zero; tokens and latency are usage, hardware/electricity costs are excluded. Consultation summaries are not counted again.'
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/'summary.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    write_csv(output_dir/'metrics.csv', report['groups'])
    write_csv(output_dir/'component_costs.csv', cost_rows)
    write_csv(output_dir/'review_outcomes.csv', reviews)
    write_csv(output_dir/'assessor_status.csv', assessor_rows)
    write_csv(output_dir/'semantic_decisions.csv', semantic_rows)
    by_tool = defaultdict(list)
    for review in reviews:
        by_tool[(review['policy'],int(review['k']),review['condition'],review['tool'])].append(review)
    write_csv(output_dir/'review_by_tool.csv', [dict(policy=p,k=k,condition=c,tool=t,
        consultations=len(items),approved=sum(r['approved'] is True for r in items),
        denied=sum(r['approved'] is False for r in items),errors=sum(bool(r['error']) for r in items))
        for (p,k,c,t),items in sorted(by_tool.items())])
    write_csv(output_dir/'failure_candidates.csv', candidates)
    escalation = []
    for g in report['groups']:
        rr = [r for r in reviews if (r['policy'],int(r['k']),r['condition']) ==
              (g['policy'],g['k'],g['condition'])]
        escalation.append(dict(policy=g['policy'], k=g['k'], condition=g['condition'],
            consultations=len(rr), approved=sum(r['approved'] is True for r in rr),
            denied=sum(r['approved'] is False for r in rr),
            errors=sum(bool(r['error']) for r in rr),
            reviews_on_successes=g['hitl_successful_cohort_total'],
            successful_episodes=g['hitl_successful_cohort_size'],
            outcome_rate=g['valid_only_rate']))
    write_csv(output_dir/'escalation_value.csv', escalation)
    plot(report['groups'], cost_rows, output_dir)
    return report


def plot(groups, costs, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for condition in ('clean','attacked'):
        selected = [g for g in groups if g['condition']==condition]
        if not selected:
            continue
        for field, label in [('valid_only_rate', 'AgentDojo TCR' if condition=='attacked' else 'Clean utility'),
                             ('utility_valid_only','Utility'), ('attack_success_valid_only','Attack success rate'),
                             ('hitl_successful_cohort_total','Total reviews on successful episodes'),
                             ('reviews_observed','Total observed reviews')]:
            fig, ax = plt.subplots(figsize=(7,4))
            for policy in sorted({g['policy'] for g in selected}):
                points = sorted([g for g in selected if g['policy']==policy and g[field] is not None], key=lambda g:g['k'])
                if points:
                    ax.plot([g['k'] for g in points],[g[field] for g in points],marker='o',label=policy)
            if not ax.lines:
                plt.close(fig)
                continue
            ax.set(xlabel=r'Review budget $k$', ylabel=label, title=condition)
            if 'rate' in field or field.endswith('only'):
                ax.set_ylim(-.03,1.03)
            ax.grid(alpha=.3);ax.legend();fig.tight_layout()
            fig.savefig(out/f'{condition}_{field}.png',dpi=180,bbox_inches='tight');plt.close(fig)
    keys = sorted({(r['policy'],r['k'],r['condition']) for r in costs})
    fig, ax = plt.subplots(figsize=(max(9,len(keys)*.4),6))
    bottom = [0]*len(keys)
    for component in ('agent','policy','reviewer'):
        lookup = {(r['policy'],r['k'],r['condition']):r for r in costs if r['component']==component}
        values = [lookup[key]['input_tokens']+lookup[key]['output_tokens'] for key in keys]
        ax.bar(range(len(keys)),values,bottom=bottom,label=component)
        bottom = [b+v for b,v in zip(bottom,values)]
    ax.set_xticks(range(len(keys)),[f"{p} / {k} / {c}" for p,k,c in keys],rotation=90)
    ax.set_ylabel('Known tokens')
    ax.set_title('Component token usage (unknown counts in CSV)')
    ax.legend();fig.tight_layout();fig.savefig(out/'component_tokens.png',dpi=180,bbox_inches='tight');plt.close(fig)



def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True,action='append',help='Repeat for separate matched policy runs')
    parser.add_argument('--manifest',type=Path,help='Frozen master plan; omitted partitions remain missing')
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--allow-incomplete',action='store_true',help='Export diagnostic pilot/error results with exit code zero')
    parser.add_argument('--allow-config-mismatch',action='store_true',
        help='Export exploratory comparisons across differing configurations; record differences in summary.json')
    parser.add_argument('--exclude-task', action='append', default=[], help='Exclude development identities from a held-out analysis')
    args=parser.parse_args(argv)
    report=analyze_runs(args.run_dir,args.output_dir,exclude_tasks=args.exclude_task,master_manifest=args.manifest,
        allow_config_mismatch=args.allow_config_mismatch)
    print(f"Complete: {report['complete']}; comparison ready: {report['comparison_ready']}; groups: {len(report['groups'])}; audit issues: {len(report['audit_issues'])}")
    if report['config_mismatches']:
        print('Exploratory comparison: input configurations differ; details recorded in summary.json')
    return 0 if (report['complete'] and report['comparison_ready']) or args.allow_incomplete else 2


if __name__=='__main__':
    raise SystemExit(main())
