import { useEffect, useState } from "react";
import { api, go, message } from "./api";
import { number, type Dataset, type ExternalRun } from "./types";
import { TEPStudyDashboard } from "./TEPStudyDashboard";

type CachedRun = Pick<ExternalRun, "id" | "faultNumber" | "simulationRun" | "split" | "samples" | "features" | "sampleIntervalSeconds" | "faultOnsetSample" | "faultOnsetSeconds">;
type CachedSource = { id: string; source: Pick<ExternalRun, "sourceFile" | "sha256" | "sourceUrl">; timeConvention: string; runs: CachedRun[] };

export function ExternalProvenance({ dataset }: { dataset: Dataset }) {
  const source = dataset.metadata.external;
  if (!source) return null;
  return <details className="ws-panel" aria-label="External dataset provenance"><summary>External source · fault {source.faultNumber} · simulationRun {source.simulationRun} · {source.split}</summary>
    <p><a className="ws-link" href={source.sourceUrl} target="_blank" rel="noreferrer">Rieth et al. (2017) · Harvard Dataverse V1 ↗</a></p>
    <p>{source.sourceFile} · object {source.sourceObject}</p><p>{source.samples} samples · {source.features} inputs · {source.sampleIntervalSeconds} s cadence</p>
    <p>{source.faultOnsetSeconds == null ? "Published fault-free trajectory" : `Published fault injection: sample ${source.faultOnsetSample}, t=${number(source.faultOnsetSeconds)} s. Fault ${source.faultNumber} is a dataset label.`}</p>
    <p>{source.timeConvention}</p><p>Sequence: {source.sequenceId}</p><p>Original SHA-256: <code>{source.sha256}</code></p><p>Extract SHA-256: <code>{source.extractedSha256}</code></p>
    <p>Imported {source.importedAt}</p><ul>{source.processing.map(step => <li key={step}>{step}</li>)}</ul><details><summary>Original column identities</summary><p>{source.originalColumns.join(", ")}</p></details>
  </details>;
}

export function TEPWorkspace({ workspaceId, search, onChanged }: { workspaceId: string; search?: string; onChanged: () => void }) {
  const [sources, setSources] = useState<CachedSource[]>([]), [sourceId, setSourceId] = useState("");
  const [selected, setSelected] = useState<string[]>([]), [preview, setPreview] = useState<{ runs: CachedRun[]; timeConvention: string } | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
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
    try { const r = await api<{ datasets: Dataset[] }>(`/workspaces/${workspaceId}/external/tep`, { sourceId, runIds: selected }); onChanged(); setNotice(`${r.datasets.length} independent runs saved with published label versions. Open Datasets or Signal Explorer to inspect all 52 channels.`); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function caseStudy() {
    setError(""); setBusy(true);
    try { const r = await api<{ id: string }>(`/workspaces/${workspaceId}/external/tep/experiment`, {}); onChanged(); go(`workspaces/${workspaceId}/experiments/${r.id}`); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <div className="notranslate" translate="no"><div className="ws-page-title"><div><div className="ws-kicker">EXTERNAL DATA / TENNESSEE EASTMAN</div><h1>A public process benchmark<span className="ws-accent">.</span></h1><p>Import verified independent simulation runs, fit on normal training data and evaluate untouched test trajectories.</p></div><span className="ws-badge">RIETH 2017 · 52 CHANNELS</span></div>
    <section className="ws-panel"><h2>01 / Cached external runs</h2><p><a className="ws-link" href="https://doi.org/10.7910/DVN/6C3JR1" target="_blank" rel="noreferrer">Source data and citation ↗</a> · 180-second samples · file and run identities retained</p>
      {!sources.length ? <><p className="ws-notice">Prepare selected official runs in the local cache before importing.</p><pre>python -m examples.tep.prepare --source-dir PATH --cache-dir PATH --source faulty-testing --faults 1 3 5 --runs 1 2 --download</pre><p>Set L5_TEP_CACHE to that cache directory when starting L5. See examples/tep/README.md for the three source preparation commands.</p></> : <>
        <label>Cached TEP source<select disabled={busy} value={sourceId} onChange={e => { setSourceId(e.target.value); setSelected([]); setPreview(null); setNotice(""); }}>{sources.map(s => <option key={s.id} value={s.id}>{s.source.sourceFile} · {s.runs.length} prepared runs</option>)}</select></label>
        <fieldset disabled={busy}><legend>Independent fault / simulationRun pairs</legend><div className="ws-option-grid">{source?.runs.map(run => <label key={run.id}><input type="checkbox" checked={selected.includes(run.id)} onChange={e => { setPreview(null); setSelected(v => e.target.checked ? [...v, run.id] : v.filter(id => id !== run.id)); }} />Fault {run.faultNumber} · run {run.simulationRun} · {run.samples} × {run.features}</label>)}</div></fieldset>
        <div className="ws-inline"><button disabled={busy || !selected.length} onClick={() => void inspect()}>Inspect selected runs</button><button className="ws-primary" disabled={busy || !preview} onClick={() => void save()}>Import independent runs</button></div>
        {preview && <><p>{preview.timeConvention}</p><div className="ws-table-scroll"><table><thead><tr><th>Fault / run</th><th>Split</th><th>Samples / inputs</th><th>Cadence</th><th>Published onset</th></tr></thead><tbody>{preview.runs.map(r => <tr key={r.id}><td>{r.faultNumber} / {r.simulationRun}</td><td>{r.split}</td><td>{r.samples} / {r.features}</td><td>{r.sampleIntervalSeconds} s</td><td>{r.faultOnsetSeconds == null ? "Fault-free" : `sample ${r.faultOnsetSample} · ${r.faultOnsetSeconds} s`}</td></tr>)}</tbody></table></div></>}
      </>}
    </section><section className="ws-panel"><h2>02 / Reproduce the fixed case study</h2><p>Fit: FaultFree Training run 1. Calibration: FaultFree Training run 2. Test: FaultFree Testing runs 1–2 and Faulty Testing faults 1, 3, 5, runs 1–2. Nine algorithms, α=0.01, persistence=3; 72 tasks.</p><p>Each independent run starts fresh. Fault labels only evaluate saved predictions. This is mode 1 process simulation; two runs per fault give descriptive results.</p><button className="ws-primary" disabled={busy || sources.length < 3} onClick={() => void caseStudy()}>Create fixed nine-algorithm experiment ↗</button><p className="ws-muted">Imports required cached runs, reuses matching imports and opens the saved experiment for review and execution.</p></section>
    <TEPStudyDashboard workspaceId={workspaceId} search={search} onChanged={onChanged} />
    {busy && <p role="status">Verifying and saving selected data…</p>}{error && <p role="alert" className="ws-error">{error}</p>}{notice && <p role="status" className="ws-notice">{notice} <a href={`#/workspaces/${workspaceId}/datasets`}>Open datasets ↗</a></p>}
  </div>;
}
