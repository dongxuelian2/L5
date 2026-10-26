import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale, type Message } from "../i18n";
import { useEffect, useState } from "react";
import { api, go, message } from "./api";
import { number, type Dataset, type ExternalRun } from "./types";
import { TEPStudyDashboard } from "./TEPStudyDashboard";

type CachedRun = Pick<ExternalRun, "id" | "faultNumber" | "simulationRun" | "split" | "samples" | "features" | "sampleIntervalSeconds" | "faultOnsetSample" | "faultOnsetSeconds">;
type CachedSource = { id: string; source: Pick<ExternalRun, "sourceFile" | "sha256" | "sourceUrl">; timeConvention: string; runs: CachedRun[] };

export function ExternalProvenance({ dataset }: { dataset: Dataset }) {
  useLocale();
  const source = dataset.metadata.external;
  if (!source) return null;
  return <details className="ws-panel" aria-label={tr("External dataset provenance")}><summary>{tr("External source · fault")}{" "}{source.faultNumber}{" "}{tr("· simulationRun")}{" "}{source.simulationRun} · {tr(source.split)}</summary>
    <p><a className="ws-link" href={source.sourceUrl} target="_blank" rel="noreferrer">{tr("Rieth et al. (2017) · Harvard Dataverse V1 ↗")}</a></p>
    <p>{source.sourceFile}{" "}{tr("· object")}{" "}{source.sourceObject}</p><p>{source.samples}{" "}{tr("samples ·")}{" "}{source.features}{" "}{tr("inputs ·")}{" "}{source.sampleIntervalSeconds}{" "}{tr("s cadence")}</p>
    <p>{source.faultOnsetSeconds == null ? tr("Published fault-free trajectory") : tr("Published fault injection: sample {0}, t={1} s. Fault {2} is a dataset label.", {0: source.faultOnsetSample, 1: number(source.faultOnsetSeconds), 2: source.faultNumber})}</p>
    <p>{tr(source.timeConvention)}</p><p>{tr("Sequence:")}{" "}{source.sequenceId}</p><p>{tr("Original SHA-256:")}{" "}<code>{source.sha256}</code></p><p>{tr("Extract SHA-256:")}{" "}<code>{source.extractedSha256}</code></p>
    <p>{tr("Imported")}{" "}{source.importedAt}</p><ul>{source.processing.map(step => <li key={step}>{tr(step)}</li>)}</ul><details><summary>{tr("Original column identities")}</summary><p>{source.originalColumns.join(", ")}</p></details>
  </details>;
}

export function TEPWorkspace({ workspaceId, search, onChanged }: { workspaceId: string; search?: string; onChanged: () => void }) {
  useLocale();
  const [sources, setSources] = useState<CachedSource[]>([]), [sourceId, setSourceId] = useState("");
  const [selected, setSelected] = useState<string[]>([]), [preview, setPreview] = useState<{ runs: CachedRun[]; timeConvention: string } | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState<Message | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api<{ sources: CachedSource[] }>("/external/tep/sources", undefined, "GET", controller.signal).then(r => { if (!controller.signal.aborted) { setSources(r.sources); setSourceId(r.sources[0]?.id || ""); } }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [workspaceId]);
  const source = sources.find(s => s.id === sourceId);
  async function inspect() {
    setError(""); setBusy(true);
    try { setPreview(await api("/external/tep/preview", { sourceId, runIds: selected })); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function save() {
    setError(""); setBusy(true);
    try { const r = await api<{ datasets: Dataset[] }>(`/workspaces/${workspaceId}/external/tep`, { sourceId, runIds: selected }); onChanged(); setNotice(["{0} independent runs saved with published label versions. Open Datasets or Signal Explorer to inspect all 52 channels.", {0: r.datasets.length}]); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function caseStudy() {
    setError(""); setBusy(true);
    try { const r = await api<{ id: string }>(`/workspaces/${workspaceId}/external/tep/experiment`, {}); onChanged(); go(`workspaces/${workspaceId}/experiments/${r.id}`); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <div className="notranslate" translate="no"><div className="ws-page-title"><div><div className="ws-kicker">{tr("EXTERNAL DATA / TENNESSEE EASTMAN")}</div><h1>{tr("A public process benchmark")}<span className="ws-accent">.</span></h1><p>{tr("Import verified independent simulation runs, fit on normal training data and evaluate untouched test trajectories.")}</p></div><span className="ws-badge">{tr("RIETH 2017 · 52 CHANNELS")}</span></div>
    <section className="ws-panel"><h2>{tr("01 / Cached external runs")}</h2><p><a className="ws-link" href="https://doi.org/10.7910/DVN/6C3JR1" target="_blank" rel="noreferrer">{tr("Source data and citation ↗")}</a>{" "}{tr("· 180-second samples · file and run identities retained")}</p>
      {!sources.length ? <><p className="ws-notice">{tr("Prepare selected official runs in the local cache before importing.")}</p><pre>python -m examples.tep.prepare --source-dir PATH --cache-dir PATH --source faulty-testing --faults 1 3 5 --runs 1 2 --download</pre><p>{tr("Set L5_TEP_CACHE to that cache directory when starting L5. See examples/tep/README.md for the three source preparation commands.")}</p></> : <>
        <label>{tr("Cached TEP source")}<select disabled={busy} value={sourceId} onChange={e => { setSourceId(e.target.value); setSelected([]); setPreview(null); setNotice(null); }}>{sources.map(s => <option key={s.id} value={s.id}>{s.source.sourceFile} · {s.runs.length}{" "}{tr("prepared runs")}</option>)}</select></label>
        <fieldset disabled={busy}><legend>{tr("Independent fault / simulationRun pairs")}</legend><div className="ws-option-grid">{source?.runs.map(run => <label key={run.id}><input type="checkbox" checked={selected.includes(run.id)} onChange={e => { setPreview(null); setSelected(v => e.target.checked ? [...v, run.id] : v.filter(id => id !== run.id)); }} />{tr("Fault")}{" "}{run.faultNumber}{" "}{tr("· run")}{" "}{run.simulationRun} · {run.samples} × {run.features}</label>)}</div></fieldset>
        <div className="ws-inline"><button disabled={busy || !selected.length} onClick={() => void inspect()}>{tr("Inspect selected runs")}</button><button className="ws-primary" disabled={busy || !preview} onClick={() => void save()}>{tr("Import independent runs")}</button></div>
        {preview && <><p>{tr(preview.timeConvention)}</p><div className="ws-table-scroll"><table><thead><tr><th>{tr("Fault / run")}</th><th>{tr("Split")}</th><th>{tr("Samples / inputs")}</th><th>{tr("Cadence")}</th><th>{tr("Published onset")}</th></tr></thead><tbody>{preview.runs.map(r => <tr key={r.id}><td>{r.faultNumber} / {r.simulationRun}</td><td>{tr(r.split)}</td><td>{r.samples} / {r.features}</td><td>{r.sampleIntervalSeconds} s</td><td>{r.faultOnsetSeconds == null ? tr("Fault-free") : tr("sample {0} · {1} s", {0: r.faultOnsetSample, 1: r.faultOnsetSeconds})}</td></tr>)}</tbody></table></div></>}
      </>}
    </section><section className="ws-panel"><h2>{tr("02 / Reproduce the fixed case study")}</h2><p>{tr("Fit: FaultFree Training run 1. Calibration: FaultFree Training run 2. Test: FaultFree Testing runs 1–2 and Faulty Testing faults 1, 3, 5, runs 1–2. Nine algorithms, α=0.01, persistence=3; 72 tasks.")}</p><p>{tr("Each independent run starts fresh. Fault labels only evaluate saved predictions. This is mode 1 process simulation; two runs per fault give descriptive results.")}</p><button className="ws-primary" disabled={busy || sources.length < 3} onClick={() => void caseStudy()}>{tr("Create fixed nine-algorithm experiment ↗")}</button><p className="ws-muted">{tr("Imports required cached runs, reuses matching imports and opens the saved experiment for review and execution.")}</p></section>
    <TEPStudyDashboard workspaceId={workspaceId} search={search} onChanged={onChanged} />
    {busy && <p role="status">{tr("Verifying and saving selected data…")}</p>}{error && <p role="alert" className="ws-error">{errorMessage(error)}</p>}{notice && <p role="status" className="ws-notice">{tr(...notice)} <a href={`#/workspaces/${workspaceId}/datasets`}>{tr("Open datasets ↗")}</a></p>}
  </div>;
}
