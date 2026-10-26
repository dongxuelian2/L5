import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
import { useEffect, useState } from "react";
import { api, go, message } from "./api";
import { algorithms } from "./AlgorithmControls";
import { Plot } from "./Charts";
import { FaultMatrix, MatrixMetric, type StudyCell } from "./TEPBenchmark";
import { number, type Interval } from "./types";
import type { DetectionMetrics, Experiment } from "./experimentTypes";
import "./experiments.css";

const protocols = { get original() { return tr("Original case study · 72 tasks"); }, get "rieth-expanded-nine-v1"() { return tr("Expanded benchmark · faults 1–20"); }, get "rieth-robustness-nine-v1"() { return tr("Normal training robustness · A / B / C"); } };
type StudyIndex = { id: string; protocolId: string };
type StudyTask = { id: string; algorithm: string; experimentId: string; datasetId: string; datasetName: string; status: string; error: string | null; result_id: string | null; benchmark: { configuration: string; batch: number }; external: { faultNumber: number; simulationRun: number }; metrics: null | { detection: DetectionMetrics; training: { threshold: number }; sample: { recall: number | null } } };
type Study = { id: string; workspaceId: string; protocolHash: string; protocol: { id: string; name: string; configurations: Record<string,unknown> }; tasks: StudyTask[]; cells: StudyCell[]; statusCounts: Record<string,number>; batches: { experimentId: string; name: string; status: string }[] };
type Curve = { times: number[]; scores: number[]; intervals: Interval[]; metrics: { detection: DetectionMetrics } };
type Control = { onset: number; targetTime: number; interpretation: string; diagnostics: { preInjection: { exactlyEqual: boolean }; postInjection: { exactlyEqual: boolean; maxAbsoluteDifference: number } } | null; configurations: { configuration: string; threshold: number; normal: Curve; fault: Curve; localScoreCorrelation: number; contributionsAtTarget: Record<string,{ signal: string; value: number; fraction: number }[]>; otherMethodsAtTarget: { algorithm: string; faultNumber: number; score: number; threshold: number; ratio: number; state: string }[] }[]; raw: { signal: string; times: number[]; normal: number[]; fault: number[] }[]; controls: { configuration: string; faultNumber: number; simulationRun: number; peakTime: number; peakRatio: number; targetState: string }[] };
const show = (v: number | null | undefined) => v == null ? "—" : number(v);
const axis = { kind: "numeric" as const, column: "sample", origin: null, start: 0, end: 172620, sourceUnit: "seconds" };

export function TEPStudyDashboard({ workspaceId, search = "", onChanged }: { workspaceId: string; search?: string; onChanged: () => void }) {
  const locale = useLocale();
  const [protocol, setProtocol] = useState("rieth-expanded-nine-v1"), [studies, setStudies] = useState<StudyIndex[]>([]), [selected, setSelected] = useState("");
  const [study, setStudy] = useState<Study | null>(null), [configuration,setConfiguration] = useState("A"), [metric,setMetric] = useState("1800");
  const [cell,setCell] = useState<StudyCell | null>(null), [error,setError] = useState(""), [busy,setBusy] = useState(false), [refresh,setRefresh] = useState(0);
  const [originals,setOriginals] = useState<Experiment[]>([]);
  const path = `/workspaces/${workspaceId}/external/tep/studies`;
  useEffect(() => {
    const query = new URLSearchParams(search), requested = query.get("protocol");
    setProtocol(requested && requested in protocols ? requested : "rieth-expanded-nine-v1");
    setSelected(query.get("study") || ""); setConfiguration(query.get("training") || "A");
    setMetric(query.get("metric") || "1800"); setCell(null);
  }, [search]);
  useEffect(() => {
    const controller = new AbortController(); setStudies([]); setOriginals([]); setStudy(null); setCell(null); setError(""); setBusy(false);
    Promise.all([api<{studies:StudyIndex[]}>(path,undefined,"GET",controller.signal),api<{experiments:Experiment[]}>(`/workspaces/${workspaceId}/experiments`,undefined,"GET",controller.signal)]).then(([s,e]) => {
      if (!controller.signal.aborted) { setStudies(s.studies); setOriginals(e.experiments.filter(e => e.description.includes("rieth-mode1-independent-nine-v1"))); }
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  },[workspaceId,path]);
  const matching = studies.filter(s => s.protocolId === protocol);
  const studyId = matching.some(s => s.id === selected) ? selected : matching[0]?.id || "";
  function navigate(changes: Record<string, string>) {
    const query = new URLSearchParams({ protocol, study: studyId, training: configuration, metric, ...changes });
    go(`workspaces/${workspaceId}/tep?${query}`);
  }
  useEffect(() => {
    const controller = new AbortController(); setStudy(null); setCell(null); setError("");
    if (studyId) api<Study>(`${path}/${studyId}`,undefined,"GET",controller.signal).then(s => { if (!controller.signal.aborted) setStudy(s); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  },[path,studyId,refresh]);
  useEffect(() => {
    if (!study || !study.statusCounts.queued && !study.statusCounts.running) return;
    const timer = setTimeout(() => setRefresh(v => v+1),2000);
    return () => clearTimeout(timer);
  },[study]);
  async function create() {
    setBusy(true); setError("");
    try { const created = await api<Study>(path,{protocolId:protocol}); setStudies(v => [{id:created.id,protocolId:protocol},...v]); setSelected(created.id); setStudy(created); navigate({ study: created.id }); onChanged(); }
    catch(e) { setError(message(e)); } finally { setBusy(false); }
  }
  const cells = study?.cells.filter(c => c.configuration === configuration) || [];
  useEffect(() => {
    const query = new URLSearchParams(search), fault = query.get("fault"), algorithm = query.get("algorithm");
    if (fault !== null && algorithm) setCell(study?.cells.find(c => c.configuration === configuration && c.faultNumber === Number(fault) && c.algorithm === algorithm) || null);
  }, [search, study, configuration]);
  const chosenTasks = cell ? study?.tasks.filter(t => cell.taskIds.includes(t.id)) || [] : [];
  return <section className="ws-panel tep-study" aria-label={tr("TEP protocol dashboard")}><div className="ws-section-heading"><h2>{tr("03 / Expanded benchmark and training robustness")}</h2><span className="ws-kicker">{tr("SAVED RESEARCH")}</span></div>
    <label>{tr("Experiment protocol")}<select disabled={busy} value={protocol} onChange={e => { setProtocol(e.target.value); setSelected(""); setCell(null); setConfiguration("A"); navigate({ protocol: e.target.value, study: "", training: "A" }); }}>{Object.entries(protocols).map(([id,label]) => <option key={id} value={id}>{tr(label)}</option>)}</select></label>
    {protocol === "original" ? <><p>{tr("The original eight test trajectories and 72 tasks keep their own experiment and evaluation reference.")}</p>{originals.length ? originals.map(e => <p key={e.id}><a className="ws-link" href={`#/workspaces/${workspaceId}/experiments/${e.id}`}>{e.name} ↗</a></p>) : <p>{tr("Create the original fixed experiment above to inspect this protocol.")}</p>}</> : <>
      <p>{tr("Faults 1–20 × Testing runs 1–3, plus normal Testing runs 1–5.")}{" "}{protocol.includes("robustness") ? tr("A: fit/calibration 1/2; B: 3/4; C: 5/6. All three use the same 65 tests and fixed method parameters; 1,755 tasks.") : tr("Fit/calibration: normal Training runs 1/2; 585 tasks.")}</p>
      <div className="ws-inline"><button disabled={busy} onClick={() => void create()}>{tr("Create declared study experiments")}</button><button onClick={() => setRefresh(v => v+1)}>{tr("Refresh saved results")}</button></div>
      <p className="ws-muted">{tr("The prepared cache must contain every declared input. Each saved batch can be reviewed and executed in Experiment; completed, failed and unrun tasks remain visible.")}</p>
      {matching.length > 0 && <label>{tr("Saved study")}<select value={studyId} onChange={e => { setSelected(e.target.value); navigate({ study: e.target.value }); }}>{matching.map(s => <option key={s.id} value={s.id}>{protocols[protocol as keyof typeof protocols]} · {s.id.slice(0,8)}</option>)}</select></label>}
      {study && <><p>{tr("Protocol SHA-256")}{" "}<code>{study.protocolHash}</code></p><p role="status">{Object.entries(study.statusCounts).map(([s,n]) => `${n} ${s}`).join(" · ")}</p>
        <details><summary>{tr("Saved batches and execution status")}</summary>{study.batches.map(b => <p key={b.experimentId}><a className="ws-link" href={`#/workspaces/${workspaceId}/experiments/${b.experimentId}`}>{b.name} ↗</a> · {tr(b.status)}</p>)}</details>
        <div className="ws-form-grid"><label>{tr("Normal training configuration")}<select value={configuration} onChange={e => { setConfiguration(e.target.value); setCell(null); navigate({ training: e.target.value }); }}>{Object.keys(study.protocol.configurations).map(c => <option key={c}>{c}</option>)}</select></label><MatrixMetric metric={metric} setMetric={value => { setMetric(value); navigate({ metric: value }); }} /></div>
        <p>{tr("All declared fault events enter each early/eventual denominator. Unobserved, truncated and unresolved outcomes are shown separately. Delay distributions describe detected events only. Normal burden in fault rows describes the pre-injection interval.")}</p>
        <FaultMatrix cells={cells} metric={metric} onCell={value => { setCell(value); navigate({ fault: String(value.faultNumber), algorithm: value.algorithm }); }} />
        {cell && <section aria-label={tr("Selected matrix cell")}><h3>{tr("Fault")}{" "}{cell.faultNumber} · {algorithms[cell.algorithm]}{" "}{tr("· configuration")}{" "}{configuration}</h3><div className="ws-table-scroll"><table><thead><tr><th>{tr("Testing run")}</th><th>{tr("Status / error")}</th><th>{tr("Event denominator")}</th><th>{tr("Delay (s)")}</th><th>{tr("Recall")}</th><th>{tr("Saved evidence")}</th></tr></thead><tbody>{chosenTasks.map(t => <tr key={t.id}><td>{t.external.simulationRun}</td><td>{tr(t.status)}{t.error && <p role="alert">{t.error}</p>}</td><td>{t.metrics?.detection.windows?.eventual.totalEvents ?? "unresolved"}</td><td>{show(t.metrics?.detection.events[0]?.delay)}</td><td>{show(t.metrics?.sample?.recall)}</td><td><a href={`#/workspaces/${workspaceId}/datasets/${t.datasetId}`}>{tr("Dataset ↗")}</a> · <a href={`#/workspaces/${workspaceId}/experiments/${t.experimentId}`}>{tr("Experiment / algorithms / timeline ↗")}</a></td></tr>)}</tbody></table></div></section>}
        <TrainingComparison study={study} />
        <Fault3View path={`${path}/${study.id}/fault3`} />
        <p><a className="ws-link" href={`/api${path}/${study.id}/report.html?lang=${locale}&download=1`} download>{tr("Download offline study report ↗")}</a></p>
      </>}
    </>}{busy && <p role="status">{tr("Verifying cached inputs and saving study batches…")}</p>}{error && <p role="alert" className="ws-error">{errorMessage(error)}</p>}
  </section>;
}

function TrainingComparison({ study }: { study: Study }) {
  useLocale();
  return <section aria-label={tr("Normal training comparison")}><h3>{tr("Normal-training sensitivity · same fixed parameters")}</h3><div className="ws-table-scroll"><table><thead><tr><th>{tr("Method")}</th><th>{tr("Config")}</th><th>{tr("Threshold")}</th><th>{tr("Normal FP / observations")}</th><th>{tr("Normal episodes / seconds")}</th><th>{tr("30m / 1h / 4h / eventual hits")}</th><th>{tr("Declared fault events")}</th></tr></thead><tbody>{Object.keys(study.protocol.configurations).flatMap(configuration => Object.keys(algorithms).map(algorithm => {
    const cells = study.cells.filter(c => c.configuration === configuration && c.algorithm === algorithm), normal = cells.find(c => c.faultNumber === 0)?.burden?.normal;
    const faults = cells.filter(c => c.faultNumber !== 0), task = study.tasks.find(t => t.benchmark.configuration === configuration && t.algorithm === algorithm && t.metrics);
    return <tr key={`${configuration}-${algorithm}`}><th>{algorithms[algorithm]}</th><td>{configuration}</td><td>{show(task?.metrics?.training.threshold)}</td><td>{normal?.alarmSamples ?? "—"}/{normal?.observedSamples ?? "—"}</td><td>{normal?.alarmEvents ?? "—"} / {show(normal?.alarmDuration)} s</td><td>{["1800","3600","14400","eventual"].map(k => faults.reduce((sum,c) => sum+(c.windows?.[k]?.detectedEvents || 0),0)).join(" / ")}</td><td>{faults.reduce((sum,c) => sum+(c.windows?.eventual.totalEvents || 0),0)}</td></tr>;
  }))}</tbody></table></div></section>;
}

function Fault3View({ path }: { path: string }) {
  useLocale();
  const [run,setRun] = useState("1"), [data,setData] = useState<Control | null>(null), [error,setError] = useState(""), [time,setTime] = useState(167580), [open,setOpen] = useState(false);
  const [window,setWindow] = useState("full");
  function sliced(times: number[], values: number[]) {
    const bounds = window === "injection" ? [27000,34200] : window === "late" ? [166500,168660] : [0,172620];
    const indexes = times.map((t,i) => t >= bounds[0] && t <= bounds[1] ? i : -1).filter(i => i >= 0);
    return { times: indexes.map(i => times[i]), values: indexes.map(i => values[i]) };
  }
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError("");
    if (open) api<Control>(`${path}?run=${run}`,undefined,"GET",controller.signal).then(v => { if (!controller.signal.aborted) setData(v); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  },[path,run,open]);
  return <details onToggle={e => setOpen(e.currentTarget.open)} aria-label={tr("Fault 3 background control")}><summary>{tr("Fault 3 · normal-background control and original measurements")}</summary>
    <label>{tr("Fault 3 Testing run")}<select value={run} onChange={e => setRun(e.target.value)}>{[1,2,3].map(r => <option key={r}>{r}</option>)}</select></label>
    {data && <><p>{data.interpretation}</p>{data.diagnostics && <p>{tr("Raw measurements equal before injection:")}{" "}{String(data.diagnostics.preInjection.exactlyEqual)}{tr(". Equal after injection:")}{" "}{String(data.diagnostics.postInjection.exactlyEqual)}{tr("; maximum original-unit difference")}{" "}{show(data.diagnostics.postInjection.maxAbsoluteDifference)}.</p>}
      <label>{tr("Fault 3 plot window")}<select value={window} onChange={e => setWindow(e.target.value)}><option value="full">{tr("Full trajectory")}</option><option value="injection">{tr("Around published injection")}</option><option value="late">{tr("Around PR22 late alarm")}</option></select></label>
      <p>{tr("Green: normal Testing. Orange: fault 3 Testing. Shaded bands: saved fault-3 alarms. Aligning elapsed seconds is an exploratory control.")}</p>
      <label>{tr("Shared simulation elapsed time (s)")}<input type="number" min={0} max={172620} step={180} value={time} onChange={e => setTime(Number(e.target.value))} /></label>
      {data.configurations.map(pair => <div key={pair.configuration}><h4>{tr("Configuration")}{" "}{pair.configuration} · DPCA-Q</h4><Plot title={tr("Normal / fault 3 · DPCA-Q · {0}", {0: pair.configuration})} axis={axis} {...sliced(pair.normal.times,pair.normal.scores)} overlays={[{title:"Fault 3",color:"#e9927d",...sliced(pair.fault.times,pair.fault.scores)}]} threshold={pair.threshold} intervals={pair.fault.intervals} selectedTime={time} onSelectTime={setTime} markers={[{time:data.onset,label:"Published injection"},{time:data.targetTime,label:"PR22 late alarm"}]} />
        <p>{tr("Local score correlation around the PR22 alarm:")}{" "}{pair.localScoreCorrelation.toFixed(6)}{tr(". Normal alarms:")}{" "}{pair.normal.intervals.map(v => `${v.start}–${v.end} s`).join("; ") || "none"}{tr(". Fault 3 alarms:")}{" "}{pair.fault.intervals.map(v => `${v.start}–${v.end} s`).join("; ") || "none"}.</p>
        <div className="ws-table-scroll"><table><thead><tr><th>{tr("Series")}</th><th>{tr("Contributions at 167580 s")}</th></tr></thead><tbody>{Object.entries(pair.contributionsAtTarget).map(([key,values]) => <tr key={key}><th>{key}</th><td>{values.map(v => `${v.signal}: ${show(v.value)} (${show(v.fraction*100)}%)`).join(" · ")}</td></tr>)}</tbody></table></div>
        <details><summary>{tr("All nine methods at 167580 s")}</summary><div className="ws-table-scroll"><table><thead><tr><th>{tr("Method")}</th><th>{tr("Fault")}</th><th>{tr("Score / threshold")}</th><th>{tr("Ratio")}</th><th>{tr("State")}</th></tr></thead><tbody>{pair.otherMethodsAtTarget.map(v => <tr key={`${v.algorithm}-${v.faultNumber}`}><th>{algorithms[v.algorithm]}</th><td>{v.faultNumber}</td><td>{show(v.score)} / {show(v.threshold)}</td><td>{show(v.ratio)}</td><td>{tr(v.state)}</td></tr>)}</tbody></table></div></details>
      </div>)}
      {data.raw.slice(0,6).map(v => <Plot key={v.signal} title={tr("{0} · normal / fault 3 · original measurements", {0: v.signal})} axis={axis} {...sliced(v.times,v.normal)} overlays={[{title:"Fault 3",color:"#e9927d",...sliced(v.times,v.fault)}]} selectedTime={time} onSelectTime={setTime} markers={[{time:data.onset,label:"Published injection"},{time:data.targetTime,label:"PR22 late alarm"}]} />)}
      <details><summary>{tr("Other normal and fault-3 runs · DPCA-Q peaks")}</summary><div className="ws-table-scroll"><table><thead><tr><th>{tr("Config")}</th><th>{tr("Fault / run")}</th><th>{tr("Peak time")}</th><th>{tr("Peak / threshold")}</th><th>{tr("State at PR22 alarm time")}</th></tr></thead><tbody>{data.controls.map(c => <tr key={`${c.configuration}-${c.faultNumber}-${c.simulationRun}`}><td>{c.configuration}</td><td>{c.faultNumber} / {c.simulationRun}</td><td>{c.peakTime} s</td><td>{show(c.peakRatio)}</td><td>{c.targetState}</td></tr>)}</tbody></table></div></details>
    </>}{open && !data && !error && <p role="status">{tr("Loading saved models and original measurements…")}</p>}{error && <p role="alert">{errorMessage(error)}</p>}
  </details>;
}
