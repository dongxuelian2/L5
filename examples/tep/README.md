# Tennessee Eastman 外部数据案例

## 扩展覆盖与正常训练稳定性

原 PR22 的[协议](protocol.json)和 72 项任务定义继续保留。本轮使用[扩展协议](expanded_protocol.json)、[稳定性协议](robustness_protocol.json)、[研究报告](../../docs/tep-benchmark-expanded.md)。详细 CSV/JSON 与故障 3 过程记录仅生成到本地忽略目录。扩展有 585 项任务；A/B/C 在同一完整测试集合上有 1,755 项任务；每次正式批次不超过 252 项。

显式准备 71 个所需运行（复用既有缓存时会校验哈希并跳过重复提取）：

```sh
node scripts/python.mjs -m examples.tep.prepare --source-dir /path/rieth --cache-dir /path/cache --source fault-free-training --faults 0 --runs 1 2 3 4 5 6 --download
node scripts/python.mjs -m examples.tep.prepare --source-dir /path/rieth --cache-dir /path/cache --source fault-free-testing --faults 0 --runs 1 2 3 4 5 --download
node scripts/python.mjs -m examples.tep.prepare --source-dir /path/rieth --cache-dir /path/cache --source faulty-testing --faults 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 --runs 1 2 3 --download
```

下面命令应使用空闲、独立的数据目录，避免离线 CLI 与正在运行的服务同时持有同一个 worker。建议 `OPENBLAS_NUM_THREADS=1`、`OMP_NUM_THREADS=1`；本地 HTTP 验证设置 `NO_PROXY=127.0.0.1,localhost`。`--download` 是显式网络入口；正式运行不会自行下载大型数据。

```sh
node scripts/python.mjs -m examples.tep.expanded_run --data-dir /path/workspace --cache-dir /path/cache --output-dir /path/output/expanded
# 从 /path/output/expanded/study.json 读取实际 workspaceId，替换下面 ID。
node scripts/python.mjs -m examples.tep.robustness --data-dir /path/workspace --cache-dir /path/cache --output-dir /path/output/robustness --workspace-id ID
node scripts/python.mjs -m examples.tep.expanded_verify /path/output/expanded/results.json /path/output/robustness/results.json
node scripts/python.mjs -m examples.tep.finish_study --data-dir /path/workspace --cache-dir /path/cache --output-dir /path/output
```

`study.json` 保存可恢复的 Workspace／study ID。给运行命令加 `--workspace-id ID --study-id ID` 会导出／继续既有研究，保留已失败的执行，不静默重试或替换负结果。需要重试时使用正式 Experiment 的 retry；结果页明确保留历史尝试。`finish_study` 在本地输出研究 HTML、故障 3 曲线和必要的会话恢复信息；可选 `--publish-dir` 应指向本地忽略目录，不向 Git 发布生成产物。

启动服务时把 `L5_TEP_CACHE` 指向相同缓存，并使用 `node scripts/python.mjs server.py --data-dir /path/workspace`。TEP 页的 Experiment protocol 可选择 Original case study、Expanded benchmark 和 Normal training robustness，选择已存 study 后查看故障矩阵、正常训练比较和故障 3 对照；协议、训练配置、指标和选中单元格保留在 URL，返回或刷新可以恢复。点击单元格进入真实 Dataset／Experiment，复用已有多算法比较、Signal Explorer 和 Incident。


## 原始 72 项案例

本案例把 Rieth 等人公开的 TEP mode 1 仿真轨迹接入 L5 的 Dataset、Experiment、AnalysisResult、Incident 和离线报告。发布结果使用官方原始文件；普通测试使用明确标记的生成夹具。

- [固定协议](protocol.json)：在评分前固定正常训练运行 1、校准运行 2、正常测试运行 1–2，以及故障 1、3、5 的测试运行 1–2。九算法共 72 项任务。
- 逐运行结果通过下述本地命令生成 `output/tep/results.json`，不在 Git 中维护第二份过程记录。
- 结果总结见[案例说明](../../docs/tep-case-study.md)；运行时另在本地生成 `output/tep/scoreboard.md`。
- [案例说明](../../docs/tep-case-study.md)：时间约定、指标、发现、浏览器验收和限制。

## 准备环境与官方数据

在仓库根目录使用 Python 3.12+。运行环境只使用已有 NumPy、pandas；新版提取器不需要 R、pyreadr 或新增解析依赖。原有可选研究环境继续支持 pyreadr。

```bash
node scripts/python.mjs -m pip install -r requirements.txt
node scripts/python.mjs -m examples.tep.prepare --source-dir .integration-cache/tep-originals --cache-dir .integration-cache/tep-cache --source fault-free-training --faults 0 --runs 1 2 --download
node scripts/python.mjs -m examples.tep.prepare --source-dir .integration-cache/tep-originals --cache-dir .integration-cache/tep-cache --source fault-free-testing --faults 0 --runs 1 2 --download
node scripts/python.mjs -m examples.tep.prepare --source-dir .integration-cache/tep-originals --cache-dir .integration-cache/tep-cache --source faulty-testing --faults 1 3 5 --runs 1 2 --download --metrics output/tep-extraction.json
```

下载源为 [Harvard Dataverse V1](https://doi.org/10.7910/DVN/6C3JR1)。三份文件合计 908,887,717 字节；Faulty Testing 为 836,882,037 字节。文件大小、官方 MD5 和固定 SHA-256 见 [来源清单](../../benchmarks/rieth_sources.json)。已有原始文件时，指定其目录并省略 `--download`。准备步骤逐块校验、逐列读取，只保存所选独立运行的 52 个输入及原始 sample 索引。

`--faults` 和 `--runs` 可改变提取集合，每次最多提取 64 个运行。它们改变本地可导入数据，固定官方案例仍按 `protocol.json` 执行。RDX2 格式以外的 R 对象和不符合官方列序的文件明确拒绝。大型原始文件和本地缓存均被 Git 忽略。

## 通过浏览器完成案例

先构建前端，再启动服务，并让 `L5_TEP_CACHE` 指向准备后的缓存。

```bash
npm ci
npm run build
L5_TEP_CACHE=.integration-cache/tep-cache npm run serve
```

PowerShell 启动方式：

```powershell
$env:L5_TEP_CACHE = (Resolve-Path .integration-cache/tep-cache).Path
npm run serve
```

1. 打开 `http://127.0.0.1:8787`，创建 Workspace，进入 **TEP case study**。
2. 选择缓存来源及故障／运行，点击 **Inspect selected runs**，检查 52 输入、样本数、180 s 周期和故障起点，再导入。
3. 在 Datasets 或 Signal Explorer 查看曲线、质量和来源。每次运行保留独立 Dataset 与时钟。
4. 点击 **Create fixed nine-algorithm experiment**，核对两个正常训练来源、八个测试运行和固定参数，再 **Save & run all tasks**。
5. 打开 **TEP benchmark**，切换事件检出、样本 recall、正常 FAR、延迟或覆盖率。展开单元格查看分母、中位数、范围和失败数。
6. 选择 fault 1 / simulationRun 1，比较九算法。原始信号及分数标出已知注入时间；每份 AnalysisResult 独立保存。
7. 选择实际报警区间，创建 Incident，关联其他算法，保存候选解释、来源证据与结论，生成并下载离线 HTML。

通用 Experiments 也可配置独立训练、校准、各测试时间范围、信号映射及标签版本；保留原来的单 Dataset 流程。独立实验最多 256 项任务，普通单 Dataset 参数研究仍最多 64 项。

## 命令行复现与导出

在单独的数据目录中执行；不要同时让另一个 L5 服务管理同一目录的任务。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 node scripts/python.mjs -m examples.tep.run --data-dir .integration-cache/tep-workspace --cache-dir .integration-cache/tep-cache --output-dir output/tep --investigate
node scripts/python.mjs -m examples.tep.verify output/tep/results.json
```

PowerShell 可先分别设置 `$env:OPENBLAS_NUM_THREADS='1'` 和 `$env:OMP_NUM_THREADS='1'`，然后执行同一 Python 命令。

脚本复用正式 Workspace 导入和 Experiment worker；同一固定模型在八个测试运行上评分。输出 `results.json`、`scoreboard.md`、`experiment.html`，以及可选的 `incident.html`。`--investigate` 为预先指定的 fault 1 / run 1 保存一份自动生成的证据复查，区别于浏览器中编辑的调查记录。结果没有通过故障表现反向选择参数。

导出已有已完成实验时可使用 `--existing-experiment ID --incident-id ID`，保留原保存结果。报告生成读取结果，不重算历史分数。需要在浏览器继续查看命令行项目时，以相同 `--data-dir` 启动 `server.py`。

## 校验

```bash
npm run check
npm run test:research
```

带代理的环境应像仓库 CI 一样设置 `NO_PROXY=127.0.0.1,localhost`，让本机 HTTP 回归直连。不再提供官方数据专项 CI；研究者根据上述命令在本地手动复算。
