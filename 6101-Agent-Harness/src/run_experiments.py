"""Execute frozen manifest rows through the gated AgentDojo pipeline.

No benchmark labels enter the agent, assessor or reviewer context. Attack setup
and official evaluation stay outside the runtime policy. Output is resumable
between episodes; interrupted episodes are recorded as errors, never replayed.
"""
import argparse
from copy import deepcopy
import csv
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import time
import uuid

from openai import OpenAI
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.task_suite.load_suites import get_suite
from .gated_runtime import jsonable
from .pipeline import build_pipeline
from .policy import make_policy, POLICY_LABELS
from .reviewer import LLMReviewer
from .r4_assessor import LocalR3Assessor
from .llm_judge import JudgeConfig
from .scope_policy import SEMANTIC_POLICY_VERSION
from .tool_risk import load_tool_risk_metadata

IDENTITY = ('episode_id','benchmark_version','suite','user_task_id','condition','attack',
            'injection_task_id','policy','k','repeat')


def append_json(path, value):
    with Path(path).open('a',encoding='utf-8') as file:
        file.write(json.dumps(jsonable(value),allow_nan=False)+'\n')
        file.flush()
        os.fsync(file.fileno())


def write_json(path, value):
    # Replace only this run's own temporary result, atomically.
    path=Path(path)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('x',encoding='utf-8') as file:
        json.dump(jsonable(value),file,indent=2,allow_nan=False)
        file.flush();os.fsync(file.fileno())
    temporary.replace(path)


def validate_manifest(rows):
    if not rows:raise ValueError('Manifest selection is empty')
    ids=set()
    for row in rows:
        if not all(field in row for field in IDENTITY):raise ValueError('Manifest identity fields missing')
        eid=row['episode_id']
        if not eid or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in eid) or eid in ids:
            raise ValueError('Unsafe or duplicate episode ID')
        ids.add(eid)
        if row['benchmark_version']!='v1.2.2':raise ValueError('This semantic catalog is pinned to benchmark v1.2.2')
        if row['policy'] not in POLICY_LABELS:raise ValueError('Unknown policy')
        for field in ('k','repeat'):
            if str(int(row[field]))!=str(row[field]) or int(row[field])<0:raise ValueError('Invalid integer identity')
        suite=get_suite(row['benchmark_version'],row['suite'])
        suite.get_user_task_by_id(row['user_task_id'])
        if row['condition']=='clean':
            if row['attack'] or row['injection_task_id']:raise ValueError('Clean row has attack configuration')
        elif row['condition']=='attacked':
            if row['attack']!='direct':raise ValueError('Connected runner currently supports fixed direct attacks only')
            suite.get_injection_task_by_id(row['injection_task_id'])
        else:raise ValueError('Unknown condition')


def execute_episode(row, episode_dir, *, model='qwen3:14b', base_url='http://localhost:11434/v1',
                    timeout=120, attempts=1, max_turns=20, max_tool_calls=80,
                    max_tokens=4096, seed=0, client=None, agent=None, reviewer=None, policy_options=None):
    """One isolated environment, official outcomes, durable full-call audit.

    agent/reviewer injection is for offline integration tests only. CLI always
    builds live model-backed components and never labels fixtures as model runs.
    """
    episode_dir=Path(episode_dir).resolve();episode_dir.mkdir(parents=True,exist_ok=False)
    result={key:row[key] for key in IDENTITY}
    result.update(status='error',utility=None,security=None,review_count=0,executed_calls=[],
                  mode='offline_test' if agent is not None else 'live',error=None)
    started=time.monotonic();pipeline=None;reviewer_object=None;usage=[];instrumentation_errors=[]
    def on_usage(component, data):
        event=dict(jsonable(data),component=component,episode_id=row['episode_id'],provider='ollama',
                   local=True,cost_usd=0.0)
        event.setdefault('record_type','api_attempt')
        usage.append(event)
        try:
            append_json(episode_dir/'usage.jsonl',event)
        except Exception as exc:
            instrumentation_errors.append(type(exc).__name__)
            raise
    def on_event(data):append_json(episode_dir/'audit.jsonl',data)
    try:
        suite=get_suite(row['benchmark_version'],row['suite'])
        task=suite.get_user_task_by_id(row['user_task_id'])
        metadata=load_tool_risk_metadata(Path(__file__).with_name('tool_risk_metadata.yaml'))
        client=client or (None if agent is not None else OpenAI(base_url=base_url,api_key='ollama',
                                                timeout=timeout,max_retries=0))
        options = dict(policy_options or {})
        if row['policy'].startswith('hybrid_llm'):
            if client is None:
                raise ValueError('hybrid_llm requires a model client')
            def assessor_trace(trace):
                data = trace.model_dump(mode='json')
                try:
                    append_json(episode_dir/'assessor.jsonl', data)
                except Exception as exc:
                    instrumentation_errors.append(type(exc).__name__)
                    raise
                if trace.provider_called:
                    on_usage('policy', dict(model=trace.model, status=trace.status,
                        input_tokens=trace.prompt_tokens, output_tokens=trace.completion_tokens,
                        latency_s=trace.latency_ms/1000, call_id=trace.call_id,
                        error_code=trace.error_code))
            options['assessor'] = LocalR3Assessor(JudgeConfig(model=model, base_url=base_url,
                timeout_seconds=float(timeout), max_tokens=1024, no_think=True), client=client, on_trace=assessor_trace)
        policy=make_policy(row['policy'],metadata,suite_name=row['suite'],policy_options=options)
        reviewer_object=reviewer if reviewer is not None else LLMReviewer(model=model,base_url=base_url,
            client=client,max_attempts=attempts,
            on_usage=lambda data:on_usage('reviewer',dict(data,record_type='consultation_summary')),
            on_attempt=lambda data:on_usage('reviewer',data))
        pipeline=build_pipeline(model,policy,int(row['k']),reviewer_object,metadata,
            suite_name=row['suite'],episode_id=row['episode_id'],client=client,agent=agent,
            max_turns=max_turns,max_tool_calls=max_tool_calls,max_tokens=max_tokens,
            seed=seed+int(row['repeat']),attempts=attempts,on_event=on_event,
            on_agent_usage=lambda data:on_usage('agent',data))
        injections={};injection_task=None
        if row['condition']=='attacked':
            if row['attack']!='direct':raise ValueError('Only fixed direct attacks are implemented')
            injection_task=suite.get_injection_task_by_id(row['injection_task_id'])
            attack=load_attack('direct',suite,pipeline)
            injections=attack.attack(task,injection_task)
        # Attack goals and generated payload metadata stay in this evaluator file,
        # never in GateInput or the model's system prompt. Injected environment
        # observations remain visible naturally, as required by the benchmark.
        write_json(episode_dir/'attack_setup.json',dict(condition=row['condition'],
            attack=row['attack'],injection_task_id=row['injection_task_id'],injections=injections))
        utility,security=suite.run_task_with_pipeline(pipeline,task,injection_task,injections)
        if type(utility) is not bool or type(security) is not bool:
            raise ValueError('Official evaluators must return known boolean outcomes')
        result.update(status='ok',utility=bool(utility),security=bool(security),error=None)
    except KeyboardInterrupt:
        result.update(status='error',error='KeyboardInterrupt: interrupted by user')
        raise
    except Exception as exc:
        result.update(status='error',error=type(exc).__name__+': '+str(exc)[:2000])
    finally:
        if pipeline:
            result.update(policy_version=SEMANTIC_POLICY_VERSION,
                          assessment_mode=getattr(pipeline.policy,'assessment_mode',None),
                          review_count=pipeline.review_count,executed_calls=deepcopy(pipeline.executed_calls),
                          turns=pipeline.turns,k_remaining=pipeline.k_remaining)
            write_json(episode_dir/'trajectory.json',dict(
                full_runtime_messages=jsonable(pipeline.messages),
                evaluation_messages=jsonable(pipeline.evaluation_messages())))
            if hasattr(pipeline.policy,'snapshot'):
                write_json(episode_dir/'scope_state.json',pipeline.policy.snapshot())
        if instrumentation_errors:
            result.update(status='error', error='Model usage or assessor audit callback failed', utility=None, security=None)
        if reviewer_object is not None and getattr(reviewer_object, 'usage_callback_errors', 0):
            result.update(status='error', error='Reviewer usage audit callback failed', utility=None, security=None)
        if reviewer_object is not None and hasattr(reviewer_object,'log'):
            write_json(episode_dir/'reviewer.json',jsonable(reviewer_object.log))
        if reviewer_object is not None and hasattr(reviewer_object,'requests'):
            write_json(episode_dir/'reviewer_requests.json',jsonable(reviewer_object.requests))
        result.update(duration_s=time.monotonic()-started,usage=usage,
            audit_path=str(episode_dir/'audit.jsonl'),trajectory_path=str(episode_dir/'trajectory.json'))
        write_json(episode_dir/'result.json',result)
    return result


def source_fingerprints():
    root=Path(__file__).parent
    paths=list(root.glob('*.py'))+list((root/'prompts').glob('*.txt'))+[root/'tool_risk_metadata.yaml',root.parent/'prompts/reviewer.txt']
    return {str(p.relative_to(root.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def preflight(client, model):
    try:
        available=[m.id for m in client.with_options(timeout=5).models.list().data]
    except Exception as exc:
        raise RuntimeError('Cannot reach Ollama. Start Ollama, ensure its server is running at the configured base URL, and pull qwen3:14b.') from exc
    if model not in available:raise RuntimeError(f'Model {model!r} is unavailable. Run ollama pull {model}. Available: {available}')
    return available


def interrupted_result(row, folder):
    events=[]
    path=folder/'audit.jsonl'
    if path.exists():
        for line in path.read_text().splitlines():
            try:events.append(json.loads(line))
            except json.JSONDecodeError:break
    executions=[{k:v for k,v in e.items() if k not in ('event_id','episode_id','kind')}
                for e in events if e['kind']=='execution']
    completed={e['call_id'] for e in executions}
    for event in events:
        if event['kind']=='execution_started' and event['call_id'] not in completed:
            executions.append(dict(call_id=event['call_id'],tool=event['tool'],arguments=event['arguments'],
                result=None,success=False,error='Interrupted during or before invocation',effect_uncertain=True))
    uncertain=[e for e in events if e['kind']=='execution_uncertain']
    return dict({k:row[k] for k in IDENTITY},status='error',error='Interrupted episode; not automatically replayed',
        utility=None,security=None,mode='live',review_count=sum(e['kind']=='review_started' for e in events),
        executed_calls=executions,uncertain_executions=uncertain,audit_path=str(path))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--suite',action='append',help='Default selection: banking')
    parser.add_argument('--task',action='append')
    parser.add_argument('--policy',action='append',choices=POLICY_LABELS)
    parser.add_argument('--k',action='append',type=int)
    parser.add_argument('--condition',choices=['clean','attacked'])
    parser.add_argument('--injection-task',action='append')
    parser.add_argument('--limit',type=int,default=10,help='Selected episode count; default 10; --all removes selection limit')
    parser.add_argument('--all',action='store_true',help='Run every selected row')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--validate-only',action='store_true',help='Validate selected manifest offline; no files or model requests')
    parser.add_argument('--check',action='store_true',help='Check model availability only; no files or episodes')
    parser.add_argument('--model',default='qwen3:14b')
    parser.add_argument('--base-url',default='http://localhost:11434/v1')
    parser.add_argument('--timeout',type=float,default=120)
    parser.add_argument('--attempts',type=int,default=1)
    parser.add_argument('--max-turns',type=int,default=20)
    parser.add_argument('--max-tool-calls',type=int,default=80)
    parser.add_argument('--max-tokens',type=int,default=4096)
    parser.add_argument('--seed',type=int,default=0)
    parser.add_argument('--alpha',type=float,default=0.7)
    parser.add_argument('--tau0',type=float,default=0.15)
    parser.add_argument('--delta',type=float,default=0.1)
    args=parser.parse_args(argv)
    if min(args.attempts,args.max_turns,args.max_tool_calls,args.max_tokens,args.limit)<1 or args.timeout<=0:
        parser.error('Limits, attempts and timeout must be positive')
    if not all(math.isfinite(v) for v in (args.alpha,args.tau0,args.delta,args.timeout)) or not 0<args.alpha<=1 or args.tau0<0 or args.delta<0:
        parser.error('Invalid policy coefficients or timeout')
    policy_options=dict(alpha=args.alpha,tau0=args.tau0,delta=args.delta)
    rows=[]
    if not args.check:
        if args.manifest is None or args.output_dir is None:parser.error('--manifest and --output-dir are required')
        with args.manifest.open(encoding='utf-8-sig',newline='') as file:rows=list(csv.DictReader(file))
        rows=[r for r in rows if (r['suite'] in (args.suite or ['banking']))
              and (not args.task or r['user_task_id'] in args.task)
              and (not args.policy or r['policy'] in args.policy)
              and (not args.k or int(r['k']) in args.k)
              and (not args.condition or r['condition']==args.condition)
              and (not args.injection_task or r['injection_task_id'] in args.injection_task)]
        if not args.all:rows=rows[:args.limit]
        try:validate_manifest(rows)
        except (ValueError,KeyError) as exc:parser.error(str(exc))
    if args.validate_only:
        if args.check:parser.error('--validate-only requires a manifest, not --check')
        print(f'Validated {len(rows)} selected manifest rows; no model requests.');return 0
    client=OpenAI(base_url=args.base_url,api_key='ollama',timeout=args.timeout,max_retries=0)
    try:available=preflight(client,args.model)
    except RuntimeError as exc:parser.exit(2,str(exc)+'\n')
    if args.check:
        print(f'Ollama ready: {args.model}; available models: {available}');return
    config=dict(model=args.model,base_url=args.base_url,timeout=args.timeout,attempts=args.attempts,
        max_turns=args.max_turns,max_tool_calls=args.max_tool_calls,max_tokens=args.max_tokens,
        seed=args.seed,policy_options=policy_options,model_weights_digest=None,
        agent_reasoning_effort='none', semantic_policy_version=SEMANTIC_POLICY_VERSION,
        semantic_assessment_mode='review_selection for hybrid_llm; advisory for hybrid_stub',
        reviewer_protocol=dict(max_format_repairs=1, max_tokens=512, no_think=True,
            repair_budget='one consultation; all HTTP attempts logged'),
        benchmark_package=version('agentdojo'),source_fingerprints=source_fingerprints(),
        episode_ids=[r['episode_id'] for r in rows],mode='live')
    root=args.output_dir
    if root.exists():
        if not args.resume:parser.error('Output directory exists; use a new directory or --resume')
        if json.loads((root/'config.json').read_text())!=config:parser.error('Resume configuration/source/selection differs from frozen run')
        with (root/'manifest.csv').open(encoding='utf-8-sig',newline='') as file:frozen=list(csv.DictReader(file))
        if frozen!=rows:parser.error('Resume manifest differs from frozen run')
    else:
        if args.resume:parser.error('Cannot resume a nonexistent run')
        root.mkdir(parents=True)
        write_json(root/'config.json',config)
        with (root/'manifest.csv').open('x',encoding='utf-8-sig',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        (root/'episodes').mkdir()
    # Rebuild the aggregate from immutable per-episode result files on resume.
    aggregate=root/'results.jsonl'
    temp=root/'results.rebuild.next'
    aggregated=set()
    with temp.open('w',encoding='utf-8') as file:
        for row in rows:
            result_path=root/'episodes'/row['episode_id']/'result.json'
            if result_path.exists():
                record=json.loads(result_path.read_text())
                file.write(json.dumps(record,allow_nan=False)+'\n');aggregated.add(row['episode_id'])
        file.flush();os.fsync(file.fileno())
    temp.replace(aggregate)
    error_count = 0
    for index,row in enumerate(rows,1):
        folder=root/'episodes'/row['episode_id']
        if (folder/'result.json').exists():
            result=json.loads((folder/'result.json').read_text())
        elif folder.exists():
            result=interrupted_result(row,folder);write_json(folder/'result.json',result)
        else:
            result=execute_episode(row,folder,model=args.model,base_url=args.base_url,client=client,
                timeout=args.timeout,attempts=args.attempts,max_turns=args.max_turns,
                max_tool_calls=args.max_tool_calls,max_tokens=args.max_tokens,seed=args.seed,policy_options=policy_options)
        if row['episode_id'] not in aggregated:
            append_json(aggregate,result);aggregated.add(row['episode_id'])
        error_count += result['status'] != 'ok'
        print(f'[{index}/{len(rows)}] {row["suite"]} {row["user_task_id"]} {row["condition"]} {row["policy"]} k={row["k"]}: {result["status"]} utility={result["utility"]} security={result["security"]} reviews={result["review_count"]}',flush=True)
    print(f'Completed selection with {error_count} errors. Compare {root/"manifest.csv"} with {root/"results.jsonl"}.')
    return 2 if error_count else 0


if __name__=='__main__':raise SystemExit(main())
