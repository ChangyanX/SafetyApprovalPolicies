# Local LLM-Judge（第 4 号成员交付）

## 架构与边界

已有流程为 SystemMessage → InitQuery → BudgetReset → LocalLLM → GateElement →
ToolsExecutor。Gate 调用 Policy.decide(GateInput)，由 Gate 管理预算和 Reviewer。
本模块只输出风险评估，不返回 Decision，不读取 k_remaining，不修改规则策略。
依赖沿用 requirements.txt 中的 openai、pydantic；没有新增大型框架。

唯一已有生产代码改动：gate.py 的 user_task_text 在 extra_args.user_task 缺失或为空时
回退到 query。原实现的 BudgetReset 不设置 user_task，导致正常管线可能丢失授权依据。
1 号应确保 query/extra_args.user_task 来自真实用户，而不是工具输出或 Agent 自述；
若执行框架会改写 query，请在入口保存原始任务到 extra_args.user_task。

## 环境与运行

在仓库根目录运行，使用独立环境，不在 base 安装：

```powershell
conda create -n ai6101-judge python=3.11 pip -y
conda activate ai6101-judge
python -m pip install -r requirements.txt
python -m pytest tests/ -q
```

模型服务另行部署。Judge 不自动下载模型、不自动启动服务、不回退到云端。
配置服务提供的 OpenAI-compatible `/v1` endpoint 和实际模型名称：

```powershell
$env:JUDGE_BASE_URL = "http://localhost:11434/v1"  # 示例，按部署修改
$env:JUDGE_MODEL = "qwen3:14b"                    # 示例，须已部署
$env:RUN_JUDGE_INTEGRATION = "1"
python -m pytest tests/test_judge_integration.py -v
```

JUDGE_API_KEY 可选，默认使用本地占位值 local；不写入追踪或配置文件。
from_env 要求显式给出 model 和 base_url。其它设置通过 JudgeConfig 构造参数或评估
脚本的 --config JSON 文件指定：timeout_seconds=30、temperature=0、max_tokens=512、
max_input_chars=24000、max_history_messages=512、response_format=json_object。
支持 json_schema 和 none；不支持所选格式的服务会返回 service_error，不隐式重试。
为降低本地开销，SDK 自动重试关闭；超时是 SDK 请求超时，并非严格的进程级墙钟上限。
思考模型可能将 token 预算耗尽在推理上，应由部署端关闭思考或调高 max_tokens 并实测。

## 独立调用示例

```python
from src.judge_types import JudgeInput
from src.llm_judge import LocalLLMJudge, JudgeConfig

judge = LocalLLMJudge(JudgeConfig.from_env())
result = judge.assess(JudgeInput(
    user_task_text="Show my account balance.",
    tool_name="get_balance", args={},
    tool_metadata={"risk": "low", "category": "read"},
))
print(result.status, result.assessment.authorization)
```

## 3 号调用接口

```python
from src.llm_judge import LocalLLMJudge, JudgeConfig
from src.judge_types import JudgeInput

judge = LocalLLMJudge(JudgeConfig.from_env())  # 重用实例
result = judge.assess(gate_input)             # 直接接受现有 GateInput
# 或 judge.assess(JudgeInput(...))，不需要 AgentDojo 或预算字段
if not result.usable:
    # 由 3 号的策略决定如何处理不可用/不确定结果，绝不能当成低风险。
    pass
else:
    risk = result.assessment
    # 结合 authorization、operational_risk、injection_suspected 等作最终决策。
    # 本模块不提供决策阈值或审批算法。
```

在 Policy.decide 中调用 assess 后返回现有 GateOutput 即可。1 号无需新增拦截器；
把 3 号策略传给 build_pipeline。为了成本分析，应另行收集 result.trace；现有 GateResult
不存 Judge 详情，本交付不扩大 GateResult 的职责。可添加调用 ID 关联，但不要记录敏感参数。
authorization_scope 是独立调用时可选的可信授权限制，不从历史中自动提取；适配 GateInput
时保留默认空值。如需多轮真实用户授权，入口应可靠汇总到 user_task_text/authorization_scope。

## 输出与失败语义

- authorization：authorized / unauthorized / uncertain。
- operational_risk：low / medium / high / critical / unknown，与授权分离。
- risk_score：0–1 的**未校准风险关注指标**，不是攻击率或违规概率。
  Prompt 使用明确分段锚点；高影响但获授权的操作仍可有较高分数。
- confidence：模型自述确定程度，同样未经校准。
- injection_suspected、context_sufficient、简短 rationale。
- status：ok / insufficient_context / invalid_output / timeout / service_error。
- schema_valid：是否真实获得了通过 Schema 的模型输出；与 usable 不等价。
- trace：模型、推理和长度配置、Prompt+Schema SHA256、耗时、可用 token 用量、截断标记。

Pydantic 严格校验枚举、类型、有限数值、范围、额外字段；JSON 重复键、代码围栏、
截断生成、拒答都不被自动“修复”为安全输出。缺失任务、输入不可序列化、上下文超长时
不调用模型；失败占位返回 uncertain/unknown、score=1、confidence=0，不能计为模型风险分数。
模型声明上下文不足、授权不确定或操作影响未知时 usable=False。调用方构造错误和配置错误会直接报错，
需要上层处理，不能据此批准。网络/SDK 错误转换为结构化状态，服务错误原文不落日志。

Prompt 是独立文本 src/prompts/risk_judge.txt，可用 prompt_path 替换。历史角色全部放入
同一个 JSON 数据字段，不重新发成 live system/user 消息。用户意图、调用、元数据、历史
分别标识来源；工具内容不能扩大授权。提示词隔离降低风险但不能证明模型免疫注入。

长度限制按字符而非精确 token；任务、参数和历史均不截断。超过消息数或字符上限时
直接返回 insufficient_context；history_truncated 表示历史无法完整送入模型，不会静默删减证据。
长轨迹应用需要调整上限或在后续设计有来源保证的摘要接口；应同时评估覆盖率和成本。
元数据中的 default_decision 不能当作授权；缺失工具语义时模型应报告不确定。
不默认记录请求、原始输出、理由或错误全文；理由本身仍可能含敏感内容，存储前需检查。

## 测试与轻量评估

单元测试用模拟模型响应覆盖授权读、未授权支付、授权删除、注入和目标/金额不匹配，
验证的是协议、证据来源隔离和异常处理，不代表模型具有正确识别能力。
真实模型测试显式启用，只检查服务连通和结构化输出；语义质量通过独立标注数据评估。

```powershell
python -m pytest tests/test_llm_judge.py tests/test_judge_evaluation.py -q
python -m scripts.evaluate_judge --data path/to/labeled_calls.jsonl --output judge-results.json
# 可选：--prompt path/to/prompt.txt --config path/to/config.json
```

评估输入 JSONL 每行含唯一 id、input（JudgeInput）、authorization 标签。
仓库不内置演示数据集；请提供人工审核的单次调用授权标签，不用冒烟案例拟合校准。
输出包含逐例标签/预测/状态/评分/trace 和聚合指标，不保存参数、任务、理由或服务地址。
数据集 id 也应避免包含个人信息。不同模型/Prompt 分别保存结果进行比较。

指标以 unauthorized 为正类；Precision/Recall/F1 和 FP/FN 仅对可用二分类结果计算。
同时明确报告 abstentions、按标签的弃权数和 coverage，避免服务失败被当作正确预测。
零分母为 null，不伪造 0/1。风险直方图排除失败占位值；结构化成功率的分母是全部案例，
同时报告 status_counts。token 缺失用 null 并统计可用调用数；合计是已报告部分，不代表全量。
延迟包含本地准备、请求与验证，提供平均值和最大值。

校准扩展协议 ScoreCalibrator 预留在 judge_types.py，当前没有拟合映射。
应先双人标注单次工具调用的授权状态，并按任务/攻击来源划分 train/validation/test，
避免同任务泄漏；再在验证集拟合映射，在独立测试集报告可靠性/Brier/ECE 等。
综合分数混合操作影响和授权风险，不一定适合单调映射为“未授权概率”，须先验证。
AgentDojo 的攻击成功是任务/攻击级结果，不能直接冒充单次调用授权标签。

## 已有仓库待集成注意点

RiskBasedPolicy 当前传 reason，但 GateOutput 定义 rationale，理由可能被忽略；本次未改动。
检查已安装 agentdojo 0.1.35 源码还发现：AgentPipeline.query 只顺序运行各元素一次，
当前 build_pipeline 没有使用 ToolsExecutionLoop，尚不是完整的多步任务管线。
混合批准/拒绝的批量调用中，Gate 会追加 blocked tool 消息，而 ToolsExecutor 在末条消息
不是 assistant 时直接返回，因此同批已批准项可能不执行。这些问题需由 1 号另行修复，
加入真实数据结构和多步任务测试；构造测试通过不等于端到端运行正确。
另外 LocalLLM 产生 Pydantic FunctionCall 对象，当前 Gate 用 tool_call["function"]
等字典访问方式，真实调用会遇到类型不兼容。既有测试只传字典，所以未覆盖此问题。
这也需 1 号统一 Gate/ToolsExecutor 的调用结构；独立 Judge 不依赖此拦截逻辑。
本模块未实现 Reviewer、审批算法、
预算策略或 TCR@k 实验，也没有声称完成端到端 AgentDojo 实验。
