"""Bounded native tool-calling adapter for an Ollama OpenAI-compatible endpoint."""
from copy import deepcopy
import json
import time
from agentdojo.agent_pipeline import BasePipelineElement
from agentdojo.functions_runtime import FunctionCall
from .gated_runtime import text, jsonable


class OllamaToolAgent(BasePipelineElement):
    def __init__(self, client, model='qwen3:14b', *, max_tokens=4096, seed=0,
                 attempts=1, on_usage=None):
        self.client, self.model = client, model
        self.max_tokens, self.seed, self.attempts = max_tokens, seed, attempts
        self.on_usage = on_usage
        self.usage = []

    def query(self, query, runtime, env=None, messages=None, extra_args=None):
        wire=[]
        for message in messages or []:
            role=message['role']
            value=dict(role=role,content=text(message.get('content')))
            if role=='assistant' and message.get('tool_calls'):
                value['tool_calls']=[dict(id=c.id,type='function',function=dict(name=c.function,
                    arguments=json.dumps(jsonable(c.args),allow_nan=False))) for c in message['tool_calls']]
            if role=='tool':
                value['tool_call_id']=message['tool_call_id']
                value['content']=message.get('error') or text(message.get('content'))
            wire.append(value)
        tools=[dict(type='function',function=dict(name=t.name,description=t.description,
                    parameters=t.parameters.model_json_schema())) for t in runtime.functions.values()]
        for attempt in range(1,self.attempts+1):
            start=time.monotonic()
            try:
                response=self.client.chat.completions.create(model=self.model,messages=wire,
                    tools=tools,tool_choice='auto',temperature=0,seed=self.seed,
                    max_tokens=self.max_tokens,extra_body={'think':False})
            except Exception as exc:
                event=dict(component='agent',model=self.model,status='error',attempt=attempt,
                    latency_s=time.monotonic()-start,error=type(exc).__name__,input_tokens=None,output_tokens=None)
                self.usage.append(event)
                if self.on_usage:self.on_usage(deepcopy(event))
                if attempt==self.attempts:raise
                continue
            usage=getattr(response,'usage',None)
            event=dict(component='agent',model=self.model,status='ok',attempt=attempt,
                latency_s=time.monotonic()-start,input_tokens=getattr(usage,'prompt_tokens',None),
                output_tokens=getattr(usage,'completion_tokens',None))
            self.usage.append(event)
            if self.on_usage:self.on_usage(deepcopy(event))
            choice=response.choices[0]
            if choice.finish_reason=='length':
                raise RuntimeError('Agent response truncated at token bound')
            message=choice.message
            calls=[]
            for call in message.tool_calls or []:
                arguments=json.loads(call.function.arguments)
                if not isinstance(arguments,dict):raise ValueError('Tool arguments must be a JSON object')
                calls.append(FunctionCall(function=call.function.name,args=arguments,id=call.id))
            assistant=dict(role='assistant',content=[dict(type='text',content=message.content)] if message.content else None,
                           tool_calls=calls or None)
            return query,runtime,env,[*(messages or []),assistant],dict(extra_args or {})
