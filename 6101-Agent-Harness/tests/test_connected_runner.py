"""Real runtime/official-evaluator integration with offline scripted transports."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentdojo.functions_runtime import FunctionsRuntime,FunctionCall
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.task_suite.task_suite import functions_stack_trace_from_messages
from src.experiment_runner import build_experiment_plan,save_plan_csv
from src.gated_runtime import GatedAgentPipeline,EpisodeLimitError
from src.gated_smoke import ScriptedAgent,ScriptedReviewer
from src.ollama_agent import OllamaToolAgent
from src.policy import FullApprovePolicy,FullEscalatePolicy
from src.r3_compare import compare
from src.run_experiments import execute_episode,main,validate_manifest,interrupted_result,append_json
from src.scope_policy import ScopeAwarePolicy
from src.reviewer import LLMReviewer
from tenacity import wait_none
from src.tool_risk import load_tool_risk_metadata
from src.types import GateOutput,Decision

CATALOG=Path(__file__).resolve().parents[1]/'src/tool_risk_metadata.yaml'


def call(name='get_balance',args=None):return FunctionCall(function=name,args=args or {},id='reused_provider_id')


class Actor:
    def __init__(self,batches):self.batches=deepcopy(batches);self.seen=[]
    def query(self,query,runtime,env=None,messages=None,extra_args=None):
        self.seen.append(deepcopy(messages));calls=self.batches.pop(0) if self.batches else []
        message=dict(role='assistant',content=None if calls else [dict(type='text',content='Done.')],tool_calls=calls or None)
        return query,runtime,env,[*(messages or []),message],dict(extra_args or {})


class ConnectedTests(unittest.TestCase):
    def setUp(self):
        self.suite=get_suite('v1.2.2','banking');self.runtime=FunctionsRuntime(self.suite.tools)
        self.env=self.suite.load_and_inject_default_environment({})
        self.metadata=load_tool_risk_metadata(CATALOG)
    def pipeline(self,actor,policy=None,reviewer=None,k=1,**kw):
        return GatedAgentPipeline(actor,policy or FullApprovePolicy(),reviewer or ScriptedReviewer(),self.metadata,
            suite_name='banking',k=k,episode_id='ep-test',**kw)
    def runpipe(self,p,task='Get my current balance.'):
        return p.query(task,self.runtime,self.env)
    def test_mixed_batch_does_not_skip_allowed_and_no_transcript_mutation(self):
        class Selective:
            def decide(self,gi):return GateOutput(decision=Decision.AUTO_APPROVE if gi.tool_name=='get_balance' else Decision.AUTO_DENY)
        original=[call('read_file',{'file_path':'not-allowed'}),call()]
        actor=Actor([original]);p=self.pipeline(actor,Selective())
        with patch.object(self.runtime,'run_function',wraps=self.runtime.run_function) as invoked:
            self.runpipe(p)
            self.assertEqual(invoked.call_count,1)
        self.assertEqual(original[0].id,'reused_provider_id')
        self.assertEqual(len(p.messages[2]['tool_calls']),2)
        self.assertEqual(len([m for m in p.messages if m['role']=='tool']),2)
        self.assertEqual([c.function for c in functions_stack_trace_from_messages(p.evaluation_messages())],['get_balance'])
        self.assertEqual(p.executed_calls[0]['call_id'],'c000002')
    def test_repeated_loop_and_retry_entry_never_refill_budget(self):
        actor=Actor([[call()],[call()],[call()]])
        p=self.pipeline(actor,FullEscalatePolicy(),k=1);self.runpipe(p)
        self.assertEqual((p.turns,p.review_count,p.k_remaining),(4,1,0))
        self.assertEqual(len(p.executed_calls),1)
        p.query('Get my current balance.',self.runtime,self.env,extra_args={'k_remaining':100})
        self.assertEqual((p.review_count,p.k_remaining),(1,0))
        with self.assertRaises(ValueError):p.query('Different task',self.runtime,self.env)
    def test_reviewer_error_consumes_one_and_denies(self):
        class Broken:
            def approve(self,gi):raise TimeoutError('fixture')
        p=self.pipeline(Actor([[call(),call()]]),FullEscalatePolicy(),Broken())
        self.runpipe(p);self.assertEqual(p.review_count,1);self.assertEqual(p.executed_calls,[])
        self.assertTrue(any('Reviewer error' in e.get('rationale','') for e in p.events))
    def test_reviewer_http_retries_do_not_spend_extra_review_slots(self):
        attempts=[];summaries=[]
        reviewer=LLMReviewer(client=object(),max_attempts=2,retry_wait=wait_none(),
                             on_attempt=attempts.append,on_usage=summaries.append)
        responses=[TimeoutError('fixture'),('{"decision":"approve","reason":"scoped"}',
                    {'model':'qwen3:14b','status':'ok','input_tokens':10,'output_tokens':5})]
        def raw(prompt):
            value=responses.pop(0)
            if isinstance(value,Exception):raise value
            return value
        reviewer._raw_call=raw
        p=self.pipeline(Actor([[call(),call()]]),FullEscalatePolicy(),reviewer,k=1)
        self.runpipe(p)
        self.assertEqual((p.review_count,reviewer.consultations),(1,1))
        self.assertEqual(len(p.executed_calls),1)
        self.assertEqual([a['status'] for a in attempts],['error','ok'])
        self.assertEqual(len(summaries),1)

    def test_scope_begin_feedback_duplicates_and_original_task(self):
        policy=ScopeAwarePolicy();p=self.pipeline(Actor([[call()],[call()]]),policy,k=0)
        self.runpipe(p)
        snapshot=policy.snapshot();self.assertEqual(snapshot['task'],'Get my current balance.')
        self.assertEqual(len(p.executed_calls),1);self.assertEqual(len(snapshot['executions']),2)
        self.assertEqual(snapshot['decisions'][1]['decision'],'AUTO_DENY')
        self.assertEqual(p.k_remaining,0)
    def test_partial_failure_commits_capacity(self):
        policy=ScopeAwarePolicy();p=self.pipeline(Actor([[call()],[call()]]),policy,k=0)
        env={'effects':0}
        def partial(*args):env['effects']+=1;return '', 'Partial failure'
        with patch.object(self.runtime,'run_function',side_effect=partial):p.query('Get my current balance.',self.runtime,env)
        self.assertEqual(len(p.executed_calls),1)
        self.assertFalse(p.executed_calls[0]['success']);self.assertTrue(p.executed_calls[0]['effect_committed'])
    def test_uncertain_execution_aborts_and_is_audited(self):
        p=self.pipeline(Actor([[call()]]),ScopeAwarePolicy(),k=0)
        with patch.object(self.runtime,'run_function',side_effect=RuntimeError('uncertain')):
            with self.assertRaises(RuntimeError):self.runpipe(p)
        self.assertEqual(len(p.executed_calls),1)
        self.assertTrue(p.executed_calls[0]['effect_uncertain'])
    def test_nested_and_invalid_arguments_never_reach_runtime(self):
        nested=FunctionCall(function='read_file',args={'file_path':call()})
        p=self.pipeline(Actor([[nested,call('send_money',{'amount':'invalid'})]]))
        with patch.object(self.runtime,'run_function',wraps=self.runtime.run_function) as invoked:self.runpipe(p);invoked.assert_not_called()
    def test_episode_bounds_and_audit_failure_abort(self):
        p=self.pipeline(Actor([[call()],[call()]]),max_turns=1)
        with self.assertRaises(EpisodeLimitError):self.runpipe(p)
        p=self.pipeline(Actor([[call(),call()]]),max_tool_calls=1)
        with self.assertRaises(EpisodeLimitError):self.runpipe(p)
        self.assertEqual(p.executed_calls,[])
        def fail(event):raise OSError('disk full')
        p=self.pipeline(Actor([[call()]]),on_event=fail)
        with self.assertRaises(OSError):self.runpipe(p)
        self.assertEqual(p.executed_calls,[])
    def test_ids_unique_across_turns_and_exact_effective_args_audited(self):
        p=self.pipeline(Actor([[call()],[call()]]));self.runpipe(p)
        self.assertEqual([r['call_id'] for r in p.executed_calls],['c000001','c000002'])
        proposals=[e for e in p.events if e['kind']=='proposal']
        self.assertEqual(proposals[0]['provider_id'],proposals[1]['provider_id'])
        self.assertEqual(proposals[0]['original']['id'],'reused_provider_id')


class NativeAdapterTests(unittest.TestCase):
    def test_native_tool_wire_and_usage(self):
        received=[]
        def create(**kwargs):
            received.append(kwargs)
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=3,completion_tokens=4),
                choices=[SimpleNamespace(finish_reason='tool_calls',message=SimpleNamespace(content=None,
                    tool_calls=[SimpleNamespace(id='p1',function=SimpleNamespace(name='get_balance',arguments='{}'))]))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        agent=OllamaToolAgent(client)
        runtime=FunctionsRuntime(get_suite('v1.2.2','banking').tools)
        _,_,_,messages,_=agent.query('q',runtime,messages=[{'role':'system','content':[{'type':'text','content':'sys'}]}])
        self.assertEqual(received[0]['messages'][0]['role'],'system')
        self.assertTrue(received[0]['tools']);self.assertEqual(messages[-1]['tool_calls'][0].function,'get_balance')
        self.assertEqual(agent.usage[0]['input_tokens'],3)
    def test_model_retries_bounded_and_truncation_detected(self):
        from unittest.mock import Mock
        create=Mock(side_effect=TimeoutError())
        agent=OllamaToolAgent(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),attempts=2)
        with self.assertRaises(TimeoutError):agent.query('q',FunctionsRuntime([]))
        self.assertEqual(create.call_count,2)
        create.side_effect=None;create.return_value=SimpleNamespace(usage=None,choices=[SimpleNamespace(finish_reason='length')])
        with self.assertRaises(RuntimeError):agent.query('q',FunctionsRuntime([]))


class RunnerTests(unittest.TestCase):
    def row(self):
        return next(r for r in build_experiment_plan(suite_name='banking',policies=['full_approve'],k_values=[1],include_attacked=False) if r['user_task_id']=='user_task_0')
    def test_real_official_clean_and_attack_fixtures_are_separate(self):
        rows=build_experiment_plan(suite_name='banking',policies=['full_escalate'],k_values=[1])
        rows=[r for r in rows if r['user_task_id']=='user_task_0' and (r['condition']=='clean' or r['injection_task_id']=='injection_task_0')]
        with tempfile.TemporaryDirectory() as tmp:
            for row in rows:
                folder=Path(tmp)/row['episode_id']
                result=execute_episode(row,folder,agent=ScriptedAgent('banking'),reviewer=ScriptedReviewer())
                self.assertEqual(result['status'],'ok',result.get('error'))
                self.assertEqual(result['mode'],'offline_test');self.assertEqual(result['review_count'],1)
                self.assertTrue((folder/'trajectory.json').exists());self.assertTrue((folder/'audit.jsonl').exists())
                self.assertIs(type(result['utility']),bool);self.assertIs(type(result['security']),bool)
                with self.assertRaises(ValueError):compare([row],[result])
    def test_manifest_validation_and_interrupted_reconstruction(self):
        row=self.row();validate_manifest([row])
        with self.assertRaises(ValueError):validate_manifest([row,row])
        with self.assertRaises(ValueError):validate_manifest([dict(row,episode_id='../escape')])
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            append_json(folder/'audit.jsonl',dict(kind='review_started',call_id='c1'))
            append_json(folder/'audit.jsonl',dict(kind='execution_started',call_id='c1',tool='get_balance',arguments={}))
            result=interrupted_result(row,folder)
            self.assertEqual(result['review_count'],1);self.assertEqual(len(result['executed_calls']),1)
            self.assertEqual(result['status'],'error')
    def test_cli_resume_skips_completed_episode_and_keeps_single_result(self):
        class Client:
            models=SimpleNamespace(list=lambda:SimpleNamespace(data=[SimpleNamespace(id='qwen3:14b')]))
            def with_options(self,**kw):return self
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=root/'plan.csv';save_plan_csv([self.row()],manifest)
            out=root/'run';argv=['--manifest',str(manifest),'--output-dir',str(out),'--all']
            real_execute=execute_episode
            def fixture(row,folder,**kw):return real_execute(row,folder,agent=ScriptedAgent('banking'),reviewer=ScriptedReviewer())
            with patch('src.run_experiments.OpenAI',return_value=Client()),patch('src.run_experiments.execute_episode',side_effect=fixture) as execute:
                main(argv);main(argv+['--resume']);self.assertEqual(execute.call_count,1)
            self.assertEqual(len((out/'results.jsonl').read_text().splitlines()),1)


if __name__=='__main__':unittest.main()
