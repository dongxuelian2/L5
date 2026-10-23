# L5 / Workspace First

**把自己的工业时序数据，变成可以持续分析的项目。**

[English](README.en.md) · [运行项目](#运行项目) · [架构](docs/architecture.md) · [TripLens 视频](video/README.md)

L5 现在默认打开 Workspace。你可以创建项目、导入任意列名的数值 CSV、选择信号和时间窗口，运行真实异常检测，并在重启后继续查看数据和分析历史。原来的 TripLens 事故调查工作站保留在 **TripLens examples** 入口。

## 现在可以做什么

- **Workspace**：创建、打开、重命名和删除项目。一个项目保存多个数据集和多次分析。
- **CSV 导入**：预览列、样本和曲线；支持逗号、分号、Tab、竖线分隔，UTF-8 和常见中文编码。可以指定时间列、数值时间单位，或使用固定采样间隔生成时间轴。
- **通用信号**：保留用户自己的列名，不依赖 TripLens 的 18 通道格式。Max-Z 支持单信号；PCA 支持两个及以上信号。
- **真实分析**：Robust Max-Z、PCA-Q、PCA-T²，显示原始测量、异常分数、固定阈值、超阈区间、首次检出时间和相关信号。
- **分析历史**：每次成功运行自动保存模型、参数和完整结果；可以重新打开、修改参数再运行，或导出 JSON。
- **本机持久化**：SQLite 保存元数据和任务；原始 CSV、数值数组和结果文件保存到本地目录。关闭浏览器或重启服务不会清空项目。

## 运行项目

需要 Node.js 20.19+ / 22.12+、npm 和 Python 3.12+。

```bash
npm ci
python -m venv .venv
node scripts/python.mjs -m pip install -r requirements.txt
npm run build
npm run serve
```

打开 **http://127.0.0.1:8787**。不需要 API 密钥或云服务。脚本优先使用项目 `.venv`；也可以通过 `PYTHON` 指定解释器。

开发时在两个终端分别运行：

```bash
npm run serve
npm run dev
```

Vite 将 `/api` 请求代理到本机 8787。只有静态前端时仍可进入 TripLens 示例；Workspace 需要 Python 服务。

## 完成一次分析

1. 在首页输入项目名，点击 **Create workspace**。
2. 在 **Datasets** 选择自己的 CSV，检查时间轴和数据预览，点击 **Import and save dataset**。
3. 勾选信号，点击 **Configure analysis**。
4. 设置假定正常的基线区间和位于其后的分析区间。时间输入统一为秒；日期时间数据会显示对应的 UTC 起点。
5. 选择算法和参数，点击 **Run analysis and save**。
6. 查看曲线、阈值、异常区间和相关信号。在 **History** 可以重新打开结果或使用原参数再次分析。
7. 关闭服务后，再次运行 `npm run serve`，打开同一项目继续工作。

正常基线至少包含 100 个样本：前 70% 拟合模型及缺失值中位数，后 30% 校准阈值。分析区间不参与拟合或阈值选择。原始缺失值保留在数据中，图表显示断点；分析时用拟合区间的中位数补齐。默认区间只是起点，需要选择你认为健康的数据。

## 数据保存位置

默认保存在仓库下被 Git 忽略的 `data/`。启动时可指定其他目录：

```bash
node scripts/python.mjs server.py --data-dir /path/to/l5-data
```

也支持环境变量 `L5_DATA_DIR`。重启时使用同一目录即可恢复。复制整个数据目录可以备份项目；删除 Workspace 会同时删除其数据集和分析记录。

## TripLens 示例与研究

**TripLens examples** 保留 12 个模拟事故、证据调查、报警压缩、干预搜索、案例对比，以及原有 Live / Replay / Lab。示例中的物理关系和诊断器只属于各自的模拟过程。

`benchmarks/` 保留 Tennessee Eastman、时间监测器、PCA/DPCA、独立种子及六工况研究。通用 Max-Z/PCA 计算已提取到 `l5/monitoring.py`，供 Workspace 与研究复用。52、53、18 通道数据之间不做物理含义映射。

Workspace 当前提供统计异常监测，相关信号表示偏离贡献。外部数据的根因分析、调查笔记、实时接入和大数据后台执行是后续方向。

## 验证

```bash
npm run test:workspace  # CSV、算法、保存恢复、HTTP 服务重启
npm run check          # 产品与示例测试、TypeScript、生产构建
npm run test:research  # 单独运行已有研究测试
npm run verify:artifacts # 按需验证示例数值产物
```

研究与生成产物的完整验证不再是 Workspace 日常开发的默认门禁。[研究说明](benchmarks/README.md) · [PR #13 整合记录](docs/integration-2026-10-23.md)
