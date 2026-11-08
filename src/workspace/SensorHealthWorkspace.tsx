import { useEffect, useRef, useState, type FormEvent } from "react";
import { t, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { api, go, message } from "./api";
import { Plot } from "./Charts";
import { IncidentLinkDialog } from "./IncidentLinkDialog";
import { dateLabel, namedSignal, number, timeLabel, type Dataset, type Interval } from "./types";
import type { HealthConfig, HealthEpisode, HealthHistory, HealthResult, SensorRelationship, TankDiagnosticModel } from "./sensorHealthTypes";
import "./sensor-health.css";

const roles = ["level1", "level2", "inlet", "transfer", "outlet", "pump", "valve"];
const parameters = { area1: 1, area2: 1, connection: .04, outlet: .03, outletValve: 1, pumpRate: .03, tankHeight: 2.5 };
export function newHealthConfig(dataset: Dataset): HealthConfig {
  const { start, end } = dataset.metadata.time, step = (end-start)/Math.max(1, dataset.metadata.rowCount-1);
  // User must declare normal; do not use simulator onset or ground-truth ranges.
  const baselineEnd = Math.min(end-step, start+Math.max(step*89, (end-start)*.15));
  return { signals: dataset.metadata.columns.slice(0, 24).map(s => s.name), baselineRange: [start, baselineEnd], analysisRange: [baselineEnd+step, end], window: 21, persistence: 3, z: 6, relationships: [] };
}

export function SensorHealthWorkspace({ workspaceId, datasets, diagnosticId, onChanged }: { workspaceId: string; datasets: Dataset[]; diagnosticId?: string; onChanged: () => void }) {
  useLocale();
  const [selected, setSelected] = useState(datasets[0]?.id || ""), [config, setConfig] = useState<HealthConfig | null>(datasets[0] ? newHealthConfig(datasets[0]) : null);
  const [history, setHistory] = useState<HealthHistory[]>([]), [result, setResult] = useState<HealthResult | null>(null), [defaults, setDefaults] = useState<TankDiagnosticModel | null>(null);
  const [normalConfirmed, setNormalConfirmed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(""), [revision, setRevision] = useState(0);
  const dataset = datasets.find(d => d.id === selected);
  const mounted = useRef(true), route = useRef(diagnosticId);
  route.current = diagnosticId;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (!selected && datasets[0]) { setSelected(datasets[0].id); setConfig(newHealthConfig(datasets[0])); } }, [datasets, selected]);
  useEffect(() => {
    const controller = new AbortController();
    api<{ diagnostics: HealthHistory[] }>(`/workspaces/${workspaceId}/sensor-health`, undefined, "GET", controller.signal).then(r => setHistory(r.diagnostics)).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [workspaceId, revision]);
  useEffect(() => {
    setDefaults(null);
    if (!selected) return;
    const controller = new AbortController();
    api<{ model: TankDiagnosticModel | null }>(`/datasets/${selected}/sensor-model`, undefined, "GET", controller.signal).then(r => { if (!controller.signal.aborted) setDefaults(r.model); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [selected]);
  useEffect(() => {
    setResult(null); setError("");
    if (!diagnosticId) return;
    const controller = new AbortController();
    api<HealthResult>(`/sensor-health/${diagnosticId}`, undefined, "GET", controller.signal).then(r => {
      if (r.workspaceId !== workspaceId) throw new Error("Sensor diagnostic belongs to a different workspace.");
      if (!controller.signal.aborted) setResult(r);
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [diagnosticId, workspaceId]);
  function choose(id: string) {
    const next = datasets.find(d => d.id === id);
    setSelected(id); setConfig(next ? newHealthConfig(next) : null); setNormalConfirmed(false);
  }
  async function run(e: FormEvent) {
    e.preventDefault(); if (!config || !dataset || !normalConfirmed) return;
    const startedRoute = route.current;
    setBusy(true); setError("");
    try {
      const saved = await api<HealthResult>(`/workspaces/${workspaceId}/sensor-health`, { datasetId: dataset.id, ...config });
      if (!mounted.current || route.current !== startedRoute) return;
      setResult(saved); setRevision(v => v+1); onChanged(); go(`workspaces/${workspaceId}/sensor-health/${saved.id}`);
    } catch (e) { if (mounted.current && route.current === startedRoute) setError(message(e)); } finally { if (mounted.current) setBusy(false); }
  }
  function patch(value: Partial<HealthConfig>) { setConfig(c => c && ({ ...c, ...value })); }
  async function importSimulation(id: string) {
    if (!id) return; setBusy(true); setError("");
    try {
      const saved = await api<Dataset>(`/simulations/${id}/save`, { workspaceId });
      if (!mounted.current) return;
      onChanged(); setSelected(saved.id); setConfig(newHealthConfig(saved)); setNormalConfirmed(false);
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <div className="health-workspace">
    <div className="ws-page-title"><div><div className="ws-kicker">{t("MEASUREMENT / PROCESS / EVIDENCE")}</div><h1>{t("Sensor health")}<span className="ws-accent">.</span></h1><p>{t("Investigate sensor integrity and compare physical fault explanations.")}</p></div><span className="ws-badge">{t("Reference-based diagnostics")}</span></div>
    <div className="ws-inline health-links"><a href={`#/workspaces/${workspaceId}/models`}>{t("Open process simulator ↗")}</a><SimulationPicker workspaceId={workspaceId} disabled={busy} onSelect={importSimulation} /></div>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    <details className="ws-panel" open={!result}><summary>{t("Diagnostic configuration")}</summary>
      {!dataset || !config ? <p>{t("Import a dataset or save a simulation to begin.")}</p> : <form onSubmit={run}>
        <label>{t("Dataset")}<select value={selected} onChange={e => choose(e.target.value)} disabled={busy}>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        <fieldset className="health-signals"><legend>{t("Analysis signals")}</legend>{dataset.metadata.columns.map(s => <label key={s.name}><input type="checkbox" checked={config.signals.includes(s.name)} onChange={e => patch({ signals: e.target.checked ? [...config.signals, s.name] : config.signals.filter(n => n !== s.name) })} />{s.displayName || s.name}{s.unit ? ` (${s.unit})` : ""}</label>)}</fieldset>
        <div className="ws-form-grid">{(["baselineRange", "analysisRange"] as const).map(key => <fieldset key={key}><legend>{t(key === "baselineRange" ? "Normal reference interval (seconds)" : "Analysis interval (seconds)")}</legend>{([0, 1] as const).map(i => <label key={i}>{t(i === 0 ? "Start" : "End")}<input type="number" step="any" required value={config[key][i]} onChange={e => { const range = [...config[key]] as [number, number]; range[i] = Number(e.target.value); patch({ [key]: range }); setNormalConfirmed(false); }} /></label>)}</fieldset>)}</div>
        <label className="health-confirm"><input type="checkbox" checked={normalConfirmed} onChange={e => setNormalConfirmed(e.target.checked)} />{t("I declare this reference interval to be normal operation.")}</label>
        <p className="ws-muted">{t("The reference needs at least max(90, 3 × window) samples. Thresholds use a chronological 70% fit / 30% calibration split.")}</p>
        <div className="ws-form-grid">{(["window", "persistence", "z"] as const).map(key => <label key={key}>{t(key === "window" ? "Window samples" : key === "persistence" ? "Consecutive exceedances" : "Threshold multiplier")}<input type="number" step={key === "z" ? "any" : 1} min={key === "z" ? 3 : key === "window" ? 5 : 1} max={key === "z" ? 12 : key === "window" ? 101 : 20} required value={config[key]} onChange={e => patch({ [key]: Number(e.target.value) })} /></label>)}</div>
        <RelationshipEditor signals={config.signals} relationships={config.relationships} onChange={relationships => patch({ relationships })} />
        <label>{t("Physical reference")}<select value={config.model ? "coupled-tanks" : "none"} onChange={e => patch({ model: e.target.value === "none" ? undefined : defaults || { kind: "coupled-tanks", mapping: Object.fromEntries(roles.map(k => [k, ""])), parameters } })}><option value="none">{t("Integrity and declared relationships only")}</option><option value="coupled-tanks">{t("Coupled-tank constraints")}</option></select></label>
        {config.model && <details className="health-model" open><summary>{t("Signal mapping and nominal physical parameters")}</summary><p className="ws-muted">{t("Use independent flow measurements and known geometry. Simulator fault labels, onset and severity are excluded.")}</p><p className="ws-muted">{t("Levels: m · flows: m³/s · pump command: % · opening: fraction. Convert incompatible units in Transformations first.")}</p><div className="ws-form-grid">{roles.map(role => <label key={role}>{t(role === "outlet" ? "Outlet flow (m³/s)" : role)}<select required value={config.model!.mapping[role] || ""} onChange={e => patch({ model: { ...config.model!, mapping: { ...config.model!.mapping, [role]: e.target.value } } })}><option value="">{t("Choose signal")}</option>{config.signals.map(s => <option key={s} value={s}>{s}</option>)}</select></label>)}</div><div className="ws-form-grid">{Object.entries(config.model.parameters).map(([key, value]) => <label key={key}>{t(key === "outlet" ? "Outlet discharge coefficient (m^(5/2)/s)" : key)}<input type="number" step="any" min={.000001} required value={value} onChange={e => patch({ model: { ...config.model!, parameters: { ...config.model!.parameters, [key]: Number(e.target.value) } } })} /></label>)}</div></details>}
        <button className="ws-primary" disabled={busy || !normalConfirmed || !config.signals.length}>{busy ? t("Computing diagnostics…") : t("Run and save diagnostics")}</button>
      </form>}
    </details>
    {result && <SensorHealthResult key={result.id} result={result} dataset={datasets.find(d => d.id === result.datasetId)} />}
    <section className="ws-panel"><h2>{t("Saved diagnostics")}</h2>{history.length ? <div className="ws-history">{history.map(h => <a className="ws-history-row" key={h.id} href={`#/workspaces/${workspaceId}/sensor-health/${h.id}`} aria-current={h.id === result?.id ? "page" : undefined}><div><strong>{h.name}</strong><p>{dateLabel(h.created_at)}</p></div><span>{h.summary.episodes} {t("fault intervals")} ↗</span></a>)}</div> : <p className="ws-muted">{t("No saved sensor diagnostics yet.")}</p>}</section>
  </div>;
}

function SimulationPicker({ workspaceId, disabled, onSelect }: { workspaceId: string; disabled: boolean; onSelect: (id: string) => void }) {
  const [sessions, setSessions] = useState<{ id: string; title: string }[]>([]), [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<{ simulations: { id: string; title: string }[] }>(`/simulations?workspaceId=${workspaceId}`, undefined, "GET", controller.signal).then(r => setSessions(r.simulations)).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [workspaceId]);
  return <label>{t("Use existing simulation")}<select value="" onChange={e => onSelect(e.target.value)} disabled={disabled}><option value="">{t("Select simulation to save as dataset")}</option>{sessions.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select>{error && <span role="alert">{errorMessage(error)}</span>}</label>;
}

function RelationshipEditor({ signals, relationships, onChange }: { signals: string[]; relationships: SensorRelationship[]; onChange: (r: SensorRelationship[]) => void }) {
  return <fieldset><legend>{t("Declared cross-signal relationships")}</legend><p className="ws-muted">{t("Agreement compares redundant measurements after normal offset calibration. Linear prediction is fitted on the reference. Neither identifies the faulty channel alone.")}</p>{relationships.map((r, i) => <div className="ws-inline health-relationship" key={i}><select aria-label={t("Relationship method")} value={r.kind} onChange={e => onChange(relationships.map((v, j) => i === j ? { ...v, kind: e.target.value as SensorRelationship["kind"] } : v))}><option value="agreement">{t("Redundant agreement")}</option><option value="linear">{t("Baseline linear prediction")}</option></select>{(["target", "predictor"] as const).map(role => <label key={role}>{t(role)}<select value={r[role]} onChange={e => onChange(relationships.map((v, j) => i === j ? { ...v, [role]: e.target.value } : v))}>{signals.map(s => <option key={s} value={s}>{s}</option>)}</select></label>)}<button type="button" onClick={() => onChange(relationships.filter((_, j) => i !== j))}>{t("Remove")}</button></div>)}<button type="button" disabled={signals.length < 2 || relationships.length >= 8} onClick={() => onChange([...relationships, { kind: "agreement", target: signals[0], predictor: signals[1] }])}>{t("Add relationship")}</button></fieldset>;
}

function intervals(episodes: HealthEpisode[]): Interval[] { return episodes.map(e => ({ start: e.start, end: e.end, samples: e.samples, peakScore: e.severity, peakTime: e.detectedAt, signals: e.signals })); }
export function SensorHealthResult({ result: r, dataset, embedded = false, initialEpisode }: { result: HealthResult; dataset?: Dataset; embedded?: boolean; initialEpisode?: number }) {
  useLocale();
  const [signal, setSignal] = useState(r.indicators.find(i => i.kind !== "model_residual" && i.intervals.length)?.signals[0] || r.config.signals[0]), [episodeIndex, setEpisodeIndex] = useState(initialEpisode ?? 0), [cursor, setCursor] = useState<number>(), [linking, setLinking] = useState<number | "all" | null>(null);
  const axis = r.datasetSnapshot.time, episode = r.episodes[episodeIndex], evidence = episode ? r.indicators.filter(i => episode.indicatorIds.includes(i.id)) : r.indicators;
  const selected = r.signals[signal], expected = r.physical?.expected[signal] || r.relationships.find(v => v.target === signal)?.expected;
  const expectedSegments = r.physical?.segmentIds[signal];
  const shade = intervals(r.episodes), timeDomain: [number, number] = [r.times[0], r.times[r.times.length-1]];
  const synced = { selectedTime: cursor, onHoverTime: setCursor, onSelectTime: setCursor, timeDomain, gaps: r.gaps || [] };
  const relevant = r.indicators.filter(i => i.signals.includes(signal) && i.kind !== "model_residual");
  let sampleIndex = 0;
  if (cursor !== undefined) { let a = 0, b = r.times.length-1; while (a < b) { const m = (a+b)>>1; if (r.times[m] < cursor) a = m+1; else b = m; } sampleIndex = a; }
  return <section className="health-result" aria-label={t("Sensor diagnostic results")}>
    <div className="ws-section-heading"><div><h2>{r.name}</h2><p className="ws-muted">{dateLabel(r.createdAt)} · v{r.version}</p></div>{!embedded && <button onClick={() => setLinking("all")}>{t("Continue in Incident")}</button>}</div>
    <div className="ws-stats"><div><strong>{r.summary.episodes}</strong><span>{t("fault intervals")}</span></div><div><strong>{r.summary.flaggedSamples} / {r.summary.samples}</strong><span>{t("samples with evidence")}</span></div><div><strong>{r.physical ? `${number(r.physical.measuredCoverage*100)}%` : "—"}</strong><span>{t("complete model evidence")}</span></div><div><strong>{r.summary.firstDetection === null ? "—" : timeLabel(axis, r.summary.firstDetection)}</strong><span>{t("first confirmed detection")}</span></div></div>
    <div className="ws-notice">{r.limitations.map(k => <p key={k}>{t(k)}</p>)}{r.physical?.assumptions.map(k => <p key={k}>{t(k)}</p>)}{r.warnings.map((w, i) => <p key={i}>{t(w.code)} · {w.signals.join(", ")}</p>)}</div>
    <div className="ws-panel"><h3>{t("Fault timeline and competing explanations")}</h3>{r.episodes.length ? <>
      <div className="health-episodes" role="group" aria-label={t("Fault intervals")}>{r.episodes.map((e, i) => <button key={i} aria-pressed={episodeIndex === i} onClick={() => { setEpisodeIndex(i); setCursor(e.detectedAt); }}>{timeLabel(axis, e.start)} → {timeLabel(axis, e.end)} · {t(e.assessment)}</button>)}</div>
      <p><strong>{t(episode.assessment)}</strong> · {t("Peak severity")} {number(episode.severity)} · {t("Evidence coverage")} {episode.evidenceCoverage === undefined ? "—" : `${number(episode.evidenceCoverage*100)}%`}</p>
      <p>{episode.signals.join(", ")}</p><p className="ws-muted">{t("Rankings compare residual corrections under a single-fault assumption. Fit scores are not causal probabilities.")}</p>
      {episode.candidates.length > 0 && <div className="health-table"><table><thead><tr>{["Candidate explanation", "Residual fit error", "Penalized error", "Improvement", "Fitted evidence"].map(k => <th key={k}>{t(k)}</th>)}</tr></thead><tbody>{episode.candidates.map(v => <tr key={v.key}><td>{t(v.key)}</td><td>{number(v.fitError)}</td><td>{number(v.penalizedError)}</td><td>{number(v.improvement*100)}%</td><td><Evidence values={v.parameters} /><small>{v.constraints.map(k => t(k)).join(", ")}</small></td></tr>)}</tbody></table></div>}
      <details><summary>{t("Evidence behind this interval")}</summary>{evidence.map(i => <div key={i.id}><h4>{t(i.kind)} · {i.signals.join(", ")}</h4><p>{t("Threshold")} {number(i.threshold)}</p><Evidence values={i.evidence} />{i.intervals.filter(s => s.start <= episode.end && s.end >= episode.start).map((s, j) => <p key={j}>{timeLabel(axis, s.start)} → {timeLabel(axis, s.end)} · {t("Peak statistic")} {number(s.evidenceValue)} · {t("Confirmed at")} {timeLabel(axis, s.detectedAt)}</p>)}</div>)}</details>
      {!embedded && <button className="ws-primary" onClick={() => setLinking(episodeIndex)}>{t("Link this interval to Incident")}</button>}
    </> : <p>{t("No diagnostic threshold exceedances in the selected interval.")}</p>}</div>
    <div className="ws-panel"><div className="ws-inline ws-between"><h3>{t("Observed and expected measurements")}</h3><label>{t("Signal")}<select value={signal} onChange={e => setSignal(e.target.value)}>{r.config.signals.map(s => <option key={s} value={s}>{dataset ? namedSignal(dataset, s) : s}</option>)}</select></label></div>
      <p className="ws-muted">{t("Reference median")} {number(selected.referenceMedian)} · {t("Reference scale")} {number(selected.referenceScale)} · {t("Measured coverage")} {number(selected.measuredFraction*100)}%</p>
      <Plot {...synced} times={r.times} values={selected.observed} segmentIds={selected.segmentIds} title={dataset ? namedSignal(dataset, signal) : signal} axis={axis} intervals={shade} overlays={expected ? [{ times: r.times, values: expected, segmentIds: expectedSegments, title: t("Expected from related measurements"), color: "#8cbfe8" }] : []} />
      {expected && <p className="health-legend">● {t("Observed")} <span>● {t("Expected from related measurements")}</span></p>}
      <div className="ws-inline health-readout"><span>{timeLabel(axis, r.times[sampleIndex])}</span><span>{t("Observed")}: {selected.observed[sampleIndex] === null ? t("missing") : number(selected.observed[sampleIndex]!)}</span>{expected && <span>{t("Expected")}: {expected[sampleIndex] === null ? "—" : number(expected[sampleIndex]!)}</span>}</div>
      {relevant.map(i => <details key={i.id} open={i.intervals.length > 0}><summary>{t(i.kind)} · {i.intervals.length} {t("fault intervals")}</summary><Plot {...synced} times={r.times} values={i.scores} title={t(i.kind)} axis={axis} threshold={i.threshold} intervals={shade} /><p>{t("Severity is statistic / threshold; values above 1 indicate an exceedance.")}</p><Evidence values={i.evidence} /></details>)}
    </div>
    {r.physical && <details className="ws-panel" open><summary>{t("Physical constraint residuals")}</summary>{r.physical.residuals.map(v => <Plot key={v.key} {...synced} times={r.times} values={v.values} title={`${t(v.key)} (${v.unit})`} axis={axis} threshold={v.threshold} thresholdLabel={t("Positive residual limit")} intervals={shade} overlays={[{ times: r.times, values: r.times.map(() => -v.threshold), title: t("Negative residual limit"), color: "#e2bc75" }]} />)}</details>}
    {r.relationships.map((v, i) => <Plot key={i} {...synced} times={r.times} values={v.residual} title={`${t("Relationship residual")} · ${v.target} / ${v.predictor}`} axis={axis} intervals={shade} />)}
    <details className="ws-panel"><summary>{t("Saved reference and reproducibility")}</summary><p>{t("Fit samples")} {r.reference.fitSamples} · {t("Calibration samples")} {r.reference.calibrationSamples}</p><Plot times={r.reference.times} values={r.reference.values[signal]} title={`${t("Normal reference")} · ${signal}`} axis={axis} /><p>{t("Source digest")} <code className="health-digest">{r.sourceDigest}</code></p><pre>{JSON.stringify(r.config, null, 2)}</pre></details>
    {linking !== null && <IncidentLinkDialog workspaceId={r.workspaceId} mode="existing" source={{ kind: "sensor-health", diagnosticId: r.id, ...(linking === "all" ? {} : { episodeIndex: linking }) }} draft={{ title: r.name, start: linking === "all" ? r.config.analysisRange[0] : r.episodes[linking].start, end: linking === "all" ? r.config.analysisRange[1] : r.episodes[linking].end, description: t("Saved sensor diagnostic evidence; candidate explanations require investigation.") }} onClose={() => setLinking(null)} />}
  </section>;
}

function Evidence({ values }: { values: Record<string, unknown> }) {
  return <dl className="health-evidence">{Object.entries(values).map(([key, value]) => <div key={key}><dt>{t(key)}</dt><dd>{typeof value === "number" ? number(value) : typeof value === "string" ? t(value) : JSON.stringify(value)}</dd></div>)}</dl>;
}
