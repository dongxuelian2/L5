# 产品截图来源

中英文 README 共使用六张真实 L5 浏览器截图。本轮于 2026-10-26 启动生产构建，在持久化验收目录中通过实际页面操作导入 CSV、运行实验、调查事件及恢复模型结果。CSV 与模型场景使用仓库提供的合成示例；TEP 使用已保存的官方公开仿真数据。

| 图片 | 画面内容 | 来源与对应记录 |
|---|---|---|
| [workspace-experiment.jpg](workspace-experiment.jpg) | 三源派生数据的九算法报警时间线，作为首页主视觉。 | 本轮浏览器实验 `5a0d2af5b775449aab98f37b84c2b95e`，9 项任务全部成功。 |
| [workspace-signals.jpg](workspace-signals.jpg) | 温度、流量、压力三个选中来源；UTC 250–470 s 窗口、压力采样空档及原始样本游标。 | 本轮保存视图 `Motor A · three-source investigation`；完整页面截图。 |
| [transformation-preview.jpg](transformation-preview.jpg) | 三源共同网格、压力 kPa→MPa、变化率与填充前后质量。 | 复用原有[变换验收](../transformation-validation.md)的真实截图；本轮另经浏览器生成 496 行派生 Dataset 并运行九算法实验。 |
| [workspace-incident.jpg](workspace-incident.jpg) | 原始温度分析与九算法结果汇入同一个 Incident 时间线。 | 本轮事件 `b43ecc4b984146e98d9b6a15f7af3209`；已保存假设、来源证据、结论并下载 HTML。 |
| [workspace-model-tank.jpg](workspace-model-tank.jpg) | 双水箱泵退化后的实际液位与进水流量，观测窗口 0–80 s。 | 本轮模拟 `8ed28e3762d54ea0ad008354460212f5`，故障起点 40.37 s；另保存了 83.17 s 开始的两方案干预。 |
| [workspace-tep-study.jpg](workspace-tep-study.jpg) | B 配置故障 3 的逐运行结果及正常训练敏感性表。 | 从既有 1,755 项稳定性研究恢复；[扩展研究](../tep-benchmark-expanded.md) · [官方验收回执](../verification/tep-expanded-2026-10-25.json)。 |

新增图片直接保存浏览器截图字节，没有生成界面或重绘图表。首页主视觉接近宽屏比例；较长的 Explorer 与详细界面放在可展开区。图片使用相对路径和信息性替代文字，原始历史图片继续供对应阶段文档使用。

本轮工作流、HTML 导出、390 px 窄屏及服务重启记录见[整合验证](../stage-one-validation.md)。
