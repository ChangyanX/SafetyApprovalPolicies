# R4 local assessor → R3 合并说明

Current implementation update (21 October 2026): live `hybrid_llm` and `hybrid_llm_fixed` use decision-effective R4 review selection and conflict denial, version `r3-r4-review-selection-v1`. They never create grants or bypass deterministic checks/review budgets. Advisory descriptions below apply to the stub ablation or historical stage. See [the combined-policy specification](../docs/R3_R4_POLICY.md) and [current banking guide](../docs/BANKING_EVALUATION_GUIDE.md); rerun pilots in fresh directories.

对照基线：`R3_policies` 的 `0257352ddfc796abbdb4ad7cfb8a9949e977bc4b`（2026-10-21 获取）。
目标是接入现有 `r3-r4/0.1` advisory 契约，不改变 R3 的审批规则、预算或状态生命周期。

## 对接结论

旧接口 `LocalLLMJudge.assess(GateInput | JudgeInput) -> JudgeResult` 输出整体风险，
不能直接注入 `ScopeAwarePolicy`。R3 要求
`assess(AssessmentRequest) -> AssessmentResponse`，以未解决的 check 为单位，
并绑定 episode_id/call_id/proposal_hash 和证据引用。

新增 `LocalR3Assessor` 使用独立 Prompt 和 R3 权威 Schema。它不把整体风险分数
机械转换成逐项结论，也不调用 R2 Reviewer。旧 Judge 仍可独立调用，但不是 R3 的 assessor。

| 项目 | 原 Judge | R3 对接版本 |
| --- | --- | --- |
| 输入 | 用户任务、参数、元数据、轨迹 | R3 已验证的有效参数、工具语义、检查项及 evidence |
| 输出 | 授权、操作影响、评分、置信度 | 检查状态、简短理由、现有 evidence IDs |
| 关联身份 | 无 | 原样回传版本、episode/call/hash，拒绝过期响应 |
| 失败 | JudgeResult.status | unavailable/error + 空 checks + 固定错误码 |
| 最终审批 | 外部 Policy | R3 原逻辑；模型结果仅写入审计 |

尤其注意：当前 R3 对合法的模型结果也**不改写确定性 checks、不生成 grants**。
因此接通真实模型主要增加审计信息和推理成本，不能据此宣称会提高 TCR 或减少 HITL。
返回 SATISFIED/NOT_APPLICABLE 均不能直接批准或关闭必要检查。
目前结果也未自动传给 Reviewer；如需这么做，应由 R2/R3 明确审查后另行接线。

## 使用现有注入点，无需修改 R3 源码

从 `6101-Agent-Harness/` 运行。沿用团队环境和 requirements，不创建项目专属环境文件。
配置 `JUDGE_MODEL`、`JUDGE_BASE_URL`；可选 `JUDGE_API_KEY`。本地推理服务需自行部署，
不自动下载模型、不回退云端。例如服务实际提供的 model 名称和 `/v1` 地址。

```python
from src.llm_judge import JudgeConfig
from src.r4_assessor import LocalR3Assessor
from src.scope_policy import ScopeAwarePolicy

assessor = LocalR3Assessor(JudgeConfig.from_env())
policy = ScopeAwarePolicy(assessor=assessor)
```

已有工厂也支持注入：

```python
from src.policy import make_policy

policy = make_policy(
    "hybrid_stub",  # R3 当前注册名称；不要把真实模型结果与 stub 结果混合汇总
    policy_options={"assessor": assessor},
)
```

`run_experiments.execute_episode(..., policy_options={"assessor": assessor})` 同样可用；
由已有 `GatedAgentPipeline` 负责 begin_episode、call ID、execution/nonexecution feedback。
不要再添加 Gate 或管理 k。R3 当前 CLI 未提供 assessor 参数，且 `POLICY_LABELS` 仅注册
stub 名称；正式实验前应由 R3/R5增加明确的 advisory-model 配置标识，并在 manifest/result
和成本记录中保存模型、Prompt 哈希、参数。不要偷偷把默认 stub 替换为真实模型。

## 安全与错误处理

- 全部历史 evidence 包在单个 JSON 数据消息中；embedded system/user 角色不能成为指令。
- task 是用户意图，工具事实不能独立扩大授权。明确的文件委托/查账可以提供任务所需值，
  但须受原始任务范围约束，不能一概把所有外部数据当作新增授权。
- 仅允许回答请求中的 UNRESOLVED check，不能覆盖确定性违规或已经确认的 check。
- 拒绝身份不匹配、额外字段、重复 JSON key、重复 check、虚构/缺失/重复 evidence 引用。
- 拒绝失败状态携带实质 check、成功状态携带 error、空理由、截断输出或拒答。
- 使用 `AssessmentResponse.model_validate_json`，兼容 strict Enum；不是宽松字典强转。
- SDK 自动重试关闭，默认 30 秒请求超时、temperature=0、max_tokens=512。
  这是 SDK 超时，不是硬性进程墙钟截止；注入自定义 client 时由调用方保持无隐式重试。
- 输入完整序列化后检查总字符上限，消息上限用于 evidence 条数；超限返回 unavailable，
  不截断证据。`history_truncated` 表示完整输入不能送入模型，非已执行部分推理。
- 响应中的 citations 只证明引用存在，不证明内容真实或授权成立；这是保持 advisory 的原因。
- 不读取 benchmark oracle、攻击目标或隐藏环境；但 R3/调用方仍须保证传入证据没有这些字段。
  不能依赖 Prompt 自动删除上游错误泄露的数据。

R3 已在构造请求时按完整 evidence item 截取上下文，并且没有传递 omitted-evidence 标志。
R4 无法恢复这些被省略的内容，不会宣称看到了全轨迹；后续若让模型结果影响审批，须先补齐
上下文覆盖信息与候选授权验证规则，再按新版本重新评估。

## R5 成本接入

`last_trace` 只保存最后一次评估。通过 `on_trace` 接收全部记录：suite、episode/call/hash、状态、
固定错误码、模型、Prompt+Schema 哈希、参数、延迟、token 用量和 provider_called。
不包含任务、调用参数、模型理由、原始输出或服务错误全文；token 未提供时为 None。
回调异常只传播一次，不重试回调，也不误报为模型输出错误。R3 当前会捕获该异常并记为
assessor error，而非中止整个 episode；如要求成本写入失败必须中止，由主流程另行落实。
每个实例按顺序使用，不跨线程共享。

现有 CostTracker 的组件名为 `policy`，不是 `judge`/`assessor`：

```python
def record_assessor_usage(trace):
    if not trace.provider_called:
        return  # 本地预检查失败不算模型请求；如需统计另存状态记录
    tracker.record_call(
        component="policy", model=trace.model, provider="local",
        input_tokens=trace.prompt_tokens, output_tokens=trace.completion_tokens,
        cost_usd=None, status=trace.status, request_id=trace.call_id,
        suite=trace.suite, episode_id=trace.episode_id, proposal_hash=trace.proposal_hash,
        latency_ms=trace.latency_ms, prompt_sha256=trace.prompt_sha256,
        parameters=trace.parameters, error_code=trace.error_code,
    )

assessor = LocalR3Assessor(JudgeConfig.from_env(), on_trace=record_assessor_usage)
```

`tracker` 由 R5 创建。默认不猜测价格；明确核实免费本地推理成本口径后才记录 0。
runner 的 agent/reviewer usage 回调不会自动记录 R4，用独立 on_trace 接线并避免重复统计。
模型 check 的 reason 仍会进入 R3 audit，可能包含敏感内容；如需外发审计日志应另行脱敏。

## 合并文件与边界

本地集成目录中的 R3 已有文件保持逐字节一致，新增：

- `6101-Agent-Harness/src/judge_types.py`：旧 Judge 类型；from_gate 显式投影字段，兼容 R3 新增 ID。
- `6101-Agent-Harness/src/llm_judge.py`：旧独立 Judge，共享配置/client/Prompt 加载，允许子类选 Schema。
- `6101-Agent-Harness/src/prompts/risk_judge.txt`：原整体风险 Prompt。
- `6101-Agent-Harness/src/r4_assessor.py`：当前 R3 的正式注入接口。
- `6101-Agent-Harness/src/prompts/r3_assessor.txt`：专用逐项评估 Prompt。
- `6101-Agent-Harness/tests/test_llm_judge.py`：保留旧 Judge 的离线回归测试。
- `6101-Agent-Harness/tests/test_r4_assessor.py`：契约、防护、真实 R3 Policy 接入和可选真实模型测试。
- `R3/R4_LOCAL_ASSESSOR.md`：本交接说明。

不要直接把旧 Judge 分支整支 merge 到当前 R3：目录已迁移，旧 gate/types 不应覆盖新实现，
旧 README/环境/缓存清理的历史也无须带入。本次增量只新增上述文件，不修改 R3 的
r3_contracts.py、scope_policy.py、gate.py、types.py、Policy 工厂或默认实验配置。

原独立评分评估脚本仍保留在旧工作目录；它评估整体授权标签，不适用于 R3 的 per-check
advisory 输出，因而未机械搬入本次集成增量。后续 per-check 质量评估须另定标注标准。

## 验证

```bash
cd 6101-Agent-Harness
python -B -m pytest tests/test_r4_assessor.py tests/test_llm_judge.py tests/test_scope_policy.py -q -p no:cacheprovider
```

实际推理测试默认跳过；部署服务并设置 `RUN_JUDGE_INTEGRATION=1` 后可运行
`tests/test_r4_assessor.py::test_live_r3_contract`。它只验证一次真实响应能通过契约，
不证明语义准确性或注入防御效果。此轮未部署模型、未产生真实模型实验结果。

R3 的 `test_agentdojo_pipeline_constructs` 仍断言返回 AgentPipeline，但实际工厂已返回
GatedAgentPipeline。该已有测试失败与本次新增模块无关，未改动其预期；由 R1/R3处理。

## 与架构 PDF 的核对（2026-10-21）

参考 [SCOPE_AWARE_POLICY_ARCHITECTURE.pdf](SCOPE_AWARE_POLICY_ARCHITECTURE.pdf)，
文档日期 2026-10-20，共 9 页；并对照当前 `r3_contracts.py` 和 `R4_INTEGRATION.md`。
PDF 第 1 页明确它是完整设计提案，semantic scope extraction 尚未完成。

| PDF 要求 | 当前实现与验证 | 状态/边界 |
| --- | --- | --- |
| 第 1 页：四个 suite、suite-specific semantics | 原样传入 suite/tool/有效参数/工具语义；成本记录含 suite；四域传递测试 | 接口已支持；未验证四域真实模型语义质量 |
| 第 2–3 页：事实不增加授权，文件委托必须有边界 | 独立 Prompt 标注 task 与 evidence，允许任务授权的查账/文件事实；不创建 grants | 与 advisory 契约一致；不是通用 ledger 提取器 |
| 第 4 页：确定性违规优先，只评估 unresolved | 检查输出 ID 必须属于未解决集合；真实 R3 违规测试验证不调用模型 | 已实现 |
| 第 5 页：固定结构、不输出隐藏推理或概率 | 使用 R3 权威 response Schema；不返回整体风险分数或概率 | 已实现；旧独立 Judge 不注入 R3 |
| 第 5 页：模型评估后重算 checks、据此批准/拒绝 | R3 v0.1 明确只审计，模型结果不改变 checks/grants | **尚未实现完整架构目标**；不能仅靠本适配器开启 |
| 第 5–6 页：支持/冲突证据、未解决问题、后果、reviewability | 当前 Check 只有 status/reason/evidence_ids；request.question 是整次请求的问题 | 缺少结构化 per-check 问题/后果/reviewability；须 R3/R4 协商新契约，不能添加会被 strict Schema 拒绝的字段 |
| 第 6–7 页：n/v/c、阈值与唯一预算 | 本适配器不计算优先级、不读写 k；真实 Policy 测试检查预算不变 | 属 R3/Gate；PDF 中数字是示例，不据此改 R3 当前参数 |
| 第 7–8 页：调用身份与 oracle 隔离 | episode/call/hash 精确绑定，不读取隐藏任务对象、evaluator 或环境 | 已实现接口隔离；上游仍须保证 evidence 来源 |
| 第 8–9 页：独立错误评估与受控实验 | 离线协议/失败/策略边界测试，可选真实模型冒烟 | 未部署模型；不能宣称语义准确率、校准质量或 TCR 提升 |

这次复查修复：模型报告 error/unavailable 时，日志回调 ValueError 以前可能被误分类为
invalid_model_output 并再次调用日志回调。现在所有外部回调位于模型解析捕获范围之外，
对 ok/unavailable/error 三种状态均验证只调用一次、异常原样传播。

## Git 上传范围

只暂存前述 8 个新增文件；源仓库 README、依赖、环境、.gitignore 和原有测试均不修改。
本地补充忽略规则放入 `.git/info/exclude`，覆盖环境配置、编辑器文件、模型权重、打包文件、
实验输出和本地报告。该文件位于 Git 元数据内，不会被提交。

`.gitignore` 已在源分支被跟踪：即使加进 ignore，也不能让它停止跟踪。本次保持它完全
不变，因此没有该文件的待上传修改。源仓库以前跟踪的缓存/runs 同理，不在本次清理。
不要使用 `git add -f` 绕过规则；提交前检查 staged diff，而非上传整个本地目录。

## 上传前验证记录（2026-10-21）

- 基线仍为 R3 `0257352`，已重新 fetch 确认。
- 专项：106 passed, 1 skipped, 8 subtests passed。
- 完整 tests/：187 passed, 1 skipped, 1 failed, 30 subtests passed。
- 唯一失败是原有工厂返回类型断言，未修改该测试；真实模型测试跳过。
- pip check：No broken requirements found。
- Git 暂存范围仅上述 8 个新增文件；无源代码覆盖、环境文件或 .gitignore 变更。
- `.env`/`.env.local`、environment.yml、虚拟环境、缓存、results、权重和 ZIP 的
  check-ignore 验证通过；`.env.example` 继续作为团队模板保留。
- 本地准备分支为 `r4-r3-integration`，尚未提交或推送。
