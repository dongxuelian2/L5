# L5 操作指南

[中文首页](../README.md) · [English overview](../README.en.md) · [架构](architecture.md)

## 数据与信号

### 创建项目与导入

1. 启动服务，在 Workspaces 输入项目名称并选择 **Create workspace**。
2. 在 **Datasets** 选择 CSV，检查预览、时间解释、数值列和缺失值，再 **Import and save dataset**。支持逗号、分号、Tab、竖线及 UTF-8／常见中文编码。
3. 为数值时间选择秒、毫秒、分钟或小时；Unix epoch 必须显式选择。日期时间保留 UTC 原点，无时区日期使用填写的解释时区。没有时间列时可按采样间隔生成时间轴。
4. 在 **Signal catalog** 编辑显示名称、单位、类别、设备、说明、标签与逻辑测点。原始列名和稳定信号 ID 保留。
5. 在 **Data quality** 检查原始行数、缺测、无效或重复时间、不规则间隔、长空档和采样覆盖。选择问题可定位对应曲线。

可复制导入 [Motor A 三源示例](../examples/data-foundation/README.md)。温度使用日期时间；流量明确选择 Unix 毫秒；压力以 `seconds` 为相对时间，并显式参考温度源、增加 **+25 秒**偏移。

### 多源浏览与变换

在 Catalog 勾选信号，或从 Dataset 进入 **Signal Explorer**。绝对时间源共享 UTC；相对来源先保存参考关系。不同物理量分图，同单位／类别可叠加。设置共同观察窗口，用游标读取完整分辨率的原始值、实际采样时刻和缺测状态，再命名并 **Save browsing view**。

选择 **Transform selected signals**，所选稳定 ID 会传入 Transformation：

1. 为各来源设置工程单位、重采样方法、最大间隔、重复时间及缺失值策略。
2. 选择共同、全部或自定义输出网格，设置采样间隔。来源覆盖外保留缺失，长空档受最大间隔约束。
3. 添加派生表达式，支持四则运算、数值函数、`diff` 和按实际秒数的 `rate`。兼容单位的加减自动换算；复杂乘积填写输出单位。
4. 查看实际计算预览、质量变化、原始观测掩码及逐点来源，保存配置并生成 Dataset。
5. 通过 **Analyze generated dataset** 或 **Create experiment from generated dataset** 继续工作；来源附录可返回原 Dataset、配置和模型会话。

单位转换区分绝对温度和温差；rpm／Hz 转换需要转速语义声明。统计填充使用所选输出窗口内的有效值。每次执行生成独立 Dataset，已有分析和事件继续引用原版本。[数值与来源规则](architecture.md#transformation-pipeline)。

## 分析与实验

### 单次分析

在 Dataset 选择信号后 **Configure analysis**，或从 Explorer 选择来源并 **Configure analysis for this window**。入口 URL 保存 Dataset、信号及传入的观察窗口，刷新或返回时可恢复。

填写假定正常的 baseline 与其后的 analysis window。输入单位为 Dataset 秒；日期数据同时显示 UTC 原点。正常基线按比例拆分为拟合与校准，默认 70%／30%，两段各至少 30 条观测。分析窗口独立于训练与阈值选择。

选择九种已有算法之一，配置适用参数、alpha、报警持续样本数、最低覆盖率与必需信号。Max-Z 支持单信号；PCA 使用至少两个信号。缺失值填补参数来自拟合段；原始覆盖不足时输出 abstain，并重置时序与持续报警状态。派生 Dataset 可明确选择 measured 或 processed 观测策略。

**Run analysis and save** 自动保存结果。查看主要异常、完整区间、固定阈值、原始测量和相关变量贡献；在 History 重开、调整参数再运行或导出 JSON。传感器缺失、噪声和偏置试验只作用于分析输入，保存的原数据保留。

### 多算法与独立来源实验

1. 在 Dataset 选择信号并 **Create a multi-algorithm experiment from this dataset**，或打开 **Experiments** 新建。单信号默认选择兼容的 Robust Max-Z。
2. 设置名称、研究问题、信号、正常 baseline、分析窗口及观测策略。勾选算法并编辑各自参数。
3. **Parameter study** 接受有限候选值，每参数最多 8 个，普通批次最多 64 个任务；先预览实际任务。
4. 需要独立评价时，分别配置正常 Fit Dataset、正常 Calibration Dataset、各 Test Dataset 的范围、映射和标签。普通独立实验最多 256 项；已声明的 TEP 研究每批至多 252 项。
5. **Save & run all tasks**。各任务分别保存状态、耗时、错误和 AnalysisResult；部分失败时仍可查看成功结果。重试在新运行中保留原快照和明确的历史关系。
6. 按算法、参数、批次或状态筛选，选择最多 12 个成功结果比较时间线、共同／独有报警、各自尺度的分数、贡献及原始测量。
7. 保存笔记、结论及其运行引用。选择具体任务或区间创建／关联 Incident；分析和事件保留返回来源 Experiment 的入口。
8. 在 **Report** 生成独立 HTML，或用浏览器 A4 打印保存 PDF。报告读取保存的配置、来源、结果、标签和结论。

### 标签与评价

手工创建或导入独立标签版本。JSON 包含 `timeBasis: "dataset-seconds"`、`timeSource` 和 `intervals`；区间包含 `kind: "normal" | "anomaly"`、`start`、`end`。闭区间不能重叠或共享端点。模型 Dataset 可从保存的模拟真值建立标签；有限故障结束后的恢复阶段保留未知。

无标签时描述报警行为。有标签时只评价明确标注且未 abstain 的样本；未标注时间保持未知，零分母指标保持未定义。样本评价与事件检出／漏检、无观测事件、正常报警片段、检测延迟分别计算。持续时间为连续片段首末样本的时间差，单点为 0 秒，采样长空档不计入。完整定义见[实验契约](architecture.md#analysis-experiments)与 [TEP 扩展协议](tep-benchmark-expanded.md)。

## 模型与场景

进入 **Models**，选择实际注册的模型，创建并保存场景。修改配置保存为新版本；每次运行固定当时的参数、种子、模型描述、测量和真值。可以复制场景、重开历史版本，并叠加同模型／版本的其他运行。

| 模型 | 调查与干预 |
|---|---|
| TripLens，18 信号、12 故障 | 在任意支持的观察时刻查看候选解释、报警与传播；主动调用 11 种工具；比较 7 种动作，选择观测拟合或已知模型模式，按需搜索恢复窗口。 |
| Coupled-Tank，7 信号、4 故障 | 查看液位、测量流量平衡和传感器一致性；比较调泵、调阀、备用泵和受控停水的已知模型预测。 |

TripLens 诊断使用所选观察窗口内的前缀数据；过程诊断需要稳定的初始基线。干预输入包含动作时间、预测终点及模型适用的强度。双水箱表单与工具按其真实能力提供；方程、守恒数值积分及示例参数见[模型文档](model-workspace.md)。

保存模拟为 **Dataset** 后，共用 Signal Catalog、Transformation、九算法、Experiment 与 Incident。工具、干预输入和结果自动保存在模拟库；从事件中的实验引用重开时恢复原观察范围与参数。**Research across models** 汇总任务及其各自模型、标签、来源和分母。

普通 CSV 使用统计分析和调查；物理诊断与预测由已关联模型提供。TripLens examples 保留原有调查、回放与教学入口。[模型方程、数值例子与限制](model-workspace.md)。

## 事件与报告

从分析的实际异常区间点击 **创建事件**，编辑标题、范围和说明，再 **创建并打开事件**。其他分析、Dataset、模拟工具及干预结果可以加入同一事件。

事件工作站可维护状态、观察笔记、候选解释、支持／反对证据和结论。时间线按来源时钟组织记录；选择条目同步窗口、比较图和原始测量，并可返回原分析、实验或模型会话。绝对来源按 UTC 对齐；相对来源只按已明确建立的关系比较。

在 **专业报告** 生成预览，导出独立 HTML 或使用浏览器打印保存 A4 PDF，也可导出事件 JSON。HTML 内嵌图表和样式，附上来源、参数、证据、结论及模型／变换记录。修改并保存事件后重新生成报告即可反映最新内容。[报告与持久化契约](architecture.md#事件时间线共享窗口与报告)。

## TEP 研究

按 [TEP 复现指南](../examples/tep/README.md) 准备官方缓存，以同一 `L5_TEP_CACHE` 启动服务。进入 **TEP case study** 预检并导入独立运行；原始案例、20 故障扩展和 A／B／C 稳定性研究分别选择。

研究仪表板在 URL 保留协议、保存的 study、正常训练配置、指标和选中单元格。打开对应 Dataset／Experiment 后，返回可恢复研究上下文。每个单元格继续进入逐运行证据、原始曲线、算法比较、Incident 与离线报告。研究方法、真实结果和复现条件分别见[原始案例](tep-case-study.md)与[扩展研究](tep-benchmark-expanded.md)。

## 保存、恢复与备份

默认 `data/` 保存 Workspace SQLite、原始 CSV、NPZ、结果及模拟会话。使用 `--data-dir` 或 `L5_DATA_DIR` 指定位置，并在重启时继续使用相同目录。

停止服务后复制整个数据目录，或使用 SQLite backup 并连同数值文件一起备份。只复制数据库不包含全部曲线证据。删除 Workspace 会同时删除所属 Dataset、分析、实验和事件；模拟会话仍保留在本机模拟库并解除项目关联。

默认助手执行所选确定性工具。可选外部摘要模型通过 `.env.example` 中的 `TRIPLENS_MODEL_ENDPOINT`、`TRIPLENS_MODEL`、`TRIPLENS_MODEL_API_KEY` 配置；数值计算继续在 Python 执行。
