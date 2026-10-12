"""AgentDojo 0.1.35 adapter preserving Gemini's signed response parts."""
from copy import deepcopy

from google.genai import types
from agentdojo.agent_pipeline.llms.google_llm import (
    GoogleLLM,
    _function_to_google,
    _google_to_assistant_message,
    _merge_tool_result_messages,
    _message_to_google,
    chat_completion_request,
)


class SignedGoogleLLM(GoogleLLM):
    """Keep provider history in episode state, outside the agent-visible messages."""

    def query(self, query, runtime, env, messages, extra_args):
        state_key = "_gemini_signed_history"
        extra_args = dict(extra_args)
        saved = dict(extra_args.get(state_key, {}))
        # A new episode must never inherit signatures from a previous one.
        if not any(message["role"] == "assistant" for message in messages):
            saved = {}
        system_instruction = None
        converted = []
        for index, message in enumerate(messages):
            if index == 0 and message["role"] == "system":
                system_instruction = message["content"][0]["content"]
                continue
            if index in saved:
                original, content = saved[index]
                if message != original:
                    raise ValueError("Signed Gemini history was modified; start a fresh episode.")
                converted.append(content.model_copy(deep=True))
            else:
                if message["role"] == "assistant":
                    raise ValueError("Missing original Gemini response; start a fresh episode.")
                converted.append(_message_to_google(message))
        functions = [_function_to_google(tool) for tool in runtime.functions.values()]
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
            tools=[types.Tool(function_declarations=functions)] if functions else None,
            system_instruction=system_instruction,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        completion = chat_completion_request(
            self.model, self.client, _merge_tool_result_messages(converted), config
        )
        output = _google_to_assistant_message(completion)
        content = completion.candidates[0].content if completion.candidates else None
        if content is not None:
            saved[len(messages)] = (deepcopy(output), content.model_copy(deep=True))
        extra_args[state_key] = saved
        return query, runtime, env, [*messages, output], extra_args
