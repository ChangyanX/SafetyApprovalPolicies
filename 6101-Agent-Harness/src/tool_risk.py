"""Load suite-scoped tool metadata while accepting legacy single-suite YAML."""
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class ToolRiskMetadata(dict):
    """Dict-compatible view with an explicit catalog of suite namespaces.

    Without a selected suite, only unambiguous names appear in the flat view.
    Always pass suite_name for production multi-domain lookup.
    """

    def __init__(self, defaults, suites, suite_name=None):
        self.suites = deepcopy(suites)
        self.suite_name = suite_name
        if suite_name is not None:
            if suite_name not in suites:
                raise ValueError(f"Unknown metadata suite: {suite_name}")
            tools = suites[suite_name]
        else:
            occurrences = {}
            for entries in suites.values():
                for name, meta in entries.items():
                    occurrences.setdefault(name, []).append(meta)
            tools = {name: values[0] for name, values in occurrences.items() if len(values) == 1}
        super().__init__(deepcopy(tools))
        self['__default__'] = deepcopy(defaults)


def load_tool_risk_metadata(path: str | Path, suite_name: str | None = None) -> ToolRiskMetadata:
    with open(path, encoding='utf-8') as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError('Tool metadata must be a YAML mapping')
    defaults = data.get('defaults', {})
    if not isinstance(defaults, dict):
        raise ValueError('Metadata defaults must be a mapping')
    if 'suites' in data:
        raw_suites = data['suites']
        if not isinstance(raw_suites, dict) or not raw_suites:
            raise ValueError('Metadata suites must be a non-empty mapping')
    else:
        # Legacy format describes one unspecified suite.
        raw_suites = {suite_name or '__legacy__': {'tools': data.get('tools', {})}}
    suites = {}
    for suite, definition in raw_suites.items():
        if not isinstance(definition, dict) or not isinstance(definition.get('tools'), dict):
            raise ValueError(f'Metadata suite {suite!r} needs a tools mapping')
        suites[suite] = {}
        for name, meta in definition['tools'].items():
            if not isinstance(meta, dict):
                raise ValueError(f'Metadata for {suite}/{name} must be a mapping')
            merged = {**deepcopy(defaults), **deepcopy(meta)}
            if merged.get('default_decision') not in (None, 'AUTO_APPROVE', 'AUTO_DENY', 'ESCALATE'):
                raise ValueError(f'Invalid default decision for {suite}/{name}')
            suites[suite][name] = merged
    return ToolRiskMetadata(defaults, suites, suite_name)


def risk_for(tool_risk_metadata: dict, tool_name: str, suite_name: str | None = None) -> dict[str, Any]:
    if suite_name is not None and isinstance(tool_risk_metadata, ToolRiskMetadata):
        if suite_name not in tool_risk_metadata.suites:
            raise ValueError(f'Unknown metadata suite: {suite_name}')
        return deepcopy(tool_risk_metadata.suites[suite_name].get(
            tool_name, tool_risk_metadata.get('__default__', {})))
    return deepcopy(tool_risk_metadata.get(tool_name) or tool_risk_metadata.get('__default__', {}))
