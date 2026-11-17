import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { t as tr } from "../../lib/text";
import { errorMessage } from "../../lib/text";
import { api, message } from "../api";
import { Plot } from "../Charts";
import { cachedSeries } from "../seriesCache";
import { incidentAxis, namedSignal, number, timeLabel, type AnalysisResult, type Dataset, type IncidentAxis } from "../types";
import type { AlarmEvent } from "./alarmTypes";

export function alarmTime(axis: IncidentAxis, time: number) {
  return timeLabel(incidentAxis(axis), time);
}

function useAlarmAnalysis(analysisId: string) {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    setError("");
    api<AnalysisResult>(`/analyses/${analysisId}`, undefined, "GET", controller.signal)
      .then(setResult).catch(err => { if (!controller.signal.aborted) setError(message(err)); });
    return () => controller.abort();
  }, [analysisId]);
  return { result: result?.id === analysisId ? result : null, error };
}

export function AlarmEvidence({ event, dataset, axis, workspaceId }: {
  event: AlarmEvent; dataset?: Dataset; axis: IncidentAxis; workspaceId: string;
}) {
  const [at, setAt] = useState(event.peakTime);
  const [signal, setSignal] = useState(event.signals[0] || "");
  const { result, error } = useAlarmAnalysis(event.analysisId);
  const padding = Math.max(1, (event.durationSeconds || 0) * .2, (dataset?.metadata.time.typicalInterval || 0) * 3);
  const start = Math.max(dataset?.metadata.time.start ?? -Infinity, event.nativeStart - padding);
  const end = Math.min(dataset?.metadata.time.end ?? Infinity, event.nativeEnd + padding);
  const cache = useMemo(() => cachedSeries(event.datasetId, [start, end]), [event.datasetId, start, end]);
  useSyncExternalStore(cache.subscribe, cache.snapshot, cache.snapshot);
  const names = event.signals.length ? event.signals : result?.config.signals || [];
  const activeSignal = signal || names[0];
  useEffect(() => {
    if (activeSignal) void cache.load([activeSignal]);
  }, [cache, activeSignal]);
  const evidence = activeSignal && cache.signals.get(activeSignal);
  const measurementError = activeSignal && cache.errors.get(activeSignal);
  const alignedAxis = incidentAxis(axis);
  const timeDomain: [number, number] = start < end ? [start + event.offset, end + event.offset] : [event.start - 1, event.end + 1];
  const qualityGaps = dataset?.metadata.quality?.gaps.map(gap => ({ start: gap.start + event.offset, end: gap.end + event.offset }));
  const highlights = [{ start: event.start, end: event.end, samples: event.samples, peakScore: event.peakScore, peakTime: event.peakTime, signals: event.signals }];
  const scoreWindow = useMemo(() => {
    const times: number[] = [], values: (number | null)[] = [];
    result?.times.forEach((time, index) => {
      if (time < start || time > end) return;
      times.push(time + event.offset);
      values.push(result.states?.[index] === "abstain" ? null : result.scores[index] ?? null);
    });
    return { times, values };
  }, [result, start, end, event.offset]);
  return <section className="alarm-evidence" aria-label={"Measurement and detector evidence"}>
    <div className="alarm-section-heading"><h3>Measurement and detector evidence</h3><a className="ws-link" href={`#/workspaces/${workspaceId}/analysis/${event.analysisId}/${event.intervalIndex}`}>Open source analysis ↗</a></div>
    <div className="alarm-facts">
      <div><span>Peak score / threshold</span><strong>{number(event.peakScore)} / {number(event.threshold)}</strong><small>{tr("{0} above threshold", { 0: number(event.peakAboveThreshold) })}</small></div>
      <div><span>Alarm samples / duration</span><strong>{event.samples.toLocaleString("en")} / {number(event.durationSeconds)} s</strong></div>
      <div><span>Event observation coverage</span><strong>{event.observedFraction == null ? "—" : `${number(event.observedFraction * 100)}%`}</strong></div>
      <div><span>Analysis abstentions</span><strong>{event.quality.abstainedSamples?.toLocaleString("en") ?? "—"}</strong></div>
    </div>
    <p className="ws-muted">{tr("Observed segment {0} → {1}", { 0: alarmTime(axis, event.observedSpan[0]), 1: alarmTime(axis, event.observedSpan[1]) })}</p>
    {event.clearTime != null && <p className="ws-muted">{tr("First normal sample at {0}", { 0: alarmTime(axis, event.clearTime) })}</p>}
    {event.affectedSignals?.length > 0 && <p>Signals used for correlation{" · "}{event.affectedSignals.join(" · ")}</p>}
    {event.peakMagnitude != null && <p>Peak contribution magnitude{" · "}{number(event.peakMagnitude)}{event.provenance.contributionMetric && <> · {tr(event.provenance.contributionMetric)}</>}</p>}
    {!!event.contributions.length && <p>Detector contributions{" · "}{event.contributions.map(item => `${item.signal} ${number(item.value)}`).join(" · ")}
      {event.nativeContributionTime != null && event.nativeContributionTime !== event.nativePeakTime && <> · {tr("Recorded at {0}", { 0: alarmTime(axis, event.nativeContributionTime + event.offset) })}</>}</p>}
    {error && <p role="alert" className="ws-error">{errorMessage(error)}</p>}
    {!result && !error && <p role="status">Loading detector evidence…</p>}
    <p className="ws-muted">{tr("Cursor at {0}. Select a chart to move both cursors.", { 0: alarmTime(axis, at) })}</p>
    <Plot {...scoreWindow} title={"Detector score"} axis={alignedAxis} threshold={event.threshold}
      intervals={highlights} timeDomain={timeDomain} gaps={qualityGaps} selectedTime={at} onSelectTime={setAt} />
    {names.length > 0 && <label className="alarm-signal-choice">Measurement signal
      <select value={activeSignal} onChange={e => setSignal(e.target.value)}>{names.map(name => <option key={name} value={name}>{dataset ? namedSignal(dataset, name) : name}</option>)}</select>
    </label>}
    {evidence ? <Plot times={evidence.times.map(time => time + event.offset)} values={evidence.values} segmentIds={evidence.segmentIds}
      title={dataset ? namedSignal(dataset, activeSignal) : activeSignal} axis={alignedAxis} intervals={highlights}
      timeDomain={timeDomain} gaps={qualityGaps} selectedTime={at} onSelectTime={setAt} />
      : measurementError ? <div role="alert" className="ws-error">{errorMessage(measurementError)} <button onClick={() => void cache.load([activeSignal], true)}>Retry signal</button></div>
      : activeSignal && <p role="status">Loading measurement evidence…</p>}
  </section>;
}
