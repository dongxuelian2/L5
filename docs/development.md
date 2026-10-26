# 开发约定

只提交源码、运行必需资源、小型输入和长期研究证据。运行数据、完整报告、数据库及临时验收产物写入已忽略的 `output/`、`data/` 或 CI artifact；不要全局忽略 JSON／CSV，不改写共享 Git 历史。

## 本次路径核查

| 分类 | 路径及处理 |
|---|---|
| 源码／运行资源 | 保留 `src/data/platform.json`、`src/data/scenario.json`；前端直接导入。保留 `video/` 展示资源，本次不另建发行设施。 |
| 配置／协议 | 保留 `benchmarks/rieth_sources.json`、`examples/tep/*protocol.json`，用于官方来源校验和冻结研究协议。 |
| 必需夹具／数值基准 | 保留 `benchmarks/numeric_reference.json`、`examples/tep/results.json`；后者由 `test_external_tep.py` 和 `finish_study.py` 读取，校验原始 72 项结果。 |
| 长期研究摘要 | 保留 `examples/tep/{expanded,robustness}_summary.json`、两份 `*_per_run.csv`、`fault3_summary.json`。它们是公开报告的长期证据，含分母、失败字段、时延及背景对照；短期 CI artifact 无法替代。 |
| 可再生大型产物 | 完整 study、HTML、逐点数组及执行数据库已写入 `output/`；不复制到 Git。精简研究摘要保持原路径，报告链接和复算入口继续可用。 |
| 短期执行回执 | 删除无程序或文档引用的 `docs/verification/2026-10-23.json`；结论已在 `integration-2026-10-23.md`。其余回执支撑已发表的研究、截图或真实重启记录，保留。临时 maintenance proposal 由本约定替代。 |

上述删除仅减少当前文件树，不缩减历史 Git 对象。保留的研究 JSON／CSV 不改变数值或 schema。

## 界面文案

自有固定文案使用 `src/i18n` 的静态词典和 `t()`；组件订阅共享语言状态。新增文案应同时提供中文简体和英文。语言选择保存到浏览器本地，不作为业务数据保存。用户输入、数据名称、信号元数据、原始研究文字和技术快照保持原样。

## 复现与验证

```sh
npm run check
npm run test:research
npm run verify:artifacts
```

官方 TEP 数据准备、完整复算和长期摘要的生成命令见 [TEP 复现指南](../examples/tep/README.md)。不为文案和文件整理修改算法、冻结协议或持久化 schema。

本次验证（2026-10-26）：`npm run check` 通过 81 项 Workspace Python、40 项模拟 Python、55 项 DOM 测试及生产构建；`npm run test:research` 通过 115 项研究回归。既有官方结果通过 `examples.tep.verify`（72 项）和 `examples.tep.expanded_verify`（585／1,755 项）；用这些已保存输入生成中英研究报告，21／27 个 SVG 的图形数据逐项相同。没有重新调参或执行新的官方研究。

浏览器实际检查了首页／跨路由语言保持、未保存名称、模型场景运行、Dataset 保存、分析、事件创建、报告失效与中英重新生成。语言状态测试还覆盖存储不可用、进行中的分析及 TripLens 表单。

`npm run verify:artifacts` 的 `scenario.json` 全量复算通过；`platform.json.cases[0].diagnosis.clock` 报字段不一致。`simulation/`、`benchmarks/`、`examples/tep/`、`src/data/` 与本次 main 基线完全相同：这是已发布 platform 夹具与现有生成器的既有差异，包含 trace／诊断变化。本次没有覆盖该历史产物，也不将此项标为通过。

原文保留范围：用户项目与调查文字、信号名称和元数据、JSON／CSV 技术内容；六信号历史示例 `scenario.json` 的研究说明与分析步骤；TEP 冻结协议的名称／局限及故障 3 原始解释；未知服务诊断。报告模板的固定文案随语言切换，已经下载的历史文件需重新生成，不回写原文件。
