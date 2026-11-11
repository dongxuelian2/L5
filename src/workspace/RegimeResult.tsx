import { useMemo, useState, type ReactNode } from "react";
import { t as tr, useLocale } from "../i18n";
import { downloadFile } from "../lib/download";
import { Plot } from "./Charts";
import { IncidentLinkDialog } from "./IncidentLinkDialog";
import { modeLabel, RegimeModelView, regimeColors } from "./RegimeModelView";
import type { RegimeApproach, RegimeDecision, RegimeRun, RegimeStatus, RegimeTransition } from "./regimeTypes";
import { namedSignal, number, timeLabel, type TimeAxis } from "./types";

const approaches: RegimeApproach[] = ["regime", "global", "single"];
const approachLabels: Record<RegimeApproach, string> = { regime: "Regime-aware", global: "Global detector", single: "Single-mode detector" };
const approachColors: Record<RegimeApproach, string> = { regime: "#b5ed9a", global: "#8cbfe8", single: "#c6a5e0" };
const statusLabels: Record<RegimeStatus, string> = { normal: "Normal", transition: "Transition", abnormal: "Abnormal", unknown: "Unknown" };
const statusColors: Record<RegimeStatus, string> = { normal: "#79a46a", transition: "#e4bb75", abnormal: "#e9927d", unknown: "#84918d" };
const outcomeLabels: Record<RegimeTransition["outcome"], string> = { confirmed: "Confirmed change", transient: "Transient candidate", pending: "Pending at window end" };

function nearestIndex(times: number[], target: number) {
  let low = 0, high = times.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (times[middle] < target) low = middle + 1;
    else high = middle;
  }
  return low > 0 && Math.abs(times[low - 1] - target) <= Math.abs(times[low] - target) ? low - 1 : low;
}

function display(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? "—" : number(value);
}

function fraction(value: number | null) {
  return value === null ? "—" : `${number(value * 100)}%`;
}

function DetectorComparison({ run }: { run: RegimeRun }) {
  return <section className="ws-panel regime-comparison">
    <h2>{tr("Detector comparison")}</h2>
    <p>{run.labelSet
      ? tr("Fault metrics use {0} v{1} after scoring. Unlabelled and unscored samples remain visible in the coverage counts.", { 0: run.labelSet.name, 1: run.labelSet.version })
      : tr("This run reports alarm burden and coverage. Add evaluation labels to measure false alarms and missed faults.")}</p>
    <div className="ws-table-scroll"><table>
      <thead><tr><th>{tr("Approach")}</th><th>{tr("Samples with monitoring decisions")}</th><th>{tr("Alarm samples")}</th><th>{tr("Alarm episodes")}</th><th>{tr("Alarm share of monitoring decisions")}</th>{run.labelSet && <>
        <th>{tr("Normal false alarm rate")}</th><th>{tr("Detected fault events")}</th><th>{tr("Missed events")}</th><th>{tr("Unobserved events")}</th><th>{tr("First detection delay (s)")}</th>
      </>}</tr></thead>
      <tbody>{approaches.map(key => {
        const { behavior, detection, labelled } = run.metrics[key];
        const eventual = detection.windows?.eventual;
        return <tr key={key}><th scope="row"><i className="regime-swatch" style={{ background: approachColors[key] }} />{tr(approachLabels[key])}</th>
          <td>{behavior.validSamples.toLocaleString()} / {behavior.totalSamples.toLocaleString()}</td><td>{behavior.alarmSamples.toLocaleString()}</td><td>{behavior.alarmIntervalCount.toLocaleString()}</td><td>{fraction(behavior.alarmFraction)}</td>
          {run.labelSet && <><td>{fraction(labelled?.sample.falseAlarmRate ?? null)}</td><td>{eventual ? `${eventual.detectedEvents} / ${eventual.totalEvents}` : "—"}</td><td>{eventual ? eventual.totalEvents - eventual.detectedEvents : "—"}</td><td>{eventual?.unobservedEvents ?? "—"}</td><td>{display(labelled?.event.firstDetectionDelay)}</td></>}
        </tr>;
      })}</tbody>
    </table></div>
    <p className="ws-muted">{tr("Single-mode reference")} {modeLabel(run.model, run.model.config.recognition.referenceMode)}</p>
  </section>;
}

type Band = { start: number; end: number; key: string; color: string; label: string };

function bands(decisions: RegimeDecision[], describe: (row: RegimeDecision) => Pick<Band, "key" | "label" | "color">, gap: number | null) {
  const output: Band[] = [];
  for (let i = 0; i < decisions.length; i++) {
    const row = decisions[i], before = decisions[i - 1], after = decisions[i + 1];
    const description = describe(row);
    const nearBefore = before && (gap === null || row.time - before.time <= gap);
    const nearAfter = after && (gap === null || after.time - row.time <= gap);
    const start = nearBefore ? before.time + (row.time - before.time) / 2 : row.time;
    const end = nearAfter ? row.time + (after.time - row.time) / 2 : row.time;
    const last = output[output.length - 1];
    if (last?.key === description.key && nearBefore) last.end = end;
    else output.push({ ...description, start, end });
  }
  return output;
}

function ModeTimeline({ run, rows, axis, selected, onSelectTime }: {
  run: RegimeRun; rows: RegimeDecision[]; axis: TimeAxis; selected: number; onSelectTime: (time: number) => void;
}) {
  const [first, last] = [rows[0].time, rows[rows.length - 1].time];
  const x = (time: number) => 76 + (time - first) * 866 / (last - first || 1);
  const locale = useLocale();
  const modeColors = useMemo(() => new Map(run.model.config.modes.map((mode, i) => [mode.id, regimeColors[i % regimeColors.length]])), [run.model]);
  const tracks = useMemo(() => {
    const modeBands = bands(rows, row => {
      const id = row.mode;
      return { key: id ? `mode:${id}` : "unconfirmed", label: id ? modeLabel(run.model, id) : tr("Unconfirmed mode"), color: modeColors.get(id ?? "") ?? "#4c5953" };
    }, run.gapThreshold);
    const stateBands = bands(rows, row => ({ key: row.status, color: statusColors[row.status], label: tr(statusLabels[row.status]) }), run.gapThreshold);
    return [modeBands, stateBands];
  }, [rows, run, modeColors, locale]);
  return <div className="regime-mode-timeline">
    <div className="regime-legend">{run.model.config.modes.map(mode => <span key={mode.id}><i className="regime-swatch" style={{ background: modeColors.get(mode.id) }} />{mode.label}</span>)}<span><i className="regime-swatch regime-unconfirmed" />{tr("Unconfirmed mode")}</span></div>
    <svg viewBox="0 0 960 82" role="img" aria-label={tr("Recognized modes and monitoring status over time")} onClick={e => {
      const rect = e.currentTarget.getBoundingClientRect();
      if (rect.width > 0) {
        const proportion = ((e.clientX - rect.left) * 960 / rect.width - 76) / 866;
        onSelectTime(first + Math.max(0, Math.min(1, proportion)) * (last - first));
      }
    }}>
      <text x="2" y="22">{tr("Mode")}</text><text x="2" y="50">{tr("Status")}</text>
      {tracks.map((track, lane) => <g key={lane}>
        <rect x="76" y={8 + lane * 28} width="866" height="20" rx="2" fill="#1b231b" />
        {track.map((band, i) => <rect key={i} x={x(band.start)} y={8 + lane * 28} width={Math.max(1, x(band.end) - x(band.start))} height="20" fill={band.color}><title>{band.label} · {timeLabel(axis, band.start)} – {timeLabel(axis, band.end)}</title></rect>)}
      </g>)}
      <line x1={x(selected)} x2={x(selected)} y1="4" y2="60" stroke="#f9f6e8" strokeWidth="2" strokeDasharray="3 2" />
      <text x="76" y="75">{timeLabel(axis, first)}</text><text x="942" y="75" textAnchor="end">{timeLabel(axis, last)}</text>
    </svg>
    <div className="regime-legend">{(Object.keys(statusColors) as RegimeStatus[]).map(status => <span key={status}><i className="regime-swatch" style={{ background: statusColors[status] }} />{tr(statusLabels[status])}</span>)}</div>
  </div>;
}

function DecisionEvidence({ run, row }: { run: RegimeRun; row: RegimeDecision }) {
  const recognitionLabels = { supported: "Supported", ambiguous: "Ambiguous", unknown: "Outside normal support", insufficient: "Insufficient measurements" };
  const evidence = Object.entries(row.evidence);
  return <section className="regime-evidence" aria-label={tr("Classification evidence")}>
    <div className="regime-heading"><h3>{tr("Classification evidence")}</h3><span className="regime-status" style={{ color: statusColors[row.status] }}>{tr(statusLabels[row.status])}</span></div>
    <dl className="regime-decision-grid">
      <div><dt>{tr("Recognized mode")}</dt><dd>{modeLabel(run.model, row.mode)}</dd></div>
      <div><dt>{tr("Last confirmed mode")}</dt><dd>{modeLabel(run.model, row.activeMode)}</dd></div>
      <div><dt>{tr("Candidate mode")}</dt><dd>{modeLabel(run.model, row.candidateMode)}{row.candidateSamples > 0 ? ` · ${row.candidateSamples}/${run.model.config.recognition.dwell}` : ""}</dd></div>
      <div><dt>{tr("Recognition evidence")}</dt><dd>{tr(recognitionLabels[row.recognition])}</dd></div>
      <div><dt>{tr("Discriminant margin")}</dt><dd>{display(row.margin)}</dd></div>
      <div><dt>{tr("Scoring mode")}</dt><dd>{modeLabel(run.model, row.scoringMode)}</dd></div>
      <div><dt>{tr("Transition in progress")}</dt><dd>{tr(row.transition ? "Yes" : "No")}</dd></div>
      <div><dt>{tr("Alarm")}</dt><dd>{tr(row.alarm ? "Yes" : "No")}</dd></div>
    </dl>
    {evidence.length > 0 && <div className="ws-table-scroll"><table>
      <thead><tr><th>{tr("Mode")}</th><th>{tr("Squared distance")}</th><th>{tr("Support distance limit")}</th><th>{tr("Discriminant")}</th><th>{tr("Inside support")}</th></tr></thead>
      <tbody>{evidence.map(([id, item]) => <tr key={id}><th scope="row">{modeLabel(run.model, id)}</th><td>{display(item.distance)}</td><td>{display(item.threshold)}</td><td>{display(item.discriminant)}</td><td>{tr(item.supported ? "Yes" : "No")}</td></tr>)}</tbody>
    </table></div>}
    <div className="ws-table-scroll"><table>
      <thead><tr><th>{tr("Approach")}</th><th>{tr("Score")}</th><th>{tr("Threshold")}</th><th>{tr("Alarm")}</th></tr></thead>
      <tbody>{([[row.score, row.threshold, row.alarm], [row.globalScore, row.globalThreshold, row.globalAlarm], [row.singleScore, row.singleThreshold, row.singleAlarm]] as const).map(([score, limit, alarm], i) =>
        <tr key={approaches[i]}><th scope="row">{tr(approachLabels[approaches[i]])}</th><td>{display(score)}</td><td>{display(limit)}</td><td>{tr(alarm ? "Yes" : "No")}</td></tr>)}</tbody>
    </table></div>
  </section>;
}

function RegimeTable({ title, headers, count, renderRow, empty, description }: {
  title: string; headers: string[]; count: number; renderRow: (index: number) => ReactNode; empty: string; description?: string;
}) {
  const [page, setPage] = useState(0);
  const perPage = 10, start = page * perPage, end = Math.min(count, start + perPage);
  return <section className="ws-panel regime-event-panel">
    <div className="regime-heading"><h2>{title}</h2><span className="ws-muted">{count.toLocaleString()}</span></div>
    {count ? <>
      {description && <p>{description}</p>}
      <div className="ws-table-scroll"><table>
        <thead><tr>{headers.map((header, i) => <th key={i}>{header}</th>)}</tr></thead>
        <tbody>{Array.from({ length: end - start }, (_, i) => renderRow(start + i))}</tbody>
      </table></div>
      {count > perPage && <div className="regime-actions">
        <button type="button" className="ws-outlined" disabled={page === 0} onClick={() => setPage(page - 1)}>{tr("Previous")}</button>
        <span>{tr("{0}–{1} of {2}", { 0: start + 1, 1: end, 2: count })}</span>
        <button type="button" className="ws-outlined" disabled={end >= count} onClick={() => setPage(page + 1)}>{tr("Next")}</button>
      </div>}
    </> : <p>{empty}</p>}
  </section>;
}

export function RegimeResult({ run, workspaceId, initialIntervalIndex }: { run: RegimeRun; workspaceId: string; initialIntervalIndex?: number }) {
  const locale = useLocale();
  const { times, source } = run, axis = source.metadata.time;
  const initialInterval = initialIntervalIndex === undefined ? undefined : run.intervals[initialIntervalIndex];
  const firstFocus = initialInterval ? nearestIndex(times, initialInterval.peakTime) : 0;
  const [selected, setSelected] = useState(firstFocus);
  const [window, setWindow] = useState<[number, number]>(() => initialInterval ? [Math.max(0, nearestIndex(times, initialInterval.start) - 20), Math.min(times.length - 1, nearestIndex(times, initialInterval.end) + 20)] : [0, times.length - 1]);
  const [signal, setSignal] = useState(initialInterval?.signals[0] ?? run.model.config.recognition.recognitionSignals[0]);
  const [focusedTransition, setFocusedTransition] = useState<RegimeTransition | null>(null);
  const [linking, setLinking] = useState<number | null>(null);
  const row = run.decisions[selected], selectedTime = times[selected];
  const [left, right] = window;
  const timeDomain: [number, number] = [times[left], times[right]];
  const zoomed = left !== 0 || right !== times.length - 1;
  const counts = useMemo(() => run.decisions.reduce((summary, decision) => {
    if (decision.status === "normal") summary.normal++;
    if (decision.mode === null) summary.unconfirmed++;
    return summary;
  }, { normal: 0, unconfirmed: 0 }), [run.decisions]);
  const visibleTimes = useMemo(() => times.slice(left, right + 1), [times, left, right]);
  const visibleRows = useMemo(() => run.decisions.slice(left, right + 1), [run.decisions, left, right]);
  const signalValues = useMemo(() => run.series.values[signal]?.slice(left, right + 1), [run.series, signal, left, right]);
  const { plottedScores, segmentIds } = useMemo(() => {
    const scale = (score: number | null, threshold: number | null) => score === null || threshold === null ? null : Math.log1p(score) - Math.log1p(threshold);
    let segment = 0;
    return {
      plottedScores: {
        regime: visibleRows.map(item => scale(item.score, item.threshold)),
        global: visibleRows.map(item => scale(item.globalScore, item.globalThreshold)),
        single: visibleRows.map(item => scale(item.singleScore, item.singleThreshold)),
      },
      segmentIds: visibleTimes.map((time, i) => {
        if (i > 0 && run.gapThreshold !== null && time - visibleTimes[i - 1] > run.gapThreshold) segment++;
        return segment;
      }),
    };
  }, [visibleRows, visibleTimes, run.gapThreshold]);
  const hasScore = plottedScores.regime.some(value => value !== null);
  const primary = hasScore ? "regime" : approaches.find(key => plottedScores[key].some(value => value !== null)) ?? "regime";
  const markers = focusedTransition ? [
    { time: focusedTransition.candidateTime, label: tr(focusedTransition.candidateTime === focusedTransition.confirmedTime ? "Candidate and confirmation" : "Candidate") },
    ...(focusedTransition.confirmedTime === null || focusedTransition.confirmedTime === focusedTransition.candidateTime ? []
      : [{ time: focusedTransition.confirmedTime, label: tr("Confirmation") }]),
  ] : [];
  const transitionsConfirmed = run.transitions.filter(event => event.outcome === "confirmed").length;
  function chooseTime(time: number) { setSelected(nearestIndex(times, time)); }
  function focus(start: number, end: number, time: number) {
    setWindow([Math.max(0, nearestIndex(times, start) - 20), Math.min(times.length - 1, nearestIndex(times, end) + 20)]);
    chooseTime(time);
    document.getElementById("regime-observation")?.scrollIntoView({ block: "start" });
  }
  const linked = linking === null ? null : run.intervals[linking];
  const selectedAlarm = row.alarm ? run.intervals.find(interval => selectedTime >= interval.start && selectedTime <= interval.end) : undefined;
  return <div className="regime-result">
    <section className="ws-panel regime-run-overview">
      <div className="regime-heading"><div><h2>{run.name}</h2><p>{source.name} · {timeLabel(axis, times[0])} → {timeLabel(axis, times[times.length - 1])}</p></div>
        <div className="regime-actions">
          <a className="ws-link" href={`/api/workspaces/${workspaceId}/regimes/runs/${run.id}/report.html?lang=${locale}`} target="_blank" rel="noreferrer">{tr("Open saved report ↗")}</a>
          <button className="ws-outlined" type="button" onClick={() => downloadFile(`l5-regime-${run.id}.json`, JSON.stringify(run, null, 2))}>{tr("Export result JSON ↓")}</button>
        </div>
      </div>
      <div className="regime-overview-stats">
        <div><strong>{counts.normal.toLocaleString()}</strong><span>{tr("Normal samples")}</span></div>
        <div><strong>{transitionsConfirmed.toLocaleString()}</strong><span>{tr("Confirmed changes")}</span></div>
        <div><strong>{run.intervals.length.toLocaleString()}</strong><span>{tr("Alarm intervals")}</span></div>
        <div><strong>{counts.unconfirmed.toLocaleString()}</strong><span>{tr("Unconfirmed mode samples")}</span></div>
      </div>
      <p className="ws-muted">{tr(run.protocol === "chronological-holdout" ? "Chronological holdout within a training source" : "Evaluation on a distinct dataset")} · <a className="ws-link" href={`#/workspaces/${workspaceId}/regimes/models/${run.modelId}`}>{run.model.name} ↗</a></p>
    </section>
    <section id="regime-observation" className="ws-panel regime-observation">
      <div className="regime-heading"><h2>{tr("Synchronized monitoring history")}</h2>
        {zoomed && <button className="ws-outlined" type="button" onClick={() => { setWindow([0, times.length - 1]); setFocusedTransition(null); }}>{tr("Show full evaluation window")}</button>}
      </div>
      <ModeTimeline run={run} rows={visibleRows} axis={axis} selected={selectedTime} onSelectTime={chooseTime} />
      <div className="regime-cursor">
        <label>{tr("Observation cursor")}<input type="range" min={left} max={right} step={1} value={selected} onChange={e => setSelected(Number(e.target.value))} /></label>
        <output aria-live="polite">{timeLabel(axis, selectedTime)} · {tr("Sample {0}", { 0: (selected + 1).toLocaleString() })}</output>
      </div>
      <div className="regime-chart">
        <label>{tr("Process signal")}<select value={signal} onChange={e => setSignal(e.target.value)}>{run.model.config.signals.map(name => <option key={name} value={name}>{namedSignal(source, name)}</option>)}</select></label>
        <div className="regime-current-value"><span>{tr("Observed value")}</span><strong>{display(run.series.values[signal]?.[selected])}</strong></div>
      </div>
      {signalValues && <Plot title={namedSignal(source, signal)} times={visibleTimes} values={signalValues} axis={axis} timeDomain={timeDomain} segmentIds={segmentIds} selectedTime={selectedTime} onSelectTime={chooseTime} intervals={run.intervals} markers={markers} />}
      <div className="regime-legend">{approaches.map(key => <span key={key}><i className="regime-swatch" style={{ background: approachColors[key] }} />{tr(approachLabels[key])}</span>)}</div>
      <Plot title={tr("Log-score relative to each active threshold")} times={visibleTimes} values={plottedScores[primary]} axis={axis} timeDomain={timeDomain}
        segmentIds={segmentIds} color={approachColors[primary]} threshold={0} thresholdLabel={tr("Alarm limit")}
        selectedTime={selectedTime} onSelectTime={chooseTime} intervals={run.intervals} markers={markers}
        overlays={approaches.filter(key => key !== primary).map(key => ({ times: visibleTimes, values: plottedScores[key], segmentIds, title: tr(approachLabels[key]), color: approachColors[key] }))} />
      <DecisionEvidence run={run} row={row} />
      {selectedAlarm?.contributions?.length ? <section className="regime-evidence" aria-label={tr("Alarm peak evidence")}>
        <h3>{tr("Alarm peak evidence")}</h3><p>{tr("Signal contributions at {0}", { 0: timeLabel(axis, selectedAlarm.peakTime) })}</p>
        <div className="ws-table-scroll"><table><thead><tr><th>{tr("Signal")}</th><th>{tr("Contribution")}</th></tr></thead>
          <tbody>{selectedAlarm.contributions.slice(0, 5).map(item => <tr key={item.signal}><th scope="row">{namedSignal(source, item.signal)}</th><td>{display(item.value)}</td></tr>)}</tbody></table></div>
      </section> : null}
    </section>
    <DetectorComparison run={run} />
    <RegimeTable title={tr("Candidate and confirmed transitions")} count={run.transitions.length} empty={tr("No candidate changes were recorded in this window.")}
      description={tr("First departure marks the earliest observed break from the prior mode. Confirmation follows sustained support for the candidate.")}
      headers={[tr("Mode change"), tr("First departure"), tr("Candidate time"), tr("Confirmation time"), tr("Confirmation delay (s)"), tr("Initial margin"), tr("Outcome"), tr("Decision")]}
      renderRow={index => {
        const event = run.transitions[index];
        return <tr key={index}><th scope="row">{modeLabel(run.model, event.fromMode)} → {modeLabel(run.model, event.toMode)}</th>
          <td>{timeLabel(axis, event.startTime)}</td><td>{timeLabel(axis, event.candidateTime)}</td><td>{event.confirmedTime === null ? "—" : timeLabel(axis, event.confirmedTime)}</td>
          <td>{event.confirmedTime === null ? "—" : display(event.confirmedTime - event.startTime)}</td><td>{display(event.initialMargin)}</td><td>{tr(outcomeLabels[event.outcome])}</td>
          <td><button type="button" className="ws-outlined" onClick={() => { setFocusedTransition(event); focus(event.startTime, event.resolvedTime ?? event.endTime ?? event.candidateTime, event.candidateTime); }}>{tr("Inspect transition")}</button></td></tr>;
      }} />
    <RegimeTable title={tr("Regime-aware alarm intervals")} count={run.intervals.length} empty={tr("No regime-aware alarms were raised in this window.")}
      headers={[tr("Window"), tr("Alarm context"), tr("Samples"), tr("Peak score"), tr("Evidence"), tr("Incident")]}
      renderRow={index => {
        const interval = run.intervals[index];
        const context = interval.kind === "transition" ? tr("Transition") : interval.kind === "unknown" ? tr("Unknown") : modeLabel(run.model, interval.mode ?? null);
        return <tr key={index}><th scope="row">{timeLabel(axis, interval.start)} → {timeLabel(axis, interval.end)}</th><td>{context}</td><td>{interval.samples.toLocaleString()}</td><td>{display(interval.peakScore)}</td>
          <td><button type="button" className="ws-outlined" onClick={() => { setFocusedTransition(null); if (interval.signals[0]) setSignal(interval.signals[0]); focus(interval.start, interval.end, interval.peakTime); }}>{tr("Inspect alarm")}</button></td>
          <td><button type="button" className="ws-outlined" onClick={() => setLinking(index)}>{tr("Link to incident")}</button></td></tr>;
      }} />
    <RegimeModelView model={run.model} datasets={Object.values(run.model.sources)} />
    {linked && linking !== null && <IncidentLinkDialog workspaceId={workspaceId} source={{ kind: "interval", datasetId: run.datasetId, analysisId: run.analysisId, intervalIndex: linking }}
      draft={{ title: tr("{0} · regime-monitoring alarm", { 0: source.name }), start: linked.start, end: linked.end, origin: axis.origin,
        description: tr("Run {0}. Peak at {1}; monitored signals {2}.", { 0: run.name, 1: timeLabel(axis, linked.peakTime), 2: linked.signals.map(name => namedSignal(source, name)).join(", ") }) }}
      onClose={() => setLinking(null)} />}
  </div>;
}
