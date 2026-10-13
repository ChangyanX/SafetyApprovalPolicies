# 6101 Agent Harnesses

Safety gate for LLM agents using AgentDojo framework. Intercepts tool calls and applies
a policy to approve/deny/escalate based on tool risk metadata.

## Setup

### Prerequisites

- Python 3.11+
- Ollama (for local LLM) or OpenAI-compatible API

### Installation

#### Clone the repository

```bash
git clone <repo-url>
cd 6101-agent-harness
```
#### Create conda environment
```bash
conda create -n agent python=3.11
conda activate agent
```
#### install dependencies
```bash
pip install -r requirements.txt
```
#### Install Ollama from https://ollama.com
```bash
sudo apt-get install ollama
ollama pull qwen3:14b

ollama list
ollama serve
```

## Usage
### Running Tests
```bash
pytest test/ -v
```

Expected: 18 tests passing.

### Building a Pipeline
```python
from src.pipeline import build_pipeline
from src.risk_based_policy import RiskBasedPolicy
from src.tool_risk import load_tool_risk_metadata
from openai import OpenAI
```

### Load tool risk metadata
```python
md = load_tool_risk_metadata("src/tool_risk_metadata.yaml")
```
### Create Policy
```python
policy = RiskBasedPolicy(md)
```
### Creat OpenAI client for Ollama
```python
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
```

### Build Pipeline 

```python
pipeline = build_pipeline(
model="qwen3:14b",
policy=policy,
k=5,
reviewer=my_reviewer,
tool_risk_metadata=md,
system_prompt="You are a banking assistant.",
client=client,
)
```

### Running on Agentdojo
```python
from agentdojo import AgentPipeline
```

### Use the built pipeline with AgentDojo's task suite
See agentdojo docs for task execution

## Configuration
### Tool Risk Metadata
Edit `src/tool_risk_metadata.yaml` to configure tool risk levels:

```yaml
tools:
send_money:
risk: high
category: execute
default_decision: ESCALATE
```

### Escalation Bugdgt
he `k` parameter in `build_pipeline` controls the escalation budget:
- Each `ESCALATE` decision consumes 1 budget
- When budget is exhausted, `ESCALATE` degrades to `AUTO_DENY`
- Budget resets at the start of each task

## Project Structure
```plain
├── src/
│ ├── types.py # Core type definitions
│ ├── gate.py # GateElement - tool approval gate
│ ├── budget.py # BudgetResetElement - per-task budget reset
│ ├── risk_based_policy.py # RiskBasedPolicy - YAML-driven policy
│ ├── tool_risk.py # YAML loader for tool risk metadata
│ ├── tool_risk_metadata.yaml # Tool risk configuration
│ └── pipeline.py # build_pipeline factory
├── tests/ # Unit tests (18 tests)
├── configs/ # Experiment configs
└── conftest.py # Pytest fixtures
```

## Timeline

- **Oct 12**: Interface + repo setup
- **Oct 13**: Gate draft (current)
- **Oct 14**: Merge + test hard deadline
- **Oct 15-16**: Integrate policy/reviewer v1
- **Oct 19-22**: Sweep
- **Oct 23-26**: Fresh clone testing

## Changelog

### v0.1.0 (Oct 13, 2026)

- Initial gate implementation
- RiskBasedPolicy with YAML metadata
- Pipeline factory with BudgetReset
- 18 unit tests passing