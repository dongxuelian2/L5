import { useRef, useState, type ReactNode } from "react";
import { Plot, SignalPlots } from "./Charts";
import { intervalWindow, keyFindings } from "./findings";
import { dateLabel, number, timeLabel, type AnalysisResult, type Contribution, type ContributionMetric, type Dataset, type Interval } from "./types";

const metrics: Record<ContributionMetric, { label: string; description: string }> = {
  "history-contribution": { label: "History-based channel contribution", description: "Causal channel statistics use the observed sequence through this timestamp. State resets after insufficient observation coverage." },
  "absolute-robust-z": { label: "Absolute robust z-score", description: "Absolute distance from the normal center, divided by the fitted robust scale. The largest value is the Max-Z score." },
  "squared-residual": { label: "PCA-Q squared residual", description: "Each signal’s squared standardized residual outside the PCA model. Contributions sum to the Q score." },
  "model-leverage": { label: "PCA-T² model-space leverage", description: "Absolute back-projection of the variance-scaled PCA scores. These descriptive values rank signals and do not sum to T²." },
};

function Contributions({ values, signals, metric }: { values?: Contribution[]; signals: string[]; metric?: ContributionMetric }) {
  const entries = values ?? signals.map(signal => ({ signal, value: null }));
  const maximum = values?.[0]?.value || 1;
  function rows(items: typeof entries, offset = 0) {
    return items.map((item, index) => <li key={item.signal}>
      <span className="ws-contribution-rank">{offset + index + 1}</span><span className="ws-contribution-name">{item.signal}</span>
      {item.value !== null && <><span className="ws-contribution-bar" aria-hidden="true"><i style={{ width: `${item.value / maximum * 100}%` }} /></span><strong>{number(item.value)}</strong></>}
    </li>);
  }
  return <div className="ws-contributions">
    {metric && values && <><span className="ws-kicker">{metrics[metric].label}</span><p className="ws-muted">{metrics[metric].description}</p></>}
    <ol>{rows(entries.slice(0, 3))}</ol>
    {entries.length > 3 && <details><summary>All {entries.length} signal contributions</summary><ol start={4}>{rows(entries.slice(3), 3)}</ol></details>}
    {!values && <p className="ws-muted">This saved run retains signal rankings. Run again to save numerical contributions.</p>}
  </div>;
}

export function ResultView({ result, dataset, signalPicker }: { result: AnalysisResult; dataset: Dataset; signalPicker: (selected: string[], onChange: (signals: string[]) => void) => ReactNode }) {
  const [plotted, setPlotted] = useState(result.relatedSignals.slice(0, 3));
  const [allIntervals, setAllIntervals] = useState(false), [focused, setFocused] = useState<Interval | null>(null);
  const detail = useRef<HTMLElement>(null);
  const { summary } = result, axis = dataset.metadata.time;
  const findings = keyFindings(result.intervals);
  const range = focused ? intervalWindow(focused, result.config.analysisRange) : result.config.analysisRange;
  const contributions = focused ? focused.contributions : result.signalContributions;
  const related = focused ? focused.signals : result.relatedSignals;
  const peakTime = focused?.peakTime ?? result.peakTime ?? result.times[result.scores.indexOf(summary.peakScore)];

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
    <div className="ws-section-heading"><div><span className="ws-kicker">RESULT / {result.algorithmLabel}</span><h2>{result.name}</h2></div><button className="ws-outlined" onClick={exportResult}>Export result JSON ↓</button></div>
    <p className="ws-saved" role="status">● Saved to workspace · {dateLabel(result.completedAt)} · {number(result.durationMs)} ms</p>
    <div className="ws-stats ws-result-stats"><div><strong className={result.intervals.length ? "ws-coral" : "ws-accent"}>{result.intervals.length}</strong><span>detected intervals · all events</span></div><div><strong>{summary.flaggedSamples.toLocaleString()} / {summary.analysisSamples.toLocaleString()}</strong><span>samples above threshold</span></div><div><strong>{number(result.threshold)}</strong><span>fixed threshold</span></div><div><strong>{summary.firstDetection === null ? "None" : timeLabel(axis, summary.firstDetection)}</strong><span>first detected sample</span></div></div>

    {findings.length > 0 && <section aria-label="Key findings" className="ws-key-findings">
      <div className="ws-section-heading"><h3>Key findings</h3><span className="ws-muted">{findings.length} highlighted / {result.intervals.length} detected</span></div>
      <p className="ws-muted">Prioritized by sample count, then peak score. Every detected interval remains in the complete record below.</p>
      <div className="ws-finding-grid">{findings.map((interval, index) => <article key={interval.start} className={`ws-finding${focused === interval ? " ws-finding-active" : ""}`}>
        <div className="ws-inline ws-between"><span className="ws-kicker">INTERVAL {index + 1}</span><strong>{interval.samples} samples</strong></div>
        <h4>{timeLabel(axis, interval.start)} <span>→</span> {timeLabel(axis, interval.end)}</h4>
        <p>{number(interval.end - interval.start)} s span · peak <b>{number(interval.peakScore)}</b> / threshold {number(result.threshold)}</p>
        <p className="ws-accent">{interval.signals.slice(0, 2).join(" · ")}</p>
        <button type="button" className="ws-outlined" onClick={() => focus(interval)} aria-pressed={focused === interval} aria-label={`Inspect interval ${number(interval.start)} to ${number(interval.end)} seconds`}>Inspect interval & curves ↗</button>
      </article>)}</div>
    </section>}

    <Plot title={`${result.algorithmLabel} anomaly score · full analysis window`} times={result.times} values={result.scores.map((s,i) => result.states?.[i] === "abstain" ? null : s)} axis={axis} threshold={result.threshold} intervals={result.intervals} color="#e9927d" />
    <div className="ws-notice">{summary.fitSamples} assumed-normal samples fitted the model; {summary.calibrationSamples} subsequent normal samples calibrated the threshold at α={result.config.alpha}. Alarm persistence: {result.config.persistence ?? 1} samples. Shading marks confirmed alarm intervals.</div>
    {result.observedFraction && <><p className="ws-notice">Observation coverage: {number((summary.coverageFraction ?? 1)*100)}% of rows eligible · {summary.abstainedSamples ?? 0} abstained samples. Abstain is neither normal nor alarm.</p><Plot title="Original sensor observation fraction" times={result.times} values={result.observedFraction} axis={axis} threshold={result.config.minCoverage ?? .9} color="#b4a0db" /></>}

    <section ref={detail} className="ws-interval-detail" tabIndex={-1} aria-label="Interval details and raw signals" hidden={summary.abstainedSamples === summary.analysisSamples}>
      <div className="ws-section-heading"><div><h3>{focused ? "Selected interval" : "Peak signal contributions"}</h3><p className="ws-muted">{focused ? `${timeLabel(axis, focused.start)} → ${timeLabel(axis, focused.end)} · peak at ` : "Highest-score sample · "}{peakTime !== undefined ? timeLabel(axis, peakTime) : ""}</p></div>
        {focused && <button type="button" className="ws-outlined" onClick={() => setFocused(null)}>Show full analysis window</button>}
      </div>
      <Contributions values={contributions} signals={related} metric={result.contributionMetric} />
      <p className="ws-muted">Missing target measurements use normal-fit medians ({summary.imputedValues.analysis} values filled).</p>
      {result.config.stress && ((result.config.stress.noise ?? 0) !== 0 || (result.config.stress.offset ?? 0) !== 0 || (result.config.stress.missingFraction ?? 0) > 0 || (result.config.stress.missingSignals?.length ?? 0) > 0) && <p className="ws-notice">Scores and coverage include the saved artificial perturbations. The raw curves below show the original dataset.</p>}
      {signalPicker(plotted, setPlotted)}
      <SignalPlots dataset={dataset} signals={plotted} range={range} intervals={result.intervals} />
    </section>

    <div className="ws-section-heading"><h3>Complete anomaly record</h3><span className="ws-muted">{result.intervals.length} intervals · chronological order</span></div>
    {result.intervals.length ? <div className="ws-table-scroll"><table><thead><tr><th>Start</th><th>End</th><th>Samples</th><th>Peak score</th><th>Related signals at peak</th><th>Curves</th></tr></thead><tbody>{(allIntervals ? result.intervals : result.intervals.slice(0, 30)).map((interval, i) => <tr key={i}><td>{timeLabel(axis, interval.start)}</td><td>{timeLabel(axis, interval.end)}</td><td>{interval.samples}</td><td className="ws-coral">{number(interval.peakScore)}</td><td>{interval.signals.join(" · ")}</td><td><button type="button" onClick={() => focus(interval)}>Inspect</button></td></tr>)}</tbody></table>{result.intervals.length > 30 && <button type="button" onClick={() => setAllIntervals(!allIntervals)}>{allIntervals ? "Show first 30" : `Show all ${result.intervals.length} intervals`}</button>}</div> : <p className="ws-notice">No confirmed alarm intervals. {summary.abstainedSamples ? `${summary.abstainedSamples} samples lack sufficient coverage and are excluded from normal/alarm decisions.` : "Observed scores did not meet the configured alarm rule."}</p>}
    <details><summary>Saved model and parameters</summary><pre>{JSON.stringify({ config: result.config, model: result.model, summary: result.summary }, null, 2)}</pre></details>
  </section>;
}
