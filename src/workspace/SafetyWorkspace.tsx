import { useEffect, useRef, useState, type FormEvent } from "react";
import { t as tr, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { api, go, message } from "./api";
import { ConstraintEditor, ForecastEditor, newConstraint, toConstraintDefinition, toConstraintDraft, toForecastDraft, toForecastOptions, type ConstraintDraft } from "./SafetyEditors";
import { SafetyResults } from "./SafetyResults";
import { dateLabel, timeLabel, type CatalogSignal, type Dataset, type Incident, type IncidentSummary } from "./types";
import type { SafetyAssessment, SafetyAssessmentSummary, SafetyConfiguration, SafetyDefinition, SafetyEvidence, ForecastOptions } from "./safetyTypes";
import type { ModelSession } from "./modelTypes";
import "./safety.css";

type SafetyRequest = { datasetId: string; name: string; constraints: SafetyDefinition[]; configurationId?: string; configurationRevision?: number; forecast?: ForecastOptions };
type SimulationSummary = Pick<ModelSession, "id" | "title" | "modelId" | "datasetId" | "createdAt">;
type OpenResult = { assessment: SafetyAssessment; request?: SafetyRequest };
type Selection = { id: string; revision: number; signature: string };
const configurationSignature = (drafts: ConstraintDraft[]) => JSON.stringify(drafts.map(toConstraintDefinition));

export function SafetyWorkspace({ workspaceId, datasets, initialDatasetId, assessmentId, onDataset }: {
  workspaceId: string; datasets: Dataset[]; initialDatasetId?: string; assessmentId?: string; onDataset: (dataset: Dataset) => void;
}) {
  const locale = useLocale();
  const route = `workspaces/${workspaceId}/safety`;
  const base = `/${route}`;
  const [datasetId, setDatasetId] = useState(initialDatasetId || datasets[0]?.id || "");
  const [addedDataset, setAddedDataset] = useState<Dataset>();
  const [simulationId, setSimulationId] = useState("");
  const [simulations, setSimulations] = useState<SimulationSummary[]>([]);
  const [catalog, setCatalog] = useState<CatalogSignal[]>([]);
  const [configurations, setConfigurations] = useState<SafetyConfiguration[]>([]);
  const [assessments, setAssessments] = useState<SafetyAssessmentSummary[]>([]);
  const [drafts, setDrafts] = useState<ConstraintDraft[]>([]);
  const [selection, setSelection] = useState<Selection>();
  const [configurationName, setConfigurationName] = useState("");
  const [assessmentName, setAssessmentName] = useState("");
  const [forecast, setForecast] = useState(toForecastDraft);
  const [result, setResult] = useState<OpenResult>();
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [evidence, setEvidence] = useState<SafetyEvidence>();
  const [incident, setIncident] = useState<Incident>();
  const [catalogRevision, setCatalogRevision] = useState(0);
  const constraintForm = useRef<HTMLFormElement>(null);
  const results = useRef<HTMLDivElement>(null);
  const active = useRef(false);
  const datasetOptions = addedDataset && !datasets.some(dataset => dataset.id === addedDataset.id) ? [addedDataset, ...datasets] : datasets;
  const dataset = datasetOptions.find(item => item.id === datasetId);
  const signals = catalog.filter(signal => signal.datasetId === datasetId);
  const pendingSimulations = simulations.filter(simulation => !datasetOptions.some(dataset => dataset.metadata.model?.simulationId === simulation.id));
  const supportedForecast = dataset?.metadata.model?.id === "coupled-tanks" && !dataset.metadata.transformation;
  const currentConfiguration = configurations.find(configuration => configuration.id === selection?.id);
  const ready = drafts.length > 0 && signals.length > 0 && !loading && !opening && !busy;

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api<{ configurations: SafetyConfiguration[] }>(`${base}/configurations`, undefined, "GET", controller.signal),
      api<{ assessments: SafetyAssessmentSummary[] }>(`${base}/assessments`, undefined, "GET", controller.signal),
      api<{ simulations: SimulationSummary[] }>(`/simulations?workspaceId=${encodeURIComponent(workspaceId)}`, undefined, "GET", controller.signal),
    ]).then(([configurationList, assessmentList, simulationList]) => {
      if (controller.signal.aborted) return;
      setConfigurations(configurationList.configurations); setAssessments(assessmentList.assessments); setSimulations(simulationList.simulations);
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [base, workspaceId]);

  useEffect(() => {
    const controller = new AbortController();
    api<{ signals: CatalogSignal[] }>(`/workspaces/${workspaceId}/signals`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) setCatalog(data.signals); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [workspaceId, catalogRevision]);

  const openId = result?.assessment.id;
  useEffect(() => {
    if (!assessmentId || openId === assessmentId) { setOpening(false); return; }
    const controller = new AbortController();
    setOpening(true); setError(""); setNotice(""); setIncident(undefined);
    api<SafetyAssessment>(`${base}/assessments/${encodeURIComponent(assessmentId)}`, undefined, "GET", controller.signal)
      .then(assessment => {
        if (controller.signal.aborted) return;
        const reopened = assessment.configuration.constraints.map(toConstraintDraft);
        setDatasetId(assessment.datasetId); setDrafts(reopened); setAssessmentName(assessment.name);
        setForecast(toForecastDraft(assessment.forecastOptions)); setResult({ assessment });
        setConfigurationName(assessment.configuration.name || "");
        setSelection(assessment.configuration.id && assessment.configuration.revision ? { id: assessment.configuration.id,
          revision: assessment.configuration.revision, signature: configurationSignature(reopened) } : undefined);
      }).catch(e => { if (!controller.signal.aborted) setError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setOpening(false); });
    return () => controller.abort();
  }, [base, assessmentId, openId]);

  useEffect(() => {
    if (!result || opening || (assessmentId && result.assessment.id !== assessmentId)) return;
    const frame = requestAnimationFrame(() => results.current?.scrollIntoView({ block: "start", behavior: "instant" }));
    return () => cancelAnimationFrame(frame);
  }, [result, assessmentId, opening]);

  function changeDataset(id: string) {
    setDatasetId(id); setSelection(undefined); setConfigurationName(""); setAssessmentName(""); setDrafts([]);
    setForecast(toForecastDraft()); setResult(undefined); setNotice(""); setError(""); setIncident(undefined);
    if (assessmentId) go(route);
  }

  function chooseConfiguration(id: string) {
    const configuration = configurations.find(item => item.id === id);
    if (!configuration) {
      setConfigurationName(""); setSelection(undefined);
      return;
    }
    const next = configuration.constraints.map(toConstraintDraft);
    setConfigurationName(configuration.name); setDrafts(next);
    setSelection({ id: configuration.id, revision: configuration.revision, signature: configurationSignature(next) });
  }

  async function saveSimulation() {
    if (!simulationId) return;
    setBusy(true); setError("");
    try {
      const saved = await api<Dataset>(`/simulations/${encodeURIComponent(simulationId)}/save`, { workspaceId });
      if (!active.current) return;
      setAddedDataset(saved); setSimulationId(""); changeDataset(saved.id);
      setCatalogRevision(revision => revision + 1); onDataset(saved);
      setNotice("Simulation measurements saved as a Dataset.");
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }

  async function saveConfiguration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dataset || !drafts.length) return;
    if (!configurationName.trim()) { setError("Enter a name to save this configuration."); return; }
    const fork = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") === "copy";
    const update = !fork ? selection : undefined;
    const body = { datasetId: dataset.id, name: configurationName.trim(), constraints: drafts.map(toConstraintDefinition), ...(update && { revision: update.revision }) };
    setBusy(true); setError(""); setNotice("");
    try {
      const saved = await api<SafetyConfiguration>(update ? `${base}/configurations/${encodeURIComponent(update.id)}` : `${base}/configurations`, body, update ? "PATCH" : "POST");
      if (!active.current) return;
      const normalized = saved.constraints.map(toConstraintDraft);
      setDrafts(normalized); setConfigurationName(saved.name);
      setSelection({ id: saved.id, revision: saved.revision, signature: configurationSignature(normalized) });
      setConfigurations(previous => [saved, ...previous.filter(item => item.id !== saved.id)]);
      setNotice("Constraint configuration saved.");
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }

  async function runAssessment(request: SafetyRequest, save: boolean) {
    setBusy(true); setError(""); setNotice(""); setIncident(undefined);
    try {
      const assessment = await api<SafetyAssessment>(`${base}/${save ? "assessments" : "evaluate"}`, request);
      if (!active.current) return;
      setResult({ assessment, request });
      if (assessment.id) {
        const summary = { id: assessment.id, name: assessment.name, workspaceId: assessment.workspaceId, datasetId: assessment.datasetId, createdAt: assessment.createdAt };
        setAssessments(previous => [summary, ...previous.filter(item => item.id !== summary.id)]);
        setNotice("Assessment saved.");
        go(`${route}/${assessment.id}`);
      } else if (assessmentId) go(route);
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }

  function evaluate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dataset || !ready || !constraintForm.current?.reportValidity()) return;
    const constraints = drafts.map(toConstraintDefinition);
    const reference = selection && selection.signature === configurationSignature(drafts)
      ? { configurationId: selection.id, configurationRevision: selection.revision } : {};
    const save = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") === "save";
    void runAssessment({ datasetId: dataset.id, name: assessmentName.trim() || configurationName.trim() || dataset.name,
      constraints, ...reference, forecast: supportedForecast ? toForecastOptions(forecast) : undefined }, save);
  }

  const assessment = result?.assessment;
  return <div className="safety-workspace">
    <header className="ws-page-title"><div><h1>{tr("Process safety & predictive risk")}</h1>
      <p>{tr("Evaluate engineering limits against measured trajectories and project when a coupled-tank process may cross them.")}</p></div></header>
    <section className="ws-panel safety-source" aria-labelledby="safety-source-title">
      <h2 id="safety-source-title">{tr("Source and saved assessments")}</h2>
      <div className="ws-form-grid safety-fields">
        <label>{tr("Dataset")}<select value={datasetId} disabled={busy || opening} onChange={event => changeDataset(event.target.value)}>
          <option value="">{tr("Choose a dataset")}</option>
          {datasetOptions.map(item => <option key={item.id} value={item.id}>{item.name}{item.metadata.model ? ` · ${tr(item.metadata.model.name || item.metadata.model.id)}` : ""}</option>)}
        </select></label>
        <label>{tr("Saved assessment")}<select value={assessmentId || ""} disabled={busy || opening || loading} onChange={event => {
          if (event.target.value) go(`${route}/${event.target.value}`); else { setResult(undefined); go(route); }
        }}><option value="">{tr("Choose an assessment")}</option>
          {assessments.map(item => <option value={item.id} key={item.id}>{item.name} · {dateLabel(item.createdAt)}</option>)}</select></label>
      </div>
      {dataset && <p className="ws-muted">{dataset.metadata.rowCount.toLocaleString(locale)} {tr("samples")} · {timeLabel(dataset.metadata.time, dataset.metadata.time.start)} → {timeLabel(dataset.metadata.time, dataset.metadata.time.end)}</p>}
      {!!pendingSimulations.length && <details><summary>{tr("Use a saved simulation")}</summary>
        <div className="safety-actions safety-source-actions">
          <label>{tr("Simulation")}<select value={simulationId} disabled={busy || opening} onChange={event => setSimulationId(event.target.value)}>
            <option value="">{tr("Choose a simulation")}</option>{pendingSimulations.map(item => <option key={item.id} value={item.id}>{item.title} · {dateLabel(item.createdAt)}</option>)}
          </select></label><button type="button" className="ws-outlined" disabled={!simulationId || busy || opening} onClick={() => void saveSimulation()}>{tr("Use simulation as Dataset")}</button>
        </div>
      </details>}
      {!dataset && !loading && <p className="ws-notice"><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets`}>{tr("Import a Dataset")}</a> · <a className="ws-link" href={`#/workspaces/${workspaceId}/models`}>{tr("Generate process data ↗")}</a></p>}
      {(loading || opening) && <p role="status">{tr(opening ? "Opening saved assessment…" : "Loading safety workspace…")}</p>}
    </section>
    {dataset && !opening && <>
      <section className="ws-panel safety-editor" aria-labelledby="safety-editor-title">
        <div className="ws-section-heading"><div><h2 id="safety-editor-title">{tr("Operating constraints")}</h2>
          <p>{tr("Choose signals from this Dataset so their observations share a clock.")}</p></div>
          <a className="ws-link" href={`#/workspaces/${workspaceId}/signals`}>{tr("Signal catalog")} ↗</a></div>
        <form ref={constraintForm} onSubmit={saveConfiguration}>
          <fieldset className="safety-form-shell" disabled={busy || loading}>
            <div className="ws-form-grid safety-fields">
              <label>{tr("Saved configuration")}<select value={selection?.id || ""} onChange={event => chooseConfiguration(event.target.value)}>
                <option value="">{tr("New configuration")}</option>
                {configurations.filter(item => item.datasetId === datasetId).map(item => <option value={item.id} key={item.id}>{item.name} · {tr("Revision {0}", { 0: item.revision })}</option>)}
              </select></label>
              <label>{tr("Configuration name")}<input value={configurationName} maxLength={160} onChange={event => setConfigurationName(event.target.value)} /></label>
            </div>
            {selection && <div className="safety-actions"><p className="ws-muted">{tr("Editing revision {0}", { 0: selection.revision })}</p>
              {currentConfiguration && currentConfiguration.revision !== selection.revision && <button type="button" className="ws-outlined" onClick={() => chooseConfiguration(currentConfiguration.id)}>{tr("Load latest revision")}</button>}</div>}
            {drafts.map((draft, index) => <ConstraintEditor key={draft.id} draft={draft} index={index} signals={signals}
              onChange={next => setDrafts(previous => previous.map(item => item.id === next.id ? next : item))}
              onRemove={() => setDrafts(previous => previous.filter(item => item.id !== draft.id))} />)}
            {!drafts.length && <p className="ws-muted">{tr("Add a constraint to evaluate process measurements.")}</p>}
            <div className="safety-actions safety-editor-actions">
              <button type="button" className="ws-outlined" disabled={!signals.length} onClick={() => setDrafts(previous => [...previous, newConstraint(signals[0])])}>{tr("Add constraint")}</button>
              <button type="submit" className="ws-outlined" disabled={!drafts.length || !signals.length || !configurationName.trim()}>{tr(selection ? "Save new revision" : "Save configuration")}</button>
              {selection && <button type="submit" value="copy" disabled={!drafts.length || !signals.length || !configurationName.trim()}>{tr("Save as new configuration")}</button>}
            </div>
          </fieldset>
        </form>
      </section>
      <section className="ws-panel safety-editor" aria-labelledby="safety-assessment-title">
        <h2 id="safety-assessment-title">{tr("Evaluate and save")}</h2>
        <form onSubmit={evaluate}><fieldset className="safety-form-shell" disabled={busy || loading}>
          <label>{tr("Assessment name")}<input value={assessmentName} maxLength={160} placeholder={configurationName || dataset.name} onChange={event => setAssessmentName(event.target.value)} /></label>
          {supportedForecast ? <ForecastEditor draft={forecast} dataset={dataset} onChange={setForecast} /> : <p className="ws-notice">{tr("History can be evaluated for this Dataset. Physics-based forecasting is available for coupled-tank simulations.")}</p>}
          <div className="safety-actions safety-editor-actions">
            <button type="submit" className="ws-outlined" disabled={!ready}>{tr("Evaluate limits")}</button>
            <button type="submit" className="ws-primary" value="save" disabled={!ready}>{tr("Evaluate and save assessment")}</button>
          </div>
        </fieldset></form>
        {busy && <p role="status">{tr("Working on safety assessment…")}</p>}
      </section>
    </>}
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {notice && <p className="ws-notice" role="status">{tr(notice)}</p>}
    {incident && <p className="ws-notice" role="status">{tr("Evidence attached to Incident.")} <a className="ws-link" href={`#/workspaces/${workspaceId}/incidents/${incident.id}`}>{incident.title} ↗</a></p>}
    {assessment && !opening && (!assessmentId || !assessment.id || assessment.id === assessmentId) && <div ref={results} className="safety-results-anchor">
      <SafetyResults key={assessment.id || assessment.createdAt} assessment={assessment} axis={assessment.source.time}
        signals={assessment.source.signals} attach={setEvidence}
        controls={assessment.id ? <div className="safety-actions safety-exports">
          {(["json", "csv", "markdown"] as const).map((format, index) => <a className="ws-outlined" download key={format}
            href={`/api${base}/assessments/${encodeURIComponent(assessment.id!)}/export?format=${format}&lang=${locale === "zh-CN" ? "zh" : "en"}`}>{tr(["Export JSON", "Export CSV", "Export report"][index])} ↓</a>)}
        </div> : result?.request && <button type="button" className="ws-outlined" disabled={busy} onClick={() => void runAssessment(result.request!, true)}>{tr("Evaluate again and save")}</button>} />
    </div>}
    {evidence && assessment?.id && <SafetyIncidentDialog workspaceId={workspaceId} endpoint={`${base}/assessments/${encodeURIComponent(assessment.id)}/incident-evidence`}
      evidence={evidence} onClose={() => setEvidence(undefined)} onAttached={item => { setIncident(item); setEvidence(undefined); }} />}
  </div>;
}

function SafetyIncidentDialog({ workspaceId, endpoint, evidence, onClose, onAttached }: {
  workspaceId: string; endpoint: string; evidence: SafetyEvidence; onClose: () => void; onAttached: (incident: Incident) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [incidentId, setIncidentId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const active = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    if (element?.showModal) element.showModal(); else element?.setAttribute("open", "");
    const controller = new AbortController();
    api<{ incidents: IncidentSummary[] }>(`/workspaces/${workspaceId}/incidents`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) setIncidents(data.incidents); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); active?.focus(); };
  }, [workspaceId]);
  async function attach(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { onAttached(await api<Incident>(endpoint, { ...evidence, incidentId })); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  const title = evidence.kind === "predicted" ? "Attach predicted violation" : evidence.raw ? "Attach raw exceedance" : "Attach observed violation";
  return <dialog ref={dialog} className="incident-dialog" aria-labelledby="safety-incident-title" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={attach} className="incident-form"><h2 id="safety-incident-title">{tr(title)}</h2>
      {evidence.kind === "predicted" && <p className="ws-notice">{tr("The Incident records this interval as a forecast under the saved assumptions.")}</p>}
      <label>{tr("Incident")}<select value={incidentId} onChange={event => setIncidentId(event.target.value)} required disabled={loading || busy}>
        <option value="">{tr(loading ? "Loading Incidents…" : "Choose an Incident")}</option>{incidents.map(item => <option value={item.id} key={item.id}>{item.title}</option>)}
      </select></label>
      {!loading && !incidents.length && !error && <p>{tr("Create an Incident before attaching evidence.")}</p>}
      {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
      <div className="safety-actions"><button type="button" className="ws-outlined" disabled={busy} onClick={onClose}>{tr("Cancel")}</button>
        <button type="submit" className="ws-primary" disabled={busy || !incidentId}>{tr("Attach evidence")}</button></div>
    </form>
  </dialog>;
}
