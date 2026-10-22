# 三策略正式实验结果

预算：{0,1,3,5,7,9}；策略：full_approve、full_escalate、hybrid_llm_fixed。
正式评估16个任务、clean+9种攻击目标、3次重复，共8640条；108条pilot单独保存。
完整性：True；比较就绪：True；审计问题：0。

## 正式结果（每个预算分别统计）

| 策略 | k | 条件 | 计划数 | 有效数 | 错误数 | 缺失数 | 完成率 / TCR_AD | 所有任务审核数 |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| full_approve | 0 | attacked | 432 | 432 | 0 | 0 | 29.861% | 0 |
| full_approve | 0 | clean | 48 | 48 | 0 | 0 | 45.833% | 0 |
| full_approve | 1 | attacked | 432 | 432 | 0 | 0 | 31.944% | 0 |
| full_approve | 1 | clean | 48 | 48 | 0 | 0 | 47.917% | 0 |
| full_approve | 3 | attacked | 432 | 432 | 0 | 0 | 29.861% | 0 |
| full_approve | 3 | clean | 48 | 48 | 0 | 0 | 45.833% | 0 |
| full_approve | 5 | attacked | 432 | 432 | 0 | 0 | 31.944% | 0 |
| full_approve | 5 | clean | 48 | 48 | 0 | 0 | 47.917% | 0 |
| full_approve | 7 | attacked | 432 | 432 | 0 | 0 | 29.861% | 0 |
| full_approve | 7 | clean | 48 | 48 | 0 | 0 | 45.833% | 0 |
| full_approve | 9 | attacked | 432 | 432 | 0 | 0 | 31.944% | 0 |
| full_approve | 9 | clean | 48 | 48 | 0 | 0 | 47.917% | 0 |
| full_escalate | 0 | attacked | 432 | 432 | 0 | 0 | 31.250% | 0 |
| full_escalate | 0 | clean | 48 | 48 | 0 | 0 | 31.250% | 0 |
| full_escalate | 1 | attacked | 432 | 432 | 0 | 0 | 31.250% | 333 |
| full_escalate | 1 | clean | 48 | 48 | 0 | 0 | 31.250% | 37 |
| full_escalate | 3 | attacked | 432 | 432 | 0 | 0 | 34.722% | 694 |
| full_escalate | 3 | clean | 48 | 48 | 0 | 0 | 39.583% | 67 |
| full_escalate | 5 | attacked | 432 | 432 | 0 | 0 | 37.500% | 703 |
| full_escalate | 5 | clean | 48 | 48 | 0 | 0 | 41.667% | 68 |
| full_escalate | 7 | attacked | 432 | 432 | 0 | 0 | 35.417% | 728 |
| full_escalate | 7 | clean | 48 | 48 | 0 | 0 | 39.583% | 70 |
| full_escalate | 9 | attacked | 432 | 432 | 0 | 0 | 37.500% | 710 |
| full_escalate | 9 | clean | 48 | 48 | 0 | 0 | 41.667% | 68 |
| hybrid_llm_fixed | 0 | attacked | 432 | 432 | 0 | 0 | 34.722% | 0 |
| hybrid_llm_fixed | 0 | clean | 48 | 48 | 0 | 0 | 37.500% | 0 |
| hybrid_llm_fixed | 1 | attacked | 432 | 432 | 0 | 0 | 34.954% | 147 |
| hybrid_llm_fixed | 1 | clean | 48 | 48 | 0 | 0 | 43.750% | 19 |
| hybrid_llm_fixed | 3 | attacked | 432 | 432 | 0 | 0 | 37.269% | 223 |
| hybrid_llm_fixed | 3 | clean | 48 | 48 | 0 | 0 | 45.833% | 28 |
| hybrid_llm_fixed | 5 | attacked | 432 | 432 | 0 | 0 | 38.194% | 197 |
| hybrid_llm_fixed | 5 | clean | 48 | 48 | 0 | 0 | 47.917% | 32 |
| hybrid_llm_fixed | 7 | attacked | 432 | 432 | 0 | 0 | 36.806% | 208 |
| hybrid_llm_fixed | 7 | clean | 48 | 48 | 0 | 0 | 45.833% | 26 |
| hybrid_llm_fixed | 9 | attacked | 432 | 432 | 0 | 0 | 38.657% | 233 |
| hybrid_llm_fixed | 9 | clean | 48 | 48 | 0 | 0 | 43.750% | 32 |

## 上传内容与实验版本

- analysis/full：8,640 条正式实验的汇总指标、成本与图表。
- analysis/full-heldout：排除开发任务 0–2 后的 7,020 条留出分析，复用正式运行数据。
- analysis/pilot：108 条试跑，单独统计，不并入正式结果。
- experiment.json：模型、参数、预算与实际代码来源；汇总 JSON 的路径已改为相对路径。

本次运行基于 main `a4a8439` 加本地 judge-guard/2、防护日志和 Windows 路径修复。核心防护代码随后提交为 `f3aea12`；实验冻结副本还包含未上传的评估工具，不能声称运行的是该提交的完全相同副本，也未评估后来更新的 main。

原始轨迹、逐调用判断、失败案例明细、预测文件、标注模板、运行日志、测试代码与本机环境路径均不包含在本报告包中，已在本地保留。图表与 CSV 数值保留原始汇总结果。

## 解读限制

Clean 指标为任务完成率；attacked 的 TCR_AD 是任务完成且指定攻击未成功的代理指标，不代表逐调用授权准确率。无独立逐调用真值，因此不发布授权或注入检测混淆矩阵。

本次运行错误、缺失和审计问题均为 0，但任务失败和攻击成功仍可能发生。表中审核数为所有任务审核总量；成功队列 HITL 口径见 metrics.csv 的 hitl_* 字段。

未运行动态 hybrid_llm，不能据此比较动态与固定调度，也不能将策略间差异归因于单独的注入防护改动。结果不包含统计显著性结论。

本地 Ollama API 费用记为 0，不包含电费和硬件成本；Token 和耗时见 component_costs.csv。全部运行结束后已确认 qwen3:14b 卸载。
