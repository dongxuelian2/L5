import { useEffect, useRef, useState } from "react";
import { useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { downloadFile } from "../lib/download";
import { api, go, message } from "./api";
import { command, fmt, label, mapIndex, pair, StateMap, type View } from "./ReachabilityMap";
import { changedPair, Comparison, Numeric, plantKeys, ResultMetrics, Settings } from "./ReachabilityPanels";
import type { Config, Index, Pair, Scenario, Strategy, Study } from "./reachabilityTypes";
import type { Dataset } from "./types";
import "./reachability.css";

const initialHeads: Pair = [2.1, .8];
const inBox = (heads: Pair, box: [Pair, Pair]) => heads.every((v, i) => v >= box[i][0] - 1e-10 && v <= box[i][1] + 1e-10);

export function ReachabilityWorkspace({ workspaceId, studyId, onDataset }: {
  workspaceId: string; studyId?: string; onDataset: (dataset: Dataset) => void;
}) {
  const locale = useLocale();
  const [index, setIndex] = useState<Index>();
  const [config, setConfig] = useState<Config>();
  const [result, setResult] = useState<Study>();
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [incidentId, setIncidentId] = useState("");
  const [heads, setHeads] = useState<Pair>(initialHeads);
  const [previous, setPrevious] = useState(0);
  const [disturbance, setDisturbance] = useState("nominal");
  const [view, setView] = useState<View>("reach");
  const [strategy, setStrategy] = useState<Strategy>("policy");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [exported, setExported] = useState<Dataset>();
  const pending = useRef<AbortController>(null);
  const base = "/workspaces/" + workspaceId + "/reachability";
  const route = "workspaces/" + workspaceId + "/reachability";

  useEffect(() => () => pending.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    api<Index>(base, undefined, "GET", controller.signal).then(value => {
      setIndex(value);
      setConfig(current => current ?? value.defaults);
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [base]);

  useEffect(() => {
    if (!studyId) return;
    const controller = new AbortController();
    setBusy(true);
    setError("");
    api<Study>(base + "/" + studyId, undefined, "GET", controller.signal).then(saved => {
      setConfig(saved.analysis.config);
      setResult(saved);
      setScenario(saved.scenario);
      setIncidentId(saved.incident?.id ?? "");
      setName(saved.name ?? "");
      setExported(undefined);
      setStrategy("policy");
      setView("reach");
      setHeads(saved.evaluation?.initial.heads ?? initialHeads);
      setPrevious(saved.evaluation?.initial.previousAction ?? 0);
      setDisturbance(saved.evaluation?.initial.disturbance ?? "nominal");
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => { controller.abort(); setBusy(false); };
  }, [base, studyId]);

  const analysis = result?.analysis;
  const stored = result?.evaluation;
  const evaluation = stored && stored.initial.heads.every((v, i) => heads[i] === v) &&
    stored.initial.previousAction === previous && stored.initial.disturbance === disturbance ? stored : null;
  const validHeads = heads.every(v => Number.isFinite(v) && v >= 0 && v <= 10.8);
  const selection = analysis && validHeads ? mapIndex(analysis, heads) : undefined;
  const cell = selection?.cell;
  const rank = cell === undefined ? -1 : analysis!.ranks[cell][previous];
  const safe = analysis && inBox(heads, analysis.config.safe);
  const target = analysis && inBox(heads, analysis.config.target);
  const onGrid = selection && heads.every((v, i) => Math.abs(v - analysis!.numerical.axes[i][selection.indices[i]]) < 1e-10);
  const category = !safe ? "unsafe" : target ? "target" : cell === undefined || !analysis!.safe[cell] || analysis!.target[cell]
    || (!onGrid && analysis!.boundary[cell][previous]) ? "uncertain" : rank >= 0 ? "recoverable" : "nonrecoverable";
  const witness = cell === undefined ? -1 : analysis!.policy[cell][previous];
  const trajectory = evaluation?.replays[strategy];
  const exportRoot = result?.id ? base + "/" + result.id : "";

  function update(next: Config) {
    setConfig(next);
    setResult(undefined);
    setView("reach");
    setExported(undefined);
  }

  async function compute(operation: "compute" | "simulate" | "save") {
    if (!config) return;
    const controller = new AbortController();
    pending.current = controller;
    setError(""); setBusy(true); setExported(undefined);
    const saved = operation === "save";
    try {
      const data = await api<Study>(saved ? base : base + "/compute", {
        config, name: name.trim() || label("defaultName"), scenarioId: scenario?.id, scenarioVersion: scenario?.version,
        incidentId, initial: operation !== "compute" ? { heads, previousAction: previous, disturbance } : null,
      }, "POST", controller.signal);
      if (controller.signal.aborted) return;
      if (!analysis) {
        const distance = (action: Pair) => Math.abs(action[0] - 100) / 150 + Math.abs(action[1] - 1);
        const actions = data.analysis.numerical.actions;
        setPrevious(actions.reduce((best, action, i) => distance(action) < distance(actions[best]) ? i : best, 0));
      }
      setResult(data);
      if (data.id) {
        const item = { id: data.id, name: data.name ?? name };
        setIndex(current => current && { ...current, studies: [item, ...current.studies] });
        go(route + "/" + data.id);
      }
    } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }

  async function exportDataset() {
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true); setError("");
    try {
      const data = await api<Dataset>(exportRoot + "/dataset", { strategy }, "POST", controller.signal);
      if (controller.signal.aborted) return;
      setExported(data); onDataset(data);
    } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }

  return <div className="reach-workspace">
    <header className="reach-heading"><h1>{label("title")}</h1><p>{label("scope")}</p></header>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {!index || !config ? <p role="status">{label("opening")}</p> : <>
      <div className="reach-layout">
        <section className="reach-panel">
          <h2>{label("setup")}</h2>
          <fieldset disabled={busy} className="reach-controls">
            <label>{label("saved")}<select value={studyId ?? ""} onChange={e => {
              if (!e.target.value) {
                update(index.defaults); setScenario(null); setIncidentId(""); setName("");
                setHeads(initialHeads); setDisturbance("nominal"); setStrategy("policy"); go(route);
              } else go(route + "/" + e.target.value);
            }}><option value="">{label("new")}</option>
              {index.studies.map(s => <option value={s.id} key={s.id}>{s.name}</option>)}
            </select></label>
            <Settings config={config} update={update} index={index} scenario={scenario} chooseScenario={id => {
              const selected = index.scenarios.find(s => s.id === id) ?? null;
              setScenario(selected);
              const plant = selected ? Object.fromEntries(plantKeys.map(key => [key, selected.config[key]])) as Config["plant"] : index.defaults.plant;
              update({ ...config, plant });
            }} incidentId={incidentId} setIncidentId={setIncidentId} />
            <button type="button" className="ws-primary" onClick={() => void compute("compute")}>{label("compute")}</button>
          </fieldset>
        </section>
        <section className="reach-panel">
          <h2>{label("map")}</h2>
          {analysis ? <>
            <div className="ws-form-grid">
              <label>{label("mapView")}<select value={view} onChange={e => setView(e.target.value as View)}>
                <option value="reach">{label(analysis.config.mode === "robust" ? "robustReach" : "nominalReach")}</option>
                {analysis.config.mode === "robust" && <option value="nominal">{label("nominalReach")}</option>}
                <option value="viability">{label("viability")}</option>
                {analysis.config.mode === "robust" && <option value="nominalViability">{label("nominalViability")}</option>}
                <option value="viableTarget">{label("viableTarget")}</option>
              </select></label>
              <label>{label("previous")}<select value={previous} disabled={busy} onChange={e => setPrevious(Number(e.target.value))}>
                {analysis.numerical.actions.map((a, i) => <option value={i} key={i}>{command(a)}</option>)}
              </select></label>
            </div>
            <StateMap data={analysis} view={view} heads={heads} previous={previous} select={value => { if (!busy) setHeads(value); }} replay={trajectory} />
            <ResultMetrics data={analysis} previous={previous} />
            <details><summary>{label("assumptions")}</summary>
              <p>{label("objectives")}</p><p>{label("robustHint")}</p><p>{label("numbering")}</p>
              <dl className="reach-metrics">
                <div><dt>{label("spacing")}</dt><dd>{pair(analysis.numerical.spacing)}</dd></div>
                <div><dt>{label("horizonSeconds")}</dt><dd>{fmt(analysis.numerical.horizonSeconds)}</dd></div>
                <div><dt>{label("boundaryStates")}</dt><dd>{analysis.numerical.boundaryAugmentedStates}</dd></div>
                <div><dt>{label("graphSize")}</dt><dd>{fmt(analysis.numerical.graphBytes / 1024)} KiB</dd></div>
                <div><dt>{label("computeSeconds")}</dt><dd>{fmt(analysis.numerical.seconds)}</dd></div>
                <div><dt>{label("modelVersion")}</dt><dd>{analysis.modelVersion}</dd></div>
              </dl>
              <p>{Object.keys(analysis.numerical.scenarios).map(label).join(" · ")}</p>
            </details>
          </> : <div className="reach-placeholder"><p>{label("empty")}</p></div>}
        </section>
      </div>
      {busy && <p role="status" className="ws-notice">{label("working")}</p>}
      {analysis && <section className="reach-panel">
        <h2>{label("plan")}</h2>
        <fieldset className="reach-controls" disabled={busy}>
          <div className="ws-form-grid">
            <Numeric name="level1" value={heads[0]} set={v => setHeads(changedPair(heads, 0, v))} />
            <Numeric name="level2" value={heads[1]} set={v => setHeads(changedPair(heads, 1, v))} />
            <label>{label("realization")}<select value={disturbance} onChange={e => setDisturbance(e.target.value)}>
              {Object.keys(index.disturbances).map(v => <option key={v} value={v}>{label(v)}</option>)}
            </select></label>
          </div>
          <dl className="reach-metrics">
            <div><dt>{label("classification")}</dt><dd>{validHeads ? label(category) : "—"}</dd></div>
            <div><dt>{label("gridSteps")}</dt><dd>{safe && rank >= 0 ? rank : "—"}</dd></div>
            <div><dt>{label("firstAction")}</dt><dd>{safe && !target && witness >= 0 ? command(analysis.numerical.actions[witness]) : "—"}</dd></div>
          </dl>
          <button className="ws-primary" type="button" disabled={!validHeads} onClick={() => void compute("simulate")}>{label("simulate")}</button>
        </fieldset>
      </section>}
      {evaluation && <Comparison evaluation={evaluation} strategy={strategy} setStrategy={setStrategy} />}
      {result && <section className="reach-panel">
        <h2>{label("saveExport")}</h2>
        <fieldset disabled={busy} className="reach-controls">
          <div className="ws-form-grid"><label>{label("studyName")}<input value={name} maxLength={160} onChange={e => setName(e.target.value)} /></label></div>
          <div className="ws-inline">
            <button type="button" className="ws-primary" disabled={!validHeads} onClick={() => void compute("save")}>{label("save")}</button>
            <button type="button" className="ws-outlined" onClick={() => downloadFile("l5-recovery.json", JSON.stringify(result))}>{label("json")}</button>
            {exportRoot && <a href={"/api" + exportRoot + "/report.html?download=1&lang=" + locale}>{label("report")}</a>}
            {trajectory && <button type="button" className="ws-outlined" onClick={() => {
              const fields = ["t", "level1", "level2", "pump", "valve", "safetyMargin"] as const;
              downloadFile("l5-recovery-" + strategy + ".csv", [fields.join(","), ...trajectory.trajectory.map(p => fields.map(k => p[k]).join(","))].join("\n"), "text/csv");
            }}>{label("csv")}</button>}
            {exportRoot && evaluation && <button type="button" className="ws-outlined" onClick={() => void exportDataset()}>{label("exportDataset")}</button>}
          </div>
          {result.incident && <a href={"#/workspaces/" + workspaceId + "/incidents/" + result.incident.id}>{label("incident")} · {result.incident.title}</a>}
          {exported && <p role="status">{label("datasetSaved")} <a href={"#/workspaces/" + workspaceId + "/datasets/" + exported.id}>{exported.name}</a>
            {" · "}<a href={"#/workspaces/" + workspaceId + "/experiments/new/" + exported.id}>{label("experiment")}</a></p>}
        </fieldset>
      </section>}
    </>}
  </div>;
}
