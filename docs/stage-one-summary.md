# L5 第一阶段成果总结

整理日期：2026-10-26（Asia/Shanghai）。依据合并后的代码、PR #13–#23 实际变更、保存的研究结果与对应验收记录。第一阶段基线为 main `495799f87dea5e4217473793c1a92c52b462d009`，包含 PR #23 最终 head `0eb7a099eedfff69e9d7cfb30b4dba5548e8153b`。

## 产品定位

L5 是本地运行的工业过程分析与调查工作区。一个项目连接原始数据、信号语义、处理步骤、检测结果、研究记录和事件证据，使同一次调查可以在多次会话和服务重启后继续。

核心数据工作流是：**工业数据 → 数据处理 → 异常检测 → 实验比较 → 事件调查 → 研究报告**。支持用户自己的数值 CSV、保存的模拟输出和经校验的官方 Tennessee Eastman 独立运行。

模型工作流是：**过程模型 → 故障场景 → 模拟观测 → 诊断与干预 → Dataset → 实验分析**。TripLens 和 Coupled-Tank 通过显式模型目录和能力分发进入同一项目；原有 TripLens examples 保留教学与调查入口。

## 已完成的用户能力

| 模块 | 实际能力与界面 | 主要代码入口 |
|---|---|---|
| **Data Workspace** | Workspace 创建、管理与多 Dataset 持久化；CSV 预览、时间解释、原始数值和分析历史。 | `l5/workspace.py`、`l5/datasets.py`、`l5/api.py`；`src/workspace/WorkspaceApp.tsx` |
| **Signal & Time-Series Explorer** | 稳定信号 ID 与元数据；真实质量检查；UTC／显式相对参考；多源窗口、原始样本游标及保存视图。 | `l5/signals.py`、`l5/data_quality.py`；`SignalWorkspace.tsx`、`Charts.tsx`、`seriesCache.ts` |
| **Transformation Pipeline** | 工程单位换算、重采样、重复时间与缺失处理、表达式／差分／变化率；实际预览、逐点来源和版本化输出。 | `l5/transformations.py`、`units.py`、`resampling.py`、`expressions.py`；`TransformationWorkspace.tsx` |
| **Anomaly Detection** | Robust Max-Z、PCA-Q、PCA-T²、EWMA、Page CUSUM、有限窗口 CUSUM、DPCA-Q、DPCA-T²、Adaptive Max-Z（Experimental）；固定阈值、覆盖门控、区间、延迟与贡献。 | `l5/analysis.py`、`monitoring.py`、`independent.py`；`AlgorithmControls.tsx`、`Results.tsx` |
| **Experiment & Benchmark** | 九算法批量运行、有限参数研究、独立拟合／校准／测试；不可变快照、逐任务状态、重试、标签、比较和研究结论；TEP 故障矩阵与背景对照。 | `l5/experiments.py`、`experiment_evaluation.py`、`tep_study.py`、`tep_study_views.py`、`tep_fault3.py`；`ExperimentWorkspace.tsx`、`TEPBenchmark.tsx`、`TEPStudyDashboard.tsx` |
| **Incident Investigation** | 多来源事件、笔记、假设、支持／反对证据、结论、状态历史；时钟感知时间线和共同／独有报警比较；返回具体分析、实验、模拟运行。 | `l5/incidents.py`、`incident_timeline.py`；`Incidents.tsx`、`IncidentTimeline.tsx`、`IncidentComparison.tsx` |
| **Models & Scenarios** | 显式 Model Registry；版本化场景、独立运行、模型适用的工具和干预、历史参数恢复；模拟 Dataset 真值与来源。 | `l5/models/`、`l5/scenarios.py`、`l5/runtime.py`、`l5/model_research.py`；`ModelWorkspace.tsx`、`ScenarioEditor.tsx`、`ModelSimulation.tsx`、`RuntimeWorkbench.tsx` |
| **Reporting & Export** | 保存结果驱动的事件／实验／TEP HTML，内嵌原始测量、分数、阈值、来源与结论；浏览器 A4 PDF、分析／事件 JSON 和模拟 CSV。 | `l5/reports.py`、`experiment_reports.py`、`tep_study_reports.py`；`IncidentReport.tsx`、`ExperimentReport.tsx`、`src/lib/download.ts` |
| **Persistent Project Management** | SQLite 增量表、级联项目归属和 WAL；CSV／NPZ／JSON 文件；配置修订、独立执行记录、重启恢复和旧记录兼容。 | `l5/workspace.py`、`experiments.py`、`scenarios.py`、`runtime.py`；`server.py` 的 `--data-dir`／`L5_DATA_DIR` |

前端表格中省略目录前缀的文件均位于 `src/workspace/`；后端同理位于 `l5/`。[操作指南](user-guide.md)按用户工作流说明入口，[架构](architecture.md)记录 API、数据契约和存储。

### 模型能力

| 模型 | 已有范围 | 调查与干预 |
|---|---|---|
| TripLens `triplens-synthetic-18-v2` v2.0.0 | 18 通道、12 故障、两个控制回路；可配工况、故障起点／强度、噪声、响应、延迟、种子、时长和积分步长。 | 前缀诊断、报警与传播、11 种工具、7 种动作；观测拟合或已知模型预测及恢复窗口搜索。 |
| Coupled-Tank `coupled-tanks` v1.0.0 | 7 个液位／流量／控制信号，泵退化、连接阀受限、泄漏和传感器偏置；质量守恒、压差流量和保持非负的 SSPRK2。 | 液位、流量平衡和传感器一致性工具；调泵、调阀、备用泵、受控停水的已知模型预测。 |

两个模型都可以保存 Dataset、执行九算法与真值评价、关联 Incident 并生成报告。双水箱不提供 TripLens 的观测拟合、分类诊断或恢复搜索；模型专用能力由实际描述明确提供。[方程与接口](model-workspace.md)。

## 已完成的研究

### 原有 TEP 算法研究

[研究索引](../benchmarks/README.md)保留十一套配置及其正负结果，包括经典 52 通道参考、冻结模型传感器扰动、覆盖率与 abstain、阈值／种子敏感性、时序与有限窗口检测、漂移自适应、动态 PCA、正常数据前向校准、独立种子正常运行及六工况迁移。`benchmarks/numeric_reference.json` 与对应回归检验软件数值变化。

[研究整合记录](integration-2026-10-23.md)保存 PR #1–#12 的来源、输入哈希、跨平台验证、正常报警负担与失效案例。经典 52 通道、原生 THUFDD 53 通道和 TripLens 18 通道保持各自契约，未按列位置混用物理含义。

### 官方独立运行案例：72 项

[原始案例报告](tep-case-study.md)与[固定协议](../examples/tep/protocol.json)使用官方正常 Training runs 1／2 分别拟合和校准；测试正常 Testing runs 1–2、faults 1／3／5 各 runs 1–2。九算法 × 八条测试轨迹，共 72 项；CLI 与真实浏览器均完成正式执行。

保留的实际发现包括：故障 1 样本 recall 0.960625–0.994375；故障 3 的 18 个方法／运行事件中 17 个漏检，DPCA-Q 唯一名义命中延迟 138,780 s；故障 5 的 recall 和长时延差异均记录。独立正常 1,920 样本中，DPCA-Q 有 2 个报警样本，其余方法为零。[逐运行原始结果](../examples/tep/results.json) · [结果表](../examples/tep/scoreboard.md)。

### 扩展覆盖：585 项；正常训练稳定性：1,755 项

[扩展报告](tep-benchmark-expanded.md)与[复现指南](../examples/tep/README.md)使用三份官方 RData、71 个不同 Dataset：六个正常训练、五个正常测试、60 个故障测试。每故障三个 Testing 运行，52 个输入、180 s 采样；首个故障观测为 28,800 s。

| 研究 | 正常 Fit／Calibration | 测试集合 | 成功执行 |
|---|---|---|---:|
| 扩展覆盖 | A：Training 1／2 | 正常 Testing 1–5；faults 1–20 × runs 1–3 | 585／585 |
| 正常训练稳定性 | A：1／2；B：3／4；C：5／6 | 三组使用同一 65 条测试轨迹和固定九算法参数 | 1,755／1,755 |

两项研究共 2,340 次成功执行，覆盖 1,755 个独特的配置／算法／测试组合。扩展 A 与稳定性 A 的 585 个组合重复用于校验；原始 72 项案例独立保留。实际拟合分别为 9 次和 27 次，观测覆盖 100%、abstain=0。重叠的原始 72 项在本机的样本／事件指标、分数 SHA-256 和阈值完全一致。

| 代表性发现 | 保存的证据 |
|---|---|
| PCA-Q 与 DPCA-Q | 配置 A 最终名义检出分别为 51／60、54／60；30 分钟内为 19／60、20／60；两者正常报警均为 2／4,800 样本。 |
| 正常训练来源影响报警预算 | Page CUSUM 在 A／B／C 的正常报警为 0、739、1,833／4,800。阈值、正常负担和算法排序一起变化。 |
| 延迟与持续报警分别统计 | 例如故障 5 的 Page CUSUM 样本 recall 为 0.83542，中位延迟 17,460 s；早报、晚报与长时间持续报警有独立指标。 |
| 弱故障 3／9／15 | 配置 A 下均只有 DPCA-Q 的一次晚期名义命中，延迟 138,780 s；三类故障在 30 分钟、1 小时和 4 小时均无命中。负结果保留在逐运行 CSV。 |
| 故障 3 正常背景对照 | A／run 1 的正常和故障 DPCA-Q 报警同为 167,580–167,760 s，局部 Q 相关系数 0.999893676，前三贡献变量相同；三运行 × 三配置的配对报警片段全部重合。名义命中保留，但未提供故障 3 特异性证据。 |

原始数据来自 [Rieth et al. 2017，Harvard Dataverse V1](https://doi.org/10.7910/DVN/6C3JR1)，[来源清单](../benchmarks/rieth_sources.json)固定大小、MD5、SHA-256 和文件 DOI。研究范围为 mode 1、每故障三个运行的描述性结果；训练与测试划分、漏检、未观测及背景配对解释完整保存在专题报告。

公开结果入口：[扩展协议](../examples/tep/expanded_protocol.json) · [稳定性协议](../examples/tep/robustness_protocol.json) · [扩展汇总](../examples/tep/expanded_summary.json) · [稳定性汇总](../examples/tep/robustness_summary.json) · [585 项逐运行 CSV](../examples/tep/expanded_per_run.csv) · [1,755 项逐运行 CSV](../examples/tep/robustness_per_run.csv) · [故障 3 摘要](../examples/tep/fault3_summary.json)。

## 已有验证与证据

以下是历史阶段实际完成的记录，具体测试数按各记录当时的提交计，不与本轮测试数相加。

| 验证范围 | 已完成内容 | 记录 |
|---|---|---|
| Python、React DOM、TypeScript、生产构建 | PR #23 最终本地通过 80 项 Workspace Python、40 项模拟 Python、44 项 DOM、115 项研究回归及构建。 | [PR #23 回执](verification/tep-expanded-2026-10-25.json) |
| Windows／Linux CI | PR #23 最终 head 的 Check 双平台、官方扩展、原始案例、reference、独立正常、六工况共七个 job 成功。 | [最终 Check](https://github.com/dongxuelian2/L5/actions/runs/40197012539) · [官方扩展](https://github.com/dongxuelian2/L5/actions/runs/40197012552) |
| CSV → 事件 → 报告 | 真实浏览器导入、双算法、证据／结论、时间线、HTML／PDF 与重启恢复。 | [事件报告验收](incident-reporting-validation.md) |
| 多源数据与变换 | 三源导入、+25 s 参考、游标质量状态、496 行变换、单位／变化率、分析、事件与版本恢复。 | [信号验收](signal-workspace-validation.md) · [变换验收](transformation-validation.md) |
| Experiment 历史与重试 | 批量九算法、参数研究、标签、部分失败／重试、比较、结论和离线报告；历史结果文件保持。 | [实验验收](experiment-validation.md) |
| 双模型工作流 | 场景版本、曲线、调查／干预、2 Dataset、18 AnalysisResult、2 Experiment、2 Incident；两次真实重启，30 个文件哈希保持。 | [模型验收](model-workspace-validation.md) · [结构化回执](verification/model-workspace-2026-10-25.json) |
| 官方数据与大文件 | 校验三份官方 RData；正式 CLI／浏览器执行原始与扩展协议；提取保留 52 输入及独立轨迹。 | [原始案例验收](verification/tep-case-study-2026-10-25.json) · [扩展验收](verification/tep-expanded-2026-10-25.json) |
| 保存与真实服务重启 | PR #23 恢复 71 Dataset、2,340 结果、12 Experiment／Run、9 事件关联及结论，2,482 个文件哈希保持。 | [扩展验收的 actualServiceRestart](verification/tep-expanded-2026-10-25.json) |
| 本地／GitHub 数值对照 | 最终 head 的 585＋1,755 项检测指标全部一致；阈值最大绝对差 `1.2789769243681803e-13`。浮点末位字节差异独立记录。 | [最终官方产物](https://github.com/dongxuelian2/L5/actions/runs/40197012552/artifacts/12599833163) · [完整数值回执](verification/tep-expanded-2026-10-25.json) |

完整快照、逐点曲线、全部尝试及 HTML 继续由正式 Actions artifact 保存；固定协议、汇总、逐运行 CSV 和专题摘要保存在 Git。产物具有保留期限，可依同一指南重新生成。此次整理保留原始验收版本及复现条件，不搬移已有研究材料。

## 本轮产品整理

中英文 README 改为产品能力、真实界面、代表性研究发现和快速启动入口。详细操作迁入[操作指南](user-guide.md)，专题文档继续负责数值规则与研究条件。六张图片使用真实验收截图，[图片索引](images/README.md)记录来源。

工程修复集中于分析入口的 Dataset／信号／窗口恢复、分析异步响应与历史刷新、单信号实验默认算法、派生 Dataset 和 TripLens 保存数据直达 Experiment、TEP 研究上下文恢复，以及长结果页的导航。逐项原因、测试结果和本轮浏览器复验状态见[整合验证](stage-one-validation.md)。

## 后续发展空间

- **多正常运行校准与误报预算**：将训练来源敏感性、长轨迹累积报警和独立正常检验一起评价。
- **更多公开工业数据集**：保留来源、时间、单位和特征契约，在不同运行条件下复现。
- **弱故障与背景报警区分**：继续采用正常对照、早期检测窗口及独立开发／最终测试划分。
- **性能与使用体验**：优化大项目的数据浏览、长表格及跨工作站上下文，持续进行真实浏览器验收。
- **外部发布与复现**：以稳定协议、来源清单、精简结果和可重新生成的完整产物支持公开研究与演示。
