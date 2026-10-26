import { t as tr, useLocale } from "../i18n";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Plot, SignalPlots } from "./Charts";
import { intervalWindow, keyFindings } from "./findings";
import { dateLabel, namedSignal, number, timeLabel, type AnalysisResult, type Contribution, type ContributionMetric, type Dataset, type Interval } from "./types";
import { IncidentLinkDialog } from "./IncidentLinkDialog";
import { ExternalProvenance } from "./TEPWorkspace";
import { TransformationLineage } from "./TransformationWorkspace";

const metrics: Record<ContributionMetric, { label: string; description: string }> = {
  "history-contribution": { get label() { return tr("History-based channel contribution"); }, get description() { return tr("Causal channel statistics use the observed sequence through this timestamp. State resets after insufficient observation coverage."); } },
  "absolute-robust-z": { get label() { return tr("Absolute robust z-score"); }, get description() { return tr("Absolute distance from the normal center, divided by the fitted robust scale. The largest value is the Max-Z score."); } },
  "squared-residual": { get label() { return tr("PCA-Q squared residual"); }, get description() { return tr("Each signal’s squared standardized residual outside the PCA model. Contributions sum to the Q score."); } },
  "model-leverage": { get label() { return tr("PCA-T² model-space leverage"); }, get description() { return tr("Absolute back-projection of the variance-scaled PCA scores. These descriptive values rank signals and do not sum to T²."); } },
};
export function Contributions({ values, signals, metric, label = (name: string) => name }: { values?: Contribution[]; signals: string[]; metric?: ContributionMetric; label?: (name: string) => string }) {
  useLocale();
  const entries = values ?? signals.map(signal => ({ signal, value: null }));
  const maximum = values?.[0]?.value || 1;
  function rows(items: typeof entries, offset = 0) {
    return items.map((item, index) => <li key={item.signal}>
      <span className="ws-contribution-rank">{offset + index + 1}</span><span className="ws-contribution-name">{label(item.signal)}</span>
      {item.value !== null && <><span className="ws-contribution-bar" aria-hidden="true"><i style={{ width: `${item.value / maximum * 100}%` }} /></span><strong>{number(item.value)}</strong></>}
    </li>);
  }
  return <div className="ws-contributions">
    {metric && values && <><span className="ws-kicker">{metrics[metric].label}</span><p className="ws-muted">{metrics[metric].description}</p></>}
    <ol>{rows(entries.slice(0, 3))}</ol>
    {entries.length > 3 && <details><summary>{tr("All {0} signal contributions", {0: entries.length})}</summary><ol start={4}>{rows(entries.slice(3), 3)}</ol></details>}
    {!values && <p className="ws-muted">{tr("This saved run retains signal rankings. Run again to save numerical contributions.")}</p>}
  </div>;
}

export function ResultView({ result, dataset, signalPicker, initialIntervalIndex }: { result: AnalysisResult; dataset: Dataset; signalPicker: (selected: string[], onChange: (signals: string[]) => void) => ReactNode; initialIntervalIndex?: number }) {
  useLocale();
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

  return <section className="ws-results" aria-label={tr("Analysis result")}>
    {result.experiment && <p className="ws-notice"><a className="ws-link" href={`#/workspaces/${result.workspaceId}/experiments/${result.experiment.experimentId}`}>{tr("Return to source experiment ↗")}</a>{" "}{tr("· run")}{" "}{result.experiment.runId}{" "}{tr("· task")}{" "}{result.experiment.taskId}</p>}
    {dataset.metadata.transformation && <><p className="ws-notice">{tr("Transformation data · observation policy:")}{" "}{result.config.observationPolicy === "processed" ? tr("processed values included in coverage") : tr("original observations only")}{tr(". Interpolation and fill provenance is retained.")}</p><TransformationLineage dataset={dataset} /></>}
    <ExternalProvenance dataset={dataset} />{result.training && <details className="ws-panel"><summary>{tr("Independent normal training / calibration / test provenance")}</summary><pre>{JSON.stringify(result.training, null, 2)}</pre></details>}
    <div className="ws-section-heading"><div><span className="ws-kicker">{tr("RESULT /")}{" "}{tr(result.algorithmLabel)}</span><h2>{result.name}</h2></div><button className="ws-outlined" onClick={exportResult}>{tr("Export result JSON ↓")}</button></div>
    <p className="ws-saved" role="status">{tr("● Saved to workspace ·")}{" "}{dateLabel(result.completedAt)} · {number(result.durationMs)} ms</p>
    <div className="ws-stats ws-result-stats"><div><strong className={result.intervals.length ? "ws-coral" : "ws-accent"}>{result.intervals.length}</strong><span>{tr("detected intervals")}</span></div><div><strong>{summary.flaggedSamples.toLocaleString()} / {summary.analysisSamples.toLocaleString()}</strong><span>{tr("samples above threshold")}</span></div><div><strong>{number(result.threshold)}</strong><span>{tr("fixed threshold")}</span></div><div><strong>{summary.firstDetection === null ? tr("None") : timeLabel(axis, summary.firstDetection)}</strong><span>{tr("first detected sample")}</span></div></div>

    {findings.length > 0 && <section aria-label={tr("Key findings")} className="ws-key-findings">
      <div className="ws-section-heading"><h3>{tr("Key findings")}</h3><span className="ws-muted">{findings.length}{" "}{tr("highlighted /")}{" "}{result.intervals.length}{" "}{tr("detected")}</span></div>
      <p className="ws-muted">{tr("Prioritized by sample count, then peak score. Every detected interval remains in the complete record below.")}</p>
      <div className="ws-finding-grid">{findings.map((interval, index) => <article key={interval.start} className={`ws-finding${focused === interval ? " ws-finding-active" : ""}`}>
        <div className="ws-inline ws-between"><span className="ws-kicker">{tr("INTERVAL")}{" "}{index + 1}</span><strong>{interval.samples}{" "}{tr("samples")}</strong></div>
        <h4>{timeLabel(axis, interval.start)} <span>→</span> {timeLabel(axis, interval.end)}</h4>
        <p>{number(interval.end - interval.start)}{" "}{tr("s span · peak")}{" "}<b>{number(interval.peakScore)}</b>{" "}{tr("/ threshold")}{" "}{number(result.threshold)}</p>
        <p className="ws-accent">{interval.signals.slice(0, 2).map(s => namedSignal(dataset, s)).join(" · ")}</p>
        <button type="button" className="ws-outlined" onClick={() => focus(interval)} aria-pressed={focused === interval} aria-label={tr("Inspect interval {0} to {1} seconds", {0: number(interval.start), 1: number(interval.end)})}>{tr("Inspect interval & curves ↗")}</button>
        <div className="ws-inline incident-actions"><button type="button" onClick={() => setLinking({ interval, mode: "new" })}>{tr("创建事件")}</button><button type="button" onClick={() => setLinking({ interval, mode: "existing" })}>{tr("添加到已有事件")}</button></div>
      </article>)}</div>
    </section>}

    <Plot title={tr("{0} anomaly score · full analysis window", {0: tr(result.algorithmLabel)})} times={result.times} values={result.scores.map((s,i) => result.states?.[i] === "abstain" ? null : s)} axis={axis} markers={dataset.metadata.external?.faultOnsetSeconds == null ? [] : [{ time: dataset.metadata.external.faultOnsetSeconds, label: "Published fault onset" }]} gaps={dataset.metadata.quality?.gaps} threshold={result.threshold} intervals={result.intervals} color="#e9927d" />
    <div className="ws-notice">{summary.fitSamples}{" "}{tr("assumed-normal samples fitted the model;")}{" "}{summary.calibrationSamples}{" "}{tr("subsequent normal samples calibrated the threshold at α=")}{result.config.alpha}{tr(". Alarm persistence:")}{" "}{result.config.persistence ?? 1}{" "}{tr("samples. Shading marks confirmed alarm intervals.")}</div>
    {result.observedFraction && <><p className="ws-notice">{tr("Observation coverage:")}{" "}{number((summary.coverageFraction ?? 1)*100)}{tr("% of rows eligible ·")}{" "}{summary.abstainedSamples ?? 0}{" "}{tr("abstained samples. Abstain is neither normal nor alarm.")}</p><Plot title={dataset.metadata.transformation && result.config.observationPolicy === "processed" ? tr("Available processed value fraction") : tr("Original sensor observation fraction")} times={result.times} values={result.observedFraction} axis={axis} threshold={result.config.minCoverage ?? .9} color="#b4a0db" /></>}

    <section ref={detail} className="ws-interval-detail" tabIndex={-1} aria-label={tr("Interval details and raw signals")} hidden={summary.abstainedSamples === summary.analysisSamples}>
      <div className="ws-section-heading"><div><h3>{focused ? tr("Selected interval") : tr("Peak signal contributions")}</h3><p className="ws-muted">{focused ? tr("{0} → {1} · peak at ", {0: timeLabel(axis, focused.start), 1: timeLabel(axis, focused.end)}) : tr("Highest-score sample · ")}{peakTime !== undefined ? timeLabel(axis, peakTime) : ""}</p></div>
        {focused && <button type="button" className="ws-outlined" onClick={() => setFocused(null)}>{tr("Show full analysis window")}</button>}
      </div>
      <Contributions values={contributions} signals={related} metric={result.contributionMetric} label={s => namedSignal(dataset, s)} />
      <p className="ws-muted">{tr("Missing target measurements use normal-fit medians (")}{summary.imputedValues.analysis}{" "}{tr("values filled).")}</p>
      {result.config.stress && ((result.config.stress.noise ?? 0) !== 0 || (result.config.stress.offset ?? 0) !== 0 || (result.config.stress.missingFraction ?? 0) > 0 || (result.config.stress.missingSignals?.length ?? 0) > 0) && <p className="ws-notice">{tr("Scores and coverage include the saved artificial perturbations. The raw curves below show the original dataset.")}</p>}
      {signalPicker(plotted, setPlotted)}
      <SignalPlots dataset={dataset} signals={plotted} range={range} intervals={result.intervals} />
    </section>

    <div className="ws-section-heading"><h3>{tr("Complete anomaly record")}</h3><span className="ws-muted">{result.intervals.length}{" "}{tr("intervals · chronological order")}</span></div>
    {result.intervals.length ? <div className="ws-table-scroll"><table><thead><tr><th>{tr("Start")}</th><th>{tr("End")}</th><th>{tr("Samples")}</th><th>{tr("Peak score")}</th><th>{tr("Related signals at peak")}</th><th>{tr("Curves / 事件")}</th></tr></thead><tbody>{(allIntervals ? result.intervals : result.intervals.slice(0, 30)).map((interval, i) => <tr key={i}><td>{timeLabel(axis, interval.start)}</td><td>{timeLabel(axis, interval.end)}</td><td>{interval.samples}</td><td className="ws-coral">{number(interval.peakScore)}</td><td>{interval.signals.map(s => namedSignal(dataset, s)).join(" · ")}</td><td><div className="ws-inline incident-actions"><button type="button" onClick={() => focus(interval)}>{tr("Inspect")}</button><button type="button" onClick={() => setLinking({ interval, mode: "new" })}>{tr("创建事件")}</button><button type="button" onClick={() => setLinking({ interval, mode: "existing" })}>{tr("添加到已有事件")}</button></div></td></tr>)}</tbody></table>{result.intervals.length > 30 && <button type="button" onClick={() => setAllIntervals(!allIntervals)}>{allIntervals ? tr("Show first 30") : tr("Show all {0} intervals", {0: result.intervals.length})}</button>}</div> : <p className="ws-notice">{tr("No confirmed alarm intervals.")}{" "}{summary.abstainedSamples ? tr("{0} samples lack sufficient coverage and are excluded from normal/alarm decisions.", {0: summary.abstainedSamples}) : tr("Observed scores did not meet the configured alarm rule.")}</p>}
    <details><summary>{tr("Saved model and parameters")}</summary><pre>{JSON.stringify({ config: result.config, model: result.model, summary: result.summary }, null, 2)}</pre></details>
    {linking && <IncidentLinkDialog workspaceId={result.workspaceId || dataset.workspace_id} mode={linking.mode} onClose={() => setLinking(null)} source={{ kind: "interval", analysisId: result.id, datasetId: dataset.id, intervalIndex: result.intervals.indexOf(linking.interval) }} draft={{ title: tr("{0} · {1}–{2}s 异常调查", {0: dataset.name, 1: number(linking.interval.start), 2: number(linking.interval.end)}), start: linking.interval.start, end: linking.interval.end, origin: axis.origin, description: tr("{0} 检出异常；峰值时间 {1}，相关变量：{2}。", {0: tr(result.algorithmLabel), 1: timeLabel(axis, linking.interval.peakTime), 2: linking.interval.signals.map(s => namedSignal(dataset, s)).join("、")}) }} />}
  </section>;
}
