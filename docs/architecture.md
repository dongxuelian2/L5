# L5 / TripLens architecture and contracts

## Workspace first

The default React route is a persistent, dataset-neutral workspace. `#/examples` lazy-loads the original TripLens workstation and teaching examples.

| Module | Implementation | Responsibility |
|---|---|---|
| Workspace repository | `l5/workspace.py` | Workspace CRUD, dataset metadata, completed analysis jobs; SQLite with cascading ownership |
| Signal and time-series workspace | `l5/signals.py`, `src/workspace/SignalWorkspace.tsx` | Stable signal semantics, explicit time references, source-aware exploration, raw cursor reads and saved browsing views |
| Transformation pipeline | `l5/transformations.py`, `units.py`, `resampling.py`, `expressions.py`, `src/workspace/TransformationWorkspace.tsx` | Saved definitions, engineering conversions, bounded resampling/fill, safe derived expressions and immutable ordinary Dataset executions |
| Measured data quality | `l5/data_quality.py`, `l5/datasets.py` | Source-row statistics, timestamp issues, cadence policy, measured sample spans and display segment identities |
| Persistent incident investigation | `l5/incidents.py`, `src/workspace/Incidents.tsx` | User-maintained incidents, source links, editable notes/evidence/hypotheses/conclusions, source-window plots and experiment reopening |
| Incident timeline and comparison | `l5/incident_timeline.py`, `src/workspace/IncidentTimeline.tsx`, `IncidentComparison.tsx` | Clock-aware event aggregation, linked interval comparison, shared source navigation and observation cursor |
| Professional incident reports | `l5/reports.py`, `src/workspace/IncidentReport.tsx` | Saved-data Chinese reports, inline SVG figures, offline HTML, preview and A4 browser PDF printing |
| CSV ingestion | `l5/datasets.py` | Named numeric columns, timestamp/numeric/generated time, missing measurements, display previews |
| Generic analysis | `l5/analysis.py`, `l5/monitoring.py` | Max-Z, PCA, EWMA, CUSUM, window CUSUM, DPCA, Adaptive Max-Z; chronological normal fit/calibration; full-resolution scoring |
| Analysis experiments | `l5/experiments.py`, `experiment_routes.py`, `src/workspace/ExperimentWorkspace.tsx` | Editable SQLite definitions, finite studies, bounded local batches, immutable input snapshots, per-task AnalysisResult references and research record revisions |
| Experiment evaluation and reports | `l5/experiment_evaluation.py`, `experiment_reports.py`, `src/workspace/ExperimentComparison.tsx`, `ExperimentLabels.tsx`, `ExperimentReport.tsx` | Explicit truth versions, separate sample/event evaluation, clock-aware comparisons, shared measurement cursor and offline research reports |
| Runtime model sessions | `l5/runtime.py`, `simulation/platform.py` | Configurable simulation, cached prefix evidence, user tools, fitted/known-model forecasts and optional recovery grid search |
| Analysis assistant | `l5/assistant.py` | Selected deterministic tools, keyword routing and an optional evidence summarizer |
| Local API | `l5/api.py`, `server.py` | JSON routes and experiment progress polling on the local HTTP server serving the built React application |
| Workspace workstation | `src/workspace/`, `src/App.tsx` | Projects, import, signal plots, analysis configuration, saved results and history |

`data/workspace.sqlite3` stores projects, dataset metadata and completed job summaries. Each project has `datasets/<id>/source.csv`, `datasets/<id>/series.npz` and `results/<id>.json`. Originals remain available locally; previews never replace stored measurements. A result file is written atomically before its job is committed. `--data-dir` or `L5_DATA_DIR` selects another persistent directory. Restarting the service uses the same directory; browser storage is not part of the workspace persistence path.

Baseline and target windows use seconds and must be disjoint in chronological order. Timestamp datasets retain their UTC origin. The first 70% of the assumed-normal baseline fits preprocessing and the model; its final 30% calibrates a fixed empirical threshold. Missing measurements use medians from the fit partition. Models, parameters, scores, intervals and timing are saved together. Related signals describe statistical contributions. Only datasets explicitly saved from a simulation carry a model association and its process capabilities. Ordinary CSV remains dataset-neutral. Original observation masks determine abstention and reset temporal history across unobservable rows.

Main endpoints: `GET/POST /api/workspaces`, `GET/PATCH/DELETE /api/workspaces/:id`, `GET/POST /api/workspaces/:id/datasets`, `POST /api/datasets/preview`, `GET /api/datasets/:id/series`, `GET/POST /api/workspaces/:id/analyses`, and `GET /api/analyses/:id`. Import and analysis accept JSON; the browser reads a chosen CSV and sends its text with the import options. Completed analyses save automatically; rerunning creates another history entry.

`npm run test:workspace` exercises storage, CSV import, known anomalies, threshold independence and the HTTP workflow across a service restart. `npm run check` includes product/example tests and the production build. Research tests and numerical regeneration remain separately available through `npm run test:research` and `npm run verify:artifacts`.

## Analysis experiments

`WorkspaceStore.experiments` adds `experiments`, `experiment_runs`, `experiment_tasks`, `experiment_labels` and `experiment_records` with cascading Workspace/Dataset ownership. These additive migrations leave previous datasets, analyses, incidents and simulation files in place. Definitions have stable IDs and optimistic revisions. Notes/conclusions and their run references receive independent immutable research records when changed; copies start without execution history or inherited conclusion references.

The definition contains one shared dataset, signal selection, chronological baseline/target windows, alpha, fit fraction, observation policy, minimum coverage, required signals and persistence. Each selected algorithm contains applicable scalar parameters and optional candidate lists. Expansion takes a Cartesian product within each method, caps candidates at eight per dimension and the whole batch at 64 tasks, and saves the concrete effective configuration for every task. Algorithms continue through `WorkspaceStore.analyze` → `run_analysis` → `build_monitor`; no detector is reimplemented.

An execution saves its definition revision, input dataset metadata/clock/lineage, NPZ and source CSV SHA-256, label version, engine source hashes and environment versions before it enters the queue. One daemon worker per store processes tasks sequentially; at most four runs may be queued/running across the local store. SQLite uses WAL so Workspace read snapshots and nested source/clock projections do not block batch commits. Each task has a stable ID, status, start/end, wall duration, error, metrics and ordinary AnalysisResult reference. A completed result carries server-authored `{experimentId, runId, taskId}`. Partial failures retain successful work. At startup, queued/running rows become interrupted; retry creates a different run using the original snapshot and only unfinished task configurations. This is a single-process local runner, not a durable distributed scheduler or an exact code/environment replay system.

Label versions are immutable and owned by one Dataset. They contain explicit `dataset-seconds`, a human-readable time source, a clock snapshot and nonoverlapping closed normal/anomaly intervals. TripLens labels read saved simulation fault/configuration and map onset through an explicitly compatible source clock; derived datasets can use a uniquely identified or explicitly selected simulation source. The original onset remains in provenance even when the dataset clips the event. Labels never enter detector fitting or calibration.

Evaluation stores behavior separately from truth-dependent results. Sample TP/FP/TN/FN require a labelled non-abstained row. Unknown time remains unknown; zero-denominator ratios are null. An eligible truth event needs at least one evaluated observation; a hit needs an alarm inside it, with delay from the original onset. Completely unobserved events are counted outside recall. False alarm events count contiguous alarms in explicit normal intervals and split at annotation boundaries, abstention and acquisition gaps. Alarm durations sum last minus first timestamps of contiguous spans, with zero duration for point alarms. Positive-only annotation cannot establish global precision or false alarm rates. `RULES` travels with snapshots and is shown in reports.

Detailed comparison loads only selected successful task results (up to 12) and uses the run’s frozen clock, not today’s editable dataset reference. It reuses `observed_spans`/`compare_intervals`, groups independent clocks separately, reports differing windows/coverage/inputs/baselines/label versions, and pairs exact shared timestamps for agreement without interpolating states. Duplicate timestamps make that pairing ambiguous and produce an explicit unavailable result. Plot ordinates and contribution units remain independent. React reuses `Plot`, `SignalPlots` and contribution views; obsolete experiment, comparison, label and cursor responses are discarded.

Incident association validates all selected task/result/interval identities before adding existing source-link types in a transaction. New interval-only incidents retain that scope; they do not silently add the whole analysis. Existing incident investigation and report logic is reused. Source details and report appendices include the experiment/run/task IDs; the browser links back to the experiment.

Experiment HTML reports read saved runs and records without rerunning detection. They reuse incident SVG/table/A4 facilities, embed method-specific curves, measured input curves, timeline comparisons, labelled evaluations, provenance and technical result IDs. Measurement figures are omitted if the input hash no longer matches; saved detection results remain available. Measurement figures show at most eight input signals, and detailed common/unique/agreeing-task figures use at most 12 successful tasks per run; full configurations, summaries and individual method curves remain in the report. HTML is offline and PDF uses browser printing.

| API | Purpose |
|---|---|
| `GET/POST /api/workspaces/:id/experiments` | List/create saved definitions |
| `POST /api/workspaces/:id/experiments/preview` | Validate and expand a concrete bounded plan |
| `GET/PATCH /api/experiments/:id` | Open/edit definition, run summaries and research record history |
| `POST /api/experiments/:id/copy` | Copy configuration into a new experiment |
| `GET/POST /api/experiments/:id/runs` | Inspect history or queue execution; optional `retryRunId` |
| `GET /api/experiment-runs/:id` | Immutable snapshot and live task progress/results |
| `POST /api/experiments/:id/comparison` | Summary plus selected `taskIds` and clock-aware comparisons |
| `GET/POST /api/datasets/:id/labels` | List/create independent label versions |
| `POST /api/datasets/:id/labels/triplens` | Import known simulator truth, with optional explicit `simulationId` |
| `POST /api/experiment-runs/:id/incidents` | Associate selected tasks/scoped intervals with a new/existing incident |
| `GET /api/experiments/:id/report.html` | Offline report; optional `run` and `download=1` |

Verification covers nine-method execution, studies and bounds, partial failures/retries, immutable history, restart recovery, labels/unknown/abstain/gaps, source clocks, derived observation policies, simulator truth, scoped incident lineage and HTML evidence. DOM tests cover the actual editor, filters/notes/references, stale loads, label import, synchronous cursors and report generations. [Browser validation](experiment-validation.md) records the actual exercised workflows and remaining limits.

## Signal & Time-Series Workspace

`WorkspaceStore.signals` 管理数据语义和跨源浏览。`signals` 按 `(dataset_id, column_name)` 唯一，使用数据集 ID 和原始列名生成稳定 UUID；用户元数据单独存放，包含显示名称、单位、说明、类别、设备、标签和显式逻辑测点键。读取数据集时将它们投影到 `metadata.columns`，原始 `name` 和分析配置键不改变。TripLens 保存输出经同一个 CSV 导入入口注册信号，从明确的模拟模型元数据取得单位和来源；普通 CSV 不通过列名推断物理含义。

CSV 导入显式区分相对数值时间、生成时间、ISO 日期时间及 Unix 时间。数值单位在转换成秒后保存；Unix 解释由用户选择，不能由数值大小自动推断。日期按时区转换为 UTC，无时区日期采用用户配置的时区（默认 UTC）。绝对数据以首个有效时刻为 UTC 起点，数组中的秒数继续使用原有相对表示。无效时间行的行号、原值和附近有效时刻进入质量记录，原始 CSV 保留这些行；定时数组只保存有效时间行并稳定排序，重复时刻保留全部测量。

`dataset_time_references` 保存相对来源的独立时钟、参考数据集／秒数偏移，或者带时区的源零点。`SignalWorkspace.clock` 递归求出 `{key, axisId, offset, reference}`：原始来源秒数加 `offset` 得到浏览秒数。绝对来源归入 `utc`；没有关联的相对来源保留 `dataset:<id>` 或 `simulation:<id>`。关系必须位于同一 Workspace，写入前检查循环。原始数组与 `metadata.time` 不随参考配置重写。Incident 的 `clock_for_key` 和前端 `datasetClock` 复用该结果；已有显式事件 `time_origin` 仍优先，旧分析和观察记录继续使用原始秒数及原有来源身份。

`data_quality.summarize` 从实际数值生成质量快照，保存在数据集元数据内。它分别记录来源总行数、有效时间行数、有限数值数量、同时具有有效时间及数值的可用数量、缺失比例、无效／重复时间、最小／最大／均值／总体标准差，以及缺测与可用样本分组。有限数值统计包含无效时间行，而可用数量不包含它们。正时间差中位数定义典型间隔；超过 5 倍中位数为采样空档，其余偏离超过 5% 为不规则。样本分组不表示任意两个观测之间持续可观测。Incident 比较的有效观测范围也在长空档处拆分。

`series_preview` 在完整数组上生成每信号的片段 ID，再保留极值及缺测边界采样。`Plot` / 报告 SVG 使用这些 ID 断开隐藏缺测和长空档；显示采样不改变原始文件或分析输入。跨源浏览不生成公共采样网格：每条曲线仍有独立采样时刻。UTC 来源共享横轴，不同单位／类别默认分图，叠加模式只组合非空且完全相同的单位和类别。窗口以相应时钟的秒数保存，UTC 输入框显示相对来源覆盖起点的秒数；游标滑块使用窗口内的小量偏移，避免原生控件处理大 Unix 数值时损失精度。

游标从完整数组读取最近时刻的原始行，显示实际采样时间、来源时间、时间差和数值。空档、窗口外覆盖和缺测分别标记，不插值、不把停止采样前的旧值延伸到后续时刻。重复时间采用该最近时刻稳定排序后的第一行，并返回重复数量。`explorer_views` 保存命名选择、分时钟窗口、游标与布局；React 进入 Explorer 时恢复最近保存的视图。异步曲线和游标请求均拒绝过期响应，游标移动只读取样本，不重新加载显示序列。

启动时增量添加三个表，并为缺少质量信息的旧数据集从现有数组回填。既有信号元数据通过 `INSERT OR IGNORE` 保留。原始 CSV、NPZ、分析结果、事件和模拟实验文件不重写，浏览状态不依赖浏览器存储。

| API | 用途 |
|---|---|
| `GET /api/workspaces/:id/signals` | Workspace 全部信号、语义、来源、时钟与质量 |
| `PATCH /api/signals/:id` | 编辑可变元数据，拒绝修改原始列名和身份 |
| `GET /api/datasets/:id/quality` | 读取实际来源质量快照 |
| `GET/PATCH /api/datasets/:id/time-reference` | 查看／保存显式时间参考 |
| `POST /api/workspaces/:id/explore` | 按信号 ID 和分时钟窗口读取独立原始曲线 |
| `POST /api/workspaces/:id/cursor` | 按时钟读取完整分辨率样本及观测状态 |
| `GET/POST /api/workspaces/:id/views` | 恢复／创建命名浏览配置 |
| `PATCH /api/workspaces/:id/views/:viewId` | 更新本 Workspace 的已有配置 |

`SignalWorkspace.tsx` 提供目录、元数据编辑器、时间关系表单、质量分布、共享窗口、曲线与游标。Explorer 通过已有数据集和原始信号键进入 Monitoring，携带当前窗口；用户仍须选择健康且在分析之前的基线。选中来源窗口可经 `IncidentLinkDialog` 创建事件，也可打开重叠的已有分析。模拟信号带原会话入口，调查与干预继续使用现有运行时。事件曲线、贡献度和独立报告展示保存的名称和单位，报告附录保留原始列名及来源／浏览时钟。

验证覆盖 `tests/test_data_foundation.py` 和真实 React DOM 交互测试；[浏览器及旧库验证记录](signal-workspace-validation.md) 包含重启恢复和原始文件校验。统一网格、单位转换与派生计算由以下独立变换模块实现。

## Transformation pipeline

`WorkspaceStore.transformations` adds one SQLite `transformations` table with Workspace ownership, a versioned JSON definition, editable name, integer revision and timestamps. Definition version 1 is ordered: select stable signal IDs and bind expression keys; resolve source clocks and unit semantics; deduplicate; convert units; resample each source; handle missing values; evaluate derived signals in declaration order. Definitions retain resolved clocks and source units when saved. The editor can explicitly refresh current source metadata. Independent clocks must be related explicitly before a common grid is constructed.

`units.py` uses an explicit scale/offset registry. Unknown units support identity only; rpm/Hz requires declared rotational meaning. Absolute temperatures convert affinely; subtraction first converts compatible inputs and produces a delta unit. Delta scales and simple rates support proportional conversion. Absolute-temperature sums, products and ratios are rejected as ambiguous. Complex products carry an unknown inferred unit until the user specifies a numeric output-unit convention; this is intentionally a small engineering registry rather than dimensional algebra.

`resampling.py` operates in seconds relative to the target grid origin. Source-clock origins are subtracted before sample seconds are added; Unix-sized per-sample additions cannot round away millisecond endpoints. Boundary matching uses a tolerance bounded by grid spacing and source-clock float resolution. Intersection, union and custom windows produce a regular grid of at most 1,000,000 rows / 10,000,000 values. Every method retains source coverage boundaries. Linear interpolation limits bracket span; previous value limits age; nearest requires a bounded bracket and distance. Original missing samples remain missing during resampling and may be filled in the following explicit step. Mean/min/max use left-closed `[g, g + interval)` windows. Duplicates use first, last, finite mean or error. Linear/previous filling anchors to source values rather than newly held values, so repeated processing cannot extend a hold's allowed age. Fixed/statistical fills remain inside source coverage; statistical values use original valid observations inside the output window and record the statistic, numeric result and sample count.

`expressions.py` interprets a bounded AST (2,000 characters, 200 nodes). Only numeric constants, selected/earlier signal keys, arithmetic and documented numeric functions are accepted; Python evaluation, attributes, indexing, imports and arbitrary calls are unavailable. Compatible arithmetic converts values before computation. Scalar clip/minimum/maximum bounds use the first argument's unit. Division/domain failures yield missing values. diff/rate require adjacent values; rate divides by actual timestamp differences and leaves its first value missing. Output conversion copies quantities so it cannot mutate a selected input. Derived columns retain expression, dependency keys, stable source signal IDs, inferred/declared units, display metadata and float64 type.

`WorkspaceStore.save_dataset` is shared by CSV imports and executions. Every execution creates a new ordinary Dataset folder, output `source.csv` and full-precision `series.npz`. NPZ adds aligned `provenance` uint8 and `observed` Boolean matrices; imports keep their existing format. Provenance distinguishes missing, measurement, interpolation, hold, aggregation, fixed/statistical fill, calculation, nearest and processed source. A derived point counts as observed only when its dependencies have original coverage. Aggregates require their finite contributing values to have original coverage. Chaining transformations preserves that mask. Dataset metadata embeds the complete definition snapshot, definition/revision/execution IDs, creation time, source IDs/names/hashes, simulation links, frozen source clock, output grid and quality summaries. Existing arrays are never rewritten. Relative output clocks are restored directly from the execution snapshot; UTC outputs store their own origin. Generated dataset time references cannot be edited independently of a new execution.

Monitoring uses the ordinary analysis endpoint and saved result format. Generated inputs default to `observationPolicy=measured`: processed values are excluded from preprocessing and original coverage. Max-Z/PCA filter fit/calibration rows by the configured coverage policy and still need 30 eligible rows per partition; temporal models require a covered baseline to preserve sequence history. Explicit `processed` uses finite processed values as available input, while ordinary missing values still undergo the existing median/abstention policy. The selected policy and processed-input count are saved in the analysis; results retain execution identity. Explorer cursor samples expose processed status and provenance. Incident links continue to reference the fixed dataset/result IDs. Reports add source hashes, unit relations, expressions, processing policies and quality to the technical appendix. Transformed TripLens data retain source-session links without claiming that calculated columns satisfy the simulator's raw schema.

| API | Purpose |
|---|---|
| `GET /api/units` | Explicit engineering-unit registry |
| `GET/POST /api/workspaces/:id/transformations` | List/create saved definitions |
| `GET/PATCH /api/transformations/:id` | Reopen/edit a definition; editing increments revision |
| `POST /api/workspaces/:id/transformations/preview` | Compute an unsaved `{config}` without creating a dataset |
| `POST /api/transformations/:id/preview` | Compute a saved definition |
| `POST /api/transformations/:id/execute` | Create a new Dataset from the saved revision |
| `GET /api/datasets/:id/sample` | Existing full-resolution sample plus provenance/observation flags for generated data |

The React workspace restores definitions, allows per-source policy and expression editing, debounces actual previews and rejects stale responses. Save/generate actions validate with the same computation engine. An unchanged repeat execution reuses the definition revision and creates another dataset ID. `TransformationLineage` is shared by dataset details, analysis results and Incident sources. Existing Explorer plots, monitoring forms, incident timelines and report rendering remain the downstream path. [Acceptance records](transformation-validation.md) cover numerical, HTTP/restart, DOM and browser workflows.

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

时间轴拥有明确的身份和秒数偏移。带日期时间起点的数据先加上该起点的 Unix 秒数，归入 UTC 绝对时间轴。数值／生成时间轴默认使用 `dataset:<id>`；同一过程模型的数据和实验使用 `simulation:<id>`，并可复用数据工作区保存的显式参考与偏移。不同相对时间源不因数值相近而合并。事件新增可选 `time_axis_key`，从来源创建时自动写入；旧事件不推断原点，可由用户指定参考来源。显式 `time_origin` 优先。调查记录新增 `observed_axis_key`，解除来源关联后仍保留观察时刻所属的时钟。状态、结论和事件信息变更以同一事务写入 `incident_history`，保存前后值及记录时间，放在独立的调查操作序列，不冒充设备观察时间。迁移只添加表与可空列。

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

| Schema / model descriptor | Width | Clock | Interpretation |
|---|---:|---|---|
| `triplens-synthetic-18-v2` | 18 | seconds, configured 0.05–1 s | Explicit synthetic engineering keys and units; accepted by current diagnosis/CSV API |
| `coupled-tanks` descriptor | 7 | seconds, sampling 0.02–10 s | Separate hydraulic measurements and units; generic Dataset analysis and model-local tools, without TripLens diagnosis |
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

## Model & Scenario Workspace

`l5.models` 显式注册 TripLens 与双水箱，`ProcessModel` 约定描述、验证、模拟、观察、调查与干预。`l5.runtime` 按 Model ID 和能力分发，公共层只维护会话、时间窗口、缓存、运行记录和 Dataset 导出。TripLens 算法保留在原模拟模块和独立适配器内；双水箱具有独立方程、7 通道、工具和指标，不调用 TripLens 的 18 通道诊断。外部助手入口同样检查诊断能力。

`ScenarioService` 在 SQLite 中添加定义和不可变版本表。会话固定模型描述、配置、场景版本、测量和真值，保存后编辑或再次运行不会重写已有轨迹。旧 TripLens 文件读取时仅补充投影元数据。模型数据与派生数据保留来源快照，实验真值入口读取保存的故障区间并映射时钟；有限故障结束后的恢复时间保持未知标签。

前端 Models 从实际目录生成配置表单、保存与复制场景、恢复版本及会话。TripLens 使用原专业调查组件，双水箱使用公共曲线、窗口和通用指标展示。Incident、实验研究索引及报告保留各自模型、场景、单位和评价分母。[接口、方程、数值方法与存储细节](model-workspace.md) 和 [实际验收](model-workspace-validation.md) 单独记录。

## External TEP and independent datasets

`benchmarks/rieth_stream.py` 为已固定的官方 numeric RDX2 data.frame 提供有界提取；不执行 R 代码。原始文件按 `benchmarks/rieth_sources.json` 的大小、MD5 和 SHA-256 校验。每次最多选择 64 个 fault/run 对，逐列以 65536 行块读取，完整消费压缩流并校验列名、对象、运行和 sample 连续性。`examples.tep.prepare` 把所选运行保存为独立 NPZ 和来源清单，服务不下载或常驻加载原始大型文件。

`l5.tep_import` 从 `L5_TEP_CACHE`（默认 `data/external/tep`）读取已准备的缓存。HTTP 预检和导入重新验证提取哈希、52 通道及故障时间约定。每个运行通过既有 `WorkspaceStore.save_dataset` 保存，`metadata.external` 保留原始来源、文件和提取哈希、运行／故障编号、Schema、sample 解释和处理记录；原始 sample 另存 NPZ。标签通过既有 `experiment_labels` 保存独立版本。

通用分析配置可增加 `training: {fit: {datasetId,range,signalMapping}, calibration: {...}}`，`datasetId/analysisRange/signalMapping` 描述独立测试。`l5.independent` 按原始列名和单位验证映射；TEP 还必须具有相同完整 Schema。重导入同一原始运行仍按 `sequenceId` 识别，不能冒充独立测试。Fit 只读取正常拟合数组，Calibration 决定阈值；测试数据不参与任一步。时序算法还验证三个分区的一致采样周期。

`fit_detector` 复用 `l5.analysis.build_monitor` 和现有九算法；`score_detector` 复用共同的 `score_analysis` 生成原有 AnalysisResult。缺测使用正常 Fit 中位数并服从既有覆盖／abstain 门控；EWMA、CUSUM、DPCA 和 Adaptive Max-Z 的每次独立评分均重启内部历史。原单 Dataset `run_analysis` 保留。CSV 读取采用 round-trip 浮点解析，保证数值导出的双精度往返。

Experiment 的可选 `testDatasets` 定义各独立运行、评价范围、映射和标签版本。版本 2 执行快照增加全部训练／测试 Dataset 哈希、标签和新增引擎文件哈希；版本 1 历史继续读取。worker 在批内按完整训练／算法配置复用拟合，每个测试保留独立任务和结果。普通研究上限仍为 64，独立研究为 256，测试运行最多 32。`external_benchmark` 按批次、故障、算法及固定参数条件汇总，保留计数分母、中位数、范围和失败；不合并参数候选或不同历史批次。

前端 `TEPWorkspace` 提供缓存预检、导入、来源详情及固定案例入口。`IndependentTraining` 复用 Experiment 参数配置；映射控件按需挂载。`TEPBenchmark` 在同一 Experiment 中显示矩阵并选择单运行，之后使用既有 ExperimentComparison、Signal Explorer、AnalysisResult 和 Incident。注入时间以独立真值标记呈现，通用调查不应用 TripLens 18 通道规则。

独立实验报告按实际测试 Dataset 组织原始曲线、标签、模型来源和结果；Incident 报告增加保存的来源与评价。报告读取历史结果，不重算分数。原始数据、缓存和生成 HTML 保留本地，仓库提交固定协议、逐运行结果、摘要和浏览器截图。[完整案例](tep-case-study.md) 与 [复现命令](../examples/tep/README.md) 单独记录。

| API | 用途 |
|---|---|
| `GET /api/external/tep/sources` | 已准备的来源及可用独立运行 |
| `GET /api/external/tep/protocol` | 固定九算法案例配置 |
| `POST /api/external/tep/preview` | 重新验证所选运行及采样／注入身份 |
| `POST /api/workspaces/:id/external/tep` | 导入所选运行及独立标签版本 |
| `POST /api/workspaces/:id/external/tep/experiment` | 复用匹配导入，保存固定 Experiment |

## Verification and operation

`npm run check` runs workspace/example Python tests, frontend export tests and TypeScript/Vite. Complete numerical regeneration is available separately through `npm run verify:artifacts`. The Python runner chooses `.venv` when present and forces UTF-8 across platforms. CI checks Linux and Windows. The separate external-data workflows run on relevant source/protocol changes or manual dispatch, cache fixed inputs, revalidate hashes and cancel obsolete runs; ordinary UI/docs changes do not trigger all external downloads.

The reference suite preserves all eleven study configurations and their logs. Numerical snapshots capture audited thresholds, workload, coverage, fold/seed summaries and negative outcomes with float tolerance. They check software drift; repeatedly consulted simulator data provide no new independent evidence. Raw third-party datasets remain outside Git and report artifacts.
