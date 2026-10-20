"""Exercise real environments, direct attacks and official evaluators offline.

The scripted actor does not solve the original user tasks and is not a model
benchmark. Its fixed proposals and approvals are integration fixtures only.
"""
import argparse
from pathlib import Path
from agentdojo.functions_runtime import FunctionCall
from agentdojo.task_suite.load_suites import get_suites
from .experiment_runner import build_experiment_plan,save_plan_csv
from .run_experiments import execute_episode,append_json


class ScriptedAgent:
    def __init__(self,suite):self.suite=suite;self.turn=0
    def query(self,query,runtime,env=None,messages=None,extra_args=None):
        self.turn+=1
        helpers={'workspace':('get_current_day',{}),'travel':('get_all_hotels_in_city',{'city':'Paris'}),
                 'banking':('get_balance',{}),'slack':('get_channels',{})}
        tool,args=helpers[self.suite]
        if self.turn<=2:
            calls=[FunctionCall(function=tool,args=args,id='provider_repeated_id')]
            if self.turn==1:calls.append(FunctionCall(function='not_a_real_tool',args={},id='invalid'))
            assistant=dict(role='assistant',content=None,tool_calls=calls)
        else:assistant=dict(role='assistant',content=[dict(type='text',content='Offline integration fixture completed.')],tool_calls=None)
        return query,runtime,env,[*(messages or []),assistant],dict(extra_args or {})


class ScriptedReviewer:
    def approve(self,gate_input):return True


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(argv)
    args.output_dir.mkdir(parents=True,exist_ok=False)
    (args.output_dir/'episodes').mkdir()
    rows=build_experiment_plan(policies=['full_approve','full_escalate','risk_based','hybrid_stub_fixed','hybrid_stub'],k_values=[1])
    first_injection={name:next(iter(suite.injection_tasks)) for name,suite in get_suites('v1.2.2').items()}
    rows=[r for r in rows if r['user_task_id']=='user_task_0' and (r['condition']=='clean' or r['injection_task_id']==first_injection[r['suite']])]
    save_plan_csv(rows,args.output_dir/'manifest.csv')
    for row in rows:
        result=execute_episode(row,args.output_dir/'episodes'/row['episode_id'],
            agent=ScriptedAgent(row['suite']),reviewer=ScriptedReviewer())
        append_json(args.output_dir/'results.jsonl',result)
        if result['status']!='ok':raise RuntimeError(f'Offline integration failed: {result["error"]}')
        if result['review_count']>1:raise AssertionError('Review budget exceeded')
    print(f'PASS: {len(rows)} offline integration episodes across all suites and five policies.')
    print('Real environments, direct attack setup and official evaluation exercised with scripted actors; not model benchmark evidence.')


if __name__=='__main__':main()
