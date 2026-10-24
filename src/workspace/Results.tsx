import { useEffect, useRef, useState, type ReactNode } from "react";
import { Plot, SignalPlots } from "./Charts";
import { intervalWindow, keyFindings } from "./findings";
import { dateLabel, namedSignal, number, timeLabel, type AnalysisResult, type Contribution, type ContributionMetric, type Dataset, type Interval } from "./types";
import { IncidentLinkDialog } from "./IncidentLinkDialog";
import { TransformationLineage } from "./TransformationWorkspace";

const metrics: Record<ContributionMetric, { label: string; description: string }> = {
  "history-contribution": { label: "History-based channel contribution", description: "Causal channel statistics use the observed sequence through this timestamp. State resets after insufficient observation coverage." },
  "absolute-robust-z": { label: "Absolute robust z-score", description: "Absolute distance from the normal center, divided by the fitted robust scale. The largest value is the Max-Z score." },
  "squared-residual": { label: "PCA-Q squared residual", description: "Each signal’s squared standardized residual outside the PCA model. Contributions sum to the Q score." },
  "model-leverage": { label: "PCA-T² model-space leverage", description: "Absolute back-projection of the variance-scaled PCA scores. These descriptive values rank signals and do not sum to T²." },
};
const metricsZh: typeof metrics = {
  "history-contribution": { label: "历史序列贡献度", description: "使用截至该时刻的已观测序列计算各变量贡献。观测覆盖不足时重置历史状态。" },
  "absolute-robust-z": { label: "稳健 Z 分数绝对值", description: "与正常中心的绝对偏差除以拟合的稳健尺度；最大值是 Max-Z 分数。" },
  "squared-residual": { label: "PCA-Q 残差平方贡献", description: "各变量在 PCA 模型外的标准化残差平方，贡献之和为 Q 分数。" },
  "model-leverage": { label: "PCA-T² 模型空间贡献", description: "方差缩放后的 PCA 得分反投影绝对值，用于排列相关变量，贡献之和不等于 T²。" },
};

export function Contributions({ values, signals, metric, locale = "en", label = (name: string) => name }: { values?: Contribution[]; signals: string[]; metric?: ContributionMetric; locale?: "en" | "zh"; label?: (name: string) => string }) {
  const entries = values ?? signals.map(signal => ({ signal, value: null }));
  const maximum = values?.[0]?.value || 1;
  function rows(items: typeof entries, offset = 0) {
    return items.map((item, index) => <li key={item.signal}>
      <span className="ws-contribution-rank">{offset + index + 1}</span><span className="ws-contribution-name">{label(item.signal)}</span>
      {item.value !== null && <><span className="ws-contribution-bar" aria-hidden="true"><i style={{ width: `${item.value / maximum * 100}%` }} /></span><strong>{number(item.value)}</strong></>}
    </li>);
  }
  return <div className="ws-contributions">
    {metric && values && <><span className="ws-kicker">{(locale === "zh" ? metricsZh : metrics)[metric].label}</span><p className="ws-muted">{(locale === "zh" ? metricsZh : metrics)[metric].description}</p></>}
    <ol>{rows(entries.slice(0, 3))}</ol>
    {entries.length > 3 && <details><summary>{locale === "zh" ? `查看全部 ${entries.length} 个变量的贡献` : `All ${entries.length} signal contributions`}</summary><ol start={4}>{rows(entries.slice(3), 3)}</ol></details>}
    {!values && <p className="ws-muted">{locale === "zh" ? "此历史分析仅保存变量排序；重新运行分析可保存数值贡献。" : "This saved run retains signal rankings. Run again to save numerical contributions."}</p>}
  </div>;
}

export function ResultView({ result, dataset, signalPicker, initialIntervalIndex }: { result: AnalysisResult; dataset: Dataset; signalPicker: (selected: string[], onChange: (signals: string[]) => void) => ReactNode; initialIntervalIndex?: number }) {
  const [plotted, setPlotted] = useState(result.relatedSignals.slice(0, 3));
  const [allIntervals, setAllIntervals] = useState(false), [focused, setFocused] = useState<Interval | null>(null);
  const [linking, setLinking] = useState<{ interval: Interval; mode: "new" | "existing" } | null>(null);
  const detail = useRef<HTMLElement>(null);
  const { summary } = result, axis = dataset.metadata.time;
  const findings = keyFindings(result.intervals);
  const range = focused ? intervalWindow(focused, result.config.analysisRange) : result.config.analysisRange;
  const contributions = focused ? focused.contributions : result.signalContributions;
  const related = focused ? focused.signals : result.relatedSignals;
  const peakTime = focused?.peakTime ?? result.peakTime ?? result.times[result.scores.indexOf(summary.peakScore)];
  useEffect(() => {
    if (initialIntervalIndex !== undefined && result.intervals[initialIntervalIndex]) focus(result.intervals[initialIntervalIndex]);
  }, [initialIntervalIndex]);

  function focus(interval: Interval) {
    setFocused(interval);
    setPlotted((interval.contributions?.map(c => c.signal) ?? interval.signals).slice(0, 3));
    detail.current?.focus({ preventScroll: true });
    detail.current?.scrollIntoView({ behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start" });
  }

  function exportResult() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = `l5-analysis-${result.id}.json`; a.click(); URL.revokeObjectURL(url);
  }

  return <section className="ws-results" aria-label="Analysis result">
    {dataset.metadata.transformation && <><p className="ws-notice">Transformation data · observation policy: {result.config.observationPolicy === "processed" ? "processed values included in coverage" : "original observations only"}. Interpolation and fill provenance is retained.</p><TransformationLineage dataset={dataset} /></>}
    <div className="ws-section-heading"><div><span className="ws-kicker">RESULT / {result.algorithmLabel}</span><h2>{result.name}</h2></div><button className="ws-outlined" onClick={exportResult}>Export result JSON ↓</button></div>
    <p className="ws-saved" role="status">● Saved to workspace · {dateLabel(result.completedAt)} · {number(result.durationMs)} ms</p>
    <div className="ws-stats ws-result-stats"><div><strong className={result.intervals.length ? "ws-coral" : "ws-accent"}>{result.intervals.length}</strong><span>detected intervals</span></div><div><strong>{summary.flaggedSamples.toLocaleString()} / {summary.analysisSamples.toLocaleString()}</strong><span>samples above threshold</span></div><div><strong>{number(result.threshold)}</strong><span>fixed threshold</span></div><div><strong>{summary.firstDetection === null ? "None" : timeLabel(axis, summary.firstDetection)}</strong><span>first detected sample</span></div></div>

    {findings.length > 0 && <section aria-label="Key findings" className="ws-key-findings">
      <div className="ws-section-heading"><h3>Key findings</h3><span className="ws-muted">{findings.length} highlighted / {result.intervals.length} detected</span></div>
      <p className="ws-muted">Prioritized by sample count, then peak score. Every detected interval remains in the complete record below.</p>
      <div className="ws-finding-grid">{findings.map((interval, index) => <article key={interval.start} className={`ws-finding${focused === interval ? " ws-finding-active" : ""}`}>
        <div className="ws-inline ws-between"><span className="ws-kicker">INTERVAL {index + 1}</span><strong>{interval.samples} samples</strong></div>
        <h4>{timeLabel(axis, interval.start)} <span>→</span> {timeLabel(axis, interval.end)}</h4>
        <p>{number(interval.end - interval.start)} s span · peak <b>{number(interval.peakScore)}</b> / threshold {number(result.threshold)}</p>
        <p className="ws-accent">{interval.signals.slice(0, 2).map(s => namedSignal(dataset, s)).join(" · ")}</p>
        <button type="button" className="ws-outlined" onClick={() => focus(interval)} aria-pressed={focused === interval} aria-label={`Inspect interval ${number(interval.start)} to ${number(interval.end)} seconds`}>Inspect interval & curves ↗</button>
        <div className="ws-inline incident-actions"><button type="button" onClick={() => setLinking({ interval, mode: "new" })}>创建事件</button><button type="button" onClick={() => setLinking({ interval, mode: "existing" })}>添加到已有事件</button></div>
      </article>)}</div>
    </section>}

    <Plot title={`${result.algorithmLabel} anomaly score · full analysis window`} times={result.times} values={result.scores.map((s,i) => result.states?.[i] === "abstain" ? null : s)} axis={axis} gaps={dataset.metadata.quality?.gaps} threshold={result.threshold} intervals={result.intervals} color="#e9927d" />
    <div className="ws-notice">{summary.fitSamples} assumed-normal samples fitted the model; {summary.calibrationSamples} subsequent normal samples calibrated the threshold at α={result.config.alpha}. Alarm persistence: {result.config.persistence ?? 1} samples. Shading marks confirmed alarm intervals.</div>
    {result.observedFraction && <><p className="ws-notice">Observation coverage: {number((summary.coverageFraction ?? 1)*100)}% of rows eligible · {summary.abstainedSamples ?? 0} abstained samples. Abstain is neither normal nor alarm.</p><Plot title={dataset.metadata.transformation && result.config.observationPolicy === "processed" ? "Available processed value fraction" : "Original sensor observation fraction"} times={result.times} values={result.observedFraction} axis={axis} threshold={result.config.minCoverage ?? .9} color="#b4a0db" /></>}

    <section ref={detail} className="ws-interval-detail" tabIndex={-1} aria-label="Interval details and raw signals" hidden={summary.abstainedSamples === summary.analysisSamples}>
      <div className="ws-section-heading"><div><h3>{focused ? "Selected interval" : "Peak signal contributions"}</h3><p className="ws-muted">{focused ? `${timeLabel(axis, focused.start)} → ${timeLabel(axis, focused.end)} · peak at ` : "Highest-score sample · "}{peakTime !== undefined ? timeLabel(axis, peakTime) : ""}</p></div>
        {focused && <button type="button" className="ws-outlined" onClick={() => setFocused(null)}>Show full analysis window</button>}
      </div>
      <Contributions values={contributions} signals={related} metric={result.contributionMetric} label={s => namedSignal(dataset, s)} />
      <p className="ws-muted">Missing target measurements use normal-fit medians ({summary.imputedValues.analysis} values filled).</p>
      {result.config.stress && ((result.config.stress.noise ?? 0) !== 0 || (result.config.stress.offset ?? 0) !== 0 || (result.config.stress.missingFraction ?? 0) > 0 || (result.config.stress.missingSignals?.length ?? 0) > 0) && <p className="ws-notice">Scores and coverage include the saved artificial perturbations. The raw curves below show the original dataset.</p>}
      {signalPicker(plotted, setPlotted)}
      <SignalPlots dataset={dataset} signals={plotted} range={range} intervals={result.intervals} />
    </section>

    <div className="ws-section-heading"><h3>Complete anomaly record</h3><span className="ws-muted">{result.intervals.length} intervals · chronological order</span></div>
    {result.intervals.length ? <div className="ws-table-scroll"><table><thead><tr><th>Start</th><th>End</th><th>Samples</th><th>Peak score</th><th>Related signals at peak</th><th>Curves / 事件</th></tr></thead><tbody>{(allIntervals ? result.intervals : result.intervals.slice(0, 30)).map((interval, i) => <tr key={i}><td>{timeLabel(axis, interval.start)}</td><td>{timeLabel(axis, interval.end)}</td><td>{interval.samples}</td><td className="ws-coral">{number(interval.peakScore)}</td><td>{interval.signals.map(s => namedSignal(dataset, s)).join(" · ")}</td><td><div className="ws-inline incident-actions"><button type="button" onClick={() => focus(interval)}>Inspect</button><button type="button" onClick={() => setLinking({ interval, mode: "new" })}>创建事件</button><button type="button" onClick={() => setLinking({ interval, mode: "existing" })}>添加到已有事件</button></div></td></tr>)}</tbody></table>{result.intervals.length > 30 && <button type="button" onClick={() => setAllIntervals(!allIntervals)}>{allIntervals ? "Show first 30" : `Show all ${result.intervals.length} intervals`}</button>}</div> : <p className="ws-notice">No confirmed alarm intervals. {summary.abstainedSamples ? `${summary.abstainedSamples} samples lack sufficient coverage and are excluded from normal/alarm decisions.` : "Observed scores did not meet the configured alarm rule."}</p>}
    <details><summary>Saved model and parameters</summary><pre>{JSON.stringify({ config: result.config, model: result.model, summary: result.summary }, null, 2)}</pre></details>
    {linking && <IncidentLinkDialog workspaceId={result.workspaceId || dataset.workspace_id} mode={linking.mode} onClose={() => setLinking(null)} source={{ kind: "interval", analysisId: result.id, datasetId: dataset.id, intervalIndex: result.intervals.indexOf(linking.interval) }} draft={{ title: `${dataset.name} · ${number(linking.interval.start)}–${number(linking.interval.end)}s 异常调查`, start: linking.interval.start, end: linking.interval.end, origin: axis.origin, description: `${result.algorithmLabel} 检出异常；峰值时间 ${timeLabel(axis, linking.interval.peakTime)}，相关变量：${linking.interval.signals.map(s => namedSignal(dataset, s)).join("、")}。` }} />}
  </section>;
}
