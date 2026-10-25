import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, message } from "./api";
import { dateLabel } from "./types";
import type { ModelConfig, ModelDescriptor, ModelSession, Scenario } from "./modelTypes";

export function ScenarioEditor({ workspaceId, model, scenario, onSaved, onRun, onSelect }: {
  workspaceId: string; model: ModelDescriptor; scenario: Scenario | null;
  onSaved: (scenario: Scenario) => void; onRun: (session: ModelSession) => void; onSelect: (scenario: Scenario) => void;
}) {
  const [config,setConfig] = useState<ModelConfig>({ ...model.defaults,...scenario?.config });
  const [name,setName] = useState(scenario?.name || `${model.name} scenario`), [description,setDescription] = useState(scenario?.description || "");
  const [saved,setSaved] = useState(scenario), [versions,setVersions] = useState<Scenario[]>([]);
  const [busy,setBusy] = useState(false), [error,setError] = useState(""), [notice,setNotice] = useState("");
  const active = useRef(true);
  useEffect(() => {active.current=true;return () => {active.current=false;};},[]);
  const dirty = !saved || JSON.stringify(config) !== JSON.stringify(saved.config) || name !== saved.name || description !== saved.description;
  const historical = Boolean(saved && versions[0] && saved.version < versions[0].version);
  useEffect(() => {
    if (!saved) return;
    const controller = new AbortController();
    api<{versions:Scenario[]}>(`/scenarios/${saved.id}/versions`,undefined,"GET",controller.signal)
      .then(data => { if (!controller.signal.aborted) setVersions(data.versions); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  },[saved?.id,saved?.version]);
  async function persist() {
    if (!dirty && saved) return saved;
    const next = await api<Scenario>(saved ? `/scenarios/${saved.id}` : `/workspaces/${workspaceId}/scenarios`,
      { modelId:model.modelId,name,description,config,...(saved ? {expectedVersion:saved.version} : {}) },saved ? "PATCH" : "POST");
    if (active.current) {setSaved(next);onSaved(next);setNotice(`Saved scenario v${next.version}. Previous runs retain their original version.`);}
    return next;
  }
  async function save(e: FormEvent) {
    e.preventDefault();setBusy(true);setError("");
    try { await persist(); } catch(e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function run() {
    setBusy(true);setError("");
    try {
      const version = await persist();
      if (!active.current) return;
      const next = await api<ModelSession>(`/scenarios/${version.id}/run`,{ scenarioVersion:version.version,workspaceId });
      if (active.current) onRun(next);
    } catch(e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function copy() {
    if (!saved) return;
    setBusy(true);setError("");
    try { const next = await api<Scenario>(`/scenarios/${saved.id}/copy`,{ version:saved.version });if (active.current) {onSaved(next);onSelect(next);} }
    catch(e) { setError(message(e)); } finally { setBusy(false); }
  }
  const groups = [...new Set(model.configFields.map(f => f.group))];
  return <section className="ws-panel scenario-editor"><div className="ws-section-heading"><h2>Scenario editor</h2><span className="ws-kicker">{model.name} / {saved ? `v${saved.version}` : "NEW"}</span></div>
    {saved && <div className="ws-form-grid"><label>Saved scenario version<select aria-label="Scenario version" value={saved.version} disabled={busy} onChange={e => { const chosen=versions.find(v => v.version===Number(e.target.value));if (chosen) onSelect(chosen); }}>{versions.map(v => <option key={v.version} value={v.version}>v{v.version} · {dateLabel(v.updatedAt)}</option>)}</select></label><p className="ws-muted">Scenario {saved.id} · model {saved.modelVersion}</p></div>}
    {historical && <p className="ws-notice">Viewing a historical version. Run its saved parameters or copy it to edit independently.</p>}
    <form onSubmit={save}><fieldset disabled={busy || historical}><div className="ws-form-grid"><label>Scenario name<input required maxLength={160} value={name} onChange={e => setName(e.target.value)} /></label><label>Fault scenario<select value={config.fault} onChange={e => setConfig({...config,fault:e.target.value})}>{Object.entries(model.faults).map(([id,label]) => <option key={id} value={id}>{label}</option>)}</select></label></div>
      <label>Description<textarea maxLength={10000} value={description} onChange={e => setDescription(e.target.value)} rows={2} /></label>
      {groups.map(group => <details key={group} open={group !== "Model parameters"}><summary>{group}</summary><div className="ws-form-grid ws-three">{model.configFields.filter(f => f.group===group).map(f => <label key={f.key}>{f.label}{f.unit ? ` (${f.unit})` : ""}<input type="number" required={!f.nullable} min={f.min} max={f.max} step={f.type==="integer" ? 1 : "any"} value={config[f.key] ?? ""} onChange={e => setConfig({...config,[f.key]:e.target.value==="" ? null : Number(e.target.value)})} /><small>{f.min}–{f.max}{f.nullable ? " · optional" : ""}</small></label>)}</div></details>)}
    </fieldset><div className="ws-inline model-actions"><button disabled={busy || !dirty || historical}>{saved ? "Save new version" : "Save scenario"}</button>{saved && <button type="button" disabled={busy || dirty} onClick={() => void copy()}>Copy saved scenario</button>}<button type="button" className="ws-primary" disabled={busy || historical && dirty} onClick={() => void run()}>{busy ? "Computing…" : dirty ? "Save & run scenario ↗" : "Run saved version ↗"}</button></div></form>
    {error && <p role="alert" className="ws-error">{error}</p>}{notice && <p role="status" className="ws-notice">{notice}</p>}
    <p className="ws-muted">Each run fixes its seed, model version and full configuration. A blank seed generates a new seed per run.</p>
  </section>;
}
