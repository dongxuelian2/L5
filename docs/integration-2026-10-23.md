# L5 / TripLens 整合审计 · 2026-10-23

本记录区分软件验证、外部模拟数据研究和工业有效性。原始研究记录保留于各 PR 与 `benchmarks/README.md`；没有把单次表现较好的实验算法改成默认生产路径。

## 基线与历史

审计起点 `main = f4d45f95388c5c068440155dcad7ee3cfbd9a628`。工作目录最初为空，没有覆盖用户修改。Git 直连不可用后，通过已连接 GitHub API 恢复 111 个原始提交、248 个目录树和 179 个源码/媒体 Blob，逐对象验证 SHA；`git fsck --full` 通过。

Git 祖先关系和 merge-base 验证表明：#1—#11 为连续堆叠，#11 的 Head 完整包含前十个 Head；#12 独立基于同一 main。main 与 #11/#12 的 merge-base 均为上述基线。集成分支为 [integration/l5-research-consolidation](https://github.com/dongxuelian2/L5/tree/integration/l5-research-consolidation)。仅吸收最终堆叠树及独立比较树，没有逐个重放整条堆叠链，没有强推或删除历史分支。

基线实际执行：29 项原有 Python 测试通过、TypeScript/Vite 构建通过。首次受限运行的本机 HTTP/临时目录失败来自 Windows 沙箱，允许回环请求后复跑通过；默认 GBK 读取 UTF-8 的兼容性问题由显式编码及跨平台运行器修复。基线 Vite 7.3.6 的 npm 审计报告 1 项高危；升级 7.3.7 后审计为 0。

## 十二个 PR 的逐项吸收

下列提交数是各 PR 当前 Base…Head 的真实增量，不是将每个堆叠 PR 相对 main 的总差异重复相加。

| PR | 原始 Head | 增量提交 | 保留内容 | 集成处理 |
|---|---|---:|---|---|
| [#1](https://github.com/dongxuelian2/L5/pull/1) | `1897a79` | 29 | 数据导入、52 列契约与可复现经典基准 | 完整吸收；保留原始 Head 祖先关系 |
| [#2](https://github.com/dongxuelian2/L5/pull/2) | `62dc9ea` | 4 | 传感器扰动、冻结训练与报警事件指标 | 完整吸收；保留原始 Head 祖先关系 |
| [#3](https://github.com/dongxuelian2/L5/pull/3) | `8992760` | 6 | 覆盖率、缺失掩码和三状态 Abstain | 完整吸收；保留原始 Head 祖先关系 |
| [#4](https://github.com/dongxuelian2/L5/pull/4) | `e68b384` | 4 | 预先声明的阈值与五组扰动种子敏感性 | 完整吸收；保留原始 Head 祖先关系 |
| [#5](https://github.com/dongxuelian2/L5/pull/5) | `9694dbb` | 6 | 因果 Page CUSUM 与 EWMA | 完整吸收；保留原始 Head 祖先关系 |
| [#6](https://github.com/dongxuelian2/L5/pull/6) | `c7b4696` | 10 | 有限窗口 CUSUM、正常校准预算与状态复位 | 完整吸收；保留原始 Head 祖先关系 |
| [#7](https://github.com/dongxuelian2/L5/pull/7) | `9b3e84f` | 9 | 漂移自适应、迟滞恢复与失败案例 | 完整吸收；保留原始 Head 祖先关系 |
| [#8](https://github.com/dongxuelian2/L5/pull/8) | `d0a278c` | 9 | 因果两滞后 DPCA-Q/T² | 完整吸收；保留原始 Head 祖先关系 |
| [#9](https://github.com/dongxuelian2/L5/pull/9) | `35620c4` | 5 | 正常数据前向折与报警负荷预算 | 完整吸收；保留原始 Head 祖先关系 |
| [#10](https://github.com/dongxuelian2/L5/pull/10) | `70f5af7` | 7 | Rieth 独立种子正常运行验证 | 完整吸收；保留原始 Head 祖先关系 |
| [#11](https://github.com/dongxuelian2/L5/pull/11) | `e98409a` | 7 | 六工况正常迁移矩阵及持续报警负面发现 | 完整吸收；保留原始 Head 祖先关系 |
| [#12](https://github.com/dongxuelian2/L5/pull/12) | `cf46214` | 7 | 双事故同截点比较、JSON 导出与既有来源声明 | 完整吸收；保留原始 Head 祖先关系 |

## 实际修复

1. 新增不可变来源/信号契约，严格区分经典 52、THUFDD 原生 53 和合成 18 通道；未知含义、单位和采样秒数保持未知。研究会话明确验证正常拟合/校准角色、同序列不重叠、序列边界、缺失值和 Schema 兼容性。
2. CSV 拒绝重复列名、短/长行、错误引号、非有限值和错误时间；支持 UTF-8 BOM。错误通过 API 返回 400；已有请求兼容，显式外部 Schema 不会被静默当作合成过程。
3. 模型拟合从绝对整数时间索引改为相对一秒时钟，拒绝不支持的采样/时域与包含未来信息的缓存诊断；无可用拟合证据时明确失败。
4. 缺失观测中断报警连续状态，未观测时段不计入持续时间，也不制造 Normal/return。持续时间按时间戳秒计算；传播滞后按采样间隔换算。
5. 干预搜索保持 +20 和 +240 两端点及全部中间秒，保持拟合基线的干预前缀。物理 trip 与未作显示舍入的 `physicalPeak` 是安全计算依据。物理基线未越限时取消压力干预排名，避免把传感器误报解释成施救收益；拟合误差和未量化模型不确定性显式披露。
6. 双案例比较/导出抽成纯接口并回归验证所有截点、不同会话、JSON round-trip 与未来值隔离。界面保留既有布局，修复新增第五个标签导致的 390px 窄屏横向溢出，收敛了“物理已验证”一类过强措辞。
7. 经典 TEP 原脚本仅固定下载版本并检查缓存形状；新增 23 文件 SHA-256/字节清单，独立对照上游固定 Git Blob 后记录，缓存被改动时立即失败。
8. 增加统一完整研究运行器、数值回归快照、两个完整生成产物的数值对照、跨平台 UTF-8/Python 运行器、Linux/Windows CI、数据/依赖缓存和过期运行取消；保留 Linux libc 锁文件元数据。

## 外部研究复现

所有数据实际获取并校验，原始第三方数据仅保存在被忽略的本地缓存，未写入仓库。完整结果为 JSON/Markdown/CSV 与独立运行日志；CI 将继续产生可下载结果工件。数值快照 `benchmarks/numeric_reference.json` 记录本次审计后的阈值、报警负荷、覆盖率、种子与折间结果；这是软件数值回归，不是新独立验证集。

经典基准采用正常 d00 的时间顺序拟合/校准、独立正常测试文件及原 21 个故障测试；onset=160 是协议假设。60 分钟早检为 20 个三分钟采样间隔（含端点）；故障后可观测区间约 40 小时。平均延迟仅在检出的故障上有定义。

| 方法 | 60 分钟内检出 /21 | 最终检出 /21 | 正常测试报警事件 | 正常报警活跃样本 /960 |
|---|---:|---:|---:|---:|
| Max-Z | 11 | 21 | 4 | 6 |
| PCA-Q | 9 | 20 | 0 | 0 |
| PCA-T² | 9 | 21 | 1 | 1 |
| Page CUSUM | 8 | 18 | 5 | 433 |
| EWMA | 11 | 21 | 4 | 26 |
| 窗口 CUSUM-12 | 10 | 21 | 4 | 25 |
| 窗口 CUSUM-24 | 9 | 21 | 4 | 57 |
| DPCA-Q 两滞后 | 12 | 21 | 3 | 5 |
| DPCA-T² 两滞后 | 11 | 21 | 3 | 5 |

全部 11 组经典流程均已运行：baseline、robustness、coverage、sensitivity、temporal、bounded、bounded-coverage、drift-recovery、dynamic-pca、dpca-coverage、forward-budget。噪声/偏移增加早检时也可增加误报；必需通道完全缺失时 Abstain 使全 21 故障留在分母，未被伪装为正常。五个扰动种子不是五次独立工厂重复。

漂移/恢复的负面结果保留：干净条件下 Max-Z 的迟滞恢复将早检从 11 降到 10、正常活跃样本从 6 增到 78；自适应 Max-Z 的早检 10、正常事件 6，未显示稳定优势。

前向 A/B 折中，Max-Z 早检 15/11，DPCA-Q 为 10/9。原单次 12 对 11 的微弱优势没有稳定复现。校准预算不等于外推预算：折 B 的同一短校准约束下，外部正常测试 Max-Z 10 事件/56 活跃点、DPCA-Q 16/37、DPCA-T² 41/178。事件更少不等于活跃时间更短。

Rieth 固定 DOI 两份正常 RData 的 SHA-256 均匹配。训练 1/2/3 与 4/5/6 分别拟合/校准/验证，测试 1…10 使用作者声明不重叠的随机种子；全部仍是 mode 1。固定 alpha=.01 的 10 条测试轨迹总误报事件：

| 方法 | 折 A | 折 B |
|---|---:|---:|
| Max-Z | 0 | 16 |
| PCA-Q | 3 | 2 |
| PCA-T² | 0 | 4 |
| DPCA-Q | 4 | 7 |
| DPCA-T² | 1 | 31 |

这些数字与 #10 原记录一致，说明正常拟合/校准轨迹选择会明显影响误报，没有跨折统一最优方法；没有新的外部故障检出结论。

## 六工况专项审计

来源固定为 [THUFDD/Lichen0102 的 09c194f 版本](https://github.com/Lichen0102/Multi-mode-Fault-Diagnosis-Datasets-with-TE-process/tree/09c194f78281bb495da6669cae7a726515f4a4cb)。6 份原始 MAT 均为 7201×81，Git Blob 和 SHA-256 全部匹配。依据源 Python 示例，监测列为 0…52 共 53 列，排除后 28 列扰动。源 README 的 MATLAB 53:81 示例与该 53+28 分界有重叠；适配器遵循明确的 Python 切片及总列数，没有采纳重叠列。原文只给出 12 输入+41 测量的总数，未充分提供逐列物理名称/顺序/单位；当前代码保留原始顺序和通用列名，不套用旧 52 通道。原文 72 小时描述不足以单独验证采样秒数，故只报样本指标。

每个源工况：拟合 [0,720)、校准 [720,1080)；每个目标工况测试 [1080,7201)，共 6121 点。全部 180 单元重跑一致：

| 方法 | 同工况事件 /活跃点（36726 点） | 跨工况事件 /活跃点（183630 次样本评分） |
|---|---:|---:|
| Max-Z | 211 /7405 | 30 /183570 |
| PCA-Q | 323 /5486 | 30 /183570 |
| PCA-T² | 270 /5100 | 30 /183570 |
| DPCA-Q | 361 /6484 | 30 /183570 |
| DPCA-T² | 276 /6157 | 30 /183570 |

每个跨工况单元在第 3 个超阈样本确认后持续超阈，共 6119 活跃点；30×6119 / (30×6121) = 99.9673256%。这不是把 6119 个活跃样本算作 6119 个事件，也不是不可恢复的报警锁存。评分入口每次重新建立时间历史，持续性确认在低于阈值时会复位。仅六条原始轨迹反复组合，不能把 183630 次评分视作独立样本或给出总体置信区间。该负面发现成立，不能宣称现有监测器跨工况可靠。

## 验证与复现

- 原基线 29 项 Python 测试及类型/构建实际通过。
- 集成后 40 项模拟器/契约/API 测试、115 项基准测试及 4 项前端导出测试通过。
- TypeScript、Vite 7.3.7 生产构建、离线 npm 锁文件重装通过，npm 审计 0 漏洞。
- 两个完整生成产物实际重新计算并逐字段数值对照通过，包含全部观测、快照、拟合与干预试验；Python tuple 与 JSON array 按同一数组语义比较。
- 经典全部 11 流程、Rieth 20 组方法/折/政策结果和六工况 180 单元均执行；13 份报告的数值投影回归通过。
- 本机无头 Chrome 实测生产构建、70/240 秒 JSON 下载、传感器偏差案例不排名、390px 窄屏和原 Live 路由；未出现页面脚本错误。
- 构建仍提示模拟数据 chunk 较大，属于已知性能债务；未删除提示或放宽测试掩盖它。

```bash
python -m venv .venv
node scripts/python.mjs -m pip install -r benchmarks/requirements.txt
npm ci
npm run check

node scripts/python.mjs -m benchmarks.fetch_reference --dest .integration-cache/tep-reference
node scripts/python.mjs -m benchmarks.run_suite .integration-cache/tep-reference --output-dir benchmark-reports/reference
node scripts/python.mjs -m benchmarks.verify_reports reference benchmark-reports/reference

node scripts/python.mjs -m pip install -r benchmarks/requirements-external.txt
node scripts/python.mjs -m benchmarks.rieth_independent .integration-cache/tep-rieth --output-dir benchmark-reports/rieth
node scripts/python.mjs -m benchmarks.multimode_normal .integration-cache/tep-six-mode --output-dir benchmark-reports/six-mode
node scripts/python.mjs -m benchmarks.verify_reports rieth benchmark-reports/rieth
node scripts/python.mjs -m benchmarks.verify_reports six-mode benchmark-reports/six-mode
```

本地复现环境：Windows、Python 3.12.14、Node 22.14.0、NumPy 2.3.5、SciPy 1.16.2、pandas 2.3.3、pyreadr 0.5.7、TypeScript 5.9.3、Vite 7.3.7。CI 使用 Python 3.12/Node 22，外部数据仅在相关源码/协议变更或手动触发时执行，缓存恢复后仍校验哈希。

## 保留的关键债务与下一阶段

仍需独立工业数据、53 列完整物理定义、外部故障分类/根因和干预验证、未知工况拒绝、预测不确定性与更长时间动力学，以及模拟数据的按需加载和长期证据存储。当前单一领先假设、有限参数网格、预设基线窗口和传播规则均有限制，不应解释为真实工业安全结论。

优先推进三项：①可审计外部数据/物理 Schema 与独立正常及故障验证；②工况条件化监测和未知工况 Abstain；③外部根因与干预检验，量化参数及模型不确定性。后续改算法应另行冻结新协议和独立保留集，不能继续在同一 21 故障套件上选“胜者”。
