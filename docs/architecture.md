# L5 / TripLens architecture and contracts

## Workspace first

The default React route is a persistent, dataset-neutral workspace. `#/examples` lazy-loads the original TripLens workstation and teaching examples.

| Module | Implementation | Responsibility |
|---|---|---|
| Workspace repository | `l5/workspace.py` | Workspace CRUD, dataset metadata, completed analysis jobs; SQLite with cascading ownership |
| Persistent incident investigation | `l5/incidents.py`, `src/workspace/Incidents.tsx` | User-maintained incidents, source links, editable notes/evidence/hypotheses/conclusions, source-window plots and experiment reopening |
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
