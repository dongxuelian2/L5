# Model & Scenario Workspace

L5 uses two explicit model implementations behind a shared runtime. The registry is an in-process dictionary; there is no dynamic third-party code loader. `l5.models.base.ProcessModel` documents the small implementation contract. `l5.models` resolves a stable Model ID. Descriptors supply version, category, source, capabilities, ordered signals and units, configuration fields, fault templates, tools and intervention parameters.

`SimulationService` owns session identity, causal observation windows, bounded observation caching, run records and Dataset export. A model validates its configuration, computes its trajectory, observes a window, executes supported tools and calculates interventions. Capability checks happen before dispatch. Unsupported operations return a client error. The assistant's diagnosis entry point requires a model that declares diagnosis support.

TripLens's established simulator and evidence algorithms remain in `simulation/platform.py`. `l5/models/triplens.py` adapts them without applying those rules to other signal spaces. The original 18-channel ID, 12 faults, tool arguments, observation fitting, physical-pressure decisions and recovery search remain available. A nullable `fault_duration` adds finite injection intervals; a missing value preserves the original persistent-fault behavior. TripLens's detailed React view remains an explicit model-specific component.

## Coupled tanks

`l5/models/tanks.py` models two interacting tanks. Areas `A1`, `A2` are in m², heads `h1`, `h2` in m, and volumetric flows in m³/s:

```text
A1 dh1/dt = qin - q12 - qleak - qspill1
A2 dh2/dt = q12 - qout - qspill2
q12 = c12 * v12 * sign(h1-h2) * sqrt(abs(h1-h2))
qout = cout * vout * sqrt(h2)
qin = pumpRate * pumpCommand / 100 * pumpEfficiency
qleak = leakCoefficient * faultIntensity * sqrt(h1)  [leak fault]
qspilli = 0.1 * max(hi-tankHeight, 0)^1.5
```

The coefficient convention incorporates discharge area and `sqrt(2g)`. The head-difference flow approximation follows the type of interacting-tank balance described in the [University of Jordan two-level laboratory notes](https://engineering.ju.edu.jo/ar/arabic/Laboratories/Two%20Level%20System.pdf). L5's geometry, discharge coefficients, fault intensities and spill law are illustrative implementation choices; they are not parameters fitted to that apparatus.

The default `qin=0.03`, `c12=0.04`, `cout=0.03`, unit valve openings and `h1=1.5625`, `h2=1` satisfy both steady-state balances. Initial levels can be changed independently. Connection flow reverses when Tank 2 has the higher head.

Pump degradation reduces efficiency by `0.7 * intensity`; connection restriction reduces effective opening by `0.85 * intensity`; a leak adds the specified discharge; sensor bias changes only the Tank 2 measurement. Level measurement noise is seeded Gaussian noise and does not enter the physical state equations. Flow and control channels are ideal observations in this reduced model.

Integration uses SSPRK2, as two conservative forward Euler stages followed by their convex combination. Each stage jointly limits a tank's outgoing fluxes by the available donor volume. The inter-tank withdrawal and receipt use the same limited flux. This keeps physical levels nonnegative without inventing volume. Integrated inlet, outlet, leak and spill volumes provide an independent balance residual. Step boundaries land on fault start/end and action times. Forecast output includes the exact action time, even when it is between sampling points.

Sampling is 0.02–10 s; the maximum integration step is 0.005–0.25 s. Configuration checks bound runs to 100,000 sampling intervals and 500,000 integration intervals. Tools use the selected measurements only. Their residuals can also reflect measurement error, overflow and sampling error. A sensor check anchored after an existing constant bias cannot identify that bias.

Intervention branches rerun the same saved model and seed with different pump or valve inputs after the specified action time. They preserve the physical pre-action prefix. Metrics start at that time: Tank 2 absolute level deviation, peak physical level, delivered volume, overflow volume and pump-command change. Backup-pump switching has no additional cost model. Tank forecasts support known parameters; they do not infer parameters or provide uncertainty intervals from real data.

## Versions, persistence and provenance

`model_scenarios` stores Workspace ownership, Model ID and the latest version. `model_scenario_versions` stores append-only JSON definitions, including name, description, model version and full model configuration. An optimistic `expectedVersion` prevents overwriting another editor's newer save. Copies receive a new Scenario ID. A saved version can be run repeatedly; overrides must first be saved as a new version.

`simulations/<id>/session.json` stores actual measurements, configuration, descriptor/version, scenario snapshot/version, fixed seed, status and optional Dataset association. Each `runs/<id>.json` stores a separate immutable request and actual computed result with model/scenario identity. Loading a legacy TripLens session projects missing metadata without rewriting the original file. Computation rejects an unavailable saved model version; saved rows and results remain readable.

Dataset export uses each descriptor's ordered signal keys. Server-authored metadata retains units, model/version, scenario/version, simulation ID, configuration and saved fault truth. Transformations carry those model snapshots in `sourceModels` and retain the existing `sourceSimulations` compatibility field. Generic analysis does not interpret model IDs as a signal mapping. Incident links expose the same provenance and preserved tool/forecast results. Reports use a model's metric and signal definitions for generic forecasts and preserve the original TripLens pressure report path.

Truth intervals describe configured injection on the simulation clock. Finite ends are exclusive; persistent faults include the final simulated observation. Normal labels cover the known pre-fault range, or the whole healthy run. Finite-fault recovery remains unknown because physical transients may persist. Label generation maps persisted truth through compatible source/dataset clocks, clips to actual coverage and preserves original onset for event delay. Detectors never consume these labels as input features.

The model research index reads saved Experiment run snapshots and task metrics. It returns at most 200 tasks from the latest 100 runs, retaining each model/scenario, dataset, algorithm, configuration, label version and evaluation denominator. Full history remains in each Experiment. It makes no cross-model diagnosis or physical score conversion.

## API and interface

| Route | Purpose |
|---|---|
| `GET /api/models`, `GET /api/models/:modelId` | Actual registered descriptors |
| `GET/POST /api/workspaces/:wid/scenarios` | List or create saved definitions |
| `GET/PATCH /api/scenarios/:id` | Read latest or save a new version |
| `GET /api/scenarios/:id?version=N`, `GET .../versions` | Read immutable versions |
| `POST /api/scenarios/:id/copy`, `POST .../run` | Copy a saved version or create a session |
| `GET/POST /api/simulations` | Existing session API, now dispatching by Model ID |
| `POST /api/simulations/:id/analysis`, `tools`, `interventions`, `save` | Observe, calculate supported operations, export Dataset |
| `GET /api/simulations/:id/runs`, `GET .../runs/:runId` | Reopen saved results |
| `POST /api/datasets/:id/labels/simulation` | Save evaluation labels from persisted model truth |
| `GET /api/workspaces/:wid/model-research` | Compare saved research rows with explicit provenance |

`/api/simulations/catalog` and `/labels/triplens` remain compatibility entry points. The generic Models page lives at `#/workspaces/:wid/models`; existing `simulations/:sessionId[/runId]` and saved observation-window links still open the appropriate model. `ModelWorkspace`, `ScenarioEditor`, `ModelSimulation` and `ModelResults` reuse Dataset charts, Incident linking and the existing Experiment workflow. React does not maintain a separate catalog of model metadata.

## 数值验证与示例

数值断言、场景版本、HTTP／重启兼容和双模型端到端回归见 [tests/test_models.py](../tests/test_models.py)。下面保留 2026-10-25 的数值检查与已保存演示例，不作为实际工厂精度或外部验证。

默认无故障、无噪声的 180 s 运行保持 `h1=1.5625 m`、`h2=1 m`，质量残差为 0。健康、泄漏、反向流、干箱和溢流测试的最大绝对体积残差小于 `1e-9 m³`，所有物理液位非负。泄漏运行中，0.025 与 0.05 s 的液位差小于 `2e-6 m`；0.1 s 积分配合 0.4 s 采样与默认结果的差小于 `1e-5 m`。这些阈值验证数值实现，不代表实际装置精度。

浏览器运行的双水箱场景使用泵退化、强度 0.6、故障起点 40.37 s、种子 1、时长 180 s、采样 0.2 s、积分 0.05 s。观察至 80 s，动作从 83.17 s 开始。保存的实际结果为：

| 方案 | Tank 2 液位绝对偏差积分 m·s | 预测期峰值液位 m | 供水量 m³ | 溢流 m³ |
|---|---:|---:|---:|---:|
| 不干预 | 30.581 | 1.203 | 2.398 | 0 |
| 泵命令 125% | 25.000 | 1.203 | 2.500 | 0 |
| 切换备用泵，命令 100% | 14.712 | 1.408 | 2.675 | 0 |

TripLens 的浏览器已知模型试验使用冷却阀故障，观察至 93 s，在 96.4 s 干预，预测至 240 s。基准物理压力峰值约 3214.5 kPa，旁路方案约 3025.6 kPa，减料方案约 3112.6 kPa；旁路分支在本次时域内未跨过 3050 kPa，基准及减料分支仍跨限。原有产量、质量和能耗指标继续显示。

双水箱不提供观测拟合、分类诊断或恢复窗口搜索；未关联过程模型的 CSV 不提供物理干预预测。
