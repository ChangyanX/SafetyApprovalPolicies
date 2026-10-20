"""Factory for the connected, repeated gated AgentDojo pipeline."""
from openai import OpenAI
from .gated_runtime import GatedAgentPipeline
from .ollama_agent import OllamaToolAgent


def build_pipeline(model, policy, k, reviewer, tool_risk_metadata, system_prompt='',
                   client=None, suite_name=None, *, episode_id=None, agent=None,
                   max_turns=20, max_tool_calls=80, on_event=None, on_agent_usage=None,
                   max_tokens=4096, attempts=1, seed=0):
    if agent is None:
        client = client or OpenAI(base_url='http://localhost:11434/v1', api_key='ollama',
                                  timeout=120, max_retries=0)
        agent = OllamaToolAgent(client, model, max_tokens=max_tokens, attempts=attempts,
                               seed=seed, on_usage=on_agent_usage)
    return GatedAgentPipeline(agent, policy, reviewer, tool_risk_metadata,
        suite_name=suite_name or getattr(tool_risk_metadata,'suite_name',None), k=k,
        episode_id=episode_id, system_prompt=system_prompt, max_turns=max_turns,
        max_tool_calls=max_tool_calls, on_event=on_event)
