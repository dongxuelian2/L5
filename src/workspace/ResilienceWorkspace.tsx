import { t as tr, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { useEffect, useRef, useState } from "react";
import { api, go, message } from "./api";
import { IncidentLinkDialog } from "./IncidentLinkDialog";
import { CampaignForm, CampaignList, CampaignResults, caseName } from "./ResilienceCampaign";
import { CaseError, EvidenceView } from "./ResilienceEvidence";
import { ResilienceScenario } from "./ResilienceScenario";
import { dateLabel, type Dataset } from "./types";
import type { Campaign, CampaignSpec, CampaignSummary, CaseDetail, Catalog, EvidenceRef, Run, RunSummary, SavedScenario, Scenario } from "./resilienceTypes";
import "./resilience.css";

function withName(scenario: Scenario, name = tr("Coupled-tank resilience scenario")) {
  return { ...scenario, name };
}

export function ResilienceWorkspace({ workspaceId, section, recordId, caseId, onExport }: {
  workspaceId: string;
  section?: string;
  recordId?: string;
  caseId?: string;
  onExport: (dataset: Dataset) => void;
}) {
  const locale = useLocale();
  const base = `/workspaces/${workspaceId}/resilience`;
  const route = `workspaces/${workspaceId}/resilience`;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [scenarioId, setScenarioId] = useState("");
  const [saved, setSaved] = useState<SavedScenario[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [exported, setExported] = useState<Record<string, Dataset>>({});
  const [incident, setIncident] = useState<{ dataset: Dataset; title: string } | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [initialLoading, setInitialLoading] = useState(true);
  const [opening, setOpening] = useState(false);
  const [retry, setRetry] = useState(0);
  const mounted = useRef(false);
  const nav = useRef<HTMLDivElement>(null);
  const lastView = useRef("");
  const activeRunId = section === "runs" ? recordId : undefined;
  const activeCampaignId = section === "campaigns" ? recordId : undefined;
  const activeCaseId = activeCampaignId ? caseId : undefined;
  const currentRun = run?.id === activeRunId ? run : null;
  const currentCampaign = campaign?.id === activeCampaignId ? campaign : null;
  const currentCase = detail?.id === activeCaseId ? detail : null;
  const mode = section === "campaigns" ? "campaigns" : "composer";

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setInitialLoading(true);
    setError("");
    Promise.all([
      api<Catalog>(`${base}/catalog`, undefined, "GET", controller.signal),
      api<{ scenarios: SavedScenario[] }>(`${base}/scenarios`, undefined, "GET", controller.signal),
      api<{ runs: RunSummary[] }>(`${base}/runs`, undefined, "GET", controller.signal),
      api<{ campaigns: CampaignSummary[] }>(`${base}/campaigns`, undefined, "GET", controller.signal),
    ]).then(([available, scenarios, recorded, batches]) => {
      if (controller.signal.aborted) return;
      setCatalog(available);
      setScenario(previous => previous ?? withName(available.defaults));
      setSaved(scenarios.scenarios);
      setRuns(recorded.runs);
      setCampaigns(batches.campaigns);
    }).catch(caught => { if (!controller.signal.aborted) setError(message(caught)); })
      .finally(() => { if (!controller.signal.aborted) setInitialLoading(false); });
    return () => controller.abort();
  }, [base, retry]);
  useEffect(() => {
    if (!activeRunId) return;
    const controller = new AbortController();
    setOpening(true);
    setError("");
    api<Run>(`${base}/runs/${activeRunId}`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) setRun(data); })
      .catch(caught => { if (!controller.signal.aborted) setError(message(caught)); })
      .finally(() => { if (!controller.signal.aborted) setOpening(false); });
    return () => controller.abort();
  }, [base, activeRunId]);
  useEffect(() => {
    if (!activeCampaignId) return;
    const controller = new AbortController();
    let timer = 0;
    async function check() {
      try {
        const next = await api<Campaign>(`${base}/campaigns/${activeCampaignId}`, undefined, "GET", controller.signal);
        if (controller.signal.aborted) return;
        setCampaign(next);
        setError("");
        const { cases: _cases, ...summary } = next;
        setCampaigns(previous => [summary, ...previous.filter(item => item.id !== next.id)]);
        if (next.status === "queued" || next.status === "running") timer = window.setTimeout(() => void check(), 900);
      } catch (caught) {
        if (!controller.signal.aborted) {
          const reason = message(caught);
          setError(reason);
          if (!reason.includes("Resilience campaign not found.")) timer = window.setTimeout(() => void check(), 2500);
        }
      }
    }
    setError("");
    void check();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [base, activeCampaignId]);
  const caseStatus = currentCampaign?.cases.find(item => item.id === activeCaseId)?.status;
  useEffect(() => {
    if (!activeCampaignId || !activeCaseId || !caseStatus || caseStatus === "queued" || caseStatus === "running" || caseStatus === "pending") return;
    const controller = new AbortController();
    setError("");
    api<CaseDetail>(`${base}/campaigns/${activeCampaignId}/cases/${activeCaseId}`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) setDetail(data); })
      .catch(caught => { if (!controller.signal.aborted) setError(message(caught)); });
    return () => controller.abort();
  }, [base, activeCampaignId, activeCaseId, caseStatus]);
  useEffect(() => {
    const key = currentCase?.id ?? currentRun?.id;
    if (key && key !== lastView.current && nav.current) {
      nav.current.scrollIntoView({ behavior: "smooth", block: "start" });
      lastView.current = key;
    }
  }, [currentCase?.id, currentRun?.id]);

  async function perform(action: () => Promise<void>) {
    setWorking(true);
    setError("");
    setNotice("");
    try { await action(); }
    catch (caught) { if (mounted.current) setError(message(caught)); }
    finally { if (mounted.current) setWorking(false); }
  }
  function selectScenario(id: string) {
    const selected = saved.find(item => item.id === id);
    if (!catalog) return;
    setScenario(selected ? withName(selected.scenario, selected.name) : withName(catalog.defaults));
    setScenarioId(selected?.id ?? "");
    setNotice("");
  }
  function saveScenario() {
    if (!scenario) return;
    void perform(async () => {
      const next = await api<SavedScenario>(`${base}/scenarios`, { id: scenarioId || undefined, name: scenario.name, scenario });
      if (!mounted.current) return;
      setSaved(previous => [next, ...previous.filter(item => item.id !== next.id)]);
      setScenarioId(next.id);
      setNotice(tr("Scenario saved."));
    });
  }
  function simulate() {
    if (!scenario) return;
    void perform(async () => {
      const next = await api<Run>(`${base}/simulate`, { scenario, name: scenario.name });
      if (!mounted.current) return;
      setRun(next);
      const { id, name, created_at, dataset_id } = next;
      setRuns(previous => [{ id, name, created_at, dataset_id }, ...previous.filter(item => item.id !== next.id)]);
      go(`${route}/runs/${next.id}`);
    });
  }
  function startCampaign(spec: CampaignSpec) {
    void perform(async () => {
      const next = await api<CampaignSummary>(`${base}/campaigns`, spec);
      if (!mounted.current) return;
      setCampaigns(previous => [next, ...previous]);
      go(`${route}/campaigns/${next.id}`);
    });
  }
  function datasetAction(reference: EvidenceRef, title: string, action: "export" | "explore" | "incident") {
    const key = "run_id" in reference ? reference.run_id : reference.case_id;
    void perform(async () => {
      const dataset = exported[key] ?? await api<Dataset>(`${base}/export`, { ...reference, name: title });
      if (!mounted.current) return;
      if (!exported[key]) {
        setExported(previous => ({ ...previous, [key]: dataset }));
        onExport(dataset);
      }
      if (action === "explore") {
        const ids = dataset.metadata.columns.map(column => column.id).filter(Boolean).join(",");
        go(`workspaces/${workspaceId}/explorer/${ids}`);
      } else if (action === "incident") setIncident({ dataset, title });
      else setNotice(tr("Observations exported to Datasets."));
    });
  }
  const simulation = currentCase?.simulation ?? currentRun;
  const reference: EvidenceRef | null = currentCase && activeCampaignId ? { campaign_id: activeCampaignId, case_id: currentCase.id } : currentRun ? { run_id: currentRun.id } : null;
  const title = currentCase ? caseName(currentCase.name) : simulation?.scenario.name ?? tr("Simulation evidence");
  const datasetId = currentCase?.dataset_id ?? currentRun?.dataset_id;
  return <div className="resilience-workspace">
    <div className="ws-page-title"><div>
      <h1>{tr("Resilience Testing")}</h1>
      <p>{tr("Compose process and acquisition faults, then compare detector behavior against the simulated timeline.")}</p>
    </div></div>
    <nav className="resilience-nav" aria-label={tr("Resilience workspace")}>
      <a href={`#/${route}`} aria-current={mode === "composer" ? "page" : undefined}>{tr("Scenario composer")}</a>
      <a href={`#/${route}/campaigns`} aria-current={mode === "campaigns" ? "page" : undefined}>{tr("Campaigns")}</a>
    </nav>
    {error && <p role="alert" className="ws-error">{errorMessage(error)}</p>}
    {notice && <p role="status" className="ws-notice">{notice}</p>}
    {initialLoading ? <p role="status">{tr("Loading resilience catalog…")}</p> : !catalog || !scenario ? <button type="button" className="ws-outlined" onClick={() => setRetry(value => value + 1)}>{tr("Reconnect")}</button> : <>
      {mode === "composer" ? <>
        <div className="ws-panel ws-form-grid resilience-saved">
          <label>{tr("Saved scenarios")}<select value={scenarioId} onChange={event => selectScenario(event.target.value)}>
            <option value="">{tr("New scenario")}</option>{saved.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}
          </select></label>
          <label>{tr("Saved simulations")}<select value={activeRunId ?? ""} onChange={event => go(event.target.value ? `${route}/runs/${event.target.value}` : route)}>
            <option value="">{tr("Choose a simulation")}</option>{runs.map(item => <option value={item.id} key={item.id}>{item.name} · {dateLabel(item.created_at)}</option>)}
          </select></label>
        </div>
        <ResilienceScenario catalog={catalog} scenario={scenario} onChange={setScenario} base={base} busy={working} onSave={saveScenario} onRun={simulate} saved={!!scenarioId} />
      </> : <>
        <div className="ws-panel resilience-saved"><CampaignList campaigns={campaigns} activeId={activeCampaignId}
          onOpen={id => go(id ? `${route}/campaigns/${id}` : `${route}/campaigns`)} /></div>
        {currentCampaign && <CampaignResults key={currentCampaign.id} campaign={currentCampaign} catalog={catalog}
          report={`/api${base}/campaigns/${currentCampaign.id}/report.html?lang=${locale}`} selected={activeCaseId}
          onSelect={id => go(`${route}/campaigns/${currentCampaign.id}/${id}`)} />}
        {activeCampaignId && !currentCampaign && !error && <p role="status">{tr("Opening campaign…")}</p>}
        {activeCaseId && currentCampaign && !caseStatus && <p className="ws-error" role="alert">{tr("Resilience case not found.")}</p>}
        {activeCaseId && caseStatus && !currentCase && !error && <p role="status">{tr("Waiting for saved case evidence…")}</p>}
        {currentCase && <CaseError detail={currentCase} />}
      </>}
      {activeRunId && opening && !currentRun && <p role="status">{tr("Opening simulation…")}</p>}
      {simulation && reference && <div ref={nav} className="resilience-evidence-anchor">
        <EvidenceView key={currentCase?.id ?? currentRun?.id} title={title} simulation={simulation} evaluation={currentCase?.evaluation}
          busy={working} exported={!!datasetId || Boolean(exported["run_id" in reference ? reference.run_id : reference.case_id])}
          onExport={() => datasetAction(reference, title, "export")} onExplore={() => datasetAction(reference, title, "explore")}
          onIncident={() => datasetAction(reference, title, "incident")} />
      </div>}
      {mode === "campaigns" && <CampaignForm catalog={catalog} scenario={scenario} busy={working} onStart={startCampaign} />}
    </>}
    {incident && <IncidentLinkDialog workspaceId={workspaceId} source={{ kind: "dataset", datasetId: incident.dataset.id }}
      draft={{ title: incident.title, start: incident.dataset.metadata.time.start, end: incident.dataset.metadata.time.end }} onClose={() => setIncident(null)} />}
  </div>;
}
