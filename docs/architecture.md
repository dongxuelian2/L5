# L5 / TripLens architecture and contracts

## Workspace first

The default React route is a persistent, dataset-neutral workspace. `#/examples` lazy-loads the original TripLens workstation and teaching examples.

| Module | Implementation | Responsibility |
|---|---|---|
| Workspace repository | `l5/workspace.py` | Workspace CRUD, dataset metadata, completed analysis jobs; SQLite with cascading ownership |
| Persistent incident investigation | `l5/incidents.py`, `src/workspace/Incidents.tsx` | User-maintained incidents, source links, editable notes/evidence/hypotheses/conclusions, source-window plots and experiment reopening |
| Incident timeline and comparison | `l5/incident_timeline.py`, `src/workspace/IncidentTimeline.tsx`, `IncidentComparison.tsx` | Clock-aware event aggregation, linked interval comparison, shared source navigation and observation cursor |
| Professional incident reports | `l5/reports.py`, `src/workspace/IncidentReport.tsx` | Saved-data Chinese reports, inline SVG figures, offline HTML, preview and A4 browser PDF printing |
| CSV ingestion | `l5/datasets.py` | Named numeric columns, timestamp/numeric/generated time, missing measurements, display previews |
| Generic analysis | `l5/analysis.py`, `l5/monitoring.py` | Max-Z, PCA, EWMA, CUSUM, window CUSUM, DPCA, Adaptive Max-Z; chronological normal fit/calibration; full-resolution scoring |
| Runtime model sessions | `l5/runtime.py`, `simulation/platform.py` | Configurable simulation, cached prefix evidence, user tools, fitted/known-model forecasts and optional recovery grid search |
| Analysis assistant | `l5/assistant.py` | Selected deterministic tools, keyword routing and an optional evidence summarizer |
| Local API | `l5/api.py`, `server.py` | Synchronous JSON routes on the same local HTTP server as the built React application |
| Workspace workstation | `src/workspace/`, `src/App.tsx` | Projects, import, signal plots, analysis configuration, saved results and history |

`data/workspace.sqlite3` stores projects, dataset metadata and completed job summaries. Each project has `datasets/<id>/source.csv`, `datasets/<id>/series.npz` and `results/<id>.json`. Originals remain available locally; previews never replace stored measurements. A result file is written atomically before its job is committed. `--data-dir` or `L5_DATA_DIR` selects another persistent directory. Restarting the service uses the same directory; browser storage is not part of the workspace persistence path.

Baseline and target windows use seconds and must be disjoint in chronological order. Timestamp datasets retain their UTC origin. The first 70% of the assumed-normal baseline fits preprocessing and the model; its final 30% calibrates a fixed empirical threshold. Missing measurements use medians from the fit partition. Models, parameters, scores, intervals and timing are saved together. Related signals describe statistical contributions. Only datasets explicitly saved from a simulation carry a model association and its process capabilities. Ordinary CSV remains dataset-neutral. Original observation masks determine abstention and reset temporal history across unobservable rows.

Main endpoints: `GET/POST /api/workspaces`, `GET/PATCH/DELETE /api/workspaces/:id`, `GET/POST /api/workspaces/:id/datasets`, `POST /api/datasets/preview`, `GET /api/datasets/:id/series`, `GET/POST /api/workspaces/:id/analyses`, and `GET /api/analyses/:id`. Import and analysis accept JSON; the browser reads a chosen CSV and sends its text with the import options. Completed analyses save automatically; rerunning creates another history entry.

`npm run test:workspace` exercises storage, CSV import, known anomalies, threshold independence and the HTTP workflow across a service restart. `npm run check` includes product/example tests and the production build. Research tests and numerical regeneration remain separately available through `npm run test:research` and `npm run verify:artifacts`.

## 持久化事件调查

`WorkspaceStore.incidents` 使用同一个 SQLite 连接和事务机制。启动时以 `CREATE TABLE IF NOT EXISTS` 添加 `incidents`、`incident_links`、`incident_entries` 及索引，保留已有 Workspace、数据集、分析文件和模拟历史。

`incidents` 保存独立 UUID、所属 Workspace、标题、说明、起止秒数、可选时间轴起点、调查状态、结论及创建／修改时间。`incident_entries` 保存可编辑的笔记、证据和候选解释；证据通过 `hypothesis_id` 与 `stance` 表达支持、反对或待判断关系，通过 `source_link_id` 指向事件来源。移除假设后，已有证据保留为未分配观察；解除来源关联后，人工记录保留。

`incident_links` 只保存来源标识和选择器：数据集 ID、分析 ID、分析中的区间序号，或模拟会话 ID 与实验 ID。详情从已保存的分析和模拟实验读取峰值、变量、贡献度、工具输出及预测结果。相同来源重复添加会复用关联，多个区间可以同时引用一个分析。创建事件并关联初始来源在同一事务内完成。关联前检查实际存在性、数据集与分析的一致性，以及 Workspace 归属；证据关系只允许指向本事件中的假设和来源。

检测区间不自动成为事件，也不自动合并。事件时间范围由用户维护。时间戳 CSV 创建的事件携带数据的 UTC 起点；每个来源的曲线和关键时间点保留自己的时间轴，系统不按列名或时间数值自动对齐数据集。

| API | 用途 |
|---|---|
| `GET/POST /api/workspaces/:id/incidents` | 列表／创建；GET 支持 `status`、`q`、`start`、`end`，时间按相交区间筛选 |
| `GET/PATCH /api/incidents/:id` | 恢复详情／修改信息、状态和结论；`archived` 状态用于归档 |
| `GET/POST /api/incidents/:id/entries` | 查看／添加笔记、证据及候选解释 |
| `PATCH/DELETE /api/incidents/:id/entries/:entryId` | 编辑／移除调查记录 |
| `GET/POST /api/incidents/:id/links` | 查看／添加数据、分析、区间、模拟或实验关联 |
| `DELETE /api/incidents/:id/links/:linkId` | 解除来源关联 |
| `GET /api/simulations/:id/runs/:runId` | 读取已有实验的参数和计算结果 |

Workspace 侧边栏的「事件」进入列表和详情。`IncidentLinkDialog` 为异常结果和 RuntimeWorkbench 提供创建／加入事件的交互。`Results.tsx` 使用分析 ID 与真实区间序号携带来源，事件详情复用 `SignalPlots`、分数曲线和贡献度组件。`#/workspaces/:wid/analysis/:analysisId/:intervalIndex` 重开来源窗口。`RuntimeWorkbench` 复用已完成的工具与干预记录；事件通过实验 ID 恢复观察窗口、候选假设和干预参数，当前候选解释也可保留其观察上下文。通用 CSV 事件独立可用，过程计算继续由已有运行时引擎承担。

`tests/test_incidents.py` 实际导入普通 CSV、运行 Max-Z／PCA、把多个区间与第二份数据加入同一事件，编辑记录和结论，重启 HTTP 服务后恢复并继续修改；另一条流程生成 TripLens 会话、完成工具调用与干预实验，关联事件并在重启后继续调查。前端测试覆盖区间入口、事件编辑、证据关系、列表筛选和实验参数恢复。

## 事件时间线、共享窗口与报告

`incident_timeline.investigation` 从持久化的 Incident、关联分析文件、数据集元数据与模拟实验派生一个调查视图，不重新计算检测。`GET /api/incidents/:id/timeline` 返回时间轴、带真实来源定位器的事件、去重后的分析及区间比较。可重复传入 `analysis=<id>` 选择参与比较的本事件分析，`analysis=` 表示不选；时间线仍保留全部关联记录。只关联异常区间时使用实际保存的区间序号，关联完整分析时使用其全部区间，重复关联不会重复计数。

时间轴拥有明确的身份和秒数偏移。带日期时间起点的数据先加上该起点的 Unix 秒数，归入 UTC 绝对时间轴。数值／生成时间轴使用 `dataset:<id>`；同一过程模型的数据和实验使用 `simulation:<id>`。不同相对时间源不因数值相近而合并。事件新增可选 `time_axis_key`，从来源创建时自动写入；旧事件不推断原点，可由用户指定参考来源。显式 `time_origin` 优先。调查记录新增 `observed_axis_key`，解除来源关联后仍保留观察时刻所属的时钟。状态、结论和事件信息变更以同一事务写入 `incident_history`，保存前后值及记录时间，放在独立的调查操作序列，不冒充设备观察时间。迁移只添加表与可空列。

比较按已关联的闭区间边界分段，保留开始等于结束的单点报警。持续时间是首末样本时间差，不外推采样周期。全部共同检出、独有检出和部分共同检出仅在各所选分析同时有有效观测的时间内判断；abstain 间隙和未覆盖窗口标为「缺少共同观测，未比较」。分数、阈值、峰值与贡献度保留所属算法的原始含义，不做跨算法归一化或分数排名。

`IncidentDetail` 持有规范化的 `IncidentSelection`（时间轴、窗口、游标、来源、分析及真实区间序号），供时间线、比较与来源预览共享。选择报警定位原始曲线，选择调查记录打开现有编辑器，选择实验保留其不可变请求并沿已有模拟路由恢复窗口与控制参数。`Plot` / `SignalPlots` 增加可选游标与点击回调，原有调用保持原行为。`GET /api/datasets/:id/sample?at=<seconds>&signal=<name>` 从完整数组读取最近的原始样本、相邻时刻及前样本值，用于多变量同步查看；曲线显示仍复用保留极值的采样缓存。

`GET /api/incidents/:id/report.html` 直接从同一个调查视图和原始数组生成中文独立 HTML；`?download=1` 返回附件。报告无需前端截图，不依赖外部脚本、字体、图片、当前 React 状态或后续 API 请求。测量、分数与阈值、区间叠加及干预方案均以带标题和坐标说明的 SVG 嵌入。长曲线仅在显示阶段保留极值采样，缺测／abstain 保留断点，分析仍使用完整数据。普通事件不包含模拟章节；模拟报告从保存的工具输出和干预分支读取参数、物理压力及方案指标。所有用户文本经 HTML 转义，未填写内容保持未记录。

`IncidentReport` 提供预览、相同预览内容的 HTML 下载、浏览器打印／保存 PDF，以及事件 JSON 导出。保存事件后预览失效，重新生成读取最新记录；过期生成请求不能覆盖新状态。打印样式设置 A4、页边距、标题层级、可重复表头、可换行技术参数和尽量保持完整的图表。PDF 由本机浏览器打印引擎生成，不增加运行时报告依赖。关键原始变量按关联峰值贡献选取前三项，完整分析参数、数据集列名、来源和实验标识进入附录。

`tests/test_incident_reporting.py` 经真实 HTTP 验证 CSV 双算法时间线／报告、UTC 不同原点、相对时间隔离、解除来源后保留时钟、完整样本读取、HTML 离线依赖与文本转义、服务重启和结论历史，以及真实 TripLens 工具／干预曲线。前端交互测试补充时间线筛选与定位、共享窗口／游标、比较选择、报告预览失效与 HTML／打印入口、实验恢复链接。

## TripLens examples and research

The workstation and external monitoring studies share evidence contracts while retaining separate process spaces. No source is converted by column position or similar signal names.

| Logical module | Implementation | Boundary |
|---|---|---|
| Data & Process Adapters | `simulation/platform.py::parse_csv`, `benchmarks/tep.py`, `rieth_independent.py`, `multimode_normal.py` | Explicit source format, ordered schema, clock, provenance; labels outside feature matrices |
| Evidence & Data Model | `l5/contracts.py` | Immutable `SignalSchema` / `ObservationBatch`, units, missing mask, sequence, operating mode, partition |
| Monitoring Engine | `benchmarks/monitoring.py`, `session.py`, `coverage.py`, temporal/adaptive/DPCA modules | Research-only sessions enforce normal fit/calibration roles, chronological disjointness, schema compatibility and fresh sequence state |
| Diagnosis Engine | `simulation/platform.py::diagnose` | Observations only; no simulator Config/fault label argument; support, contradiction and unavailable evidence remain separate |
| Decision & Counterfactual Engine | `fit_hypothesis`, `simulate`, `interventions` | Configurable duration and stable 0.05–1s cadence, explicit observation window and selectable hypothesis; on-demand recovery grid; physical pressure determines trip status |
| Investigation Workstation | `src/components`, `src/lib/comparison.ts`, `src/lib/platform.ts`, `server.py` | Shared ProcessEvidence components and RuntimeWorkbench; arbitrary time-matched prefixes, user-selected tools and intervention parameters |
| Benchmark & Verification | `benchmarks/run_suite.py`, `verify_reports.py`, `simulation/verify_artifacts.py`, `tests/`, Actions | Pinned sources, frozen protocols, separate software/numerical regressions and external research reports |

## Signal spaces

| Schema | Width | Clock | Interpretation |
|---|---:|---|---|
| `triplens-synthetic-18-v2` | 18 | seconds, configured 0.05–1 s | Explicit synthetic engineering keys and units; accepted by current diagnosis/CSV API |
| `tep-classic-52-v1` | 52 | 180 s | Original XMEAS(1…41), XMV(1…11) order; Braatz/Rieth source provenance is retained in each report/run identity |
| `thufdd-tep-native-53-v1` | 53 | source sample index | Original columns 0…52; physical meanings/units and seconds remain unknown; last 28 raw disturbance columns excluded |

The legacy six-channel PROCESS 01 demo remains a separate reduced-order model. Its results do not validate PROCESS 02 or external TEP data.

`ObservationBatch` copies caller-owned lists into immutable tuples and preserves missing values. `ResearchSession.fit` accepts only explicit normal-fit and normal-calibration partitions. Overlapping/reversed partitions from the same sequence fail. Scoring rejects schema changes, missing observations and sequence gaps unless an explicit observation policy handles them. Coverage evaluation uses its original Boolean observation mask; imputation never overrides abstention, and a temporal monitor restarts after abstained intervals.

The TripLens example CSV/API contract uses documented synthetic keys and seconds. Duplicate headers, ragged records, malformed quoting, nonfinite values and unsorted timestamps fail with a client error. Existing requests remain valid. An explicit foreign `signalSchemaId` is rejected instead of mapped into synthetic channels.

## Causality and decision scope

Runtime analysis filters the selected observation window before diagnosis or tools. An LRU cache retains bounded prefix results; it does not define available cutoffs. Fitting rejects a diagnosis from another window and uses elapsed time with regular 0.05–1 second cadence. Hypothesis and horizon are explicit. Observation-mode fitting never reads saved simulator parameters or future measurements; known-model trials explicitly use configured parameters. Comparison waits for both current cutoffs.

`data/simulations/<id>/session.json` retains configuration and actual generated observations. Each `runs/<id>.json` stores an immutable user request and computed tool, assistant or intervention result. Saving a model dataset retains the simulation ID in server-authored dataset metadata. SQLite/NumPy generic monitoring uses the same dataset; reopening follows that association to the reusable process tools. `GET/POST /api/simulations`, `GET /api/simulations/catalog`, `GET /api/simulations/:id`, and POST `analysis`, `tools`, `interventions`, `save` subroutes expose this local runtime. GET `runs` reopens model experiments. Static example JSON is not used by runtime routes or Workspace investigation.

Simulation branches preserve their fitted baseline prefix before action. They do not assert a perfect observed prefix when the fitted model differs from the measurements. `physicalPeak` and the physical trip flag retain the safety calculation; rounded display peaks must not replace them. Missing observations break alarm continuity without generating a normal-return event. Durations use timestamp seconds and do not bridge unobserved gaps.

Pressure-intervention rankings are withheld when the fitted physical baseline remains below its pressure limit. Other reported rankings are conditional simulator comparisons, without predictive intervals or external intervention validation. Parameter/model uncertainty remains open research, not an operational guarantee.

## Verification and operation

`npm run check` runs workspace/example Python tests, frontend export tests and TypeScript/Vite. Complete numerical regeneration is available separately through `npm run verify:artifacts`. The Python runner chooses `.venv` when present and forces UTF-8 across platforms. CI checks Linux and Windows. The separate external-data workflows run on relevant source/protocol changes or manual dispatch, cache fixed inputs, revalidate hashes and cancel obsolete runs; ordinary UI/docs changes do not trigger all external downloads.

The reference suite preserves all eleven study configurations and their logs. Numerical snapshots capture audited thresholds, workload, coverage, fold/seed summaries and negative outcomes with float tolerance. They check software drift; repeatedly consulted simulator data provide no new independent evidence. Raw third-party datasets remain outside Git and report artifacts.
