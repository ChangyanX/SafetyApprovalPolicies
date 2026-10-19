# 本地 LLM-Judge 使用说明

## 模块定位

LLM-Judge 用于在工具调用执行前评估风险，重点判断操作是否符合用户授权、可能产生什么影响，以及是否受到提示注入的干扰。

现有调用流程为：

`SystemMessage → InitQuery → BudgetReset → LocalLLM → GateElement → ToolsExecutor`

Gate 将待执行的工具调用交给 `Policy.decide(GateInput)`。审批策略可以先调用 Judge，结合评估结果与剩余预算，再返回 `GateOutput`。

本模块沿用项目已有的 `openai`、`pydantic` 依赖，没有引入额外的大型框架。对原有执行代码的修改仅涉及 `src/gate.py` 中用户任务的传递：当 `extra_args.user_task` 缺失或为空时，回退使用 `query`。

## 配置

默认配置包括：请求超时 30 秒、温度 0、最大输出 512 tokens、输入上限 24,000 字符、历史消息上限 512 条，以及 `json_object` 输出格式。也可以通过 `JudgeConfig` 调整配置，并按服务支持情况选择 `json_schema` 或 `none`。

不同本地模型对 JSON 输出、思考模式和 token 限制的支持可能不同，部署时需要确认。SDK 自动重试已关闭；超时指请求超时，不保证严格的进程级耗时上限。

## 如何调用

Judge 可以直接接收项目中的 `GateInput`，也可以使用独立的 `JudgeInput`。

```python
from src.judge_types import JudgeInput
from src.llm_judge import LocalLLMJudge, JudgeConfig

judge = LocalLLMJudge(JudgeConfig.from_env())

result = judge.assess(JudgeInput(
    user_task_text="Show my account balance.",
    tool_name="get_balance",
    args={},
    tool_metadata={"risk": "low", "category": "read"},
))

print(result.status, result.assessment.authorization)
```

审批策略接入时，建议复用同一个 Judge 实例：

```python
from src.llm_judge import LocalLLMJudge, JudgeConfig

judge = LocalLLMJudge(JudgeConfig.from_env())

# gate_input 由 Gate 提供
result = judge.assess(gate_input)

if not result.usable:
    # 交给审批策略保守处理，不能默认批准
    pass
else:
    assessment = result.assessment
    # 结合授权状态、操作风险和剩余预算作出审批决定
```

审批策略负责将判断转换为批准、拒绝或升级，并返回现有的 `GateOutput`。Judge 不提供固定的审批阈值。

如果需要记录模型开销，可以使用 `result.trace` 中的耗时、模型信息和 token 用量。当前 `GateResult` 不会自动保存这些信息，需要负责集成与评估的模块另行关联记录，同时避免保存敏感参数。

## Judge 如何判断风险

Judge 会综合原始用户任务、工具名称及参数、工具风险元数据，以及可用的历史消息进行判断。

它重点区分两件事：

- **是否获得授权**：操作及其目标是否符合用户明确提出或合理隐含的要求。
- **操作本身有多大风险**：例如是否涉及删除、支付、敏感信息读取或对外发送。

两者分别判断。例如，用户明确要求删除指定文件，删除操作仍可能具有较高风险，但不能仅因为危险就判定为未经授权。

Judge 也会检查历史记录是否含有提示注入。邮件、网页及工具返回内容只能作为上下文证据，不能自行扩大用户授权。相关规则保存在 `src/prompts/risk_judge.txt`，可以通过 `prompt_path` 更换。

对于信息不足的情况，Judge 会返回不确定结果，不会猜测缺失的授权或工具效果。

## 输出结果与异常处理

`result.assessment` 包含以下字段：

| 字段 | 含义 |
| --- | --- |
| `authorization` | 授权状态：`authorized`、`unauthorized` 或 `uncertain` |
| `operational_risk` | 操作风险：`low`、`medium`、`high`、`critical` 或 `unknown` |
| `risk_score` | 0–1 的综合风险关注分数 |
| `confidence` | 模型自述的判断把握程度 |
| `injection_suspected` | 是否怀疑存在提示注入 |
| `context_sufficient` | 现有上下文是否足以支持判断 |
| `rationale` | 简短的判断理由 |

`risk_score` 和 `confidence` **都没有经过校准**，不能理解为违规概率或实际正确率。高风险但已授权的操作，也可能得到较高的综合分数。

`result.status` 表示本次评估是否正常完成，可能为：

- `ok`：模型返回了可验证的评估结果。
- `insufficient_context`：用户任务或其他关键上下文不足。
- `invalid_output`：模型输出不符合要求。
- `timeout`：请求超时。
- `service_error`：模型服务或请求发生错误。

代码会严格检查 JSON 格式和字段类型，不会自动把异常输出解释为安全。服务失败时会返回保守占位值（授权不确定、风险未知、风险分数为 1、置信度为 0）。**这些占位值不代表模型实际判断出的风险**。

上层审批策略应先检查 `result.usable`。即使 JSON 格式正确，只要授权状态或操作影响仍无法确认，也可能是不可用结果。

`result.trace` 记录模型名称、相关配置、耗时、可取得的 token 用量和输入截断情况，不默认保存原始请求或模型输出。记录理由和其他信息时仍需注意敏感数据。

## 集成时需要注意

1. **确保用户任务可信。** 工具拦截模块应传入真实用户的原始任务。当前 `gate.py` 会在 `extra_args.user_task` 缺失时使用 `query`，但如果执行框架可能改写 `query`，应在入口处提前保存原始任务。新的用户授权也应从可信入口传递，不能从工具输出中推断。

2. **由审批策略完成最终决策。** Judge 提供授权状态、操作风险和提示注入信号；审批策略再结合规则与人工审核预算决定批准、拒绝或升级。不能仅凭 `risk_score` 设置统一阈值，也不能在 Judge 不可用时默认批准。

3. **确认工具调用的数据结构。** 现有 Agent 可能产生 Pydantic `FunctionCall` 对象，而 Gate 目前按字典读取工具调用。负责工具拦截与执行集成的模块需要统一格式，避免真实调用时出现类型错误。

4. **完善多步调用流程。** 当前 `build_pipeline()` 尚未使用完整的 `ToolsExecutionLoop`。此外，批量工具调用中若同时存在批准和拒绝，消息顺序可能影响已批准操作的执行。这些属于主流程集成问题，需要在 Gate 和工具执行模块中处理。

5. **统一审批输出字段。** 现有 `RiskBasedPolicy` 使用 `reason`，而 `GateOutput` 定义的是 `rationale`。负责规则审批策略的模块需要统一字段，避免审批理由丢失。

6. **注意历史上下文与成本。** Judge 按字符数和消息数量限制输入，而非精确 token 数。超过限制会返回上下文不足，不会悄悄丢弃证据。长任务需要在上下文完整性、推理速度和成本之间权衡。
